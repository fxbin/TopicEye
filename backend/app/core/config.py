from pydantic_settings import BaseSettings

DEFAULT_LOCAL_SECRET_KEY = "topiceye-local-dev-secret-change-me"


class Settings(BaseSettings):
    # ── Runtime ──
    APP_ENV: str = "development"

    # ── Database ──
    DATABASE_URL: str = "sqlite+aiosqlite:///./topiceye.db"
    DATABASE_SQLITE_DOMAIN_SPLIT_ENABLED: bool = False
    DATABASE_SQLITE_DOMAIN_DIR: str = "./data/domains"
    # SQLite 写锁等待（毫秒）。默认 30s；批量写场景临时降到 500ms
    # 以快速返回 503，避免长事务拖慢读路径。
    SQLITE_BUSY_TIMEOUT_MS: int = 30000
    SQLITE_BUSY_TIMEOUT_BATCH_MS: int = 500
    # DuckDB connects in-memory and ATTACHes the configured OLTP database
    # READ_ONLY. SQLite and PostgreSQL are both supported as DuckDB sources.
    DUCKDB_THREADS: int = 2
    DUCKDB_MEMORY_LIMIT: str = "256MB"
    DUCKDB_EXTENSION_DIR: str = "./data/duckdb_extensions"
    # PostgreSQL 的 DuckDB ATTACH 在大数据量下可能执行长时间 COPY；生产部署可
    # 跳过启动期预热，优先保证 API 先可用（对应查询已有 SQLAlchemy 兜底）。
    DUCKDB_STARTUP_INIT_ENABLED: bool = True

    # ── Alerting ──
    ALERT_WEBHOOK_URL: str = ""  # 飞书/钉钉/Slack incoming webhook URL
    # 站点根 URL，用于 webhook 卡片中的"查看全部"按钮生成绝对链接。
    # 留空时按钮链接省略（仅推送原文链接，不推站内跳转）。
    SITE_BASE_URL: str = ""

    # ── Startup behavior ──
    AUTO_CREATE_TABLES_ON_STARTUP: bool = True
    STARTUP_SEED_ENABLED: bool = True
    ADMIN_SEED_ENABLED: bool = False
    ADMIN_EMAIL: str | None = None
    ADMIN_PASSWORD: str | None = None
    ADMIN_DISPLAY_NAME: str | None = None
    APP_SECRET_KEY: str = DEFAULT_LOCAL_SECRET_KEY
    INTEGRATION_SECRET_KEY: str | None = None

    # CORS — comma-separated origins. Defaults cover the local dev frontend
    # (Next.js serves on 3000); set CORS_ORIGINS for any deployed frontend.
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    SCHEDULER_ENABLED: bool = True
    CACHE_WARMUP_ENABLED: bool = True
    READ_CACHE_TTL_SECONDS: float = 60.0
    SOURCE_SYNC_TIMEOUT_SECONDS: int = 120
    SOURCE_SYNC_WORKER_CONCURRENCY: int = 3
    # 趋势雷达全量同步并发度。串行模式下 8 个国内信源 ConnectError 累加
    # 20s+ 撑爆 120s job 超时;并发后这些同时失败,总耗时≈最慢单源。
    TRENDING_SYNC_CONCURRENCY: int = 8
    # 单次 RSS fetch 的 httpx 超时(秒)。默认 15s 比原 30s 更激进,
    # 慢站(Wired 等)会快速 fail 释放 worker,不让其拖到 sync 整体超时(120s)。
    # 调大可以更宽容但风险是 sync 任务被堵住影响其他 source。
    RSS_SCRAPER_TIMEOUT_SECONDS: float = 15.0
    # 趋势雷达单次 fetch 的 httpx 超时(秒)。trending 站点多为国内 API,
    # 偶发慢响应,保留 30s 比 RSS 宽松一些避免误杀。
    HTTP_TRENDING_TIMEOUT_SECONDS: float = 30.0
    # 抓取层统一的 proxy 单一来源。设置后所有 scraper (content + trending)
    # 都会通过此 URL 出网,优先级高于环境变量 https_proxy / HTTPS_PROXY。
    # 留空则回退到环境变量(向后兼容现有部署)。
    HTTP_PROXY_URL: str | None = None
    # 抓取层品牌 UA,用于 content scraper (RSS / Atom / Podcast 等公开协议)。
    # 走礼貌爬虫语义,标识 TopicEye 身份,便于站点统计与联系。
    # 项目暂无对外域名,UA 暂不带 URL;后续有真实域名时再加回 (+https://...)。
    HTTP_SCRAPER_USER_AGENT: str = "TopicEye/1.0 Python-httpx"
    # 抓取层浏览器 UA,用于 trending scraper (国内榜单 API 大多拒绝
    # default Python-httpx UA,返回 403/406)。集中维护避免 16+ 处硬编码漂移。
    HTTP_BROWSER_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    # User-triggered reader mode.  This is intentionally a narrow, public-page
    # fetcher: no browser automation, cookies, proxies, or anti-bot bypass.
    ARTICLE_READER_ENABLED: bool = True
    ARTICLE_READER_FETCH_TIMEOUT_SECONDS: float = 12.0
    ARTICLE_READER_TOTAL_TIMEOUT_SECONDS: float = 16.0
    ARTICLE_READER_MAX_RESPONSE_BYTES: int = 1_500_000
    ARTICLE_READER_MAX_TEXT_CHARS: int = 100_000
    ARTICLE_READER_MAX_REDIRECTS: int = 3
    ARTICLE_READER_SNAPSHOT_TTL_SECONDS: int = 86_400
    ARTICLE_READER_ROBOTS_CACHE_SECONDS: int = 3_600
    ARTICLE_READER_ALLOWED_HOSTS: str = ""
    # Comma-separated browser UA pool. Each reader fetch picks one at random
    # to reduce per-request fingerprinting by WAF / bot-detection systems.
    # Override via env var to customise; a single value works as a 1-element pool.
    ARTICLE_READER_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36,"
        " Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36,"
        " Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0,"
        " Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15,"
        " Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    # Tier 2 fallback: curl_cffi for TLS fingerprint impersonation.
    # When httpx gets 403/blocked by WAF, curl_cffi retries with a real
    # browser TLS fingerprint (JA3/JA4).
    ARTICLE_READER_CURL_CFFI_FALLBACK: bool = True
    ARTICLE_READER_CURL_CFFI_IMPERSONATE: str = "auto"
    POST_SYNC_ANALYSIS_BATCH_SIZE: int = 10
    POST_SYNC_ANALYSIS_TIME_BUDGET_SECONDS: int = 520
    POST_SYNC_MIN_REMAINING_SECONDS: int = 90
    CREATION_PLAN_TIMEOUT_SECONDS: int = 45
    WEREAD_SKILL_API_URL: str | None = None

    # ── Agent config ──
    AGENT_MAX_STEPS: int = 10
    AGENT_TEMPERATURE: float = 0.3
    AGENT_MAX_RETRIES: int = 3

    # ── Rate limiting ──
    AUTH_LOGIN_ATTEMPTS_PER_MINUTE: int = 20
    AUTH_REGISTER_ATTEMPTS_PER_MINUTE: int = 10
    AUTH_SEND_CODE_ATTEMPTS_PER_MINUTE: int = 5

    # ── Request handling ──
    # 是否信任反向代理透传的 X-Forwarded-For 首段作为客户端真实 IP。
    # 部署在 Nginx / Caddy / CDN 后应保持 True；直接暴露公网时设为 False
    # 防止客户端伪造该头部绕过限流或污染审计日志。
    TRUST_FORWARDED_IP: bool = True

    # ── OAuth (Google / GitHub 登录) ──
    # 留空则该 provider 不启用。申请方式见 .env.example。
    OAUTH_GOOGLE_CLIENT_ID: str = ""
    OAUTH_GOOGLE_CLIENT_SECRET: str = ""
    OAUTH_GITHUB_CLIENT_ID: str = ""
    OAUTH_GITHUB_CLIENT_SECRET: str = ""
    # OAuth 登录成功后重定向到的前端回调页（token 走 URL fragment 传回）
    OAUTH_FRONTEND_REDIRECT_URL: str = "http://localhost:3000/oauth/callback"

    LLM_REQUESTS_PER_MINUTE: int = 60
    LLM_TOKENS_PER_MINUTE: int = 100000
    LLM_WORKER_CONCURRENCY: int = 4
    ANALYSIS_WORKER_CONCURRENCY: int = 3
    ANALYSIS_JOB_INFLIGHT_TTL_SECONDS: int = 900
    ANALYSIS_CASCADE_ENABLED: bool = False
    ANALYSIS_LITE_ROUTING_GROUP: str = "analysis_lite"
    ANALYSIS_PRO_ROUTING_GROUP: str = "default"
    ANALYSIS_CASCADE_ESCALATE_SCORE: float = 75.0
    ANALYSIS_CASCADE_MIN_CONFIDENCE: float = 0.75
    ENRICHMENT_WORKER_CONCURRENCY: int = 3
    CLASSIFICATION_WORKER_CONCURRENCY: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.strip().lower() in {"prod", "production"}

    @property
    def cors_origins(self) -> list[str]:
        """Parse CORS_ORIGINS into a clean list of origin strings."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def oauth_enabled_providers(self) -> list[str]:
        """已配置 client_id 的 OAuth provider 列表（前端据此渲染按钮）。"""
        providers: list[str] = []
        if self.OAUTH_GOOGLE_CLIENT_ID and self.OAUTH_GOOGLE_CLIENT_SECRET:
            providers.append("google")
        if self.OAUTH_GITHUB_CLIENT_ID and self.OAUTH_GITHUB_CLIENT_SECRET:
            providers.append("github")
        return providers


settings = Settings()
