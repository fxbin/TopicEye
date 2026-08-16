"""admin 用户管理 API 集成测试。

覆盖：列表/搜索/筛选、改角色/封禁/改套餐、重置密码、安全护栏、权限校验。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 — 确保所有模型注册到 Base.metadata
from app.api.v1 import auth as auth_api, users as users_api
from app.core.database import Base
from app.services.auth_service import create_session, create_user


@pytest_asyncio.fixture
async def users_client() -> AsyncGenerator[dict, None]:
    """建内存 DB，预置 1 admin + 2 普通用户，返回一个含 client/tokens/ids/session_factory 的 dict。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        admin = await create_user(db, email="admin@x.com", password="Password123", role="admin")
        user1 = await create_user(db, email="alice@x.com", password="Password123")
        user2 = await create_user(db, email="bob@x.com", password="Password123")
        await db.commit()
        admin_token, _ = await create_session(db, admin)
        user1_token, _ = await create_session(db, user1)
        user2_token, _ = await create_session(db, user2)
        await db.commit()
        admin_id, user1_id, user2_id = admin.id, user1.id, user2.id

    app = FastAPI()
    app.include_router(users_api.router)
    app.include_router(auth_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[users_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield {
            "client": client,
            "admin_token": admin_token,
            "admin_id": admin_id,
            "user1_token": user1_token,
            "user1_id": user1_id,
            "user2_token": user2_token,
            "user2_id": user2_id,
            "user2_email": "bob@x.com",
            "session_factory": session_factory,
        }

    await engine.dispose()


def _auth(ctx: dict) -> dict:
    return {"Authorization": f"Bearer {ctx['admin_token']}"}


# ── 权限：非 admin 被拒 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_admin_cannot_access_user_management(users_client):
    resp = await users_client["client"].get(
        "/admin/users",
        headers={"Authorization": f"Bearer {users_client['user1_token']}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_missing_token_rejected(users_client):
    resp = await users_client["client"].get("/admin/users")
    assert resp.status_code == 401


# ── 创建用户 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_create_user_success(users_client):
    """管理员成功创建用户，被创建用户可用设定密码登录。"""
    resp = await users_client["client"].post(
        "/admin/users",
        headers=_auth(users_client),
        json={"email": "newuser@x.com", "password": "Abc12345", "display_name": "新用户"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "newuser@x.com"
    assert body["display_name"] == "新用户"
    assert body["role"] == "user"
    assert body["plan"] == "free"
    assert body["is_active"] is True

    # 新用户可登录
    login = await users_client["client"].post("/auth/login", json={"email": "newuser@x.com", "password": "Abc12345"})
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_create_user_email_conflict_409(users_client):
    """邮箱已存在返回 409。"""
    resp = await users_client["client"].post(
        "/admin/users",
        headers=_auth(users_client),
        json={"email": "alice@x.com", "password": "Abc12345"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_user_weak_password_422(users_client):
    """弱密码被拒。"""
    resp = await users_client["client"].post(
        "/admin/users",
        headers=_auth(users_client),
        json={"email": "weak@x.com", "password": "short"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_user_invalid_role_422(users_client):
    resp = await users_client["client"].post(
        "/admin/users",
        headers=_auth(users_client),
        json={"email": "bad@x.com", "password": "Abc12345", "role": "superadmin"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_user_invalid_plan_422(users_client):
    resp = await users_client["client"].post(
        "/admin/users",
        headers=_auth(users_client),
        json={"email": "bad@x.com", "password": "Abc12345", "plan": "studio"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_user_with_role_and_plan(users_client):
    """管理员创建时可指定 role=admin, plan=pro。"""
    resp = await users_client["client"].post(
        "/admin/users",
        headers=_auth(users_client),
        json={"email": "vip@x.com", "password": "Abc12345", "role": "admin", "plan": "pro"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "admin"
    assert resp.json()["plan"] == "pro"


@pytest.mark.asyncio
async def test_non_admin_cannot_create_user(users_client):
    resp = await users_client["client"].post(
        "/admin/users",
        headers={"Authorization": f"Bearer {users_client['user1_token']}"},
        json={"email": "hack@x.com", "password": "Abc12345"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_user_email_normalized(users_client):
    """邮箱自动小写化 + 去空格。"""
    resp = await users_client["client"].post(
        "/admin/users",
        headers=_auth(users_client),
        json={"email": "  CaseTest@X.COM  ", "password": "Abc12345"},
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "casetest@x.com"


@pytest.mark.asyncio
async def test_create_user_default_display_name(users_client):
    """不传 display_name 时取 email 前缀。"""
    resp = await users_client["client"].post(
        "/admin/users",
        headers=_auth(users_client),
        json={"email": "noname@x.com", "password": "Abc12345"},
    )
    assert resp.status_code == 201
    assert resp.json()["display_name"] == "noname"


@pytest.mark.asyncio
async def test_create_user_duplicate_email_returns_409_not_500(users_client):
    """直接用已存在邮箱创建，返回 409 而非 500（IntegrityError 兜底）。"""
    # alice@x.com 已在 fixture 中预置
    resp = await users_client["client"].post(
        "/admin/users",
        headers=_auth(users_client),
        json={"email": "ALICE@x.com", "password": "Abc12345"},  # 大小写不同但 normalize 后相同
    )
    assert resp.status_code == 409
    assert "已注册" in resp.json()["detail"]


# ── 列表 / 搜索 / 筛选 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_users_pagination_and_search(users_client):
    client = users_client["client"]
    h = _auth(users_client)

    resp = await client.get("/admin/users", headers=h)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3

    resp = await client.get("/admin/users?keyword=alice", headers=h)
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["email"] == "alice@x.com"

    resp = await client.get("/admin/users?role=admin", headers=h)
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["role"] == "admin"


@pytest.mark.asyncio
async def test_list_user_item_has_expected_fields(users_client):
    resp = await users_client["client"].get(
        "/admin/users?keyword=alice",
        headers=_auth(users_client),
    )
    item = resp.json()["items"][0]
    assert item["has_password"] is True
    assert item["oauth_providers"] == []
    assert item["is_active"] is True
    assert item["plan"] == "free"
    assert "created_at" in item


# ── 改角色 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_promotes_user_role(users_client):
    resp = await users_client["client"].patch(
        f"/admin/users/{users_client['user1_id']}",
        headers=_auth(users_client),
        json={"role": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_invalid_role_rejected(users_client):
    resp = await users_client["client"].patch(
        f"/admin/users/{users_client['user1_id']}",
        headers=_auth(users_client),
        json={"role": "superadmin"},
    )
    assert resp.status_code == 422


# ── 封禁 / 解禁 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ban_user_then_session_invalidated(users_client):
    client = users_client["client"]
    user2_token = users_client["user2_token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {user2_token}"})
    assert me.status_code == 200

    resp = await client.patch(
        f"/admin/users/{users_client['user2_id']}",
        headers=_auth(users_client),
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # 封禁后旧 session 立即失效（get_user_for_token 带 is_active 校验）
    me_after = await client.get("/auth/me", headers={"Authorization": f"Bearer {user2_token}"})
    assert me_after.status_code == 401


@pytest.mark.asyncio
async def test_cannot_ban_self(users_client):
    resp = await users_client["client"].patch(
        f"/admin/users/{users_client['admin_id']}",
        headers=_auth(users_client),
        json={"is_active": False},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cannot_demote_self(users_client):
    resp = await users_client["client"].patch(
        f"/admin/users/{users_client['admin_id']}",
        headers=_auth(users_client),
        json={"role": "user"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cannot_ban_last_active_admin(users_client):
    # admin 是唯一活跃 admin，封禁自己应被 self-guard 拦截（403）
    resp = await users_client["client"].patch(
        f"/admin/users/{users_client['admin_id']}",
        headers=_auth(users_client),
        json={"is_active": False},
    )
    assert resp.status_code == 403


# ── 改套餐（仅 free↔pro）────────────────────────────────────────────


@pytest.mark.asyncio
async def test_change_plan_free_to_pro(users_client):
    resp = await users_client["client"].patch(
        f"/admin/users/{users_client['user1_id']}",
        headers=_auth(users_client),
        json={"plan": "pro"},
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "pro"


@pytest.mark.asyncio
async def test_change_plan_studio_rejected(users_client):
    resp = await users_client["client"].patch(
        f"/admin/users/{users_client['user1_id']}",
        headers=_auth(users_client),
        json={"plan": "studio"},
    )
    assert resp.status_code == 422


# ── 重置密码 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_password_revokes_all_sessions(users_client):
    client = users_client["client"]
    user2_token = users_client["user2_token"]

    resp = await client.post(
        f"/admin/users/{users_client['user2_id']}/reset-password",
        headers=_auth(users_client),
        json={"new_password": "NewPassword456"},
    )
    assert resp.status_code == 200
    assert resp.json()["revoked_sessions"] >= 1

    # user2 的旧 session 应已失效
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {user2_token}"})
    assert me.status_code == 401

    # 新密码可登录
    login = await client.post(
        "/auth/login",
        json={"email": users_client["user2_email"], "password": "NewPassword456"},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_reset_password_weak_password_rejected(users_client):
    resp = await users_client["client"].post(
        f"/admin/users/{users_client['user2_id']}/reset-password",
        headers=_auth(users_client),
        json={"new_password": "short"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reset_password_unknown_user_404(users_client):
    resp = await users_client["client"].post(
        "/admin/users/99999/reset-password",
        headers=_auth(users_client),
        json={"new_password": "NewPassword456"},
    )
    assert resp.status_code == 404


# ── 不存在的用户 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_unknown_user_404(users_client):
    resp = await users_client["client"].patch(
        "/admin/users/99999",
        headers=_auth(users_client),
        json={"plan": "pro"},
    )
    assert resp.status_code == 404


# ── 自助改密（/auth/change-password）────────────────────────────────


@pytest.mark.asyncio
async def test_user_can_change_own_password(users_client):
    client = users_client["client"]
    user1_token = users_client["user1_token"]

    resp = await client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {user1_token}"},
        json={"old_password": "Password123", "new_password": "BrandNew789"},
    )
    assert resp.status_code == 200

    # 当前 session 保留（keep_token）
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {user1_token}"})
    assert me.status_code == 200

    # 新密码可登录
    login = await client.post("/auth/login", json={"email": "alice@x.com", "password": "BrandNew789"})
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_old_password(users_client):
    resp = await users_client["client"].post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {users_client['user1_token']}"},
        json={"old_password": "WrongOldPwd1", "new_password": "BrandNew789"},
    )
    assert resp.status_code == 400
