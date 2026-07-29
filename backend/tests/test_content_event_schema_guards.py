from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core import database

_MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260729_1100_n0b1c2d3e4f5_create_content_events.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "content_event_schema_migration",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_integrity_error(connection, statement) -> None:
    savepoint = connection.begin_nested()
    try:
        with pytest.raises(IntegrityError):
            connection.execute(statement)
    finally:
        savepoint.rollback()


def test_sqlite_migration_enforces_canonical_member_disjointness():
    migration = _load_migration()
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    contents = sa.Table(
        "content_items",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata.create_all(connection)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        connection.execute(users.insert().values(id=1))
        connection.execute(
            contents.insert(),
            [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}],
        )
        now = datetime.now(UTC)
        groups = sa.table(
            "content_event_groups",
            sa.column("id"),
            sa.column("canonical_content_id"),
            sa.column("canonical_policy"),
            sa.column("first_occurrence_at"),
            sa.column("last_occurrence_at"),
        )
        members = sa.table(
            "content_event_members",
            sa.column("event_group_id"),
            sa.column("content_id"),
            sa.column("confidence"),
            sa.column("match_method"),
        )

        connection.execute(
            groups.insert().values(
                id=1,
                canonical_content_id=1,
                canonical_policy="earliest",
                first_occurrence_at=now,
                last_occurrence_at=now,
            )
        )
        _assert_integrity_error(
            connection,
            members.insert().values(
                event_group_id=1,
                content_id=1,
                confidence=1.0,
                match_method="exact",
            ),
        )

        connection.execute(
            members.insert().values(
                event_group_id=1,
                content_id=2,
                confidence=0.9,
                match_method="semantic",
            )
        )
        _assert_integrity_error(
            connection,
            groups.update()
            .where(groups.c.id == 1)
            .values(canonical_content_id=2),
        )

        connection.execute(
            groups.insert().values(
                id=2,
                canonical_content_id=3,
                canonical_policy="earliest",
                first_occurrence_at=now,
                last_occurrence_at=now,
            )
        )
        connection.execute(
            members.insert().values(
                event_group_id=2,
                content_id=4,
                confidence=0.8,
                match_method="semantic",
            )
        )

        # Content identity is global across event groups, not scoped per group.
        _assert_integrity_error(
            connection,
            members.insert().values(
                event_group_id=2,
                content_id=1,
                confidence=0.8,
                match_method="semantic",
            ),
        )
        _assert_integrity_error(
            connection,
            members.update()
            .where(members.c.content_id == 4)
            .values(content_id=1),
        )
        _assert_integrity_error(
            connection,
            groups.insert().values(
                id=3,
                canonical_content_id=2,
                canonical_policy="earliest",
                first_occurrence_at=now,
                last_occurrence_at=now,
            ),
        )
        _assert_integrity_error(
            connection,
            groups.update()
            .where(groups.c.id == 2)
            .values(canonical_content_id=2),
        )
        _assert_integrity_error(
            connection,
            groups.insert().values(
                id=3,
                canonical_content_id=5,
                canonical_policy="score",
                first_occurrence_at=now,
                last_occurrence_at=now,
            ),
        )

        migration.downgrade()
        assert not sa.inspect(connection).has_table("content_event_members")
        assert not sa.inspect(connection).has_table("content_event_groups")


def test_postgresql_migration_defines_symmetric_trigger_lifecycle():
    migration = _load_migration()

    class RecordingOperations:
        def __init__(self):
            self.executed: list[str] = []

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement):
            self.executed.append(str(statement))

    operations = RecordingOperations()
    migration.op = operations

    migration._create_canonical_member_guards()
    create_sql = "\n".join(operations.executed)
    assert "CREATE FUNCTION enforce_content_event_canonical_member_disjoint" in create_sql
    assert create_sql.count("FROM content_items") == 2
    assert "FOR UPDATE" in create_sql
    assert "BEFORE INSERT OR UPDATE OF event_group_id, content_id" in create_sql
    assert "BEFORE INSERT OR UPDATE OF canonical_content_id" in create_sql

    operations.executed.clear()
    migration._drop_canonical_member_guards()
    drop_sql = "\n".join(operations.executed)
    assert "DROP TRIGGER IF EXISTS trg_content_event_member_not_canonical" in drop_sql
    assert "DROP TRIGGER IF EXISTS trg_content_event_canonical_not_member" in drop_sql
    assert "DROP FUNCTION IF EXISTS" in drop_sql


def test_application_sqlite_connections_enable_foreign_keys(monkeypatch):
    statements: list[str] = []

    class Cursor:
        def execute(self, statement):
            statements.append(statement)

        def close(self):
            pass

    class Connection:
        def cursor(self):
            return Cursor()

    monkeypatch.setattr(
        database,
        "database_profile",
        SimpleNamespace(is_sqlite=True),
    )
    database.set_sqlite_pragma(Connection(), None)

    assert statements[0] == "PRAGMA foreign_keys=ON"
