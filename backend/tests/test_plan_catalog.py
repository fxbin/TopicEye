import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1 import plans as plans_api
from app.core.database import Base
from app.services.auth_service import create_session, create_user
from app.services.plan_catalog import (
    get_plan_catalog,
    get_plan_catalog_for_user,
    get_tier_by_key,
)


def test_plan_catalog_declares_free_and_paid_boundaries():
    catalog = get_plan_catalog()
    tiers = {tier["key"]: tier for tier in catalog["tiers"]}

    assert {"free", "pro", "studio", "enterprise"} == set(tiers)
    assert tiers["free"]["limits"]["custom_sources"] == "管理员维护"
    assert tiers["pro"]["recommended"] is True
    assert "收藏夹、算法流程和网文雷达对登录用户开放" in tiers["free"]["features"]
    assert "自定义 AI Key 和模型配置不对免费用户开放" in tiers["free"]["features"]
    assert "普通用户自助配置个人信源和 API 数据源" in tiers["pro"]["features"]
    assert "允许配置个人自定义 AI Key / API Base / 模型路由" in tiers["pro"]["features"]
    assert "团队成员和协作看板（规划中）" in tiers["studio"]["features"]
    assert "外部 API / Webhook 接入（规划中）" in tiers["enterprise"]["features"]
    assert catalog["free_area"]
    assert catalog["paid_area"]
    assert "未完成能力只作为路线图展示，不作为当前可用承诺" in catalog["paid_area"]


def test_plan_catalog_resolves_current_user_tier():
    assert get_tier_by_key("pro")["name"] == "Pro 规划"
    assert get_tier_by_key("missing")["key"] == "free"

    catalog = get_plan_catalog_for_user("studio")

    assert catalog["current_plan"] == "studio"
    assert catalog["current_tier"]["limits"]["team_members"] == "规划：多人"


@pytest.mark.asyncio
async def test_plans_route_returns_current_boundaries():
    app = FastAPI()
    app.include_router(plans_api.router)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/plans")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tiers"][0]["name"] == "当前免费体验"
    assert payload["tiers"][1]["name"] == "Pro 规划"
    assert payload["free_area"][0].startswith("公开可看")
    assert payload["paid_area"][0] == "自定义 AI 配置需要付费权益，当前按用户 plan 做后端拦截"


@pytest.mark.asyncio
async def test_plans_api_resolves_current_plan_from_bearer_token(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(plans_api, "async_session", session_factory)

    async with session_factory() as db:
        user = await create_user(db, email="plan@example.com", password="Password123")
        user.plan = "studio"
        token, _session = await create_session(db, user)
        await db.commit()

    catalog = await plans_api.list_plans(authorization=f"Bearer {token}")

    assert catalog["current_plan"] == "studio"
    assert catalog["current_tier"]["name"] == "Studio 规划"
    await engine.dispose()
