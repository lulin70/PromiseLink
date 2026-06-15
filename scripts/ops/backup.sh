#!/bin/bash
# PromiseLink SQLite Backup Script
# Usage: ./backup.sh [backup_dir]
set -e

BACKUP_DIR="${1:-/opt/promiselink/backups}"
DB_PATH="${2:-/opt/promiselink/data/promiselink.db}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/promiselink_$TIMESTAMP.db"
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

# SQLite safe backup (uses .backup command to avoid corruption)
echo "Backing up $DB_PATH to $BACKUP_FILE..."
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'" 2>/dev/null || cp "$DB_PATH" "$BACKUP_FILE"

# Compress
gzip "$BACKUP_FILE"
echo "Backup created: ${BACKUP_FILE}.gz ($(du -h ${BACKUP_FILE}.gz | cut -f1))"

# Clean old backups
find "$BACKUP_DIR" -name "promiselink_*.db.gz" -mtime +$RETENTION_DAYS -delete
echo "Cleaned backups older than $RETENTION_DAYS days"

# List current backups
echo "Current backups:"
ls -lh "$BACKUP_DIR"/promiselink_*.db.gz 2>/dev/null | tail -5
