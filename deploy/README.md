# TopicEye 部署指南

腾讯云轻量服务器 (Ubuntu 22.04+ / 4C4G) 全 Docker 化部署。

---

## 架构

```
                      ┌──────────────────┐
  用户 ──80/443──►    │  nginx 容器       │
                      │  nginx:alpine     │
                      └────────┬─────────┘
                    ┌──────────┼──────────────┐
                    ▼                       ▼
             /api/ 等                   其余路径
                    │                       │
          ┌─────────┴──┐           ┌───────┴────┐
          │ backend    │           │ frontend   │
          │ :8000      │           │ :3000      │
          │ FastAPI    │           │ Next.js    │
          │ +DuckDB    │           │ SSR        │
          │ +Scheduler │           │            │
          └─────┬──────┘           └────────────┘
                │
          ┌─────┴──────┐
          │ postgres   │
          │ :5432      │
          │ PG 16      │
          └────────────┘

  SSL: certbot 容器 --webroot 模式签发，证书存 Docker volume
```

**所有业务容器不暴露端口到宿主机**，只有 nginx 容器映射 80/443。
backend / frontend / postgres 之间通过 Docker 内网服务名通信。

## 前置条件

1. **服务器**：腾讯云轻量 4C4G，Ubuntu 22.04+
2. **安全组**：放行 22 (SSH) / 80 (HTTP) / 443 (HTTPS)
3. **域名**（可选）：已解析到服务器 IP，用于 SSL 证书

## 快速部署

```bash
# 1. 登录服务器
ssh ubuntu@your-server-ip

# 2. 拉取代码
git clone https://github.com/fxbin/TopicEye.git && cd TopicEye

# 3a. 有域名 — 启用 SSL
sudo ./deploy/deploy.sh --domain topiceye.example.com --email you@email.com

# 3b. 无域名 — 用 IP 访问（HTTP）
sudo ./deploy/deploy.sh
```

脚本自动完成：
- 安装 Docker（如未安装）
- 生成 Nginx 反代配置
- 配置防火墙 (ufw)
- 构建并启动全部 Docker 服务（nginx + backend + frontend + postgres）
- 通过 certbot 容器签发 Let's Encrypt SSL 证书（有域名时）
- 设置证书自动续期 cron

首次运行会提示编辑 `.env`：

```bash
# 4. 编辑配置（首次部署）
cp backend/.env.production backend/.env
nano backend/.env

# 必填项：
#   APP_SECRET_KEY   → 已自动生成随机值
#   CORS_ORIGINS     → 已自动替换为你的域名
#   ADMIN_PASSWORD   → 已自动生成随机值（可修改）

# 5. 重新运行部署
sudo ./deploy/deploy.sh --domain your-domain.com --email you@email.com
```

## 文件清单

```
deploy/
├── deploy.sh                          # 一键部署脚本
├── nginx/
│   ├── topiceye.conf.template         # Nginx 配置模板（HTTP）
│   ├── ssl-server-block.conf          # SSL server 块模板
│   └── conf.d/                        # 运行时生成的配置（deploy.sh 写入）
└── README.md                          # 本文件

backend/
└── .env.production                    # 生产环境 .env 模板

docker-compose.prod.yml                # 生产 Docker Compose（含 nginx + certbot）
```

## Docker Compose 服务

| 服务 | 镜像 | 端口 | 说明 |
|---|---|---|---|
| `nginx` | nginx:alpine | 80, 443 → 宿主机 | 反向代理，唯一暴露公网 |
| `backend` | 自构建 (python:3.12-slim) | 8000 (仅内网) | FastAPI + APScheduler + DuckDB |
| `frontend` | 自构建 (node:20-alpine) | 3000 (仅内网) | Next.js production |
| `postgres` | postgres:16-alpine | 5432 (仅内网) | PostgreSQL 16 |
| `certbot` | certbot/certbot | — | 按需运行，签发/续期 SSL |

## 资源预算 (4C4G)

| 服务 | 内存限制 | 说明 |
|---|---|---|
| nginx | 128m | 反向代理 |
| backend | 1G | FastAPI + APScheduler + DuckDB |
| postgres | 512m | PG 16 Alpine |
| frontend | 512m | Next.js production |
| certbot | ~30m | 按需运行，不常驻 |
| 系统 + Docker | ~1G | OS 开销 |
| **合计** | **~3.2G** | **4G 余量充足** |

## Nginx 路由规则

| 路径 | 目标 | 说明 |
|---|---|---|
| `/.well-known/acme-challenge/` | certbot webroot | SSL 证书验证 |
| `/api/` | backend:8000 | FastAPI 主 API |
| `/docs` | backend:8000 | Swagger UI |
| `/openapi.json` | backend:8000 | OpenAPI Schema |
| `/dashboard` | backend:8000 | 内置监控大盘 |
| `/metrics` | backend:8000 | Prometheus 端点 |
| `/health/` | backend:8000 | 健康检查 |
| 其余所有 | frontend:3000 | Next.js SSR + 静态资源 |

## 常用命令

```bash
# 查看服务状态
docker compose -f docker-compose.prod.yml ps

# 查看实时日志
docker compose -f docker-compose.prod.yml logs -f
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f nginx

# 重启单个服务
docker compose -f docker-compose.prod.yml restart backend
docker compose -f docker-compose.prod.yml restart nginx

# 停止 / 启动
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d

# 更新部署
git pull
sudo ./deploy/deploy.sh --domain your-domain.com --email you@email.com

# 进入容器
docker compose -f docker-compose.prod.yml exec backend bash
docker compose -f docker-compose.prod.yml exec postgres psql -U topiceye

# Nginx 重载（修改配置后）
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

## SSL 证书管理

```bash
# 手动签发
docker compose -f docker-compose.prod.yml run --rm certbot \
  certonly --webroot -w /var/www/certbot -d your-domain.com \
  --agree-tos --email you@email.com

# 手动续期
docker compose -f docker-compose.prod.yml run --rm certbot renew
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload

# 测试续期（dry-run）
docker compose -f docker-compose.prod.yml run --rm certbot renew --dry-run
```

deploy.sh 已自动设置 cron：每日 03:00 检查续期。

## 故障排查

### 服务无法启动

```bash
# 查看后端日志
docker compose -f docker-compose.prod.yml logs backend --tail 50

# 常见问题：
# 1. APP_SECRET_KEY 未设置 → 编辑 .env 添加
# 2. DATABASE_URL 错误 → 确认 postgres 容器已启动
# 3. CORS_ORIGINS 不匹配 → 确认包含你的域名
```

### Nginx 502 Bad Gateway

```bash
# 检查后端容器是否健康
docker compose -f docker-compose.prod.yml ps

# 从 Nginx 容器内测试后端
docker compose -f docker-compose.prod.yml exec nginx \
  wget -qO- http://backend:8000/health/live

# 检查 Nginx 配置
docker compose -f docker-compose.prod.yml exec nginx nginx -t
```

### DuckDB 扩展下载失败

Dockerfile 已在构建阶段预下载。如果仍失败：

```bash
docker compose -f docker-compose.prod.yml exec backend python -c \
  "import duckdb; con=duckdb.connect(':memory:'); con.execute('INSTALL postgres; LOAD postgres;')"
```

### 磁盘空间不足

```bash
# 清理 Docker 无用资源
docker system prune -af --volumes

# 查看磁盘
df -h
```

## 备份

```bash
# 备份 PostgreSQL
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U topiceye topiceye > backup_$(date +%Y%m%d).sql

# 备份后端数据（DuckDB + 缓存）
docker run --rm -v $(pwd)/backend-data:/data -v $(pwd):/backup alpine \
  tar czf /backup/data-backup-$(date +%Y%m%d).tar.gz /data

# 备份 .env
cp backend/.env backup.env.$(date +%Y%m%d)
```
