#!/bin/bash
# backup-personal.sh - Daily backup for personal services stack
# Run via cron: 0 3 * * * $STEWARDOS_ROOT/services/backup-personal.sh
set -euo pipefail

BACKUP_DIR="/backup/personal"
LOG_FILE="/var/log/personal-backup.log"
RETENTION_DAYS=60
DATE=$(date +%Y-%m-%d_%H%M%S)
COMPOSE_DIR="$STEWARDOS_ROOT/services"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== Personal services backup started ==="

# Ensure backup directories exist
mkdir -p "$BACKUP_DIR/postgres"
mkdir -p "$BACKUP_DIR/sqlite"
mkdir -p "$BACKUP_DIR/volumes"

# ─── 1. PostgreSQL database dumps ───
log "Dumping PostgreSQL databases..."
for db in stewardos_db ghostfolio paperless wger plane postgres; do
    DUMP_FILE="$BACKUP_DIR/postgres/${db}_${DATE}.sql"
    if docker exec personal-db pg_dump -U postgres -d "$db" > "$DUMP_FILE" 2>>"$LOG_FILE"; then
        gzip "$DUMP_FILE"
        log "  OK: $db -> ${DUMP_FILE}.gz"
    else
        log "  FAIL: $db dump failed"
    fi
done

# ─── 2. SQLite database copies ───
log "Copying SQLite databases..."

# Mealie
MEALIE_VOL=$(docker volume inspect mealie-data --format '{{ .Mountpoint }}' 2>/dev/null || echo "")
if [ -n "$MEALIE_VOL" ]; then
    MEALIE_DB=$(find "$MEALIE_VOL" -name "mealie.db" -o -name "*.db" 2>/dev/null | head -1)
    if [ -n "$MEALIE_DB" ]; then
        cp "$MEALIE_DB" "$BACKUP_DIR/sqlite/mealie_${DATE}.db"
        log "  OK: mealie SQLite"
    else
        log "  SKIP: mealie DB file not found"
    fi
fi

# Actual Budget
ACTUAL_VOL=$(docker volume inspect actual-data --format '{{ .Mountpoint }}' 2>/dev/null || echo "")
if [ -n "$ACTUAL_VOL" ]; then
    if [ -d "$ACTUAL_VOL" ]; then
        tar -czf "$BACKUP_DIR/sqlite/actual-budget_${DATE}.tar.gz" -C "$ACTUAL_VOL" . 2>>"$LOG_FILE"
        log "  OK: actual-budget data"
    fi
fi

# Memos
MEMOS_VOL=$(docker volume inspect memos-data --format '{{ .Mountpoint }}' 2>/dev/null || echo "")
if [ -n "$MEMOS_VOL" ]; then
    MEMOS_DB=$(find "$MEMOS_VOL" -name "memos_prod.db" -o -name "*.db" 2>/dev/null | head -1)
    if [ -n "$MEMOS_DB" ]; then
        cp "$MEMOS_DB" "$BACKUP_DIR/sqlite/memos_${DATE}.db"
        log "  OK: memos SQLite"
    else
        log "  SKIP: memos DB file not found"
    fi
fi

# Homebox
HOMEBOX_VOL=$(docker volume inspect homebox-data --format '{{ .Mountpoint }}' 2>/dev/null || echo "")
if [ -n "$HOMEBOX_VOL" ]; then
    HOMEBOX_DB=$(find "$HOMEBOX_VOL" -name "homebox.db" -o -name "*.db" 2>/dev/null | head -1)
    if [ -n "$HOMEBOX_DB" ]; then
        cp "$HOMEBOX_DB" "$BACKUP_DIR/sqlite/homebox_${DATE}.db"
        log "  OK: homebox SQLite"
    else
        log "  SKIP: homebox DB file not found"
    fi
fi

# Grocy
GROCY_VOL=$(docker volume inspect grocy-data --format '{{ .Mountpoint }}' 2>/dev/null || echo "")
if [ -n "$GROCY_VOL" ]; then
    GROCY_DB=$(find "$GROCY_VOL" -name "grocy.db" 2>/dev/null | head -1)
    if [ -n "$GROCY_DB" ]; then
        cp "$GROCY_DB" "$BACKUP_DIR/sqlite/grocy_${DATE}.db"
        log "  OK: grocy SQLite"
    else
        log "  SKIP: grocy DB file not found"
    fi
fi

# ─── 3. Tar critical volumes ───
log "Archiving named volumes..."
for vol in vaultwarden-data paperless-data paperless-media plane-minio-data; do
    VOL_PATH=$(docker volume inspect "$vol" --format '{{ .Mountpoint }}' 2>/dev/null || echo "")
    if [ -n "$VOL_PATH" ] && [ -d "$VOL_PATH" ]; then
        TAR_FILE="$BACKUP_DIR/volumes/${vol}_${DATE}.tar.gz"
        tar -czf "$TAR_FILE" -C "$VOL_PATH" . 2>>"$LOG_FILE"
        log "  OK: $vol -> $TAR_FILE"
    else
        log "  SKIP: volume $vol not found"
    fi
done

# ─── 4. Retention cleanup ───
log "Cleaning up backups older than ${RETENTION_DAYS} days..."
DELETED=$(find "$BACKUP_DIR" -type f \( -name "*.gz" -o -name "*.sql" -o -name "*.db" \) -mtime +${RETENTION_DAYS} -delete -print | wc -l)
log "  Removed $DELETED old backup files"

log "=== Personal services backup completed ==="
