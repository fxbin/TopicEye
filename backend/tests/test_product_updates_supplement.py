"""#182 补录迁移 supplement_product_updates_v010_v013 的回归测试。

覆盖三条线：
- upgrade head（种子 + 补录两层叠加）后共 16 条；新补 4 版的 status / items 数 /
  首条标题 / shipped_at（发版 commit 日期）与迁移一致；
- 幂等：补录版本已存在（人工录入）时跳过，不重复、不覆盖既有行；
- downgrade -1（显式回 e8b1d4f7a2c9）只删本迁移补录的 4 条，前 12 条种子
  与人工录入记录原样保留，可再次 upgrade 还原。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import create_engine, text

from app.core import migrations as migrations_mod

# 补录层父级 = 种子迁移（e8b1d4f7a2c9），downgrade -1 的显式目标
SEED_HEAD = "e8b1d4f7a2c9"

# 种子层恢复的 12 个版本（downgrade 只删补录 4 条，这些必须全部留下）
SEED_LAYER_VERSIONS = frozenset(
    {
        "v0.1.0",
        "v0.1.1",
        "v0.1.2",
        "v0.2.0",
        "v0.2.1",
        "v0.3.0",
        "v0.4.0",
        "v0.5.0",
        "v0.6.0",
        "v0.7.0",
        "v0.8.0",
        "v0.9.0",
    }
)

# 补录 4 版：version -> (items 条数, 首条 item 标题)
SUPPLEMENT_VERSIONS: dict[str, tuple[int, str]] = {
    "v0.10.0": (6, "六维评分加四档行为锚点"),
    "v0.11.0": (6, "日报、周刊全面改版"),
    "v0.12.0": (6, "同一事件的多篇报道自动归并"),
    "v0.13.0": (6, "AI 分析同一事件的报道"),
}

# shipped_at = 发版代表 commit 的 committer date（+08:00 换算 UTC）
EXPECTED_SHIPPED_AT: dict[str, datetime] = {
    "v0.10.0": datetime(2026, 10, 12, 15, 58, tzinfo=UTC),  # 70e3a86
    "v0.11.0": datetime(2026, 10, 21, 15, 56, 9, tzinfo=UTC),  # 841177a
    "v0.12.0": datetime(2026, 10, 27, 9, 1, 53, tzinfo=UTC),  # 86d2480
    "v0.13.0": datetime(2026, 11, 1, tzinfo=UTC),
}


def _as_items(raw: object) -> list[dict]:
    return json.loads(raw) if isinstance(raw, str) else list(raw or [])


def _fetch_rows(db_url: str) -> dict[str, list[tuple[str, list[dict], object]]]:
    """返回 version -> [(status, items, shipped_at), ...]，保留重复行。"""
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT version, status, items, shipped_at FROM product_updates ORDER BY id")
            ).fetchall()
    finally:
        engine.dispose()
    grouped: dict[str, list[tuple[str, list[dict], object]]] = {}
    for version, status, items, shipped_at in rows:
        grouped.setdefault(version, []).append((status, _as_items(items), shipped_at))
    return grouped


def _execute(db_url: str, sql: str, params: dict | None = None) -> None:
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), params or {})
    finally:
        engine.dispose()


def test_supplement_upgrades_to_sixteen_versions(throwaway_pg_database) -> None:
    """种子 + 补录两层叠加后 16 条；补录 4 版的 status/items/标题/shipped_at 正确。"""
    from alembic import command

    command.upgrade(migrations_mod._build_alembic_config(), "head")

    rows = _fetch_rows(throwaway_pg_database)
    assert len(rows) == 16, f"两层迁移后应 16 个版本，实际 {len(rows)}"
    assert set(rows) == SEED_LAYER_VERSIONS | set(SUPPLEMENT_VERSIONS)
    for version, (n_items, first_title) in SUPPLEMENT_VERSIONS.items():
        assert len(rows[version]) == 1, f"{version} 应只有 1 条，实际 {len(rows[version])}"
        status, items, shipped_at = rows[version][0]
        assert status == "shipped", f"{version} 应为 shipped，实际 {status}"
        assert len(items) == n_items, f"{version} items 期望 {n_items} 条，实际 {len(items)}"
        assert items[0]["title"] == first_title, f"{version} 首条标题不符"
        assert shipped_at == EXPECTED_SHIPPED_AT[version], f"{version} shipped_at 应取发版 commit 日期"
        # 条目结构与 API 契约一致（ProductUpdateEntry: title/description 非空、kind 枚举值）
        for item in items:
            assert set(item) == {"title", "description", "kind"}
            assert item["kind"] in {"release", "improvement", "fix", "roadmap"}
            assert len(item["description"]) >= 5, f"{version} 条目 description 不得为空（API 读路径 min_length=5）"


def test_supplement_is_idempotent_for_existing_version(throwaway_pg_database) -> None:
    """补录版本已存在（人工录入）时跳过：不报错、不重复、不覆盖既有行。"""
    from alembic import command

    cfg = migrations_mod._build_alembic_config()
    # 只升到种子层，模拟「后台已人工录入 v0.13.0」的存量状态
    command.upgrade(cfg, SEED_HEAD)
    assert set(_fetch_rows(throwaway_pg_database)) == SEED_LAYER_VERSIONS
    _execute(
        throwaway_pg_database,
        "INSERT INTO product_updates (version, status, items, created_at, updated_at)"
        " VALUES ('v0.13.0', 'in_progress', :items, now(), now())",
        {"items": json.dumps([{"title": "手工记录", "description": "人工录入", "kind": "release"}])},
    )

    command.upgrade(cfg, "head")
    rows = _fetch_rows(throwaway_pg_database)
    assert len(rows) == 16, "12 条种子 + 3 条补录 + 1 条人工 v0.13.0"
    assert len(rows["v0.13.0"]) == 1, "已存在的 v0.13.0 不得重复插入"
    assert rows["v0.13.0"][0][0] == "in_progress", "防重跳过不应覆盖既有行"
    assert rows["v0.13.0"][0][1][0]["title"] == "手工记录"
    assert {"v0.10.0", "v0.11.0", "v0.12.0"} <= set(rows)

    # 重复 upgrade head（alembic no-op）也不产生重复
    command.upgrade(cfg, "head")
    assert len(_fetch_rows(throwaway_pg_database)["v0.13.0"]) == 1


def test_supplement_downgrade_only_removes_four_versions(throwaway_pg_database) -> None:
    """downgrade -1（显式回种子层）只删补录 4 条，前 12 条与人工记录保留，可再次还原。"""
    from alembic import command

    cfg = migrations_mod._build_alembic_config()
    command.upgrade(cfg, "head")
    _execute(
        throwaway_pg_database,
        "INSERT INTO product_updates (version, status, items, created_at, updated_at)"
        " VALUES ('v1.0.0-manual', 'shipped', '[]'::json, now(), now())",
    )

    command.downgrade(cfg, SEED_HEAD)

    rows = _fetch_rows(throwaway_pg_database)
    assert set(rows) == SEED_LAYER_VERSIONS | {"v1.0.0-manual"}, f"应只剩 12 条种子+人工，实际 {set(rows)}"
    assert not set(SUPPLEMENT_VERSIONS) & set(rows), "补录 4 条应全部删除"

    engine = create_engine(throwaway_pg_database)
    try:
        with engine.connect() as conn:
            version_num = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()
    assert version_num == SEED_HEAD

    # 再次 upgrade head 无损还原 16 条
    command.upgrade(cfg, "head")
    restored = _fetch_rows(throwaway_pg_database)
    assert set(restored) == SEED_LAYER_VERSIONS | set(SUPPLEMENT_VERSIONS) | {"v1.0.0-manual"}
    assert len(restored["v0.13.0"]) == 1 and len(restored["v0.13.0"][0][1]) == 6
