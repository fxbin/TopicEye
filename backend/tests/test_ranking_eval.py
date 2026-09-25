"""排序效果基准 PG 集成测试：harness 指标 + 标注仓库 + admin API。

走 PostgreSQL（事件去重 / upsert-on-conflict 均依赖 PG 语义）；
conftest 负责建 schema 与逐用例清表。
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api
from app.api.v1.router import router as v1_router
from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.models.content_event import ContentEventGroup, ContentEventMember
from app.models.content_label import ContentLabel
from app.models.creation import CreationPlan
from app.models.pick_mark import PickMark
from app.models.source import Source
from app.models.user import User
from app.services.auth_service import create_session, create_user
from app.services.content_labeling import rebuild_behavioral_labels
from app.services.ranking_eval import evaluate_ranking_window


@pytest_asyncio.fixture
async def eval_env() -> (
    AsyncGenerator[tuple[httpx.AsyncClient, dict[str, str], async_sessionmaker[AsyncSession], dict[str, int]], None]
):
    """PG + 管理员/普通用户 + 5 条窗口内分析内容（3 个来源）+ 1 个事件组。

    item1: 强正分（creator 90, risk 20）→ 应进 top
    item2/item3: 与 item1 同分但同属一个 active 事件组（item1 canonical）→ dup
    item4: 带成稿（CreationPlan）→ adopted
    item5: 高风险 → 被评分器过滤
    item6: 窗口外（旧内容）→ 不参与
    """
    from app.services.json_cache import invalidate_json_cache

    invalidate_json_cache("contents:")
    engine = create_async_engine(os.environ["DATABASE_URL"])
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    ids: dict[str, int] = {}
    async with session_factory() as db:
        admin = await create_user(db, email="eval-admin@example.com", password="Password123", role="admin")
        user = await create_user(db, email="eval-user@example.com", password="Password123", role="user")
        admin_token, _ = await create_session(db, admin)
        user_token, _ = await create_session(db, user)

        source_a = Source(name="SrcA", url="https://a.example.com", source_type="RSS", status="active")
        source_b = Source(name="SrcB", url="https://b.example.com", source_type="RSS", status="active")
        db.add_all([source_a, source_b])
        await db.flush()

        now = datetime.now(UTC)
        specs = [
            ("item1", source_a, 90, 20, now - timedelta(hours=2)),
            ("item2", source_a, 88, 20, now - timedelta(hours=3)),
            ("item3", source_b, 87, 20, now - timedelta(hours=4)),
            ("item4", source_b, 86, 20, now - timedelta(hours=5)),
            ("item5", source_a, 95, 95, now - timedelta(hours=5)),
            ("item6", source_b, 99, 10, now - timedelta(days=30)),
        ]
        for name, source, creator, risk, created in specs:
            item = ContentItem(
                title=f"Eval {name}",
                url=f"https://example.com/{name}",
                source_id=source.id,
                source_name=source.name,
                source_type="RSS",
                status="analyzed",
                content_hash=f"hash-{name}",
                created_at=created,
                crawled_at=created,
            )
            db.add(item)
            await db.flush()
            ids[name] = item.id
            db.add(
                AiAnalysis(
                    content_id=item.id,
                    quality_score=80,
                    hot_score=70,
                    freshness_score=70,
                    creator_score=creator,
                    viral_score=70,
                    risk_score=risk,
                    curation_score=creator,
                    summary="eval summary",
                )
            )
        await db.flush()

        # item1 是 canonical；item2/item3 是同组已接受成员 → 重复事件
        group = ContentEventGroup(
            canonical_content_id=ids["item1"],
            first_occurrence_at=now,
            last_occurrence_at=now,
            status="active",
        )
        db.add(group)
        await db.flush()
        for member_id, review in (
            (ids["item1"], "confirmed"),
            (ids["item2"], "auto"),
            (ids["item3"], "auto"),
        ):
            db.add(
                ContentEventMember(
                    event_group_id=group.id,
                    content_id=member_id,
                    review_status=review,
                    relation_type="corroboration",
                    confidence=0.9,
                    match_method="test",
                )
            )

        # item4 成稿 → adopted
        db.add(
            CreationPlan(
                user_id=user.id,
                content_id=ids["item4"],
                platform="xiaohongshu",
                content_title_snapshot="Eval item4",
                plan={"topic": "eval"},
            )
        )
        await db.commit()

    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(v1_router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, {"admin": admin_token, "user": user_token}, session_factory, ids

    await engine.dispose()


@pytest.mark.asyncio
async def test_evaluate_window_metrics(eval_env):
    client, _tokens, session_factory, ids = eval_env

    async with session_factory() as db:
        payload = await evaluate_ranking_window(db, hours=168, top_n=4)

    metrics = payload["metrics"]
    top_ids = [d["content_id"] for d in payload["item_details"]["items"]]

    # 高风险 item5 与窗口外 item6 不应进入 top
    assert ids["item5"] not in top_ids
    assert ids["item6"] not in top_ids
    # 重复事件：item2/item3 是非 canonical 成员；item1 是 canonical 不算
    dups = set(metrics["duplicate_ids"])
    assert ids["item2"] in dups or ids["item3"] in dups
    assert ids["item1"] not in dups
    # 采用：item4 有成稿
    assert ids["item4"] in set(metrics["adopted_ids"])
    # 无标注时覆盖率与值得写率为 0（不算 None——评测窗口没有标注是合法状态）
    assert metrics["top10_label_coverage"] == 0.0
    assert metrics["top10_worth_ratio"] == 0.0
    # 来源覆盖：top4 至少跨 2 个来源
    assert 0 < metrics["top10_source_coverage"] <= 1.0
    # 配置快照随评测返回
    assert "risk_threshold" in payload["scoring_config"]


@pytest.mark.asyncio
async def test_behavioral_rebuild_and_authoritative_protection(eval_env):
    client, _tokens, session_factory, ids = eval_env

    async with session_factory() as db:
        # item1: 收藏 1 次 → 3 分 → worth_writing
        from sqlalchemy import select

        from app.models.favorite import FavoriteItem, FavoriteTargetType

        user_id = (await db.execute(select(User.id).where(User.email == "eval-user@example.com"))).scalar_one()
        db.add(
            FavoriteItem(
                user_id=user_id,
                target_type=FavoriteTargetType.CONTENT,
                target_id=ids["item1"],
                target_key=f"content:{ids['item1']}",
                title="Eval item1",
            )
        )
        # item2: 反馈点踩 1 次 → -4 → not_worth
        from app.models.feedback import UserFeedback

        db.add(
            UserFeedback(
                user_id=user_id,
                content_id=ids["item2"],
                feedback_type="dislike",
                score_delta=-15.0,
            )
        )
        await db.commit()

        stats = await rebuild_behavioral_labels(db, lookback_days=30)

    assert stats["worth_writing"] >= 1
    assert stats["not_worth"] >= 1

    async with session_factory() as db:
        from sqlalchemy import select

        labels = {row.content_id: row for row in (await db.execute(select(ContentLabel))).scalars().all()}
        assert labels[ids["item1"]].label == "worth_writing"
        assert labels[ids["item1"]].source == "behavioral"
        assert labels[ids["item2"]].label == "not_worth"

        # 人工标注后重跑：不被覆盖
        repo_label = labels[ids["item1"]]
        repo_label.label = "not_worth"
        repo_label.source = "human"
        await db.commit()

        await rebuild_behavioral_labels(db, lookback_days=30)
        refreshed = await db.scalar(select(ContentLabel).where(ContentLabel.content_id == ids["item1"]))
        assert refreshed.label == "not_worth", "human 标注不可被行为刷新覆盖"
        assert refreshed.source == "human"


@pytest.mark.asyncio
async def test_pick_mark_write_imported_as_authoritative(eval_env):
    _client, _tokens, session_factory, ids = eval_env

    async with session_factory() as db:
        from sqlalchemy import select

        url = (await db.execute(select(ContentItem.url).where(ContentItem.id == ids["item1"]))).scalar_one()
        db.add(
            PickMark(
                user_id=(await db.execute(select(User.id).where(User.email == "eval-admin@example.com"))).scalar_one(),
                report_date=dt.date(2026, 9, 24),
                pick_title="Eval item1",
                action="write",
                pick_source_url=url,
            )
        )
        await db.commit()

        from app.services.content_labeling import import_pick_mark_labels

        stats = await import_pick_mark_labels(db)
        assert stats["matched"] == 1

        label = await db.scalar(select(ContentLabel).where(ContentLabel.content_id == ids["item1"]))
        assert label.label == "worth_writing"
        assert label.source == "pick_mark"


@pytest.mark.asyncio
async def test_admin_api_label_and_evaluate_flow(eval_env):
    client, tokens, session_factory, ids = eval_env
    admin_headers = {"Authorization": f"Bearer {tokens['admin']}"}

    # 非管理员 403
    resp = await client.put(
        f"/api/v1/admin/ranking-eval/labels/{ids['item1']}",
        json={"label": "worth_writing"},
        headers={"Authorization": f"Bearer {tokens['user']}"},
    )
    assert resp.status_code == 403

    # 人工标注
    resp = await client.put(
        f"/api/v1/admin/ranking-eval/labels/{ids['item1']}",
        json={"label": "worth_writing"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["source"] == "human"

    # 非法值 422
    resp = await client.put(
        f"/api/v1/admin/ranking-eval/labels/{ids['item1']}",
        json={"label": "不合法"},
        headers=admin_headers,
    )
    assert resp.status_code == 422

    # 触发评测
    resp = await client.post(
        "/api/v1/admin/ranking-eval/evaluate", json={"hours": 168, "top_n": 4}, headers=admin_headers
    )
    assert resp.status_code == 200
    metrics = resp.json()["metrics"]
    assert metrics["top_n"] == 4
    assert metrics["top10_worth_ratio"] > 0  # item1 已标 worth_writing 且应进 top

    # 快照可查
    resp = await client.get("/api/v1/admin/ranking-eval/snapshots", headers=admin_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["scoring_config"]["risk_threshold"] == 82

    # 标注列表
    resp = await client.get("/api/v1/admin/ranking-eval/labels?source=human", headers=admin_headers)
    assert resp.status_code == 200
    assert any(entry["content_id"] == ids["item1"] for entry in resp.json()["items"])
