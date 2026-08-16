#!/usr/bin/env bash
# =============================================================================
# 本地全量 PG 测试（承接 GitHub Actions 已移除的 backend-tests 作业）
#
# 为什么本地跑：GitHub Actions 上全量 PostgreSQL 测试成本高；本地用一次性
# 容器（127.0.0.1:5433）跑完即删，不占用开发栈的 postgres:5432，也就避开
# 了「测试 TRUNCATE 与运行中 backend 互相锁库」的已知竞争问题。
#
# 用法：
#   bash backend/scripts/test_full_local.sh [pytest 参数...]
#   make test-backend
# 可用环境变量：
#   TEST_PG_PORT   临时 PG 端口（默认 5433，被占用时换一个）
#   PYTHON         Python 解释器（默认 backend/venv/bin/python，缺省回退 python3）
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PORT="${TEST_PG_PORT:-5433}"
CONTAINER="topiceye-test-pg"
if [ -x "$BACKEND_DIR/venv/bin/python" ]; then
  PYTHON="${PYTHON:-$BACKEND_DIR/venv/bin/python}"
else
  PYTHON="${PYTHON:-python3}"
fi

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> 启动一次性 PostgreSQL (127.0.0.1:${PORT})..."
docker run --rm -d --name "$CONTAINER" \
  -e POSTGRES_DB=topiceye_test \
  -e POSTGRES_USER=topiceye \
  -e POSTGRES_PASSWORD=topiceye \
  -p "127.0.0.1:${PORT}:5432" \
  postgres:16-alpine >/dev/null

echo "==> 等待 PG 就绪..."
# 用 psql 而不是 pg_isready 探活：initdb 阶段的临时服务器也会让 pg_isready
# 短暂转绿，psql 真实连接成功才是可写状态。
ready=0
for _ in $(seq 1 30); do
  if docker exec "$CONTAINER" psql -U topiceye -d topiceye_test -c 'SELECT 1' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "PostgreSQL 30s 内未就绪，退出（容器已清理）" >&2
  exit 1
fi

echo "==> 运行全量测试（${PYTHON}）..."
cd "$BACKEND_DIR"
DATABASE_URL="postgresql+asyncpg://topiceye:topiceye@127.0.0.1:${PORT}/topiceye_test" \
DUCKDB_THREADS=1 \
DUCKDB_MEMORY_LIMIT=128MB \
  "$PYTHON" -m pytest tests/ -q --tb=short "$@"
