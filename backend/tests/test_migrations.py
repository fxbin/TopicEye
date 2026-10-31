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

from sqlalchemy import create_engine, inspect, text

from app.core import migrations as migrations_mod


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


def test_unknown_legacy_revision_with_squash_schema_is_stamped(throwaway_pg_database) -> None:
    """旧链指针 + schema 已达合并前 head → 自动 stamp 到 baseline，不跑 DDL。"""
    from sqlalchemy import create_engine, text

    migrations_mod.run_startup_migrations()
    engine = create_engine(throwaway_pg_database)
    with engine.begin() as conn:
        # 模拟存量库：version 指针仍是 squash 前旧链 head
        conn.execute(text("UPDATE alembic_version SET version_num = 'v2f3a4b5c6d7'"))
    engine.dispose()

    table_count_before = len(_table_names(throwaway_pg_database))
    migrations_mod.run_startup_migrations()

    # 指针被 stamp 回 baseline head，且没有重放任何 DDL
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(migrations_mod._ALEMBIC_INI))
    cfg.set_main_option("script_location", str(migrations_mod._BACKEND_DIR / "alembic"))
    assert _alembic_version(throwaway_pg_database) == ScriptDirectory.from_config(cfg).get_current_head()
    assert len(_table_names(throwaway_pg_database)) == table_count_before


def test_unknown_legacy_revision_with_stale_schema_refuses_startup(throwaway_pg_database) -> None:
    """旧链指针 + schema 未达合并前 head → 拒绝启动并给出明确指引。"""
    import pytest as _pytest
    from sqlalchemy import create_engine, text

    migrations_mod.run_startup_migrations()
    engine = create_engine(throwaway_pg_database)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE content_items DROP COLUMN content_type"))
        conn.execute(text("UPDATE alembic_version SET version_num = 'u1f2a3b4c5d6'"))
    engine.dispose()

    with _pytest.raises(RuntimeError, match="pre-squash-migrations"):
        migrations_mod.run_startup_migrations()


def test_mute_rules_migration_roundtrip(throwaway_pg_database) -> None:
    """#171 mute_rules 迁移可逆：head → downgrade 到 mute_rules 之前 → head，表与约束随迁移增删。"""
    from alembic import command

    def _cfg():
        return migrations_mod._build_alembic_config()

    def _tables() -> set[str]:
        engine = create_engine(throwaway_pg_database)
        try:
            return set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

    command.upgrade(_cfg(), "head")
    assert "mute_rules" in _tables()

    engine = create_engine(throwaway_pg_database)
    with engine.begin() as conn:
        constraints = {
            (row[0], row[1])
            for row in conn.execute(
                text("SELECT conname, contype FROM pg_constraint WHERE conrelid = 'mute_rules'::regclass")
            )
        }
    engine.dispose()
    assert ("uq_mute_rules_user_type_value", "u") in constraints, "应创建 (user_id, rule_type, value) 唯一约束"
    assert ("ck_mute_rules_rule_type", "c") in constraints, "应创建 rule_type CHECK 约束"

    # 显式回退到 mute_rules 之前的 revision：head 会随新迁移增长，-1 不再可靠
    command.downgrade(_cfg(), "c7a4e9f21b86")
    assert "mute_rules" not in _tables(), "downgrade 应完整删除 mute_rules"

    command.upgrade(_cfg(), "head")
    assert "mute_rules" in _tables(), "再次 upgrade 应重建 mute_rules"
