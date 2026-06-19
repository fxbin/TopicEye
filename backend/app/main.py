import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.models.analysis_job  # noqa: F401
import app.models.category  # noqa: F401

# Ensure all models are imported for table creation
import app.models.daily_report  # noqa: F401
import app.models.fanqie  # noqa: F401
import app.models.favorite  # noqa: F401
import app.models.feedback  # noqa: F401
import app.models.llm_model  # noqa: F401
import app.models.monthly_digest  # noqa: F401
import app.models.mother_topic  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.product_feedback  # noqa: F401
import app.models.qimao  # noqa: F401
import app.models.scheduled_job  # noqa: F401
import app.models.trending  # noqa: F401
import app.models.user  # noqa: F401
import app.models.user_integration  # noqa: F401
import app.models.weekly_digest  # noqa: F401
import app.models.zhihu  # noqa: F401
from app.api.v1.router import router as v1_router
from app.core.config import DEFAULT_LOCAL_SECRET_KEY, settings
from app.core.database import async_session, database_profile, engine
from app.core.db_backend import database_diagnostics, redact_database_secrets
from app.core.exceptions import AppException
from app.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_cache_warmup_task: asyncio.Task | None = None

# ── Structured logging (JSON for production aggregation) ──
from app.core.logging_config import configure_logging

_log_format = getattr(settings, "LOG_FORMAT", "text")
configure_logging(log_format=_log_format)

# ── Request-scoped ID (contextvar, safe for asyncio) ──
import contextvars
import uuid as _uuid

_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Current request ID (for logging / error responses). '- ' if outside a request."""
    return _request_id_ctx.get()


class RequestIdFilter(logging.Filter):
    """Inject request_id into every LogRecord for structured logging."""

    def filter(self, record):
        record.request_id = _request_id_ctx.get()
        return True


# Apply filter globally so all loggers get request_id
logging.getLogger().addFilter(RequestIdFilter())


class ProcessTimeHeaderMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract or generate request ID (allows upstream propagation)
        req_id = "-"
        for h_key, h_val in scope.get("headers", []):
            if h_key == b"x-request-id":
                req_id = h_val.decode("ascii", errors="replace")
                break
        if not req_id or req_id == "-":
            req_id = _uuid.uuid4().hex[:12]
        token = _request_id_ctx.set(req_id)

        started_at = time.perf_counter()

        async def send_with_process_time(message):
            if message["type"] == "http.response.start":
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                message.setdefault("headers", []).append((b"x-process-time-ms", f"{elapsed_ms:.3f}".encode("ascii")))
                message["headers"].append((b"x-request-id", req_id.encode("ascii")))
            await send(message)

        try:
            await self.app(scope, receive, send_with_process_time)
        finally:
            _request_id_ctx.reset(token)


def should_retry_stats_warmup(errors: list[str]) -> bool:
    """Retry stats in background only when startup critical stats warmup failed."""
    return any(error.startswith("stats:") for error in errors)


def ensure_runtime_secret_safety() -> None:
    """Fail fast when production would encrypt user secrets with the public dev key."""
    secret_material = (settings.INTEGRATION_SECRET_KEY or settings.APP_SECRET_KEY or "").strip()
    if settings.is_production and secret_material == DEFAULT_LOCAL_SECRET_KEY:
        raise RuntimeError("APP_ENV=production requires INTEGRATION_SECRET_KEY or a custom APP_SECRET_KEY")


# NOTE: The former ``ensure_*_schema`` helpers (~730 lines of hand-written
# SQLite migration DDL) and ``ensure_sqlite_upgrade_schema`` have been replaced
# by Alembic. See ``alembic/`` and ``app/core/migrations.py``. Schema upgrades
# now run via ``run_startup_migrations`` (stamp head for legacy DBs, upgrade
# head for new DBs) inside ``lifespan`` below.


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cache_warmup_task

    ensure_runtime_secret_safety()

    # Startup: bring the database to the latest Alembic revision. Legacy
    # databases shaped by the old ensure_* helpers are stamped as current;
    # brand-new databases are built via `upgrade head`.
    if settings.AUTO_CREATE_TABLES_ON_STARTUP:
        from app.core.migrations import run_startup_migrations

        await asyncio.to_thread(run_startup_migrations)
    else:
        logger.info("Startup schema migration skipped by config")

    # Post-migration: ensure PG sequences are >= max(id).
    # Historical data imports (COPY / explicit-id INSERT) can leave SERIAL
    # sequences stale, causing UniqueViolationError on subsequent inserts.
    try:
        from app.core.sequence_health import ensure_sequences_synced

        await ensure_sequences_synced()
    except Exception as exc:
        logger.warning("Sequence sync check failed (non-fatal): %s", exc)

    # Slow query listener (SQL > 1s log warning, > 5s alert webhook)
    try:
        from app.core.slow_query import attach_to_all_engines

        attach_to_all_engines()
    except Exception as exc:
        logger.warning("Slow query listener setup failed (non-fatal): %s", exc)

    admin_email = (settings.ADMIN_EMAIL or "").strip()
    admin_password = settings.ADMIN_PASSWORD or ""
    if settings.ADMIN_SEED_ENABLED and admin_email and admin_password:
        try:
            from app.services.auth_service import ensure_admin_user

            async with async_session() as admin_db:
                admin = await ensure_admin_user(
                    admin_db,
                    email=admin_email,
                    password=admin_password,
                    display_name=settings.ADMIN_DISPLAY_NAME,
                )
                await admin_db.commit()
                logger.info("Admin account ready: %s", admin.email)
        except Exception as e:
            logger.warning("Admin account seed skipped: %s", e)
    elif settings.ADMIN_SEED_ENABLED:
        logger.info("Admin account seed skipped: ADMIN_EMAIL and ADMIN_PASSWORD are not configured")
    else:
        logger.info("Admin account seed skipped by config")

    # Seed categories from hardcoded defaults (no-op if already seeded)
    if settings.STARTUP_SEED_ENABLED:
        try:
            from app.services.classifier import seed_categories

            async with async_session() as seed_db:
                await seed_categories(seed_db)
                await seed_db.commit()
        except Exception as e:
            logger.warning("Category seed skipped: %s", e)
    else:
        logger.info("Category seed skipped by config")

    # Seed mother topics (4 content pillars for 大痴小乙)
    if settings.STARTUP_SEED_ENABLED:
        try:
            from app.services.mother_topic_seed import seed_mother_topics

            async with async_session() as seed_db:
                added = await seed_mother_topics()
                await seed_db.commit()
                logger.info("Mother topics seeded (%d new)", added)
        except Exception as e:
            logger.warning("Mother topic seed skipped: %s", e)
    else:
        logger.info("Mother topic seed skipped by config")

    # Seed default content sources (idempotent, no-op for existing URLs)
    if settings.STARTUP_SEED_ENABLED:
        try:
            from app.services.source_seed import seed_default_sources

            async with async_session() as seed_db:
                added = await seed_default_sources(seed_db)
                await seed_db.commit()
                logger.info("Default sources seeded (%d new)", added)
        except Exception as e:
            logger.warning("Default source seed skipped: %s", e)
    else:
        logger.info("Default source seed skipped by config")

    # Initialize DuckDB analytical layer (in-memory + ATTACH SQLite)
    try:
        from app.services.duckdb_service import get_analytics

        analytics = get_analytics()
        if analytics.available:
            logger.info(
                "DuckDB analytical layer initialized (ATTACH %s READ_ONLY)",
                database_profile.backend,
            )
        else:
            logger.warning("DuckDB analytical layer not available — falling back to SQLAlchemy queries")
    except Exception as e:
        logger.warning("DuckDB init skipped: %s — falling back to SQLAlchemy queries", e)

    # Start the periodic scheduler
    if settings.SCHEDULER_ENABLED:
        start_scheduler()
        logger.info("Application startup complete — scheduler running")
    else:
        logger.info("Application startup complete — scheduler disabled by config")

    if settings.CACHE_WARMUP_ENABLED:
        from app.services.cache_warmup import warmup_read_caches, warmup_startup_critical_caches

        critical_warmup_result = await warmup_startup_critical_caches()
        if critical_warmup_result["errors"]:
            logger.warning(
                "Startup critical read cache warmup completed with errors: %s", critical_warmup_result["errors"]
            )
        else:
            logger.info("Startup critical read caches warmed")

        _cache_warmup_task = asyncio.create_task(
            warmup_read_caches(
                include_scoring_flow=False,
                include_stats=should_retry_stats_warmup(critical_warmup_result["errors"]),
            )
        )
        logger.info("Background read cache warmup scheduled")

    yield

    # Shutdown: stop scheduler, close connections, dispose engine
    if _cache_warmup_task and not _cache_warmup_task.done():
        _cache_warmup_task.cancel()
        with suppress(asyncio.CancelledError):
            await _cache_warmup_task
    shutdown_scheduler()

    # Close DuckDB analytics connection
    try:
        from app.services.duckdb_service import close_analytics

        close_analytics()
    except Exception:
        logger.warning("DuckDB analytics shutdown failed", exc_info=True)

    await engine.dispose()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="TopicEye API",
    description="AI-powered content discovery and topic analysis platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend origins from config (CORS_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.add_middleware(ProcessTimeHeaderMiddleware)

# Rate limiting（内存滑动窗口，按 IP + 路径前缀分桶）
from app.middleware.rate_limit import RateLimitMiddleware

app.add_middleware(RateLimitMiddleware)

# Mount v1 API routes
app.include_router(v1_router)


# ── Global exception handlers ─────────────────────────────────────────


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "detail": exc.detail},
        headers={} if not exc.detail else None,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": {}},
    )


@app.get("/health", tags=["health"])
async def health_check():
    """Alias for /health/ready (向后兼容)。"""
    return await health_ready()


@app.get("/health/live", tags=["health"])
async def health_live():
    """轻量存活检查（Docker healthcheck 用）。

    只确认：进程能响应 HTTP + DB 连接可达。
    不检查 DuckDB / scheduler / LLM——那些是就绪检查的事。
    """
    db_ok = True
    db_error = None
    try:
        async with async_session() as db:
            from sqlalchemy import text

            await db.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        db_error = type(exc).__name__

    if not db_ok:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "db": db_error},
        )
    return {"status": "alive", "service": "topiceye-backend"}


@app.get("/health/ready", tags=["health"])
async def health_ready():
    """就绪检查（深度）。

    检查 DB + DuckDB + scheduler 是否都正常。
    用于"服务是否可以接收流量"的判断（部署/路由层）。
    """
    diagnostics = database_diagnostics(database_profile)
    try:
        from app.services.duckdb_service import get_analytics

        duckdb_status = get_analytics().status()
    except Exception as exc:
        duckdb_status = {
            "status": "error",
            "available": False,
            "error": redact_database_secrets(str(exc), database_profile),
        }

    # scheduler 是否在跑
    try:
        from app.scheduler import scheduler as _scheduler

        scheduler_running = _scheduler.running
    except Exception:
        scheduler_running = False

    # 判定：DB OK 即 ready（DuckDB 有 fallback，scheduler 可能被配置禁用）
    db_ok = diagnostics.get("oltp") is not None
    overall = "ready" if db_ok else "not_ready"

    return {
        "status": overall,
        "service": "topiceye-backend",
        "database": {
            "backend": database_profile.backend,
            **diagnostics,
            "duckdb": duckdb_status,
        },
        "scheduler": {"running": scheduler_running},
    }
