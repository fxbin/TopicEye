import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.models.analysis_job  # noqa: F401
import app.models.article_reader_event  # noqa: F401
import app.models.article_snapshot  # noqa: F401
import app.models.category  # noqa: F401

# Ensure all models are imported for table creation
import app.models.daily_report  # noqa: F401
import app.models.fanqie  # noqa: F401
import app.models.favorite  # noqa: F401
import app.models.feedback  # noqa: F401
import app.models.llm_model  # noqa: F401
import app.models.metrics_snapshot  # noqa: F401
import app.models.monthly_digest  # noqa: F401
import app.models.mother_topic  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.pick_mark  # noqa: F401
import app.models.product_feedback  # noqa: F401
import app.models.prompt_registry  # noqa: F401
import app.models.qimao  # noqa: F401
import app.models.read_record  # noqa: F401
import app.models.scheduled_job  # noqa: F401
import app.models.trending  # noqa: F401
import app.models.user  # noqa: F401
import app.models.user_integration  # noqa: F401
import app.models.weekly_digest  # noqa: F401
import app.models.zhihu  # noqa: F401
from app.api.v1.auth import get_current_admin_user
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
from app.core.logging_config import configure_logging  # noqa: E402  — 在 basicConfig 之后
from app.core.request_utils import client_ip  # noqa: E402

_log_format = getattr(settings, "LOG_FORMAT", "text")
configure_logging(log_format=_log_format)

# ── Request-scoped ID (contextvar, safe for asyncio) ──
import contextvars  # noqa: E402  — 在 configure_logging 之后
import uuid as _uuid  # noqa: E402  — 同上

_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Current request ID (for logging / error responses). '- ' if outside a request."""
    return _request_id_ctx.get()


# We inject ``request_id`` via a LogRecord factory rather than a Filter on
# the root logger. Filters attached to a parent logger only run for records
# the parent itself emits — records from child loggers (``app.core.migrations``,
# ``alembic.*``, etc.) bubble up to the root *handler* without going through
# the root logger's filter chain, so ``%(request_id)s`` in the text formatter
# would raise ``KeyError: 'request_id'`` for every such record. A factory
# runs for *every* LogRecord, regardless of which logger created it, so the
# attribute is always present.
def _request_id_log_record_factory(*args, **kwargs):
    record = logging.LogRecord(*args, **kwargs)
    record.request_id = _request_id_ctx.get()
    return record


logging.setLogRecordFactory(_request_id_log_record_factory)


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


# DuckDB init 的同步 C 调用超时上限。analytics.available 在某些环境下
# (如 ATTACH 时另一个进程持写锁、扩展下载被 GFW 阻断)会永久阻塞,
# 推 worker thread + 超时兜底保证 lifespan 不会卡死。
_DUCKDB_INIT_TIMEOUT_SECONDS = 30.0


async def _init_duckdb_layer() -> bool:
    """Initialize DuckDB analytical layer with hard timeout.

    Returns:
        True if DuckDB ATTACH succeeded; False on timeout/error (degraded
        mode — scheduler / today_picks OLTP fallback still work).

    The actual ``analytics.available`` is a sync @property that runs C
    bindings (INSTALL extension, ATTACH, cross-engine SELECT). Putting it
    directly in the asyncio event loop freezes uvicorn lifespan forever.
    Pushing it to a worker thread + wait_for(N) keeps the event loop
    alive even when DuckDB is wedged.
    """
    from app.services.duckdb_service import get_analytics

    analytics = get_analytics()
    try:
        available = await asyncio.wait_for(
            asyncio.to_thread(lambda: analytics.available),
            timeout=_DUCKDB_INIT_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning(
            "DuckDB init timed out (%.0fs) — falling back to SQLAlchemy queries",
            _DUCKDB_INIT_TIMEOUT_SECONDS,
        )
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("DuckDB init skipped: %s — falling back to SQLAlchemy queries", e)
        return False
    return bool(available)


def ensure_runtime_secret_safety() -> None:
    """Fail fast when production would encrypt user secrets with the public dev key."""
    secret_material = (settings.INTEGRATION_SECRET_KEY or settings.APP_SECRET_KEY or "").strip()
    if settings.is_production and secret_material == DEFAULT_LOCAL_SECRET_KEY:
        raise RuntimeError("APP_ENV=production requires INTEGRATION_SECRET_KEY or a custom APP_SECRET_KEY")


def ensure_admin_seed_safety() -> None:
    """Fail fast when the admin seed password is a known leaked/placeholder value.

    默认种子密码曾误提交进 git 历史（b520ac7），视为已永久泄露；拒绝以该值
    （或模板占位符/过短口令）启动，避免任何沿用示例配置的部署被直接接管。
    注意：这里必须直接 raise 而不是走 _run_seed_step 的"降级为 warning"路径。
    """
    if not settings.ADMIN_SEED_ENABLED:
        return
    from app.services.auth_service import validate_admin_seed_password

    try:
        validate_admin_seed_password(settings.ADMIN_PASSWORD)
    except ValueError as exc:
        raise RuntimeError(f"Insecure ADMIN_PASSWORD refused at startup: {exc}") from exc


async def _run_seed_step(
    name: str,
    *,
    enabled: bool,
    run: Callable[[], Awaitable[None]],
    skip_reason: str | None = None,
) -> None:
    """Run one idempotent startup seed step with uniform error handling.

    Each seed step is an async callable that owns its session + commit. The
    helper centralises the ``enabled`` gate, skip log wording, and exception →
    warning downgrade so lifespan stays readable.

    Args:
        name: Human-readable step name used in logs (e.g. ``"Admin account"``).
        enabled: Whether config allows this step to run.
        run: Async callable performing the seed (import + session + commit).
        skip_reason: Optional reason when ``enabled`` is False; overrides the
            default ``"skipped by config"`` wording.
    """
    if not enabled:
        if skip_reason:
            logger.info("%s seed skipped: %s", name, skip_reason)
        else:
            logger.info("%s seed skipped by config", name)
        return
    try:
        await run()
    except Exception as e:  # noqa: BLE001 — seed steps must never block startup
        logger.warning("%s seed skipped: %s", name, e)


# NOTE: The former ``ensure_*_schema`` helpers (~730 lines of hand-written
# SQLite migration DDL) and ``ensure_sqlite_upgrade_schema`` have been replaced
# by Alembic. See ``alembic/`` and ``app/core/migrations.py``. Schema upgrades
# now run via ``run_startup_migrations`` (stamp head for legacy DBs, upgrade
# head for new DBs) inside ``lifespan`` below.


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cache_warmup_task

    ensure_runtime_secret_safety()
    ensure_admin_seed_safety()

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

    # ── Seed steps (idempotent; failures downgrade to warning, never block startup) ──
    admin_email = (settings.ADMIN_EMAIL or "").strip()
    admin_password = settings.ADMIN_PASSWORD or ""
    admin_enabled = bool(settings.ADMIN_SEED_ENABLED and admin_email and admin_password)
    admin_skip_reason = (
        "ADMIN_EMAIL and ADMIN_PASSWORD are not configured"
        if settings.ADMIN_SEED_ENABLED and not admin_enabled
        else None
    )

    async def _seed_admin() -> None:
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

    await _run_seed_step(
        "Admin account",
        enabled=admin_enabled,
        run=_seed_admin,
        skip_reason=admin_skip_reason,
    )

    seed_enabled = bool(settings.STARTUP_SEED_ENABLED)

    # Seed categories from hardcoded defaults (no-op if already seeded)
    async def _seed_categories() -> None:
        from app.services.classifier import seed_categories

        async with async_session() as seed_db:
            await seed_categories(seed_db)
            await seed_db.commit()

    await _run_seed_step("Category", enabled=seed_enabled, run=_seed_categories)

    # Seed mother topics (4 content pillars for 大痴小乙)
    async def _seed_mother_topics() -> None:
        from app.services.mother_topic_seed import seed_mother_topics

        # seed_mother_topics() opens its own session internally; the outer
        # session exists only to mirror the historical commit boundary.
        async with async_session() as seed_db:
            added = await seed_mother_topics()
            await seed_db.commit()
            logger.info("Mother topics seeded (%d new)", added)

    await _run_seed_step("Mother topic", enabled=seed_enabled, run=_seed_mother_topics)

    # Seed default content sources (idempotent, no-op for existing URLs)
    async def _seed_default_sources() -> None:
        from app.services.source_seed import seed_default_sources

        async with async_session() as seed_db:
            added = await seed_default_sources(seed_db)
            await seed_db.commit()
            logger.info("Default sources seeded (%d new)", added)

    await _run_seed_step("Default source", enabled=seed_enabled, run=_seed_default_sources)

    # Sync prompt registry (Sprint 3: read-only prompt catalog for admin)
    try:
        from app.services.prompt_registry_service import sync_prompt_registry

        async with async_session() as prompt_db:
            await sync_prompt_registry(prompt_db)
            await prompt_db.commit()
    except Exception as exc:
        logger.warning("Prompt registry sync skipped (non-fatal): %s", exc)

    # Initialize DuckDB analytical layer (in-memory + ATTACH SQLite/Postgres)
    # 关键:analytics.available 是同步 @property,内部要执行 INSTALL/LOAD 扩展 +
    # ATTACH + 跨引擎 SELECT。这些都是 C 同步调用,直接在 event loop 上跑会冻死
    # uvicorn lifespan,导致 scheduler 永远不起。
    # 修复:asyncio.to_thread 推 worker thread + asyncio.wait_for 30s 超时。
    # 即使 DuckDB 真的挂了,30s 后也会放弃,scheduler 仍能起来,_rescan_sources
    # 10 分钟一次的自愈也能跑。today_picks 在 DuckDB 不可用时走 commit 1a69db9
    # 加的 OLTP fallback 兜底。
    if settings.DUCKDB_STARTUP_INIT_ENABLED:
        available = await _init_duckdb_layer()
        if available:
            logger.info(
                "DuckDB analytical layer initialized (ATTACH %s READ_ONLY)",
                database_profile.backend,
            )
        else:
            logger.warning("DuckDB analytical layer not available — falling back to SQLAlchemy queries")
    else:
        logger.info("DuckDB startup initialization skipped — SQLAlchemy fallback remains available")

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

    # Drain interest-vector background rebuild tasks
    try:
        from app.services.interest_vector_service import drain_rebuild_tasks

        await drain_rebuild_tasks(timeout=10.0)
    except Exception:
        logger.warning("Interest vector task drain failed", exc_info=True)

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
    version="0.5.0",
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
from app.middleware.rate_limit import RateLimitMiddleware  # noqa: E402  — 路由挂载后装中间件

app.add_middleware(RateLimitMiddleware)

# HTTP 请求指标采集（计数/延迟/并发/限流命中/5xx 错误）
# 挂在最外层：捕获所有请求（含被 CORS / rate limit 拦截的），
# 但豁免 /metrics /health 等监控路径避免递归噪音。
from app.middleware.request_metrics import RequestMetricsMiddleware  # noqa: E402

app.add_middleware(RequestMetricsMiddleware)

# Mount v1 API routes
app.include_router(v1_router)

# Agent Skills discovery protocol — public, mounted at root (not under /api/v1)
# so `npx skills add https://<host>` can find /.well-known/agent-skills/index.json
from app.api.agent_skills import router as agent_skills_router  # noqa: E402

app.include_router(agent_skills_router)

# 内置监控大盘（自包含 HTML 页面，零外部依赖）
from app.api.dashboard import router as dashboard_router  # noqa: E402

app.include_router(dashboard_router)


# ── 根路径 /metrics 别名（Prometheus 标准约定）─────────────────────────
# prometheus.yml 默认 metrics_path: /metrics，此处提供根路径别名
# 避免用户必须配置 metrics_path: /api/v1/metrics
# 与 /api/v1/metrics 保持一致：要求管理员鉴权（Bearer admin token 或 cookie）。
@app.get("/metrics", tags=["metrics"], dependencies=[Depends(get_current_admin_user)])
async def root_metrics_alias():
    """Root-level /metrics alias → delegates to v1 prometheus_metrics."""
    from app.api.v1.metrics import prometheus_metrics

    return await prometheus_metrics()


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
    request_client_ip = client_ip(request)
    logger.exception(
        "Unhandled exception: %s %s ip=%s path=%s",
        request.method,
        exc,
        request_client_ip,
        request.url.path,
    )
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
        from app.services.duckdb_service import get_analytics, run_query

        duckdb_status = await run_query(get_analytics().status)
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
