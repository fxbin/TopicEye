# =============================================================================
# TopicEye 统一命令入口
#
# 以前 setup/run/test/lint 命令散落在 AGENTS.md、docker-compose.yml、CI、
# .env.example 多处；.pre-commit-config.yaml 还承诺了一个并不存在的 `make lint`。
# 本 Makefile 把这些真实命令收拢成一个可发现的入口，`make lint` 现在真实可用。
#
# 常用：
#   make setup          安装后端 + 前端依赖
#   make dev            docker compose 起全栈
#   make test           跑后端 + 前端测试
#   make lint           完整质量门（ruff + 分层 + 前端类型检查）
# =============================================================================

.DEFAULT_GOAL := help
.PHONY: help setup dev dev-db test test-backend test-frontend \
        lint lint-backend lint-frontend layering backup

help:  ## 列出所有可用目标
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup:  ## 安装后端(dev)与前端依赖
	cd backend && pip install -r requirements-dev.txt
	cd frontend && npm ci

dev:  ## docker compose 起全栈（backend + frontend + postgres）
	docker compose up

dev-db:  ## 仅启动 PostgreSQL（本地开发用）
	docker compose up postgres

test: test-backend test-frontend  ## 跑后端 + 前端测试

test-backend:  ## 后端 pytest（需要 PG 运行在 localhost:5432）
	cd backend && python -m pytest tests/ -q

test-frontend:  ## 前端 vitest + 覆盖率门禁（对应 CI frontend-tests）
	cd frontend && npm run test:coverage

lint: lint-backend layering lint-frontend  ## 完整质量门（ruff + 分层 + tsc）

lint-backend:  ## 后端 ruff 全量检查 + 格式检查（手动质量门）
	cd backend && ruff check . && ruff format --check .

layering:  ## 分层纪律检查：api/v1 禁止直接 ORM 查询 / 禁用 import
	cd backend && python scripts/check_layering.py

lint-frontend:  ## 前端类型检查（AGENTS.md 首选，比 npm run lint 稳）
	cd frontend && npx tsc --noEmit

backup:  ## 备份数据库（PG pg_dump，保留最近 7 份）
	cd backend && ./scripts/backup_db.sh
