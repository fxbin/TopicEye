from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260729_1400_q3e4f5g6h7i8_retire_legacy_duplicate_projection.py"
)


def _load_migration():
    spec = spec_from_file_location(
        "legacy_duplicate_retirement_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(engine):
    metadata = sa.MetaData()
    content = sa.Table(
        "content_items",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer, nullable=True),
        sa.Column("duplicate_of", sa.Integer, nullable=True),
        sa.Column("similarity_score", sa.Float, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    groups = sa.Table(
        "content_event_groups",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer, nullable=True),
        sa.Column("canonical_content_id", sa.Integer, nullable=False),
        sa.Column("canonical_policy", sa.String(30), nullable=False),
        sa.Column("canonical_reason", sa.Text, nullable=True),
        sa.Column("canonical_locked", sa.Boolean, nullable=False),
        sa.Column("first_occurrence_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_occurrence_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("classifier_version", sa.String(100), nullable=True),
    )
    members = sa.Table(
        "content_event_members",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_group_id", sa.Integer, nullable=False),
        sa.Column("content_id", sa.Integer, nullable=False),
        sa.Column("relation_type", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("match_method", sa.String(100), nullable=True),
        sa.Column("detector_version", sa.String(100), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
    )
    runs = sa.Table(
        "content_event_normalization_runs",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "mode IN ('shadow', 'write')",
            name="ck_content_event_normalization_runs_mode",
        ),
    )
    metadata.create_all(engine)
    return content, groups, members, runs


def test_upgrade_migrates_chains_then_removes_old_columns():
    engine = sa.create_engine("sqlite:///:memory:")
    content, groups, members, runs = _schema(engine)
    now = datetime.now(UTC)

    with engine.begin() as connection:
        connection.execute(
            content.insert(),
            [
                {
                    "id": 1,
                    "owner_user_id": None,
                    "duplicate_of": None,
                    "similarity_score": None,
                    "created_at": now,
                    "published_at": now,
                    "crawled_at": None,
                },
                {
                    "id": 2,
                    "owner_user_id": None,
                    "duplicate_of": 1,
                    "similarity_score": 0.91,
                    "created_at": now + timedelta(minutes=1),
                    "published_at": None,
                    "crawled_at": None,
                },
                {
                    "id": 3,
                    "owner_user_id": None,
                    "duplicate_of": 2,
                    "similarity_score": 0.82,
                    "created_at": now + timedelta(minutes=2),
                    "published_at": None,
                    "crawled_at": None,
                },
            ],
        )
        connection.execute(runs.insert().values(id=1, mode="write"))
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        assert {column["name"] for column in sa.inspect(connection).get_columns("content_items")} == {
            "id",
            "owner_user_id",
            "published_at",
            "crawled_at",
            "created_at",
        }
        group_row = connection.execute(sa.select(groups)).mappings().one()
        assert group_row["canonical_content_id"] == 1
        assert group_row["classifier_version"] == "legacy-retirement:v1"
        member_rows = connection.execute(sa.select(members).order_by(members.c.content_id)).mappings().all()
        assert [row["content_id"] for row in member_rows] == [2, 3]
        assert [row["confidence"] for row in member_rows] == pytest.approx([0.91, 0.82])
        assert {row["reason"] for row in member_rows} == {"migrated from retired duplicate projection"}
        assert connection.scalar(sa.select(runs.c.mode)) == "write"

        migration.downgrade()

        reflected = sa.Table(
            "content_items",
            sa.MetaData(),
            autoload_with=connection,
        )
        restored = connection.execute(
            sa.select(
                reflected.c.id,
                reflected.c.duplicate_of,
                reflected.c.similarity_score,
            ).order_by(reflected.c.id)
        ).all()
        assert restored[0] == (1, None, None)
        assert restored[1][0:2] == (2, 1)
        assert restored[2][0:2] == (3, 1)

    engine.dispose()


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [
                {"id": 1, "owner_user_id": None},
                {"id": 2, "owner_user_id": 7, "duplicate_of": 1},
            ],
            "crosses owner scope",
        ),
        (
            [{"id": 1, "owner_user_id": None, "duplicate_of": 1}],
            "self-link",
        ),
    ],
)
def test_upgrade_blocks_invalid_old_edges_without_dropping_columns(
    rows,
    message,
):
    engine = sa.create_engine("sqlite:///:memory:")
    content, _groups, _members, _runs = _schema(engine)
    now = datetime.now(UTC)
    payload = [
        {
            "owner_user_id": None,
            "duplicate_of": None,
            "similarity_score": None,
            "published_at": None,
            "crawled_at": None,
            "created_at": now + timedelta(minutes=index),
            **row,
        }
        for index, row in enumerate(rows)
    ]

    with engine.begin() as connection:
        connection.execute(content.insert(), payload)
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))

        with pytest.raises(RuntimeError, match=message):
            migration.upgrade()

        columns = {column["name"] for column in sa.inspect(connection).get_columns("content_items")}
        assert {"duplicate_of", "similarity_score"} <= columns

    engine.dispose()
