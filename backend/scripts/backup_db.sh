#!/usr/bin/env bash
# =============================================================================
# TopicEye 数据库备份脚本
#
# 用法：
#   ./scripts/backup_db.sh [backup_dir]
#
# 自动检测 DATABASE_URL（从 .env 或环境变量），使用 pg_dump 备份 PostgreSQL。
#
# 保留策略：默认保留最近 7 份，更早的自动删除。
# 适合配 cron：每天凌晨跑一次。
#   0 4 * * * cd /app && ./scripts/backup_db.sh /app/data/backups >> /app/data/backup.log 2>&1
# =============================================================================
set -euo pipefail

BACKUP_DIR="${1:-./data/backups}"
KEEP_COUNT="${BACKUP_KEEP_COUNT:-7}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# 读取 DATABASE_URL（优先环境变量，其次 .env）
DATABASE_URL="${DATABASE_URL:-}"
if [[ -z "$DATABASE_URL" && -f .env ]]; then
    DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2- | tr -d '"' || true)"
fi

if [[ -z "$DATABASE_URL" ]]; then
    echo "ERROR: DATABASE_URL not set (env or .env)" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
echo "[$(date)] Backup started → $BACKUP_DIR"

if [[ "$DATABASE_URL" == postgresql* ]]; then
    # ── PostgreSQL backup ──
    BACKUP_FILE="$BACKUP_DIR/topiceye_${TIMESTAMP}.dump"

    # 从 URL 解析连接参数
    PG_URL="${DATABASE_URL#postgresql+asyncpg://}"
    PG_URL="${PG_URL#postgresql://}"
    PG_USER="$(echo "$PG_URL" | cut -d: -f1)"
    PG_PASS="$(echo "$PG_URL" | cut -d: -f2 | cut -d@ -f1)"
    PG_HOST="$(echo "$PG_URL" | cut -d@ -f2 | cut -d: -f1)"
    PG_PORT="$(echo "$PG_URL" | cut -d@ -f2 | cut -d: -f2 | cut -d/ -f1)"
    PG_DB="$(echo "$PG_URL" | cut -d/ -f2)"
    PG_PORT="${PG_PORT:-5432}"

    export PGPASSWORD="$PG_PASS"
    pg_dump -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -Fc -f "$BACKUP_FILE" "$PG_DB"
    unset PGPASSWORD
    echo "[$(date)] PostgreSQL backup → $BACKUP_FILE"

else
    echo "ERROR: Unsupported DATABASE_URL: ${DATABASE_URL%%+*}. Use postgresql+asyncpg://." >&2
    exit 1
fi

# ── 保留策略：只留最近 KEEP_COUNT 份 ──
if [[ "$KEEP_COUNT" -gt 0 ]]; then
    # 按修改时间倒序，删除超出的
    cd "$BACKUP_DIR" || exit 1
    ls -t topiceye_* 2>/dev/null | tail -n +"$((KEEP_COUNT + 1))" | while read -r old_file; do
        rm -f "$old_file"
        echo "[$(date)] Pruned old backup: $old_file"
    done
    cd - >/dev/null || true
fi

BACKUP_SIZE="$(du -h "$BACKUP_FILE" 2>/dev/null | cut -f1 || echo "?")"
echo "[$(date)] Backup done: $BACKUP_FILE ($BACKUP_SIZE), keeping last $KEEP_COUNT"
