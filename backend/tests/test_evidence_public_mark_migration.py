from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models.content_evidence import ContentEvidenceMark

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260729_1300_p2d3e4f5g6h7_enforce_public_evidence_mark_uniqueness.py"
)


def _load_migration():
    spec = spec_from_file_location(
        "public_evidence_mark_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_mark_migration_deduplicates_reparents_and_enforces_sqlite():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    marks = sa.Table(
        "content_evidence_marks",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("content_id", sa.Integer, nullable=False),
        sa.Column("owner_user_id", sa.Integer, nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    links = sa.Table(
        "content_evidence_links",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mark_id", sa.Integer, nullable=False),
    )
    metadata.create_all(engine)
    now = datetime.now(UTC)

    with engine.begin() as connection:
        connection.execute(
            marks.insert(),
            [
                {
                    "id": 1,
                    "content_id": 10,
                    "owner_user_id": None,
                    "computed_at": now - timedelta(hours=2),
                },
                {
                    "id": 2,
                    "content_id": 10,
                    "owner_user_id": None,
                    "computed_at": now - timedelta(hours=1),
                },
                {
                    "id": 3,
                    "content_id": 10,
                    "owner_user_id": None,
                    "computed_at": now,
                },
                {
                    "id": 4,
                    "content_id": 10,
                    "owner_user_id": 7,
                    "computed_at": now,
                },
            ],
        )
        connection.execute(
            links.insert(),
            [
                {"id": 1, "mark_id": 1},
                {"id": 2, "mark_id": 2},
                {"id": 3, "mark_id": 3},
            ],
        )
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        public_marks = connection.execute(
            sa.select(marks.c.id).where(marks.c.owner_user_id.is_(None))
        ).scalars().all()
        assert public_marks == [3]
        assert connection.execute(
            sa.select(links.c.mark_id).order_by(links.c.id)
        ).scalars().all() == [3, 3, 3]

        with pytest.raises(IntegrityError):
            connection.execute(
                marks.insert().values(
                    id=5,
                    content_id=10,
                    owner_user_id=None,
                    computed_at=now,
                )
            )
        connection.execute(
            marks.insert().values(
                id=6,
                content_id=10,
                owner_user_id=8,
                computed_at=now,
            )
        )

        migration.downgrade()
        connection.execute(
            marks.insert().values(
                id=7,
                content_id=10,
                owner_user_id=None,
                computed_at=now,
            )
        )
        assert connection.execute(
            sa.select(sa.func.count())
            .select_from(marks)
            .where(marks.c.owner_user_id.is_(None))
        ).scalar_one() == 2

    engine.dispose()


def test_public_mark_partial_index_compiles_for_postgresql(monkeypatch):
    migration = _load_migration()
    captured = {}
    monkeypatch.setattr(migration, "_deduplicate_public_marks", lambda: None)

    def capture(name, table_name, columns, **kwargs):
        captured.update(
            {
                "name": name,
                "table_name": table_name,
                "columns": columns,
                **kwargs,
            }
        )

    monkeypatch.setattr(migration.op, "create_index", capture)
    migration.upgrade()

    table = sa.Table(
        "content_evidence_marks",
        sa.MetaData(),
        sa.Column("content_id", sa.Integer),
        sa.Column("owner_user_id", sa.Integer),
    )
    index = sa.Index(
        captured["name"],
        table.c.content_id,
        unique=captured["unique"],
        postgresql_where=captured["postgresql_where"],
    )
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert (
        ddl
        == "CREATE UNIQUE INDEX uq_evidence_marks_public_content "
        "ON content_evidence_marks (content_id) WHERE owner_user_id IS NULL"
    )
    assert captured["sqlite_where"].text == "owner_user_id IS NULL"


def test_content_evidence_model_has_matching_public_partial_index():
    index = next(
        value
        for value in ContentEvidenceMark.__table__.indexes
        if value.name == "uq_evidence_marks_public_content"
    )
    assert index.unique is True
    assert str(index.dialect_options["sqlite"]["where"]) == (
        "owner_user_id IS NULL"
    )
    assert str(index.dialect_options["postgresql"]["where"]) == (
        "owner_user_id IS NULL"
    )
