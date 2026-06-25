#!/bin/bash
# ==========================================
# QueryfyAI - Restore Script
# ==========================================
# Restores from backup
#
# Usage:
#   ./scripts/restore.sh                    # Interactive (latest backup)
#   ./scripts/restore.sh 20241130_020000    # Restore specific backup
#   ./scripts/restore.sh --list             # List available backups
# ==========================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-/opt/queryfyai/backups}"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.production.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" >&2
}

warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

# ==========================================
# List available backups
# ==========================================
list_backups() {
    echo ""
    echo "Available backups:"
    echo "=========================================="

    if [ -d "$BACKUP_DIR" ]; then
        ls -t "$BACKUP_DIR" | while read -r dir; do
            if [ -f "$BACKUP_DIR/$dir/manifest.json" ]; then
                size=$(du -sh "$BACKUP_DIR/$dir" 2>/dev/null | cut -f1)
                timestamp=$(cat "$BACKUP_DIR/$dir/manifest.json" | grep timestamp | cut -d'"' -f4)
                echo "  $dir ($size) - $timestamp"
            fi
        done
    else
        echo "  No backups found"
    fi
    echo ""
}

# ==========================================
# Restore from backup
# ==========================================
restore_backup() {
    local backup_name="$1"
    local backup_path="$BACKUP_DIR/$backup_name"

    # Validate backup exists
    if [ ! -d "$backup_path" ]; then
        error "Backup not found: $backup_path"
        list_backups
        exit 1
    fi

    if [ ! -f "$backup_path/manifest.json" ]; then
        error "Invalid backup (no manifest): $backup_path"
        exit 1
    fi

    log "Restoring from backup: $backup_name"

    # Confirm restore
    echo ""
    warn "This will overwrite current data!"
    read -p "Are you sure you want to continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log "Restore cancelled"
        exit 0
    fi

    # 1. Stop services (keep Redis running for restore)
    log "Stopping services..."
    docker-compose -f "$COMPOSE_FILE" stop backend frontend 2>/dev/null || true

    # 2. Restore Redis
    if [ -f "$backup_path/redis_dump.rdb" ]; then
        log "Restoring Redis..."
        docker-compose -f "$COMPOSE_FILE" stop redis 2>/dev/null || true
        docker cp "$backup_path/redis_dump.rdb" queryfy-redis:/data/dump.rdb 2>/dev/null || true
        docker-compose -f "$COMPOSE_FILE" start redis 2>/dev/null || true
        log "Redis restored"
    fi

    # 3. Restore ChromaDB
    if [ -f "$backup_path/chroma_data.tar.gz" ]; then
        log "Restoring ChromaDB..."
        docker run --rm \
            -v nl2sql-app_chroma_data:/data \
            -v "$backup_path":/backup:ro \
            alpine sh -c "rm -rf /data/* && tar -xzf /backup/chroma_data.tar.gz -C /data" 2>/dev/null || {
                # Fallback to local restore
                if [ -d "$PROJECT_DIR/data" ]; then
                    rm -rf "$PROJECT_DIR/data/chroma_db"
                    tar -xzf "$backup_path/chroma_data.tar.gz" -C "$PROJECT_DIR/data"
                fi
            }
        log "ChromaDB restored"
    fi

    # 4. Restore configuration (optional, with confirmation)
    if [ -f "$backup_path/config.tar.gz" ]; then
        read -p "Restore configuration files? (yes/no): " restore_config
        if [ "$restore_config" = "yes" ]; then
            log "Restoring configuration..."
            tar -xzf "$backup_path/config.tar.gz" -C "$PROJECT_DIR"
            log "Configuration restored"
        fi
    fi

    # 5. Restart services
    log "Starting services..."
    docker-compose -f "$COMPOSE_FILE" up -d

    # 6. Wait for health check
    log "Waiting for services to be healthy..."
    sleep 30

    # 7. Verify restore
    if curl -sf http://localhost:80/health > /dev/null 2>&1; then
        log "=========================================="
        log "Restore completed successfully!"
        log "=========================================="
    else
        error "Services may not be healthy. Check logs:"
        echo "  docker-compose -f $COMPOSE_FILE logs"
    fi
}

# ==========================================
# Get latest backup
# ==========================================
get_latest_backup() {
    ls -t "$BACKUP_DIR" 2>/dev/null | head -1
}

# ==========================================
# Main
# ==========================================
main() {
    case "${1:-}" in
        --list|-l)
            list_backups
            ;;
        --help|-h)
            echo "Usage: $0 [backup_name|--list|--help]"
            echo ""
            echo "Options:"
            echo "  (none)        Restore from latest backup"
            echo "  backup_name   Restore specific backup (e.g., 20241130_020000)"
            echo "  --list        List available backups"
            echo "  --help        Show this help message"
            ;;
        "")
            # Restore from latest
            local latest=$(get_latest_backup)
            if [ -z "$latest" ]; then
                error "No backups found"
                exit 1
            fi
            log "Using latest backup: $latest"
            restore_backup "$latest"
            ;;
        *)
            restore_backup "$1"
            ;;
    esac
}

main "$@"
