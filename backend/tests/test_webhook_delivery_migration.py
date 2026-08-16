from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from sqlalchemy.dialects import postgresql, sqlite

MIGRATION_PATH = (
    Path(__file__).parents[1] / "alembic" / "versions" / "20260729_1000_m9a0b1c2d3e4_create_webhook_delivery_logs.py"
)


def _load_migration():
    spec = spec_from_file_location("webhook_delivery_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_created_at_default_compiles_for_sqlite_and_postgresql(monkeypatch):
    migration = _load_migration()
    created_columns = []

    def capture_table(_table_name, *columns):
        created_columns.extend(columns)

    monkeypatch.setattr(migration.op, "create_table", capture_table)
    monkeypatch.setattr(migration.op, "create_index", lambda *_args, **_kwargs: None)

    migration.upgrade()

    created_at = next(column for column in created_columns if column.name == "created_at")
    default_expression = created_at.server_default.arg

    assert str(default_expression.compile(dialect=sqlite.dialect())) == "CURRENT_TIMESTAMP"
    assert str(default_expression.compile(dialect=postgresql.dialect())) == "CURRENT_TIMESTAMP"
