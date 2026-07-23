#!/usr/bin/env bash
# =============================================================================
# TopicEye 数据库迁移回滚脚本
#
# 用法：
#   ./scripts/rollback_migration.sh [target_revision]
#
#   target_revision 可选，默认 -1（回退一个版本）。也可传具体 revision id，
#   或 base（回退到空库）。示例：
#     ./scripts/rollback_migration.sh          # 回退一格
#     ./scripts/rollback_migration.sh -2       # 回退两格
#     ./scripts/rollback_migration.sh a1b2c3d4 # 回退到指定版本
#
# 顺序（安全优先）：
#   1) 先跑 backup_db.sh 产出一份迁移前备份（SQLite 热备 / PG pg_dump）
#   2) 打印当前 alembic 版本，再执行 alembic downgrade <target>
#   3) 打印回退后的版本供核对
#
# 高风险操作：回滚会丢弃对应迁移引入的 schema/数据变更。生产执行前务必确认
# 备份成功、并在测试环境先验证过目标 revision。
# =============================================================================
set -euo pipefail

TARGET="${1:--1}"

# 定位 backend 根目录（本脚本在 backend/scripts/ 下），alembic.ini 在那里。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$BACKEND_DIR"

echo "[$(date)] === 迁移回滚开始 (target=$TARGET) ==="

# ── 1) 迁移前备份 ──
echo "[$(date)] 步骤 1/3：迁移前备份"
"$SCRIPT_DIR/backup_db.sh"

# ── 2) 记录当前版本并回滚 ──
echo "[$(date)] 步骤 2/3：当前 alembic 版本"
alembic current || true

echo "[$(date)] 执行 alembic downgrade $TARGET"
alembic downgrade "$TARGET"

# ── 3) 回滚后版本 ──
echo "[$(date)] 步骤 3/3：回滚后 alembic 版本"
alembic current || true

echo "[$(date)] === 迁移回滚完成。请启动应用确认 schema 正常。 ==="
