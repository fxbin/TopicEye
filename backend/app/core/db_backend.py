"""Database backend configuration helpers.

The app uses SQLAlchemy (PostgreSQL) for OLTP writes and DuckDB for OLAP reads.
Keep the backend detection here so database differences do not leak through the
service layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.engine import URL, make_url

logger = logging.getLogger(__name__)

DatabaseBackend = Literal["postgresql"]


@dataclass(frozen=True)
class DatabaseProfile:
    url: str
    backend: DatabaseBackend
    async_driver: str | None
    sync_url: str

    @property
    def is_postgresql(self) -> bool:
        return True


def database_backend(url: str) -> DatabaseBackend:
    driver = make_url(url).drivername.split("+", 1)[0]
    if driver in {"postgresql", "postgres"}:
        return "postgresql"
    raise ValueError(
        f"Unsupported database backend for DATABASE_URL: {driver}. "
        "Use postgresql+asyncpg://."
    )


def sync_database_url(url: str) -> str:
    parsed = make_url(url)
    # Alembic uses a sync engine and needs the sync driver. ``asyncpg`` is
    # async-only and incompatible with ``create_engine``; use ``psycopg``
    # (the project pins ``psycopg[binary]==3.2.13``) for migrations and
    # the runtime sync paths (lock acquisition, etc.).
    return _render_url(parsed.set(drivername="postgresql+psycopg"))


def async_database_url(url: str) -> str:
    parsed = make_url(url)
    return _render_url(parsed.set(drivername="postgresql+asyncpg"))


def create_database_profile(url: str) -> DatabaseProfile:
    backend = database_backend(url)
    normalized_url = async_database_url(url)
    normalized = make_url(normalized_url)
    return DatabaseProfile(
        url=normalized_url,
        backend=backend,
        async_driver=normalized.drivername.split("+", 1)[1] if "+" in normalized.drivername else None,
        sync_url=sync_database_url(normalized_url),
    )


def database_diagnostics(profile: DatabaseProfile) -> dict:
    """Return a safe database diagnostics payload for health endpoints."""
    return {
        "oltp": {
            "backend": profile.backend,
            "async_driver": profile.async_driver,
            "sync_driver": make_url(profile.sync_url).drivername,
        },
        "analytics": {
            "backend": "duckdb",
            "attach_source": profile.backend,
            "attach_mode": "read_only",
            "extension": duckdb_extension_name(profile),
        },
    }


def redact_database_secrets(message: str | None, profile: DatabaseProfile) -> str | None:
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
        # 兜底：URL 渲染失败时，按 scheme 做最保守的截断，避免带密码的明文 URL 泄漏到日志
        logger.warning("database URL redaction fallback engaged", exc_info=True)
        if "://" in redacted:
            scheme, _, rest = redacted.partition("://")
            redacted = f"{scheme}://***@{rest.split('@', 1)[-1]}" if "@" in rest else f"{scheme}://***"

    return redacted


def duckdb_attach_sql(profile: DatabaseProfile, *, alias: str = "oltp_db") -> str:
    """Return the DuckDB ATTACH statement for the configured OLTP backend."""
    conninfo = _postgres_conninfo(make_url(profile.url))
    conninfo = _duckdb_sql_literal(conninfo)
    return f"ATTACH '{conninfo}' AS {alias} (TYPE postgres, READ_ONLY)"


def duckdb_extension_name(profile: DatabaseProfile) -> str:
    return "postgres"


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


def ensure_aware_utc(dt: datetime | None) -> datetime | None:
    """把从 DB 读出的 datetime 规范成 aware UTC.

    背景: PG 列改 TIMESTAMP WITH TIME ZONE 后读出是 aware;
    代码层 (datetime.now(timezone.utc)) 也是 aware.
    在比较点统一调这个 helper 把 naive 当 UTC 处理 (兼容旧数据).

    输入 None 返回 None; 输入 aware 转 UTC; 输入 naive 假设已经是 UTC 加 tzinfo.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def ensure_naive_utc(dt: datetime | None) -> datetime | None:
    """把 datetime 转 naive UTC, 用于 SQL 查询参数.

    PG asyncpg 接受 naive (session 设 UTC 时按 UTC 解释).
    Python 层比较 (now - t) 仍用 aware (ensure_aware_utc).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt  # 已经是 naive
    return dt.astimezone(UTC).replace(tzinfo=None)
