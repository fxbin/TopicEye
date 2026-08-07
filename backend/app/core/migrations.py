"""Startup database migration runner.

Replaces the former hand-written SQLite ``ensure_*_schema`` helpers in
``app/main.py``. On startup we bring the database to the latest Alembic
revision:

- Brand-new (empty) database → ``alembic upgrade head`` builds all tables.
- Existing database that predates Alembic (tables present, no
  ``alembic_version`` row) → ``alembic stamp head`` records it as current
  without running DDL, because those databases were already shaped by the old
  ``ensure_*`` helpers.
- Database already under Alembic control → ``alembic upgrade head`` applies
  any pending revisions.

The runner is synchronous on purpose: Alembic's command API is synchronous,
and wrapping it in ``asyncio.to_thread`` keeps the async startup path clean
without contending with the async engine.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.core.config import settings
from app.core.db_backend import create_database_profile

logger = logging.getLogger(__name__)

# migrations.py lives in app/core/; backend root is core -> app -> backend.
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"


def _build_alembic_config() -> Config:
    """Build an Alembic Config rooted at the backend directory.

    ``alembic.ini`` lives next to the backend app package. We pin the config
    path and the CWD so that ``%(here)s`` and relative ``script_location``
    resolve correctly regardless of the process working directory.
    """
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    return cfg


def _alembic_version_table_exists(sync_url: str) -> bool:
    """Return True when the target database already has an alembic_version table."""
    from sqlalchemy import create_engine, inspect

    engine = create_engine(sync_url)
    try:
        return inspect(engine).has_table("alembic_version")
    finally:
        engine.dispose()


def _database_has_tables(sync_url: str) -> bool:
    """Return True when the target database already contains application tables.

    Used to distinguish a brand-new empty database (needs ``upgrade head``)
    from a legacy database that predates Alembic (needs ``stamp head``).
    """
    from sqlalchemy import create_engine, inspect

    engine = create_engine(sync_url)
    try:
        existing = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    # Probe for a small set of core tables that have existed since the start.
    probes = {"sources", "content_items", "categories"}
    return bool(existing & probes)


def _stamp_or_upgrade(cfg: Config, *, has_version_table: bool, has_app_tables: bool) -> None:
    """Decide between stamp (legacy DB) and upgrade (new or tracked DB)."""
    if has_version_table:
        logger.info("Database already under Alembic control — running upgrade head")
        command.upgrade(cfg, "head")
        return

    if not has_app_tables:
        logger.info("Empty database detected — running upgrade head to build schema")
        command.upgrade(cfg, "head")
        return

    # Tables exist but no alembic_version row: a legacy DB shaped by the old
    # ensure_* helpers. Stamp it as current so future revisions apply cleanly.
    logger.info(
        "Legacy database detected (tables present, no alembic_version) — "
        "stamping current Alembic head without running DDL"
    )
    command.stamp(cfg, "head")


def run_startup_migrations() -> None:
    """Run Alembic migrations to bring the database to the latest revision.

    Safe to call on every startup. No-op side effects when already current.

    On PostgreSQL, acquires a session-level advisory lock (key 1) before
    running upgrade to prevent multiple containers from racing on the
    same migration.
    """
    profile = create_database_profile(settings.DATABASE_URL)
    sync_url = profile.sync_url
    _migration_lock_key = 7103251  # arbitrary constant; all containers share

    cfg = _build_alembic_config()

    try:
        has_version_table = _alembic_version_table_exists(sync_url)
    except Exception as exc:
        logger.warning("Could not inspect database for alembic_version (%s); attempting upgrade head", exc)
        command.upgrade(cfg, "head")
        return

    try:
        has_app_tables = _database_has_tables(sync_url) if not has_version_table else True
    except Exception as exc:
        logger.warning("Could not inspect database tables (%s); attempting upgrade head", exc)
        command.upgrade(cfg, "head")
        return

    # PG advisory lock: prevent multi-container concurrent migrations
    pg_lock_conn = None
    if profile.is_postgresql:
        from sqlalchemy import create_engine as _ce

        pg_lock_conn = _ce(sync_url).connect()
        pg_lock_conn.execution_options(autocommit=True)
        pg_lock_conn.execute(__import__("sqlalchemy").text(f"SELECT pg_advisory_lock({_migration_lock_key})"))
    try:
        _stamp_or_upgrade(cfg, has_version_table=has_version_table, has_app_tables=has_app_tables)
    finally:
        if pg_lock_conn is not None:
            try:
                pg_lock_conn.execute(__import__("sqlalchemy").text(f"SELECT pg_advisory_unlock({_migration_lock_key})"))
                pg_lock_conn.close()
            except Exception:
                pass
