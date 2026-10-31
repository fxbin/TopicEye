"""#182 恢复 changelog 丢失的 product_updates 版本记录：种子迁移回归测试。

覆盖三条线：
- upgrade head 后 v0.1.0→v0.9.0 共 12 条版本记录齐全（status / items 数 / 关键标题）；
- 幂等：已存在的 version 不重复插入（version 无唯一约束，靠 SELECT 防重）；
- downgrade -1 按 version 精确删除种子记录，不动人工录入的其它版本。
"""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text

from app.core import migrations as migrations_mod

# version -> (status, items 条数, 首条 item 标题)
EXPECTED_VERSIONS: dict[str, tuple[str, int, str]] = {
    "v0.1.0": ("shipped", 7, "全栈项目初始化"),
    "v0.1.1": ("shipped", 4, "多热榜数据源"),
    "v0.1.2": ("shipped", 4, "网文雷达：番茄 + 七猫 + 知乎盐选"),
    "v0.2.0": ("shipped", 4, "AI 分析队列并发化"),
    "v0.2.1": ("shipped", 2, "反馈与更新工作台"),
    "v0.3.0": ("shipped", 6, "公共/私有信源双层模型"),
    "v0.4.0": ("planned", 2, "算法准确性回归看板"),
    "v0.5.0": ("planned", 2, "多用户配额与规模化"),
    "v0.6.0": ("shipped", 4, "站内原文阅读"),
    "v0.7.0": ("shipped", 5, "统计仪表盘可视化升级"),
    "v0.8.0": ("shipped", 3, "母题 per-user 化：系统模板库 + 用户 fork"),
    "v0.9.0": ("shipped", 9, "跨源证据与可信线索体系"),
}

_PREVIOUS_HEAD = "d2b7f9a41c05"


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


def test_restore_seed_upgrades_to_full_changelog(throwaway_pg_database) -> None:
    """upgrade head 后 12 个版本齐全，字段与种子一致。"""
    from alembic import command

    command.upgrade(migrations_mod._build_alembic_config(), "head")

    rows = _fetch_rows(throwaway_pg_database)
    assert set(rows) == set(EXPECTED_VERSIONS), f"版本集合不一致: {set(rows) ^ set(EXPECTED_VERSIONS)}"
    for version, (status, n_items, first_title) in EXPECTED_VERSIONS.items():
        records = rows[version]
        assert len(records) == 1, f"{version} 应只有 1 条，实际 {len(records)}"
        row_status, items, shipped_at = records[0]
        assert row_status == status, f"{version} status 期望 {status}，实际 {row_status}"
        assert len(items) == n_items, f"{version} items 期望 {n_items} 条，实际 {len(items)}"
        assert items[0]["title"] == first_title, f"{version} 首条标题不符"
        # 每条 item 结构完整
        for item in items:
            assert set(item) == {"title", "description", "kind"}
            assert item["kind"] in {"release", "improvement", "fix", "roadmap"}
        # shipped 版本必有 shipped_at；planned 版本无
        if status == "shipped":
            assert shipped_at is not None, f"{version} shipped_at 不应为空"
        else:
            assert shipped_at is None, f"{version} planned 不应有 shipped_at"

    # 关键抽查：v0.5.0 的 OAuth 追加项在第二位；v0.9.0 覆盖九大板块
    v050_titles = [it["title"] for it in rows["v0.5.0"][0][1]]
    assert "OAuth 登录与开源准备" in v050_titles, "v0.5.0 应含 OAuth 路线图追加项"
    assert v050_titles[-1] == "OAuth 登录与开源准备", "OAuth 项按追加顺序应在末位"
    assert rows["v0.9.0"][0][1][-1]["title"] == "安全与工程质量加固"


def test_restore_seed_is_idempotent_for_existing_versions(throwaway_pg_database) -> None:
    """version 已存在时跳过插入：不报错、不重复、不覆盖既有行。"""
    from alembic import command

    cfg = migrations_mod._build_alembic_config()
    command.upgrade(cfg, "head")
    assert len(_fetch_rows(throwaway_pg_database)) == 12

    # 回滚种子后，手工预置 v0.1.0（模拟存量数据/人工录入）+ 一个无关版本
    # （显式指回种子迁移的父级，避免未来迁移落顶时 "-1" 语义漂移）
    command.downgrade(cfg, "d2b7f9a41c05")
    assert _fetch_rows(throwaway_pg_database) == {}, "downgrade 后应清空种子记录"
    _execute(
        throwaway_pg_database,
        "INSERT INTO product_updates (version, status, items, created_at, updated_at)"
        " VALUES ('v0.1.0', 'in_progress', :items, now(), now())",
        {"items": json.dumps([{"title": "手工记录", "description": "人工录入", "kind": "release"}])},
    )
    _execute(
        throwaway_pg_database,
        "INSERT INTO product_updates (version, status, items, created_at, updated_at)"
        " VALUES ('v1.0.0-manual', 'shipped', '[]'::json, now(), now())",
    )

    # 再次 upgrade：v0.1.0 已存在 → 跳过（保留手工行内容），其余 11 条补齐
    command.upgrade(cfg, "head")
    rows = _fetch_rows(throwaway_pg_database)
    assert len(rows["v0.1.0"]) == 1, "已存在的 v0.1.0 不得重复插入"
    assert rows["v0.1.0"][0][0] == "in_progress", "防重跳过不应覆盖既有行"
    assert rows["v0.1.0"][0][1][0]["title"] == "手工记录"
    assert len(rows) == 13, "12 个种子版本 + 1 个手工版本"
    assert "v1.0.0-manual" in rows

    # 重复 upgrade head（alembic no-op）也不产生重复
    command.upgrade(cfg, "head")
    assert len(_fetch_rows(throwaway_pg_database)["v0.1.0"]) == 1


def test_downgrade_deletes_only_seed_versions(throwaway_pg_database) -> None:
    """downgrade -1 按 version 精确删种子记录，人工版本保留，可再次 upgrade 还原。"""
    from alembic import command

    cfg = migrations_mod._build_alembic_config()
    command.upgrade(cfg, "head")
    _execute(
        throwaway_pg_database,
        "INSERT INTO product_updates (version, status, items, created_at, updated_at)"
        " VALUES ('v1.0.0-manual', 'shipped', '[]'::json, now(), now())",
    )

    command.downgrade(cfg, "d2b7f9a41c05")

    rows = _fetch_rows(throwaway_pg_database)
    assert set(rows) == {"v1.0.0-manual"}, f"只应剩人工版本，实际 {set(rows)}"

    # 指针回到上一 head，之后可无损再次 upgrade
    engine = create_engine(throwaway_pg_database)
    try:
        with engine.connect() as conn:
            version_num = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()
    assert version_num == _PREVIOUS_HEAD

    command.upgrade(cfg, "head")
    restored = _fetch_rows(throwaway_pg_database)
    assert set(restored) == set(EXPECTED_VERSIONS) | {"v1.0.0-manual"}
    assert len(restored["v0.9.0"]) == 1 and len(restored["v0.9.0"][0][1]) == 9
