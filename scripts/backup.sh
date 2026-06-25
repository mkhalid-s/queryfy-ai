#!/bin/bash
# ==========================================
# QueryfyAI - Backup Script
# ==========================================
# Backs up Redis data, ChromaDB, and configuration
#
# Usage:
#   ./scripts/backup.sh                 # Run backup
#   ./scripts/backup.sh --list          # List backups
#   ./scripts/backup.sh --cleanup       # Remove old backups
#
# Cron example (daily at 2 AM):
#   0 2 * * * /opt/queryfyai/scripts/backup.sh >> /var/log/queryfyai/backup.log 2>&1
# ==========================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-/opt/queryfyai/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
DATE=$(date +%Y%m%d_%H%M%S)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" >&2
}

# ==========================================
# Create backup
# ==========================================
create_backup() {
    log "Starting backup..."

    mkdir -p "$BACKUP_DIR/$DATE"
    local backup_path="$BACKUP_DIR/$DATE"

    # 1. Backup Redis (RDB snapshot)
    log "Backing up Redis..."
    if docker exec queryfy-redis redis-cli BGSAVE > /dev/null 2>&1; then
        sleep 5  # Wait for save to complete
        docker cp queryfy-redis:/data/dump.rdb "$backup_path/redis_dump.rdb" 2>/dev/null || true
        log "Redis backup completed"
    else
        log "Redis not running or backup failed (non-critical)"
    fi

    # 2. Backup ChromaDB
    log "Backing up ChromaDB..."
    if docker volume inspect nl2sql-app_chroma_data > /dev/null 2>&1; then
        docker run --rm \
            -v nl2sql-app_chroma_data:/data:ro \
            -v "$backup_path":/backup \
            alpine tar -czf /backup/chroma_data.tar.gz -C /data . 2>/dev/null || true
        log "ChromaDB backup completed"
    else
        log "ChromaDB volume not found (checking local path)"
        if [ -d "$PROJECT_DIR/data/chroma_db" ]; then
            tar -czf "$backup_path/chroma_data.tar.gz" -C "$PROJECT_DIR/data" chroma_db 2>/dev/null || true
        fi
    fi

    # 3. Backup configuration
    log "Backing up configuration..."
    tar -czf "$backup_path/config.tar.gz" \
        -C "$PROJECT_DIR" \
        .env.production \
        docker-compose.production.yml \
        2>/dev/null || true

    # 4. Create backup manifest
    cat > "$backup_path/manifest.json" << EOF
{
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "date": "$DATE",
    "files": [
        "redis_dump.rdb",
        "chroma_data.tar.gz",
        "config.tar.gz"
    ],
    "retention_days": $RETENTION_DAYS
}
EOF

    # 5. Calculate backup size
    local size=$(du -sh "$backup_path" | cut -f1)
    log "Backup completed: $backup_path ($size)"

    echo "$backup_path"
}

# ==========================================
# List backups
# ==========================================
list_backups() {
    echo ""
    echo "Available backups in $BACKUP_DIR:"
    echo "=========================================="

    if [ -d "$BACKUP_DIR" ]; then
        ls -lt "$BACKUP_DIR" | grep -E "^d" | head -20 | while read -r line; do
            dir=$(echo "$line" | awk '{print $NF}')
            if [ -f "$BACKUP_DIR/$dir/manifest.json" ]; then
                size=$(du -sh "$BACKUP_DIR/$dir" 2>/dev/null | cut -f1)
                echo "  $dir ($size)"
            fi
        done
    else
        echo "  No backups found"
    fi
    echo ""
}

# ==========================================
# Cleanup old backups
# ==========================================
cleanup_backups() {
    log "Cleaning up backups older than $RETENTION_DAYS days..."

    if [ -d "$BACKUP_DIR" ]; then
        local count=$(find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +$RETENTION_DAYS | wc -l)
        find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +$RETENTION_DAYS -exec rm -rf {} \;
        log "Removed $count old backup(s)"
    fi
}

# ==========================================
# Main
# ==========================================
main() {
    case "${1:-backup}" in
        --list|-l)
            list_backups
            ;;
        --cleanup|-c)
            cleanup_backups
            ;;
        --help|-h)
            echo "Usage: $0 [--list|--cleanup|--help]"
            echo ""
            echo "Options:"
            echo "  (none)      Create new backup"
            echo "  --list      List available backups"
            echo "  --cleanup   Remove backups older than $RETENTION_DAYS days"
            echo "  --help      Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  BACKUP_DIR      Backup directory (default: /opt/queryfyai/backups)"
            echo "  RETENTION_DAYS  Days to keep backups (default: 30)"
            ;;
        *)
            create_backup
            cleanup_backups
            ;;
    esac
}

main "$@"
