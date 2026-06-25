#!/bin/bash
# ==========================================
# QueryfyAI - Health Check Script
# ==========================================
# Monitors application health and sends alerts
#
# Usage:
#   ./scripts/healthcheck.sh              # Run health check
#   ./scripts/healthcheck.sh --verbose    # Detailed output
#
# Cron example (every 5 minutes):
#   */5 * * * * /opt/queryfyai/scripts/healthcheck.sh >> /var/log/queryfyai/healthcheck.log 2>&1
# ==========================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Configuration
HEALTH_URL="${HEALTH_URL:-http://localhost:80/health}"
ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"
VERBOSE="${VERBOSE:-false}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ==========================================
# Logging
# ==========================================
log() {
    if [ "$VERBOSE" = "true" ] || [ "$1" = "ERROR" ] || [ "$1" = "ALERT" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1: $2"
    fi
}

# ==========================================
# Send alert
# ==========================================
send_alert() {
    local message="$1"
    local level="${2:-warning}"

    log "ALERT" "$message"

    # Send webhook if configured
    if [ -n "$ALERT_WEBHOOK_URL" ]; then
        curl -X POST "$ALERT_WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{
                \"text\": \"QueryfyAI Alert: $message\",
                \"level\": \"$level\",
                \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
                \"host\": \"$(hostname)\"
            }" 2>/dev/null || true
    fi
}

# ==========================================
# Check service health
# ==========================================
check_service() {
    local service="$1"
    local url="$2"

    if curl -sf "$url" > /dev/null 2>&1; then
        log "OK" "$service is healthy"
        return 0
    else
        log "ERROR" "$service is unhealthy"
        return 1
    fi
}

# ==========================================
# Check container status
# ==========================================
check_container() {
    local container="$1"
    local status=$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || echo "not_found")

    if [ "$status" = "running" ]; then
        log "OK" "Container $container is running"
        return 0
    else
        log "ERROR" "Container $container is $status"
        return 1
    fi
}

# ==========================================
# Check disk space
# ==========================================
check_disk() {
    local threshold="${1:-85}"
    local usage=$(df -h / | tail -1 | awk '{print $5}' | sed 's/%//')

    if [ "$usage" -lt "$threshold" ]; then
        log "OK" "Disk usage: ${usage}%"
        return 0
    else
        log "WARN" "Disk usage high: ${usage}%"
        return 1
    fi
}

# ==========================================
# Check memory
# ==========================================
check_memory() {
    local threshold="${1:-90}"

    if command -v free > /dev/null 2>&1; then
        local usage=$(free | grep Mem | awk '{print int($3/$2 * 100)}')
        if [ "$usage" -lt "$threshold" ]; then
            log "OK" "Memory usage: ${usage}%"
            return 0
        else
            log "WARN" "Memory usage high: ${usage}%"
            return 1
        fi
    fi
    return 0
}

# ==========================================
# Main health check
# ==========================================
main() {
    local failures=0
    local checks=0

    # Parse arguments
    for arg in "$@"; do
        case $arg in
            --verbose|-v)
                VERBOSE="true"
                ;;
        esac
    done

    log "INFO" "Starting health checks..."

    # 1. Check application health endpoint
    checks=$((checks + 1))
    if ! check_service "Backend" "$HEALTH_URL"; then
        failures=$((failures + 1))
        send_alert "Backend health check failed" "critical"
    fi

    # 2. Check containers
    for container in queryfy-backend queryfy-frontend queryfy-redis; do
        checks=$((checks + 1))
        if ! check_container "$container"; then
            failures=$((failures + 1))
            send_alert "Container $container is not running" "critical"
        fi
    done

    # 3. Check disk space
    checks=$((checks + 1))
    if ! check_disk 85; then
        failures=$((failures + 1))
        send_alert "Disk space running low" "warning"
    fi

    # 4. Check memory
    checks=$((checks + 1))
    if ! check_memory 90; then
        failures=$((failures + 1))
        send_alert "Memory usage high" "warning"
    fi

    # Summary
    if [ "$failures" -eq 0 ]; then
        log "INFO" "All $checks checks passed"
        exit 0
    else
        log "ERROR" "$failures of $checks checks failed"
        exit 1
    fi
}

main "$@"
