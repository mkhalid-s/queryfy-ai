#!/bin/bash
# ==========================================
# QueryfyAI - Production Deployment Script
# ==========================================
# Zero-downtime deployment with health checks,
# database migrations, and rollback capability
#
# Usage:
#   ./scripts/deploy.sh                  # Deploy latest
#   ./scripts/deploy.sh v1.2.3           # Deploy specific version
#   ./scripts/deploy.sh --rollback       # Rollback to previous
#   ./scripts/deploy.sh --status         # Show status
#   ./scripts/deploy.sh --backup         # Create database backup
#   ./scripts/deploy.sh --logs           # Show logs
# ==========================================

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.production.yml"
ENV_FILE="$PROJECT_DIR/.env.production"
LOG_DIR="/var/log/queryfyai"
LOG_FILE="$LOG_DIR/deploy.log"
BACKUP_DIR="/opt/queryfyai/backups"
HEALTH_TIMEOUT=300  # 5 minutes
HEALTH_INTERVAL=5

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${GREEN}[${timestamp}]${NC} $1"
    echo "[${timestamp}] $1" >> "$LOG_FILE" 2>/dev/null || true
}

error() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${RED}[${timestamp}] ERROR:${NC} $1" >&2
    echo "[${timestamp}] ERROR: $1" >> "$LOG_FILE" 2>/dev/null || true
}

warn() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${YELLOW}[${timestamp}] WARNING:${NC} $1"
    echo "[${timestamp}] WARNING: $1" >> "$LOG_FILE" 2>/dev/null || true
}

info() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${BLUE}[${timestamp}] INFO:${NC} $1"
}

# ==========================================
# Pre-deployment checks
# ==========================================
pre_deploy_checks() {
    log "Running pre-deployment checks..."

    # Check if docker-compose file exists
    if [ ! -f "$COMPOSE_FILE" ]; then
        error "docker-compose.production.yml not found at $COMPOSE_FILE"
        exit 1
    fi

    # Check if .env.production exists
    if [ ! -f "$ENV_FILE" ]; then
        error ".env.production not found. Copy .env.production.example and configure it."
        exit 1
    fi

    # Check Docker is running
    if ! docker info > /dev/null 2>&1; then
        error "Docker is not running"
        exit 1
    fi

    # Check docker compose command
    if docker compose version > /dev/null 2>&1; then
        DOCKER_COMPOSE="docker compose"
    elif docker-compose version > /dev/null 2>&1; then
        DOCKER_COMPOSE="docker-compose"
    else
        error "Neither 'docker compose' nor 'docker-compose' found"
        exit 1
    fi

    # Check disk space (warn if < 20% free)
    DISK_USAGE=$(df -h "$PROJECT_DIR" | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ "$DISK_USAGE" -gt 80 ]; then
        warn "Disk usage is at ${DISK_USAGE}%"
    fi

    # Check memory (warn if < 2GB free)
    if command -v free > /dev/null 2>&1; then
        FREE_MEM=$(free -m | awk '/^Mem:/{print $7}')
        if [ "$FREE_MEM" -lt 2048 ]; then
            warn "Available memory is low: ${FREE_MEM}MB"
        fi
    fi

    # Check required ports
    for port in 80 443; do
        if lsof -i:$port > /dev/null 2>&1; then
            PROC=$(lsof -i:$port -t 2>/dev/null | head -1)
            if [ -n "$PROC" ]; then
                PROC_NAME=$(ps -p "$PROC" -o comm= 2>/dev/null || echo "unknown")
                if [[ "$PROC_NAME" != *"docker"* ]] && [[ "$PROC_NAME" != *"traefik"* ]]; then
                    warn "Port $port is in use by $PROC_NAME (PID: $PROC)"
                fi
            fi
        fi
    done

    log "Pre-deployment checks passed"
}

# ==========================================
# Create backup before deployment
# ==========================================
create_backup() {
    log "Creating backup before deployment..."

    mkdir -p "$BACKUP_DIR"
    local backup_name="pre-deploy-$(date +%Y%m%d_%H%M%S)"
    local backup_path="$BACKUP_DIR/$backup_name"
    mkdir -p "$backup_path"

    # Backup current container state info
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" ps > "$backup_path/containers.txt" 2>/dev/null || true

    # Backup current images info
    docker images --format "{{.Repository}}:{{.Tag}}" | grep queryfy > "$backup_path/images.txt" 2>/dev/null || true

    # Copy current compose file
    cp "$COMPOSE_FILE" "$backup_path/docker-compose.yml" 2>/dev/null || true

    # Copy environment file (without secrets displayed)
    grep -v -E "(PASSWORD|SECRET|KEY|TOKEN)" "$ENV_FILE" > "$backup_path/env-sanitized.txt" 2>/dev/null || true

    # Database backup
    if $DOCKER_COMPOSE -f "$COMPOSE_FILE" ps postgres 2>/dev/null | grep -q "running"; then
        log "Creating database backup..."
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T postgres pg_dump -U "${POSTGRES_USER:-queryfyai}" -Fc "${POSTGRES_DB:-queryfyai}" > "$backup_path/database.dump" 2>/dev/null || warn "Database backup failed"
    fi

    # Keep only last 10 backups
    ls -dt "$BACKUP_DIR"/pre-deploy-* 2>/dev/null | tail -n +11 | xargs -r rm -rf

    log "Backup created: $backup_name"
    echo "$backup_name" > "$BACKUP_DIR/latest"
}

# ==========================================
# Database migration
# ==========================================
run_migrations() {
    log "Checking for database migrations..."

    # Wait for database to be ready
    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T postgres pg_isready -U "${POSTGRES_USER:-queryfyai}" > /dev/null 2>&1; then
            log "Database is ready"
            break
        fi
        info "Waiting for database... ($attempt/$max_attempts)"
        sleep 2
        attempt=$((attempt + 1))
    done

    if [ $attempt -gt $max_attempts ]; then
        error "Database did not become ready in time"
        return 1
    fi

    # Run any SQL migrations from init-db directory
    if [ -d "$PROJECT_DIR/scripts/init-db" ]; then
        for migration in "$PROJECT_DIR/scripts/init-db"/*.sql; do
            if [ -f "$migration" ]; then
                log "Running migration: $(basename "$migration")"
                $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T postgres psql -U "${POSTGRES_USER:-queryfyai}" -d "${POSTGRES_DB:-queryfyai}" < "$migration" 2>/dev/null || warn "Migration may have already been applied: $(basename "$migration")"
            fi
        done
    fi

    log "Database migrations complete"
}

# ==========================================
# Deploy the application
# ==========================================
deploy() {
    local version="${1:-latest}"
    log "Starting deployment (version: $version)..."

    cd "$PROJECT_DIR"

    # Pull latest images or build
    if [ "$version" == "latest" ]; then
        log "Building Docker images..."
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" build --no-cache
    else
        log "Pulling Docker images for version $version..."
        export VERSION="$version"
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" pull || {
            warn "Pull failed, building images instead..."
            $DOCKER_COMPOSE -f "$COMPOSE_FILE" build
        }
    fi

    # Start/update infrastructure services first (postgres, redis)
    log "Starting infrastructure services..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d postgres redis traefik

    # Wait for infrastructure
    sleep 10

    # Run migrations
    run_migrations

    # Start application services
    log "Starting application services..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d backend frontend

    log "Deployment initiated, waiting for services to be healthy..."
}

# ==========================================
# Health check after deployment
# ==========================================
post_deploy_health_check() {
    log "Running post-deployment health checks..."

    local max_wait=$HEALTH_TIMEOUT
    local elapsed=0

    # Check backend health
    log "Checking backend health..."
    while [ $elapsed -lt $max_wait ]; do
        if curl -sf "http://localhost/api/health/live" > /dev/null 2>&1 || \
           curl -sf "http://localhost:8000/health/live" > /dev/null 2>&1; then
            log "Backend is healthy!"
            break
        fi

        info "Waiting for backend... (${elapsed}s/${max_wait}s)"
        sleep $HEALTH_INTERVAL
        elapsed=$((elapsed + HEALTH_INTERVAL))
    done

    if [ $elapsed -ge $max_wait ]; then
        error "Backend health check failed after ${max_wait}s"
        return 1
    fi

    # Check frontend health
    log "Checking frontend health..."
    elapsed=0
    while [ $elapsed -lt 60 ]; do
        if curl -sf "http://localhost/" > /dev/null 2>&1 || \
           curl -sf "http://localhost:8080/" > /dev/null 2>&1; then
            log "Frontend is healthy!"
            break
        fi

        info "Waiting for frontend... (${elapsed}s/60s)"
        sleep 3
        elapsed=$((elapsed + 3))
    done

    if [ $elapsed -ge 60 ]; then
        error "Frontend health check failed"
        return 1
    fi

    # Verify all containers are running
    local running_count=$($DOCKER_COMPOSE -f "$COMPOSE_FILE" ps --status running -q 2>/dev/null | wc -l)
    local expected_count=4  # traefik, backend, frontend, postgres, redis (minus backup)

    if [ "$running_count" -lt 4 ]; then
        warn "Only $running_count containers running (expected at least 4)"
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" ps
    fi

    log "All health checks passed!"
    return 0
}

# ==========================================
# Rollback to previous state
# ==========================================
rollback() {
    log "Rolling back to previous deployment..."

    # Find most recent backup
    if [ ! -f "$BACKUP_DIR/latest" ]; then
        error "No backup found to rollback to"
        exit 1
    fi

    local latest_backup=$(cat "$BACKUP_DIR/latest")
    local backup_path="$BACKUP_DIR/$latest_backup"

    if [ ! -d "$backup_path" ]; then
        error "Backup directory not found: $backup_path"
        exit 1
    fi

    log "Rolling back to: $latest_backup"

    # Stop current services
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" down --remove-orphans

    # Restore database if backup exists
    if [ -f "$backup_path/database.dump" ]; then
        log "Restoring database..."
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d postgres
        sleep 10
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T postgres pg_restore -U "${POSTGRES_USER:-queryfyai}" -d "${POSTGRES_DB:-queryfyai}" --clean < "$backup_path/database.dump" 2>/dev/null || warn "Database restore may have warnings"
    fi

    # Restart services
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d

    log "Rollback completed"

    # Run health checks
    if post_deploy_health_check; then
        log "Rollback successful!"
    else
        error "Rollback completed but health checks failed"
        exit 1
    fi
}

# ==========================================
# Show deployment status
# ==========================================
show_status() {
    echo ""
    echo "=========================================="
    echo "QueryfyAI Deployment Status"
    echo "=========================================="
    echo ""

    # Container status
    echo "Container Status:"
    echo "-----------------"
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" ps 2>/dev/null || echo "Could not get container status"
    echo ""

    # Resource usage
    echo "Resource Usage:"
    echo "---------------"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null | grep queryfy || true
    echo ""

    # Health endpoints
    echo "Health Checks:"
    echo "--------------"
    echo -n "Backend API: "
    if curl -sf http://localhost/api/health/live > /dev/null 2>&1; then
        echo -e "${GREEN}Healthy${NC}"
    elif curl -sf http://localhost:8000/health/live > /dev/null 2>&1; then
        echo -e "${GREEN}Healthy (direct)${NC}"
    else
        echo -e "${RED}Unhealthy${NC}"
    fi

    echo -n "Frontend:    "
    if curl -sf http://localhost/ > /dev/null 2>&1; then
        echo -e "${GREEN}Healthy${NC}"
    elif curl -sf http://localhost:8080/ > /dev/null 2>&1; then
        echo -e "${GREEN}Healthy (direct)${NC}"
    else
        echo -e "${RED}Unhealthy${NC}"
    fi

    echo -n "Database:    "
    if $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T postgres pg_isready -U "${POSTGRES_USER:-queryfyai}" > /dev/null 2>&1; then
        echo -e "${GREEN}Healthy${NC}"
    else
        echo -e "${RED}Unhealthy${NC}"
    fi

    echo -n "Redis:       "
    if $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T redis redis-cli ping > /dev/null 2>&1; then
        echo -e "${GREEN}Healthy${NC}"
    else
        echo -e "${RED}Unhealthy${NC}"
    fi

    echo ""

    # Disk usage
    echo "Disk Usage:"
    echo "-----------"
    df -h "$PROJECT_DIR" 2>/dev/null | tail -1 || true
    echo ""

    # Recent logs
    echo "Recent Deployments:"
    echo "-------------------"
    if [ -f "$LOG_FILE" ]; then
        tail -10 "$LOG_FILE" 2>/dev/null || true
    else
        echo "No deployment logs found"
    fi
    echo ""
}

# ==========================================
# Show logs
# ==========================================
show_logs() {
    local service="${1:-}"

    if [ -n "$service" ]; then
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" logs -f --tail=100 "$service"
    else
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" logs -f --tail=100
    fi
}

# ==========================================
# Manual backup
# ==========================================
manual_backup() {
    log "Creating manual backup..."

    mkdir -p "$BACKUP_DIR"
    local backup_name="manual-$(date +%Y%m%d_%H%M%S)"
    local backup_path="$BACKUP_DIR/$backup_name"
    mkdir -p "$backup_path"

    # Database backup
    if $DOCKER_COMPOSE -f "$COMPOSE_FILE" ps postgres 2>/dev/null | grep -q "running"; then
        log "Creating database backup..."
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T postgres pg_dump -U "${POSTGRES_USER:-queryfyai}" -Fc "${POSTGRES_DB:-queryfyai}" > "$backup_path/database.dump"
        log "Database backup created: $backup_path/database.dump"
    else
        error "PostgreSQL is not running"
        exit 1
    fi

    # Keep only last 30 manual backups
    ls -dt "$BACKUP_DIR"/manual-* 2>/dev/null | tail -n +31 | xargs -r rm -rf

    log "Manual backup completed: $backup_name"
}

# ==========================================
# Print help
# ==========================================
print_help() {
    echo "QueryfyAI Production Deployment Script"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  (none)              Deploy latest version"
    echo "  v1.2.3              Deploy specific version"
    echo "  --rollback, -r      Rollback to previous deployment"
    echo "  --status, -s        Show current deployment status"
    echo "  --backup, -b        Create manual database backup"
    echo "  --logs [service]    Show logs (optionally for specific service)"
    echo "  --help, -h          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                  # Deploy latest"
    echo "  $0 v1.2.3           # Deploy version 1.2.3"
    echo "  $0 --rollback       # Rollback to previous"
    echo "  $0 --logs backend   # Show backend logs"
    echo ""
}

# ==========================================
# Main
# ==========================================
main() {
    # Create log directory
    mkdir -p "$LOG_DIR" 2>/dev/null || true

    case "${1:-deploy}" in
        --rollback|-r)
            pre_deploy_checks
            rollback
            ;;
        --status|-s)
            show_status
            exit 0
            ;;
        --backup|-b)
            manual_backup
            exit 0
            ;;
        --logs|-l)
            show_logs "${2:-}"
            exit 0
            ;;
        --help|-h)
            print_help
            exit 0
            ;;
        -*)
            error "Unknown option: $1"
            print_help
            exit 1
            ;;
        *)
            log "=========================================="
            log "QueryfyAI Deployment Starting"
            log "=========================================="

            pre_deploy_checks
            create_backup
            deploy "$1"

            if post_deploy_health_check; then
                log "=========================================="
                log "Deployment completed successfully!"
                log "=========================================="
                show_status
            else
                error "Deployment failed health checks"
                warn "Consider running: $0 --rollback"
                exit 1
            fi
            ;;
    esac
}

main "$@"
