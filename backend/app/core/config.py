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

    # ── Alerting ──
    ALERT_WEBHOOK_URL: str = ""  # 飞书/钉钉/Slack incoming webhook URL

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
