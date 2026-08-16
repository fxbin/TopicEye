"""Tests for the Alembic-based startup migration runner.

These tests cover the two startup paths in ``app.core.migrations``:
- brand-new empty database -> ``upgrade head`` builds all tables
- legacy database (tables present, no alembic_version) -> ``stamp head``
  records current revision without running DDL
"""

from __future__ import annotations

import sqlite3

from app.core import migrations as migrations_mod


def _table_names(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()


def _alembic_version(db_path: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def test_new_empty_database_upgrades_to_head(tmp_path, monkeypatch) -> None:
    """A brand-new empty DB should run upgrade head and end at the baseline revision."""
    db_path = str(tmp_path / "fresh.db")
    monkeypatch.setattr(migrations_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setattr(migrations_mod.settings, "DATABASE_SQLITE_DOMAIN_SPLIT_ENABLED", False)

    migrations_mod.run_startup_migrations()

    tables = _table_names(db_path)
    assert "alembic_version" in tables
    assert "sources" in tables
    assert "content_items" in tables
    assert "favorite_items" in tables
    assert _alembic_version(db_path) is not None


def test_legacy_database_with_tables_is_stamped(tmp_path, monkeypatch) -> None:
    """A DB that already has app tables but no alembic_version should be stamped."""
    db_path = str(tmp_path / "legacy.db")
    monkeypatch.setattr(migrations_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setattr(migrations_mod.settings, "DATABASE_SQLITE_DOMAIN_SPLIT_ENABLED", False)

    # Simulate a legacy DB: create a couple of app tables manually (no alembic_version).
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE content_items (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO sources (id, name) VALUES (1, 'legacy')")
        conn.commit()
    finally:
        conn.close()

    migrations_mod.run_startup_migrations()

    # No DDL ran against existing tables; data preserved.
    assert _alembic_version(db_path) is not None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT name FROM sources WHERE id = 1").fetchone()
    finally:
        conn.close()
    assert row == ("legacy",)


def test_already_tracked_database_upgrades_idempotently(tmp_path, monkeypatch) -> None:
    """A DB already at head should be a no-op on a second startup run."""
    db_path = str(tmp_path / "tracked.db")
    monkeypatch.setattr(migrations_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setattr(migrations_mod.settings, "DATABASE_SQLITE_DOMAIN_SPLIT_ENABLED", False)

    migrations_mod.run_startup_migrations()
    version_after_first = _alembic_version(db_path)
    table_count_after_first = len(_table_names(db_path))

    # Second run should be idempotent.
    migrations_mod.run_startup_migrations()
    assert _alembic_version(db_path) == version_after_first
    assert len(_table_names(db_path)) == table_count_after_first
