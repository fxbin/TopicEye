from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api
from app.api.v1 import product_feedback as product_feedback_api
from app.core.database import Base
from app.services.auth_service import create_session, create_user
from datetime import UTC


@pytest_asyncio.fixture
async def product_feedback_client() -> AsyncGenerator[tuple[httpx.AsyncClient, str, str], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="feedback-user@example.com", password="Password123", role="user")
        admin = await create_user(db, email="feedback-admin@example.com", password="Password123", role="admin")
        user_token, _ = await create_session(db, user)
        admin_token, _ = await create_session(db, admin)
        # product_updates 通过 alembic migration seed, 但测试用 create_all 不走 migration,
        # 手动插一条 (test_product_updates_are_public_read_and_admin_managed 依赖)
        from app.models.product_feedback import ProductUpdate
        from datetime import datetime, timezone

        db.add(
            ProductUpdate(
                version="v0.2.1",
                status="shipped",
                shipped_at=datetime.now(UTC),
                items=[
                    {"title": "匿名问题反馈", "description": "未登录用户也可以提交产品问题", "kind": "improvement"},
                ],
            )
        )
        await db.commit()

    app = FastAPI()
    app.include_router(product_feedback_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[product_feedback_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, user_token, admin_token

    await engine.dispose()


@pytest.mark.asyncio
async def test_issue_feedback_allows_anonymous_submit_and_admin_management(product_feedback_client):
    client, user_token, admin_token = product_feedback_client

    anonymous = await client.post(
        "/product-feedback/issues",
        json={
            "title": "一直 pending",
            "description": "新进来的选题没有进入 AI 分析流程。",
            "area": "analysis",
            "severity": "high",
        },
    )
    assert anonymous.status_code == 201
    anonymous_body = anonymous.json()
    assert anonymous_body["user_id"] is None
    assert anonymous_body["reporter_email"] is None
    anonymous_issue_id = anonymous_body["id"]

    created = await client.post(
        "/product-feedback/issues",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "title": "一直 pending",
            "description": "新进来的选题没有进入 AI 分析流程。",
            "area": "analysis",
            "severity": "high",
        },
    )
    assert created.status_code == 201
    issue_id = created.json()["id"]
    assert created.json()["status"] == "open"

    mine = await client.get("/product-feedback/issues/mine", headers={"Authorization": f"Bearer {user_token}"})
    assert mine.status_code == 200
    assert mine.json()["total"] == 1
    assert mine.json()["open_count"] == 1
    assert mine.json()["items"][0]["reporter_email"] == "feedback-user@example.com"
    assert mine.json()["items"][0]["id"] == issue_id

    ordinary_list = await client.get("/product-feedback/issues", headers={"Authorization": f"Bearer {user_token}"})
    assert ordinary_list.status_code == 403

    ordinary_patch = await client.patch(
        f"/product-feedback/issues/{issue_id}",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"status": "fixed", "resolution_note": "并发队列已修复"},
    )
    assert ordinary_patch.status_code == 403

    admin_list = await client.get("/product-feedback/issues", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_list.status_code == 200
    assert admin_list.json()["total"] == 2
    admin_items = admin_list.json()["items"]
    assert any(item["id"] == anonymous_issue_id and item["user_id"] is None for item in admin_items)
    assert any(item["id"] == issue_id and item["reporter_email"] == "feedback-user@example.com" for item in admin_items)

    fixed_anonymous = await client.patch(
        f"/product-feedback/issues/{anonymous_issue_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "fixed", "resolution_note": "匿名反馈也已进入处理闭环"},
    )
    assert fixed_anonymous.status_code == 200
    assert fixed_anonymous.json()["status"] == "fixed"
    assert fixed_anonymous.json()["user_id"] is None

    fixed = await client.patch(
        f"/product-feedback/issues/{issue_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "fixed", "resolution_note": "已改为并发后台分析队列"},
    )
    assert fixed.status_code == 200
    assert fixed.json()["status"] == "fixed"
    assert fixed.json()["fixed_at"] is not None
    assert fixed.json()["resolution_note"] == "已改为并发后台分析队列"

    mine_after_fix = await client.get(
        "/product-feedback/issues/mine", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert mine_after_fix.json()["open_count"] == 0
    assert mine_after_fix.json()["fixed_count"] == 1


@pytest.mark.asyncio
async def test_product_updates_are_public_read_and_admin_managed(product_feedback_client):
    client, user_token, admin_token = product_feedback_client

    updates = await client.get("/product-feedback/updates")
    assert updates.status_code == 200
    assert updates.json()["total"] >= 1
    # items 是嵌套结构: 每个 update 有 items 数组 (含 title/description/kind)
    all_entries = [entry for update in updates.json()["items"] for entry in update.get("items", [])]
    assert any(entry["title"] == "匿名问题反馈" for entry in all_entries)

    ordinary_create = await client.post(
        "/product-feedback/updates",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "title": "AI 分析队列并发化",
            "description": "提高待分析内容吞吐，降低 pending 堆积。",
            "kind": "roadmap",
            "status": "planned",
        },
    )
    assert ordinary_create.status_code == 403

    shipped_updates = await client.get("/product-feedback/updates?status=shipped")
    assert shipped_updates.status_code == 200
    assert shipped_updates.json()["total"] >= 1
    assert all(item["status"] == "shipped" for item in shipped_updates.json()["items"])

    created = await client.post(
        "/product-feedback/updates",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "version": "v0.3.0",
            "status": "planned",
            "target_date": "2026-06-09",
            "items": [
                {"title": "AI 分析队列并发化", "description": "提高待分析内容吞吐", "kind": "release"},
            ],
        },
    )
    assert created.status_code == 201
    update_id = created.json()["id"]
    assert created.json()["target_date"] == "2026-06-09"

    shipped = await client.patch(
        f"/product-feedback/updates/{update_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "shipped", "version": "v0.2.0"},
    )
    assert shipped.status_code == 200
    assert shipped.json()["status"] == "shipped"
    assert shipped.json()["shipped_at"] is not None
