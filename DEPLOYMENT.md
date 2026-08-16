# TopicEye 部署与运维指南

> 完整的部署、监控、备份、故障排查文档。
> 涵盖 dev / 生产（PostgreSQL）两种部署形态 + 所有生产化能力。

---

## 1. 快速启动

### 1.1 开发模式（bind mount，代码改动即热重载）

```bash
# 默认 docker-compose.yml：dev 配置，uvicorn --reload + npm run dev
docker compose up -d --build
# 浏览器：http://localhost:3000
# API：http://localhost:8000/docs
# PG: 5432 (需 docker compose --profile postgres up -d)
```

⚠️ **开发配置不要用于生产**——`--reload` 会因代码改动反复触发服务重启，
杀正在跑的抓取任务（这是 TopicEye 历史上"不抓数据"故障的根因之一）。

### 1.2 稳定运行模式（推荐本地常驻与 4C4G+）

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

生产配置关键差异（vs dev）：
- backend 无 bind mount、无 `--reload`、用 `uvicorn --timeout-graceful-shutdown 30`
- frontend 用 `npm run start`（不是 dev）、build 在镜像里
- 全部有 `healthcheck`（30s 间隔查 `/health/live`）
- `depends_on.condition: service_healthy` 启动顺序保证
- `stop_grace_period: 45s`（> uvicorn 30s，确保优雅停机）
- 内存限制：backend 1g + frontend 512m + postgres 512m ≈ 2g

默认以 `APP_ENV=development` 保留既有本地密钥和加密数据，但仍使用无热重载的
生产运行进程。对外部署时请在项目根目录 `.env` 中显式设置
`APP_ENV=production`、`APP_SECRET_KEY` 和 `CORS_ORIGINS`；生产模式会拒绝默认密钥。

---

## 2. 环境变量

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `DATABASE_URL` | ✅ | *(必填)* | PostgreSQL 连接串（如 `postgresql+asyncpg://topiceye:***@postgres:5432/topiceye`；SQLite 支持已移除） |
| `CORS_ORIGINS` | ✅ | `http://localhost:3000` | 逗号分隔，前端域名 |
| `APP_SECRET_KEY` | ✅ | `topiceye-local-dev-secret-change-me` | 生产必须改（lifespan 会 fail-fast 检查） |
| `LOG_FORMAT` | ❌ | `text` | `text`（dev）/ `json`（生产聚合） |
| `AUTO_CREATE_TABLES_ON_STARTUP` | ❌ | `true` | 启动时跑 alembic migration |
| `CACHE_WARMUP_ENABLED` | ❌ | `true` | 启动时预热 read cache |
| `STARTUP_SEED_ENABLED` | ❌ | `true` | 启动时种入默认 source/category/mother topic |
| `DUCKDB_THREADS` | ❌ | `2` | DuckDB 分析层线程数 |
| `DUCKDB_MEMORY_LIMIT` | ❌ | `256MB` | DuckDB 内存上限 |
| `SCHEDULER_ENABLED` | ❌ | `true` | APScheduler 抓取调度 |
| `SOURCE_SYNC_TIMEOUT_SECONDS` | ❌ | `120` | 单源抓取超时 |
| `ALERT_WEBHOOK_URL` | ❌ | `""` | 飞书/钉钉/Slack webhook URL |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | ❌ | - | 启动时自动 seed admin 账号 |
| `LLM_*` | ❌ | - | 通过 UI 配置 LLM provider + API key |

### 生产必填

```env
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://topiceye:STRONG_PWD@postgres:5432/topiceye
CORS_ORIGINS=https://your-domain.com
APP_SECRET_KEY=<用 openssl rand -hex 32 生成>
LOG_FORMAT=json
ALERT_WEBHOOK_URL=https://hooks.slack.com/services/...   # 或飞书/钉钉
```

---

## 3. 监控

### 3.1 健康检查

| 端点 | 用途 | 用法 |
|---|---|---|
| `GET /health/live` | 轻量存活（DB ping） | Docker healthcheck / k8s liveness |
| `GET /health/ready` | 深度就绪（DB + DuckDB + scheduler） | 部署路由层 readiness |
| `GET /health` | `/health/ready` 的别名 | 向后兼容 |

容器内失败会标 `unhealthy`，自动触发重启。

### 3.2 Prometheus 指标

`GET /metrics` 暴露 Prometheus text format（无需认证）：

| 指标 | 含义 |
|---|---|
| `topiceye_sources_total{status}` | 各状态的 source 数 |
| `topiceye_content_total{status}` | 各状态的内容数 |
| `topiceye_content_recent_24h` | 最近 24h 新增内容数 |
| `topiceye_analyses_total` | AI 分析总数 |
| `topiceye_job_runs_total{status}` | 最近 24h job 运行数 |
| `topiceye_notifications_total` | 通知总数 |
| `topiceye_uptime_seconds` | 进程运行时间 |

Grafana 直接接 Prometheus data source，URL 填 `http://backend:8000/api/v1/metrics`。

### 3.3 信源抓取健康

`GET /api/v1/stats/sources-health`（admin only）：

- 每个 source 的 `status` / `last_sync_at` / `sync_error` / `next_sync_in_seconds`
- `content_count` / `recent_content_count_24h`（内容产出）
- `is_stale`：卡 SYNCING 超过 3× lease 的风险标记

### 3.4 全局 job 监控

`GET /api/v1/stats/jobs?days=7`：所有 `@track_job` 装饰的全局 job
（daily_report / post_sync_pipeline / cleanup 等）的成功率/耗时/最近失败。

### 3.5 Request-ID 排障

每个 HTTP 请求生成 12 位 hex `request_id`：
- 响应 header `X-Request-ID`
- 日志每行带 `request_id`（text 模式 + json 模式）
- 排障：`grep '3d2c40607f3e' backend.log` 拉出完整调用链

### 3.6 告警

`ALERT_WEBHOOK_URL` 配飞书/钉钉/Slack 后，`_rescan_sources`（每 10 分钟）
自动检查 `status=ERROR` 的 source，发 webhook 通知。**1 小时内同 alert_key 去重**，防告警风暴。

支持格式自动识别（按 URL 关键词）：
- `feishu.cn` / `larksuite.com` → 飞书格式
- `oapi.dingtalk.com` → 钉钉格式
- 其他 → 通用 `{"text": "..."}`（Slack/通用 webhook）

---

## 4. 备份与恢复

### 4.1 自动备份（推荐 cron）

```bash
# 每天凌晨 4 点备份，保留 7 份
0 4 * * * cd /app && ./backend/scripts/backup_db.sh /app/data/backups >> /app/data/backup.log 2>&1
```

脚本使用 `pg_dump -Fc` 自定义格式压缩备份（仅支持 PostgreSQL；遇 SQLite URL 会直接拒绝）。

保留策略：`BACKUP_KEEP_COUNT=7`（可调），超出按修改时间淘汰最旧。

### 4.2 手动备份

```bash
# PostgreSQL
docker exec topiceye-postgres-1 \
    pg_dump -U topiceye -Fc topiceye > /app/data/backups/manual_$(date +%Y%m%d).dump
```

### 4.3 恢复

```bash
# 停服
docker compose -f docker-compose.prod.yml down

# PostgreSQL 恢复
docker compose -f docker-compose.prod.yml up -d postgres -d
# 等待 postgres healthy
docker exec -i topiceye-postgres-1 pg_restore -U topiceye -d topiceye --clean --if-exists < /app/data/backups/manual_20260115.dump

# 启动
docker compose -f docker-compose.prod.yml up -d
```

### 4.4 PG sequence 同步（历史数据导入后必跑）

如果用 `COPY` 或 `INSERT ... (id, ...)` 显式导入了数据，PG SERIAL sequence
可能停留在旧值。lifespan 启动时会**自动**检查并 setval 修复（见 `app/core/sequence_health.py`）。

如需手动验证：
```sql
SELECT
    c.relname, a.attname,
    pg_get_serial_sequence(c.relname::text, a.attname) AS seq,
    (SELECT last_value FROM pg_get_serial_sequence(c.relname::text, a.attname)) AS seq_last,
    (SELECT MAX(a2.attname) FROM ONLY pg_class c2 JOIN pg_attribute a2 ON a2.attrelid = c2.oid
     WHERE c2.relname = c.relname) AS table_max
FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid
WHERE c.relkind = 'r' AND a.attisdropped = false
  AND pg_get_serial_sequence(c.relname::text, a.attname) IS NOT NULL;
```

如果 `seq_last < table_max`，需要：
```sql
SELECT setval(pg_get_serial_sequence('table_name', 'id'), (SELECT MAX(id) FROM table_name), true);
```

---

## 5. 故障排查

### 5.1 "今天没拉到新数据" / today_picks 是空的

按顺序排查：

```bash
# 1. source 状态
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/stats/sources-health | python -m json.tool

# 看：
# - status='syncing' 且 last_sync_ago > 2x interval → 卡死
# - status='error' 且 sync_error 含 "ON CONFLICT" → INSERT 路径 bug
# - 最近 5 min crawled 数为 0 但 source 在动 → 中间环节挂

# 2. backend 日志（grep request-id）
docker compose logs backend --since 10m | grep -E "Error|Exception"
docker compose logs backend --since 10m | grep "RequestID: 3d2c40607"

# 3. 确认 alembic 到位
docker compose exec -T postgres \
    psql -U topiceye -d topiceye -c "SELECT version_num FROM alembic_version;"

# 4. 看 content_items 时间分布
docker compose exec -T postgres psql -U topiceye -d topiceye -c \
    "SELECT MAX(crawled_at) FROM content_items;"

# 5. 如果 sequence 不同步（罕见，lifespan 应已自动修）
# 见 §4.4
```

### 5.2 LLM 调用全失败 / 烧配额

- 查 `/metrics` 看 `topiceye_job_runs_total{status="FAILED"}` 增长
- 熔断器状态：log 里 grep "CircuitBreaker" 看是 CLOSED/OPEN/HALF_OPEN
- 熔断开启时（OPEN），所有 LLM 调用走 fallback（summary_source=local_fallback 标记）
- cooldown 5 分钟后自动 HALF_OPEN 试探恢复

### 5.3 容器不停重启（unhealthy）

```bash
docker compose -f docker-compose.prod.yml ps
# STATUS 看是不是 "Restarting" 或 "Exit 1"

docker logs topiceye-backend-1 --tail 50
# 常见：app.core.sequence_health 或 migration 报错
# 启动 lifespan 错误 → uvicorn exit 1 → healthcheck 失败 → 反复重启
```

### 5.4 PG 连接数耗尽 / "too many clients"

```bash
# 看当前连接
docker compose exec -T postgres psql -U topiceye -d topiceye -c \
    "SELECT count(*) FROM pg_stat_activity WHERE datname='topiceye';"

# 应用层 connection pool 大小（settings / 引擎）
# 默认 SQLAlchemy pool_size=5 + max_overflow=10，单容器够用
# 多容器部署时按 worker 数 × pool_size < PG max_connections 估算
```

---

## 6. 升级与回滚

### 6.1 升级流程

```bash
# 1. 拉新代码
git pull origin main

# 2. 备份（强制）
./backend/scripts/backup_db.sh /app/data/backups/pre-upgrade

# 3. 重新 build + up
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# 启动时 lifespan 自动跑 alembic migration（无停机，但 brief 重启）
# 4. 验证
docker compose -f docker-compose.prod.yml ps  # 全部 healthy
curl http://localhost:8000/health/live  # 200
```

### 6.2 回滚

```bash
# 1. 停服
docker compose -f docker-compose.prod.yml down

# 2. 恢复 DB（向上兼容：旧代码 + 新 DB schema 通常 OK，向下可能不兼容）
# 见 §4.3

# 3. 切回老代码
git checkout <previous-tag>
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

**注意**：迁移只向上兼容（每次 migration 加字段/约束，不删）。
如果新版本 schema 用了新表，**老代码读到新表会忽略**（SQLAlchemy 行为），
但**新代码写老 schema 会失败**（缺字段）。回滚前先看 alembic 历史：

```bash
docker compose -f docker-compose.prod.yml exec backend alembic history
docker compose -f docker-compose.prod.yml exec backend alembic current
```

### 6.3 多容器防 alembic 撞车

如果未来部署多 backend 容器（HA），**多容器同时跑 alembic upgrade 可能撞 DDL 锁**。
当前实现是"best-effort"：所有容器都跑 migration，靠 PG 的 DDL 锁串行化。
高频重启可能短暂失败但不致命。**生产多实例建议**：
- 用 init container 在 docker-compose 里只跑一次 alembic
- 或加 advisory lock（见 `app/core/migrations.py` 待加）

---

## 7. 安全

### 7.1 API rate limit

- `/api/v1/auth/*`：20 req/min（防爆破）
- `/api/v1/creation/*`：30 req/min（LLM 昂贵）
- 其他 `/api/v1/*`：200 req/min
- `/health` / `/metrics`：豁免

超限返回 429 + `Retry-After` + `X-RateLimit-Limit` / `X-RateLimit-Remaining` headers。

**当前是单进程内存实现**——多实例需换 Redis。

### 7.2 CORS

`CORS_ORIGINS` 必须是**具体域名**（不能通配符），逗号分隔。
开发：`http://localhost:3000,http://127.0.0.1:3000`
生产：`https://your-domain.com`

### 7.3 API Token

每个用户可创建个人 access token（`POST /me/api-tokens`），
用于脚本/CI 调 API。明文 token 仅创建时返回一次，存 hash。
管理：`GET /me/api-tokens` / `POST /me/api-tokens/{id}/revoke` / `DELETE /me/api-tokens/{id}`

### 7.4 必须修改的密钥（生产部署 checklist）

- [ ] `APP_SECRET_KEY`（openssl rand -hex 32）
- [ ] `POSTGRES_PASSWORD`（强密码）
- [ ] `ADMIN_PASSWORD`（admin seed）
- [ ] LLM API keys（UI 配置，不在 .env）
- [ ] `ALERT_WEBHOOK_URL`（飞书/钉钉/Slack）
- [ ] `CORS_ORIGINS`（不要通配符）

---

## 8. CI/CD

`.github/workflows/ci.yml` 在 PR 上跑 5 个轻量门禁 job：

1. `frontend-types`：npx tsc --noEmit
2. `frontend-tests`：vitest + 覆盖率门禁
3. `backend-lint`：ruff check + format check（针对 PR 变更文件，阻断式）
4. `backend-layering`：API 分层 AST 检查（api → service → repo 单向依赖）
5. `security-scan`：pip-audit + npm audit（阻断式）

全量 PostgreSQL 测试不在 GitHub 跑（成本高）：本地执行 `make test-backend`
（一次性 postgres:16-alpine 容器跑在 127.0.0.1:5433，不占用开发栈，跑完即删）。

---

## 9. 关键概念速查

| 概念 | 说明 |
|---|---|
| **summary_source** | ai_analyses.summary_source 标记 summary 来源（llm_pro / llm_lite / local_fallback），影响 AI 摘要标签可信度 |
| **UNIQUE(source_id, content_hash)** | content_items 的去重约束；INSERT 走 ON CONFLICT DO NOTHING；不要显式插 id（PG SERIAL 自动生成） |
| **lease** | source.claim_sync 用 last_sync_at 防止并发同 source 抓取；超 lease 过期后下次调度可重新 claim |
| **ETag / Last-Modified** | sources 表存的 RSS 服务器响应头，下次抓取发 If-None-Match / If-Modified-Since，304 跳过 |
| **LLM Circuit Breaker** | 连续 5 次失败 → OPEN 5 分钟；OPEN 时所有 LLM 调用走 fallback（analysis._local_analysis_result） |
| **DuckDB ATTACH** | 后端进程内 DuckDB 实例 ATTACH PG 为 `oltp_db` 只读，stats 查询走 DuckDB；不可用时 fallback 到 SQLAlchemy（较慢） |
| **DuckDB 扩展** | `DUCKDB_EXTENSION_DIR=./data/duckdb_extensions`，启动时自动下载；目录权限要可写 |
