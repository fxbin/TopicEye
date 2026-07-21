#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# TopicEye 一键部署脚本 — 全 Docker 化（腾讯云轻量 4C4G）
# ═══════════════════════════════════════════════════════════════════
#
# 用法：
#   chmod +x deploy/deploy.sh
#   sudo ./deploy/deploy.sh
#
# 参数：
#   --domain <域名>      指定域名（默认用 IP，不签 SSL）
#   --no-ssl             强制不启用 SSL
#   --email <邮箱>       Let's Encrypt 注册邮箱（SSL 必填）
#   --env-file <路径>    指定 .env 文件（默认 ./backend/.env）
#
# 架构：
#   公网 80/443 ─► nginx 容器 ─► backend:8000 / frontend:3000
#   SSL 证书由 certbot 容器通过 webroot 模式签发
#   backend/frontend/postgres 不暴露端口，仅 Docker 内网通信
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step()  { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }

# ── 默认参数 ──────────────────────────────────────────────────
DOMAIN=""
ENABLE_SSL=true
EMAIL=""
ENV_FILE=""
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.prod.yml"
NGINX_CONF_DIR="${PROJECT_ROOT}/deploy/nginx/conf.d"
TEMPLATE="${PROJECT_ROOT}/deploy/nginx/topiceye.conf.template"
SSL_TEMPLATE="${PROJECT_ROOT}/deploy/nginx/ssl-server-block.conf"

# ── 解析参数 ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --domain)    DOMAIN="$2"; shift 2 ;;
        --no-ssl)    ENABLE_SSL=false; shift ;;
        --email)     EMAIL="$2"; shift 2 ;;
        --env-file)  ENV_FILE="$2"; shift 2 ;;
        *)           error "未知参数: $1" ;;
    esac
done

if [[ -z "$DOMAIN" ]]; then
    PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s ip.sb 2>/dev/null || echo "localhost")
    DOMAIN="$PUBLIC_IP"
    ENABLE_SSL=false
    warn "未指定 --domain，使用公网 IP: ${PUBLIC_IP}（不启用 SSL）"
fi

if [[ -z "$ENV_FILE" ]]; then
    ENV_FILE="${PROJECT_ROOT}/backend/.env"
fi

if [[ "$ENABLE_SSL" = true && -z "$EMAIL" ]]; then
    warn "启用 SSL 需要注册邮箱（--email），降级为不启用 SSL"
    ENABLE_SSL=false
fi

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║       TopicEye 部署配置                      ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  项目路径:  ${PROJECT_ROOT}"
echo "║  域名/IP:   ${DOMAIN}"
echo "║  SSL:       $([ "$ENABLE_SSL" = true ] && echo "启用 (${EMAIL})" || echo "禁用")"
echo "║  Env 文件:  ${ENV_FILE}"
echo "║  架构:      全 Docker（Nginx + Certbot 容器）"
echo "╚══════════════════════════════════════════════╝"
echo ""

read -p "确认以上配置正确？(y/N) " -r
echo
[[ ! $REPLY =~ ^[Yy]$ ]] && exit 0

# ═══════════════════════════════════════════════════════════════
# Step 1: 系统依赖 + Docker
# ═══════════════════════════════════════════════════════════════
step "1/6  检查系统依赖 & Docker"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl git ufw ca-certificates > /dev/null 2>&1

if ! command -v docker &>/dev/null; then
    info "安装 Docker..."
    curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun
    systemctl enable docker
    systemctl start docker
fi
info "Docker: $(docker --version)"
info "Docker Compose: $(docker compose version --short)"

# ═══════════════════════════════════════════════════════════════
# Step 2: 生成 Nginx 配置
# ═══════════════════════════════════════════════════════════════
step "2/6  生成 Nginx 配置"

mkdir -p "$NGINX_CONF_DIR"

# 从模板生成 HTTP 配置
cp "$TEMPLATE" "${NGINX_CONF_DIR}/topiceye.conf"
sed -i "s/__DOMAIN__/${DOMAIN}/g" "${NGINX_CONF_DIR}/topiceye.conf"

if [[ "$ENABLE_SSL" = true ]]; then
    info "SSL 已启用，稍后由 certbot 签发证书后注入 SSL 配置"
    # SSL 配置将在 Step 5 签发证书后注入
else
    # 清除 SSL 占位符（HTTP-only 模式）
    sed -i 's/# __SSL_REDIRECT__/# SSL disabled — HTTP only/' "${NGINX_CONF_DIR}/topiceye.conf"
    sed -i 's/# __SSL_SERVER_BLOCK__/# SSL disabled — HTTP only/' "${NGINX_CONF_DIR}/topiceye.conf"
    info "SSL 已禁用，使用纯 HTTP 模式"
fi

info "Nginx 配置: ${NGINX_CONF_DIR}/topiceye.conf"

# ═══════════════════════════════════════════════════════════════
# Step 3: .env 配置
# ═══════════════════════════════════════════════════════════════
step "3/6  检查环境配置"

if [[ ! -f "$ENV_FILE" ]]; then
    warn "未找到 ${ENV_FILE}，从模板创建..."
    cp "${PROJECT_ROOT}/backend/.env.production" "$ENV_FILE"

    if [[ "$ENABLE_SSL" = true ]]; then
        SCHEME="https"
    else
        SCHEME="http"
    fi

    sed -i "s|https://your-domain.com|${SCHEME}://${DOMAIN}|g" "$ENV_FILE"
    sed -i "s|CHANGE_THIS_TO_A_STRONG_PASSWORD|$(openssl rand -base64 16 | tr -d '/+=' | head -c 20)|g" "$ENV_FILE"
    sed -i "s|REPLACE_WITH_RANDOM_SECRET|$(openssl rand -hex 32)|g" "$ENV_FILE"

    warn "已生成 ${ENV_FILE}，请检查并修改："
    warn "  nano ${ENV_FILE}"
    echo ""
    echo "  重新运行部署："
    echo "  sudo ./deploy/deploy.sh --domain ${DOMAIN} $([ "$ENABLE_SSL" = true ] && echo "--email ${EMAIL}")"
    echo ""
    exit 0
else
    info "环境配置已存在: ${ENV_FILE}"
    grep -q "APP_ENV=development" "$ENV_FILE" 2>/dev/null && warn "APP_ENV=development，建议改为 production"
fi

# ═══════════════════════════════════════════════════════════════
# Step 4: 防火墙 + 构建启动
# ═══════════════════════════════════════════════════════════════
step "4/6  防火墙 & 构建启动"

if command -v ufw &>/dev/null; then
    ufw allow 22/tcp  comment "SSH"   2>/dev/null || true
    ufw allow 80/tcp  comment "HTTP"  2>/dev/null || true
    ufw allow 443/tcp comment "HTTPS" 2>/dev/null || true
    ufw --force enable 2>/dev/null || true
    info "防火墙: SSH(22) / HTTP(80) / HTTPS(443)"
else
    warn "ufw 未安装，请在腾讯云安全组放行 80/443"
fi

cd "$PROJECT_ROOT"

info "拉取最新代码..."
git pull --ff-only 2>/dev/null || warn "git pull 失败（可能已在最新版本）"

info "构建镜像（首次约 5-10 分钟）..."
docker compose -f "$COMPOSE_FILE" build --pull

info "启动服务（不含 certbot）..."
docker compose -f "$COMPOSE_FILE" up -d nginx backend frontend postgres

info "等待服务就绪..."
sleep 8

# 健康检查
MAX_RETRIES=30; RETRY=0
while [[ $RETRY -lt $MAX_RETRIES ]]; do
    if docker compose -f "$COMPOSE_FILE" exec -T backend python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live').read()" 2>/dev/null; then
        info "后端健康检查通过 ✓"
        break
    fi
    RETRY=$((RETRY + 1)); echo -n "."; sleep 3
done
echo ""
[[ $RETRY -ge $MAX_RETRIES ]] && warn "后端健康检查超时，查看日志: docker compose -f docker-compose.prod.yml logs backend"

# ═══════════════════════════════════════════════════════════════
# Step 5: SSL 证书签发（可选）
# ═══════════════════════════════════════════════════════════════
if [[ "$ENABLE_SSL" = true ]]; then
    step "5/6  签发 SSL 证书 (Let's Encrypt)"

    info "通过 certbot 容器签发证书..."
    info "域名: ${DOMAIN}, 邮箱: ${EMAIL}"

    docker compose -f "$COMPOSE_FILE" run --rm certbot \
        certonly --webroot -w /var/www/certbot \
        -d "$DOMAIN" \
        --non-interactive \
        --agree-tos \
        --email "$EMAIL" \
        --no-eff-email 2>&1 || {
            warn "Certbot 签发失败。可能原因："
            warn "  1. 域名未正确解析到本服务器 IP"
            warn "  2. 80 端口被防火墙/安全组拦截"
            warn "  3. Nginx 未正确响应 ACME challenge"
            warn ""
            warn "服务已以 HTTP 模式运行，可稍后手动签发："
            warn "  docker compose -f docker-compose.prod.yml run --rm certbot \\"
            warn "    certonly --webroot -w /var/www/certbot -d ${DOMAIN} --agree-tos --email ${EMAIL}"
            ENABLE_SSL=false
        }

    if [[ "$ENABLE_SSL" = true ]]; then
        info "证书签发成功，注入 SSL 配置到 Nginx..."

        # 注入 SSL server 块
        SSL_BLOCK=$(cat "$SSL_TEMPLATE")
        SSL_BLOCK="${SSL_BLOCK//__DOMAIN__/$DOMAIN}"

        # 写入临时文件再合并
        echo "$SSL_BLOCK" > "${NGINX_CONF_DIR}/_ssl_block.tmp"

        # 替换占位符：__SSL_REDIRECT__ → 301 跳转
        sed -i 's|# __SSL_REDIRECT__|return 301 https://$host$request_uri;|' \
            "${NGINX_CONF_DIR}/topiceye.conf"

        # 替换占位符：__SSL_SERVER_BLOCK__ → SSL server 块内容
        # 用 awk 处理多行替换
        awk -v ssl_file="${NGINX_CONF_DIR}/_ssl_block.tmp" '
            /# __SSL_SERVER_BLOCK__/ {
                while ((getline line < ssl_file) > 0) print line
                next
            }
            { print }
        ' "${NGINX_CONF_DIR}/topiceye.conf" > "${NGINX_CONF_DIR}/topiceye.conf.new"

        mv "${NGINX_CONF_DIR}/topiceye.conf.new" "${NGINX_CONF_DIR}/topiceye.conf"
        rm -f "${NGINX_CONF_DIR}/_ssl_block.tmp"

        # 重载 Nginx
        info "重载 Nginx 以启用 SSL..."
        docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -t 2>&1
        docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -s reload 2>&1
        info "SSL 已启用 ✓"

        # 设置自动续期 cron
        info "配置证书自动续期..."
        CRON_CMD="docker compose -f ${COMPOSE_FILE} run --rm certbot renew --quiet && docker compose -f ${COMPOSE_FILE} exec -T nginx nginx -s reload"
        (crontab -l 2>/dev/null | grep -v "certbot renew"; echo "0 3 * * * ${CRON_CMD}") | crontab -
        info "Cron 已设置：每日 03:00 自动续期"
    fi
else
    step "5/6  SSL 已跳过"
fi

# ═══════════════════════════════════════════════════════════════
# Step 6: 完成
# ═══════════════════════════════════════════════════════════════
step "6/6  部署完成"

if [[ "$ENABLE_SSL" = true ]]; then
    URL="https://${DOMAIN}"
else
    URL="http://${DOMAIN}"
fi

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ${GREEN}TopicEye 部署完成！${NC}                             ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  访问地址:  ${CYAN}${URL}${NC}"
echo "║  API 文档:  ${CYAN}${URL}/docs${NC}"
echo "║  监控大盘:  ${CYAN}${URL}/dashboard${NC}"
echo "║  管理后台:  ${CYAN}${URL}/admin${NC}"
echo "╠══════════════════════════════════════════════════╣"
echo "║  常用命令:                                        ║"
echo "║  查看日志:  docker compose -f docker-compose.prod.yml logs -f"
echo "║  重启服务:  docker compose -f docker-compose.prod.yml restart"
echo "║  停止服务:  docker compose -f docker-compose.prod.yml down"
echo "║  更新部署:  git pull && sudo ./deploy/deploy.sh --domain ${DOMAIN}"
if [[ "$ENABLE_SSL" = true ]]; then
echo "║  续期证书:  docker compose -f docker-compose.prod.yml run --rm certbot renew"
fi
echo "╚══════════════════════════════════════════════════╝"
echo ""
warn "首次启动需在管理后台配置 LLM 模型才能使用 AI 分析功能"
