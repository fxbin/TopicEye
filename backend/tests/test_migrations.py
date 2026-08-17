"""Tests for the Alembic-based startup migration runner.

These tests cover the three startup paths in ``app.core.migrations``:
- brand-new empty database -> ``upgrade head`` builds all tables
- legacy database (tables present, no alembic_version) -> ``stamp head``
  records current revision without running DDL
- database already under Alembic control -> second run is a no-op

SQLite support has been removed (``db_backend`` rejects non-PostgreSQL
URLs), so each test creates a throwaway database inside the running test
PostgreSQL instance and drops it afterwards.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core import migrations as migrations_mod


def _sync_url(database: str | None = None) -> str:
    """Sync (psycopg) URL of the test PG instance, optionally retargeting the database."""
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+psycopg")
    if database is not None:
        url = url.set(database=database)
    # str(url) 会把密码渲染成 ***，必须显式保留
    return url.render_as_string(hide_password=False)


@pytest.fixture
def throwaway_pg_database(monkeypatch):
    """一次性测试数据库：建库 → 指向 settings.DATABASE_URL → 用完删库。"""
    db_name = f"mig_test_{uuid.uuid4().hex[:10]}"
    admin = create_engine(_sync_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()

    test_url = _sync_url(db_name)
    monkeypatch.setattr(migrations_mod.settings, "DATABASE_URL", test_url)
    yield test_url

    admin = create_engine(_sync_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'REVOKE CONNECT ON DATABASE "{db_name}" FROM PUBLIC'))
        conn.execute(text(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}'"))
        conn.execute(text(f'DROP DATABASE "{db_name}"'))
    admin.dispose()


def _table_names(db_url: str) -> set[str]:
    engine = create_engine(db_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _alembic_version(db_url: str) -> str | None:
    engine = create_engine(db_url)
    try:
        if not inspect(engine).has_table("alembic_version"):
            return None
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()


def test_new_empty_database_upgrades_to_head(throwaway_pg_database) -> None:
    """A brand-new empty DB should run upgrade head and end at the baseline revision."""
    migrations_mod.run_startup_migrations()

    tables = _table_names(throwaway_pg_database)
    assert "alembic_version" in tables
    assert "sources" in tables
    assert "content_items" in tables
    assert "favorite_items" in tables
    assert _alembic_version(throwaway_pg_database) is not None


def test_legacy_database_with_tables_is_stamped(throwaway_pg_database) -> None:
    """A DB that already has app tables but no alembic_version should be stamped."""
    # Simulate a legacy DB: create a couple of app tables manually (no alembic_version).
    engine = create_engine(throwaway_pg_database)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE sources (id SERIAL PRIMARY KEY, name TEXT)"))
        conn.execute(text("CREATE TABLE content_items (id SERIAL PRIMARY KEY, title TEXT)"))
        conn.execute(text("INSERT INTO sources (id, name) VALUES (1, 'legacy')"))
    engine.dispose()

    migrations_mod.run_startup_migrations()

    # No DDL ran against existing tables; data preserved.
    assert _alembic_version(throwaway_pg_database) is not None
    engine = create_engine(throwaway_pg_database)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT name FROM sources WHERE id = 1")).one_or_none()
    engine.dispose()
    assert row == ("legacy",)


def test_already_tracked_database_upgrades_idempotently(throwaway_pg_database) -> None:
    """A DB already at head should be a no-op on a second startup run."""
    migrations_mod.run_startup_migrations()
    version_after_first = _alembic_version(throwaway_pg_database)
    table_count_after_first = len(_table_names(throwaway_pg_database))

    # Second run should be idempotent.
    migrations_mod.run_startup_migrations()
    assert _alembic_version(throwaway_pg_database) == version_after_first
    assert len(_table_names(throwaway_pg_database)) == table_count_after_first
