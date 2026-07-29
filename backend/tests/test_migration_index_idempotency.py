from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260729_0900_l8a9b0c1d2e3_add_query_performance_indexes.py"
)


def _load_migration():
    spec = spec_from_file_location("query_performance_index_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Inspector:
    def __init__(self, indexes_by_table: dict[str, set[str]]) -> None:
        self.indexes_by_table = indexes_by_table

    def get_indexes(self, table_name: str) -> list[dict[str, str]]:
        return [
            {"name": index_name}
            for index_name in self.indexes_by_table.get(table_name, set())
        ]


def test_upgrade_creates_only_indexes_missing_after_earlier_revision(monkeypatch):
    migration = _load_migration()
    inspector = _Inspector(
        {
            "ai_analyses": set(),
            "content_items": {"ix_content_items_status_crawled"},
        }
    )
    created: list[tuple[str, str]] = []

    monkeypatch.setattr(migration.op, "get_bind", object)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, table, _columns: created.append((name, table)),
    )

    migration.upgrade()

    assert created == [
        ("ix_ai_analyses_content_created", "ai_analyses"),
        ("ix_content_items_crawled_at", "content_items"),
    ]


def test_upgrade_is_idempotent_after_partial_sqlite_ddl(monkeypatch):
    migration = _load_migration()
    inspector = _Inspector(
        {
            "ai_analyses": {"ix_ai_analyses_content_created"},
            "content_items": {
                "ix_content_items_crawled_at",
                "ix_content_items_status_crawled",
            },
        }
    )
    created: list[tuple[str, str]] = []

    monkeypatch.setattr(migration.op, "get_bind", object)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, table, _columns: created.append((name, table)),
    )

    migration.upgrade()

    assert created == []


def test_downgrade_preserves_index_owned_by_earlier_revision(monkeypatch):
    migration = _load_migration()
    inspector = _Inspector(
        {
            "ai_analyses": {"ix_ai_analyses_content_created"},
            "content_items": {
                "ix_content_items_crawled_at",
                "ix_content_items_status_crawled",
            },
        }
    )
    dropped: list[tuple[str, str]] = []

    monkeypatch.setattr(migration.op, "get_bind", object)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)
    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, *, table_name: dropped.append((name, table_name)),
    )

    migration.downgrade()

    assert dropped == [
        ("ix_content_items_crawled_at", "content_items"),
        ("ix_ai_analyses_content_created", "ai_analyses"),
    ]
