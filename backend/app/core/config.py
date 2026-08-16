from pydantic import field_validator
from pydantic_settings import BaseSettings

DEFAULT_LOCAL_SECRET_KEY = "topiceye-local-dev-secret-change-me"


class Settings(BaseSettings):
    # ── Runtime ──
    APP_ENV: str = "development"

    # ── Database ──
    # 留空则启动时报错；本地开发请在 .env 中设置（参考 .env.example）。
    DATABASE_URL: str = ""
    # DuckDB connects in-memory and ATTACHes the configured OLTP database
    # READ_ONLY. PostgreSQL is the supported DuckDB source.
    DUCKDB_THREADS: int = 2
    DUCKDB_MEMORY_LIMIT: str = "256MB"
    DUCKDB_EXTENSION_DIR: str = "./data/duckdb_extensions"
    # PostgreSQL 的 DuckDB ATTACH 在大数据量下可能执行长时间 COPY；生产部署可
    # 跳过启动期预热，优先保证 API 先可用（对应查询已有 SQLAlchemy 兜底）。
    DUCKDB_STARTUP_INIT_ENABLED: bool = True

    # ── Connection pool ──
    # SQLAlchemy async engine 连接池参数。
    # pool_size: 常驻连接数；max_overflow: 超出后的临时连接上限。
    # pool_recycle: 连接回收周期（秒），防止 PG 端 idle timeout 断连。
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 3600

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

    # CORS — comma-separated origins. 留空则不允许任何跨域请求；
    # 本地开发请在 .env 中设置（参考 .env.example）。
    CORS_ORIGINS: str = ""

    SCHEDULER_ENABLED: bool = True
    CACHE_WARMUP_ENABLED: bool = True
    READ_CACHE_TTL_SECONDS: float = 60.0
    # 整体同步超时(秒)。包含 fetch + classify + persist 三阶段。
    # 120s 对 arXiv/HN/36氪 等条目多的信源太短(classify 阶段 LLM 调用慢),
    # 300s 给足时间让正常同步完成,同时仍能在卡死时及时释放 worker。
    SOURCE_SYNC_TIMEOUT_SECONDS: int = 300
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
    # PDF 体积比 HTML 大一个数量级（4MB 论文抽出仅 ~2 万字），单独放宽。
    ARTICLE_READER_MAX_PDF_BYTES: int = 8_000_000
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
    POST_SYNC_ANALYSIS_TIME_BUDGET_SECONDS: int = 280
    POST_SYNC_MIN_REMAINING_SECONDS: int = 30
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
    AUTH_REFRESH_ATTEMPTS_PER_MINUTE: int = 20

    # ── Session management ──
    # Session 有效期（天）。默认 30 天。
    SESSION_DAYS: int = 30
    # 滑动续期阈值（天）。当 session 剩余有效期低于此值时，
    # get_user_for_token 会自动延长 expires_at 到 SESSION_DAYS。
    # 设为 0 可禁用滑动续期。
    SESSION_REFRESH_THRESHOLD_DAYS: int = 7

    # ── Auth cookie ──
    # 认证 token 通过 HttpOnly cookie 下发，前端 JS 无法读取，
    # 降低 XSS 窃取 token 的风险。Bearer header 仍然支持（API 客户端）。
    AUTH_COOKIE_NAME: str = "topiceye_auth"
    # 非生产环境（HTTP）必须设为 False；HTTPS 部署设为 True。
    AUTH_COOKIE_SECURE: bool = False
    # lax 允许顶层导航携带 cookie（OAuth 回调 302 需要此行为）。
    # 生产环境如需更严格可设为 "strict"（注意 OAuth 跳转可能丢失 cookie）。
    AUTH_COOKIE_SAMESITE: str = "lax"
    # 留空则绑定当前域名；跨子域可设为 ".example.com"。
    AUTH_COOKIE_DOMAIN: str = ""
    # 非 HttpOnly 的存在标记 cookie 名，前端据此判断是否登录。
    AUTH_PRESENCE_COOKIE_NAME: str = "topiceye_auth_present"
    # 非 HttpOnly 的过期时间 cookie 名，前端用于 refresh 逻辑。
    AUTH_EXPIRES_COOKIE_NAME: str = "topiceye_auth_expires_at"

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
    # OAuth 登录成功后重定向到的前端回调页（token 走 URL fragment 传回）。
    # 留空则 OAuth 回调会返回 400；部署时必须通过 .env 设置。
    OAUTH_FRONTEND_REDIRECT_URL: str = ""

    LLM_REQUESTS_PER_MINUTE: int = 60
    LLM_TOKENS_PER_MINUTE: int = 100000
    LLM_WORKER_CONCURRENCY: int = 4
    # 单次运行时调用的硬上限；模型 extra_params.timeout 只能把它调小，不能放大。
    LLM_COMPLETION_TIMEOUT_SECONDS: float = 45.0
    ANALYSIS_WORKER_CONCURRENCY: int = 3
    ANALYSIS_MAX_ATTEMPTS: int = 5
    ANALYSIS_RETRY_BASE_DELAY_SECONDS: int = 60
    ANALYSIS_RETRY_MAX_DELAY_SECONDS: int = 3600
    # 分析队列租约。领取时发放 fencing token，worker 定期续租；过期可被其他
    # worker 接管，旧 token 的最终写回会被条件更新拒绝。
    ANALYSIS_LEASE_SECONDS: int = 600
    ANALYSIS_HEARTBEAT_SECONDS: int = 60
    ANALYSIS_JOB_INFLIGHT_TTL_SECONDS: int = 900
    ANALYSIS_CASCADE_ENABLED: bool = False
    ANALYSIS_LITE_ROUTING_GROUP: str = "analysis_lite"
    ANALYSIS_PRO_ROUTING_GROUP: str = "default"
    ANALYSIS_CASCADE_ESCALATE_SCORE: float = 75.0
    ANALYSIS_CASCADE_MIN_CONFIDENCE: float = 0.75
    ENRICHMENT_WORKER_CONCURRENCY: int = 3
    CLASSIFICATION_WORKER_CONCURRENCY: int = 3

    # ── Content-event normalization ──
    # Event truth is the only read model. This switch controls only whether
    # the incremental classifier is disabled, audited, or allowed to write.
    EVENT_NORMALIZATION_MODE: str = "off"
    EVENT_NORMALIZATION_ROUTING_GROUP: str = "event_normalization"
    EVENT_NORMALIZATION_MAX_ITEMS: int = 50
    EVENT_NORMALIZATION_MAX_CANDIDATES: int = 8
    EVENT_NORMALIZATION_MAX_BOUNDARY_LLM_CALLS: int = 10
    EVENT_NORMALIZATION_WORKER_CONCURRENCY: int = 2
    EVENT_NORMALIZATION_LEASE_SECONDS: int = 900
    EVENT_NORMALIZATION_LOOKBACK_DAYS: int = 180
    EVENT_NORMALIZATION_AUTO_ACCEPT_CONFIDENCE: float = 0.88
    EVENT_NORMALIZATION_PREDICTION_AUDIT_MAX_BYTES: int = 65_536

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("DATABASE_URL 未设置。请在 .env 中配置 PostgreSQL 连接字符串，" "参考 .env.example。")
        return v

    @field_validator("OAUTH_FRONTEND_REDIRECT_URL")
    @classmethod
    def _validate_oauth_redirect_url(cls, v: str) -> str:
        # 允许空字符串（OAuth 未启用时不强制要求）；
        # 但如果填了值，必须是合法的 http(s) URL。
        if v and not v.startswith(("http://", "https://")):
            raise ValueError(f"OAUTH_FRONTEND_REDIRECT_URL 必须是 http:// 或 https:// 开头的 URL，" f"当前值: {v!r}")
        return v

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
