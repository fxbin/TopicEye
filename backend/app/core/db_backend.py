"""Database backend configuration helpers.

The app uses SQLAlchemy for OLTP writes and DuckDB for OLAP reads.  Keep the
backend detection here so SQLite/PostgreSQL differences do not leak through the
service layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Literal, Optional

from sqlalchemy.engine import URL, make_url

DatabaseBackend = Literal["sqlite", "postgresql", "unknown"]
SUPPORTED_DATABASE_BACKENDS = {"sqlite", "postgresql"}


SQLITE_DOMAIN_TABLES: Dict[str, tuple[str, ...]] = {
    "content": (
        "sources",
        "content_items",
        "content_metrics",
        "ai_analyses",
        "ignored_items",
        "user_feedback",
    ),
    "topics": (
        "categories",
        "topic_groups",
        "topic_trends",
        "mother_topics",
        "daily_reports",
        "weekly_digests",
        "monthly_digests",
    ),
    "trending": (
        "trending_items",
        "trending_snapshots",
    ),
    "webnovel": (
        "fanqie_categories",
        "fanqie_books",
        "fanqie_rank_snapshots",
        "qimao_books",
        "zhihu_albums",
        "zhihu_categories",
        "zhihu_rank_snapshots",
    ),
    "ops": (
        "app_settings",
        "notifications",
        "scheduled_jobs",
        "job_execution_logs",
        "llm_models",
        "model_evaluations",
        "llm_call_logs",
    ),
}


@dataclass(frozen=True)
class DatabaseProfile:
    url: str
    backend: DatabaseBackend
    async_driver: Optional[str]
    sync_url: str
    sqlite_path: Optional[str]
    sqlite_domain_urls: Dict[str, str]

    @property
    def is_sqlite(self) -> bool:
        return self.backend == "sqlite"

    @property
    def is_postgresql(self) -> bool:
        return self.backend == "postgresql"


def database_backend(url: str) -> DatabaseBackend:
    driver = make_url(url).drivername.split("+", 1)[0]
    if driver == "sqlite":
        return "sqlite"
    if driver in {"postgresql", "postgres"}:
        return "postgresql"
    return "unknown"


def sync_database_url(url: str) -> str:
    parsed = make_url(url)
    backend = database_backend(url)
    if backend == "sqlite":
        return _render_url(parsed.set(drivername="sqlite"))
    if backend == "postgresql":
        # Alembic uses a sync engine and needs the sync driver. ``asyncpg`` is
        # async-only and incompatible with ``create_engine``; use ``psycopg``
        # (the project pins ``psycopg[binary]==3.2.13``) for migrations and
        # the runtime sync paths (lock acquisition, etc.).
        return _render_url(parsed.set(drivername="postgresql+psycopg"))
    return _render_url(parsed)


def async_database_url(url: str) -> str:
    parsed = make_url(url)
    backend = database_backend(url)
    if backend == "sqlite":
        return _render_url(parsed.set(drivername="sqlite+aiosqlite"))
    if backend == "postgresql":
        return _render_url(parsed.set(drivername="postgresql+asyncpg"))
    return _render_url(parsed)


def sqlite_path_from_url(url: str) -> Optional[str]:
    parsed = make_url(url)
    if database_backend(url) != "sqlite":
        return None
    database = parsed.database
    if database in {None, "", ":memory:"}:
        return database
    return os.path.abspath(database)


def sqlite_domain_urls(base_url: str, domain_dir: str) -> Dict[str, str]:
    """Build SQLite URLs for optional domain split storage.

    This does not activate routing by itself.  It gives future repository-level
    routing a deterministic set of files while keeping single-file SQLite as the
    compatibility default.
    """
    if database_backend(base_url) != "sqlite":
        return {}
    root = Path(domain_dir).expanduser().resolve()
    return {domain: f"sqlite+aiosqlite:///{root / f'topiceye_{domain}.db'}" for domain in SQLITE_DOMAIN_TABLES}


def create_database_profile(
    url: str,
    *,
    sqlite_domain_split_enabled: bool = False,
    sqlite_domain_dir: str = "./data/domains",
) -> DatabaseProfile:
    backend = database_backend(url)
    if backend not in SUPPORTED_DATABASE_BACKENDS:
        driver = make_url(url).drivername
        raise ValueError(
            "Unsupported database backend for DATABASE_URL: "
            f"{driver}. Use sqlite+aiosqlite:// or postgresql+asyncpg://."
        )
    normalized_url = async_database_url(url)
    normalized = make_url(normalized_url)
    domain_urls = (
        sqlite_domain_urls(normalized_url, sqlite_domain_dir)
        if backend == "sqlite" and sqlite_domain_split_enabled
        else {}
    )
    return DatabaseProfile(
        url=normalized_url,
        backend=backend,
        async_driver=normalized.drivername.split("+", 1)[1] if "+" in normalized.drivername else None,
        sync_url=sync_database_url(normalized_url),
        sqlite_path=sqlite_path_from_url(normalized_url),
        sqlite_domain_urls=domain_urls,
    )


def sqlalchemy_connect_args(profile: DatabaseProfile) -> dict:
    if profile.is_sqlite:
        return {"check_same_thread": False}
    return {}


def database_diagnostics(profile: DatabaseProfile) -> dict:
    """Return a safe database diagnostics payload for health endpoints."""
    analytics = {
        "backend": "duckdb",
        "attach_source": profile.backend,
        "attach_mode": "read_only",
        "extension": None,
    }
    if profile.is_sqlite or profile.is_postgresql:
        analytics["extension"] = duckdb_extension_name(profile)

    return {
        "oltp": {
            "backend": profile.backend,
            "async_driver": profile.async_driver,
            "sync_driver": make_url(profile.sync_url).drivername,
            "sqlite_path": profile.sqlite_path if profile.is_sqlite else None,
            "sqlite_domain_split_enabled": bool(profile.sqlite_domain_urls),
            "sqlite_domain_count": len(profile.sqlite_domain_urls),
        },
        "analytics": analytics,
    }


def redact_database_secrets(message: Optional[str], profile: DatabaseProfile) -> Optional[str]:
    """Remove configured database credentials from diagnostic error text."""
    if message is None:
        return None

    redacted = str(message)
    parsed = make_url(profile.url)

    if parsed.password:
        password_variants = {
            parsed.password,
            _libpq_value(parsed.password),
            _duckdb_sql_literal(_libpq_value(parsed.password)),
        }
        for password in sorted(password_variants, key=len, reverse=True):
            redacted = redacted.replace(password, "***")

    try:
        unsafe_url = parsed.render_as_string(hide_password=False)
        safe_url = parsed.render_as_string(hide_password=True)
        redacted = redacted.replace(unsafe_url, safe_url)
    except Exception:
        pass

    return redacted


def duckdb_attach_sql(profile: DatabaseProfile, *, alias: str = "oltp_db") -> str:
    """Return the DuckDB ATTACH statement for the configured OLTP backend."""
    if profile.is_sqlite:
        if not profile.sqlite_path or profile.sqlite_path == ":memory:":
            raise ValueError("DuckDB analytics requires a file-backed SQLite database")
        path = _duckdb_sql_literal(profile.sqlite_path)
        return f"ATTACH '{path}' AS {alias} (TYPE SQLITE, READ_ONLY)"

    if profile.is_postgresql:
        conninfo = _postgres_conninfo(make_url(profile.url))
        conninfo = _duckdb_sql_literal(conninfo)
        return f"ATTACH '{conninfo}' AS {alias} (TYPE postgres, READ_ONLY)"

    raise ValueError(f"Unsupported DuckDB analytics backend: {profile.backend}")


def duckdb_extension_name(profile: DatabaseProfile) -> str:
    if profile.is_sqlite:
        return "sqlite"
    if profile.is_postgresql:
        return "postgres"
    raise ValueError(f"Unsupported DuckDB analytics backend: {profile.backend}")


def _postgres_conninfo(url: URL) -> str:
    parts = []
    if url.database:
        parts.append(("dbname", url.database))
    if url.username:
        parts.append(("user", url.username))
    if url.password:
        parts.append(("password", url.password))
    if url.host:
        parts.append(("host", url.host))
    if url.port:
        parts.append(("port", str(url.port)))
    for key, value in sorted(url.query.items()):
        if isinstance(value, tuple):
            value = value[-1]
        parts.append((key, str(value)))
    return " ".join(f"{key}={_libpq_value(value)}" for key, value in parts)


def _libpq_value(value: str) -> str:
    if value == "" or any(ch.isspace() or ch in "'\\" for ch in value):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return value


def _duckdb_sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _render_url(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def ensure_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """把从 DB 读出的 datetime 规范成 aware UTC.

    背景: PG 列改 TIMESTAMP WITH TIME ZONE 后读出是 aware;
    SQLite 端 DateTime(timezone=True) 仍丢 tzinfo, 读出是 naive.
    代码层 (datetime.now(timezone.utc)) 是 aware, 跟 naive 混用比较会抛
    TypeError. 在比较点统一调这个 helper 把 naive 当 UTC 处理.

    输入 None 返回 None; 输入 aware 转 UTC; 输入 naive 假设已经是 UTC 加 tzinfo.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ensure_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """把 datetime 转 naive UTC, 用于 SQL 查询参数.

    背景: SQLite aiosqlite driver 不支持 aware datetime 作为 SQL 绑定参数,
    会抛 TypeError. PG asyncpg 接受 naive (session 设 UTC 时按 UTC 解释).
    所以所有 SQL where 条件里的 datetime 参数统一用 naive UTC.

    Python 层比较 (now - t) 仍用 aware (ensure_aware_utc).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt  # 已经是 naive
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
