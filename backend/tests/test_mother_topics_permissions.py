"""Mother topics per-user isolation + permission boundaries.

覆盖路线 C（系统模板库 + 用户 fork）的核心契约：
- 普通用户 list 能看到「系统模板 + 自己的 fork」，看不到其他用户的私有母题
- 普通用户 create 创建私有 fork（owner_user_id = self.id），不再 403
- 普通用户 update/delete 只能动自己的 fork；系统模板只读（403）；他人母题 404（不泄漏存在）
- admin 能操作系统模板（owner_user_id IS NULL）
- POST /fork-defaults 幂等：首次 fork、重复调用跳过已存在的
- score-batch 按当前用户的可见母题打分（用户改了母题能生效）
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api, mother_topics as mother_topics_api
from app.core.database import Base
from app.models.mother_topic import MotherTopic
from app.services.auth_service import create_session, create_user


@pytest.mark.asyncio
async def test_mother_topics_per_user_isolation_and_fork():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user_a = await create_user(db, email="user-a@example.com", password="Password123", role="user")
        user_b = await create_user(db, email="user-b@example.com", password="Password123", role="user")
        admin = await create_user(db, email="admin@example.com", password="Password123", role="admin")
        token_a, _ = await create_session(db, user_a)
        token_b, _ = await create_session(db, user_b)
        token_admin, _ = await create_session(db, admin)
        # 系统模板（owner IS NULL）
        db.add_all(
            [
                MotherTopic(
                    name="AI 工具",
                    keywords=["AI", "效率"],
                    is_active=True,
                    display_order=1,
                    owner_user_id=None,
                ),
                MotherTopic(
                    name="观察",
                    keywords=["趋势"],
                    is_active=True,
                    display_order=2,
                    owner_user_id=None,
                ),
                MotherTopic(
                    name="停用模板",
                    keywords=["旧"],
                    is_active=False,
                    display_order=3,
                    owner_user_id=None,
                ),
            ]
        )
        # user_b 已有的私有母题（不应被 user_a 看到）
        db.add(
            MotherTopic(
                name="B 私有",
                keywords=["secret"],
                is_active=True,
                display_order=1,
                owner_user_id=user_b.id,
            )
        )
        await db.commit()

    app = FastAPI()
    app.include_router(mother_topics_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[mother_topics_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # ── 1. 匿名访问 401 ──
        anon = await client.get("/mother-topics?active_only=true")
        assert anon.status_code == 401

        # ── 2. user_a list active_only：只看到系统模板 active + user_a 自己的（此时还没 fork，只有系统模板）──
        resp = await client.get(
            "/mother-topics?active_only=true",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        names_a = [item["name"] for item in resp.json()]
        assert names_a == ["AI 工具", "观察"]  # 不含 B 私有、不含停用模板
        # 系统模板 owner_user_id 应为 null
        assert all(item["owner_user_id"] is None for item in resp.json())

        # ── 3. user_a list active_only=false：能看到停用的系统模板（不再是 admin-only）──
        resp = await client.get(
            "/mother-topics?active_only=false",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200  # 不再是 403
        names_a_full = [item["name"] for item in resp.json()]
        assert "停用模板" in names_a_full  # 能看到停用的系统模板
        assert "B 私有" not in names_a_full  # 看不到其他用户的私有母题

        # ── 4. user_a create：创建私有 fork，不再 403 ──
        resp = await client.post(
            "/mother-topics",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"name": "我的选题", "keywords": ["自定义"], "display_order": 1},
        )
        assert resp.status_code == 200, resp.text
        created = resp.json()
        assert created["name"] == "我的选题"
        assert created["owner_user_id"] == user_a.id  # owner 是自己

        # ── 5. user_a create 重名：同 scope 内冲突 409 ──
        resp = await client.post(
            "/mother-topics",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"name": "我的选题", "keywords": ["dup"]},
        )
        assert resp.status_code == 409

        # ── 6. admin create：创建系统模板（owner=None）──
        resp = await client.post(
            "/mother-topics",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={"name": "新系统模板", "keywords": ["sys"], "display_order": 10},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["owner_user_id"] is None

        # ── 7. user_a update 系统模板：403（系统模板不可改）──
        # 找一个系统模板 id
        sys_topic_id = next(
            item["id"]
            for item in (
                await client.get(
                    "/mother-topics?active_only=false",
                    headers={"Authorization": f"Bearer {token_a}"},
                )
            ).json()
            if item["owner_user_id"] is None
        )
        resp = await client.put(
            f"/mother-topics/{sys_topic_id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"name": "篡改系统模板"},
        )
        assert resp.status_code == 403
        assert "系统模板" in resp.json()["detail"]

        # ── 8. user_a update user_b 的私有母题：404（不泄漏存在）──
        # 查 user_b 的私有母题 id
        async with session_factory() as db:
            from sqlalchemy import select

            b_topic = (await db.execute(select(MotherTopic).where(MotherTopic.owner_user_id == user_b.id))).scalar_one()
        resp = await client.put(
            f"/mother-topics/{b_topic.id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"name": "篡改B"},
        )
        assert resp.status_code == 404

        # ── 9. user_a update 自己的私有母题：200 ──
        resp = await client.put(
            f"/mother-topics/{created['id']}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"weight": 2.0, "keywords": ["改后"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["weight"] == 2.0

        # ── 10. admin update 系统模板：200 ──
        resp = await client.put(
            f"/mother-topics/{sys_topic_id}",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={"weight": 1.5},
        )
        assert resp.status_code == 200
        assert resp.json()["weight"] == 1.5

        # ── 11. fork-defaults 幂等性 ──
        # user_a 还没 fork，fork 一次
        resp = await client.post(
            "/mother-topics/fork-defaults",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200, resp.text
        fork1 = resp.json()
        assert fork1["forked"] > 0  # 首次 fork 复制了系统模板

        # 再 fork 一次：应该全部跳过（幂等）
        resp = await client.post(
            "/mother-topics/fork-defaults",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        fork2 = resp.json()
        assert fork2["forked"] == 0
        assert fork2["skipped"] > 0

        # ── 12. fork 后 user_a 的 list 应该包含 fork 的副本 ──
        resp = await client.get(
            "/mother-topics?active_only=true",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        names_after_fork = [item["name"] for item in resp.json()]
        assert "AI 工具" in names_after_fork  # fork 的副本
        assert "我的选题" in names_after_fork  # 自己创建的
        # fork 的副本 owner_user_id 应该是 user_a.id
        forked_ai = next(
            item for item in resp.json() if item["name"] == "AI 工具" and item["owner_user_id"] == user_a.id
        )
        assert forked_ai["owner_user_id"] == user_a.id

        # ── 13. score-batch：user_a 打分用「系统模板 + 自己的 fork」，不用 user_b 的 ──
        resp = await client.post(
            "/mother-topics/score-batch",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"items": [{"title": "AI 效率工具观察", "summary": "提升创作效率"}]},
        )
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        # 至少匹配到 AI 工具（系统模板 + fork 副本都叫这个名字，但打分去重后 top_topic 仍是它）
        assert result["top_topic"] is not None
        # 不应该出现 B 私有
        topic_names = [s["name"] for s in result["topic_scores"]]
        assert "B 私有" not in topic_names

        # ── 14. admin list scope=all 看全量（含其他用户私有母题）──
        resp = await client.get(
            "/mother-topics?active_only=false&scope=all",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert resp.status_code == 200
        admin_names = [item["name"] for item in resp.json()]
        assert "B 私有" in admin_names  # admin 能看到所有用户的

        # ── 14b. admin list scope=mine 只看自己（隔离）──
        resp = await client.get(
            "/mother-topics?active_only=false&scope=mine",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert resp.status_code == 200
        admin_mine_names = [item["name"] for item in resp.json()]
        assert "B 私有" not in admin_mine_names  # admin 用户侧也隔离

        # ── 14c. 普通用户 scope=all 被拒 ──
        resp = await client.get(
            "/mother-topics?active_only=false&scope=all",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

        # ── 15. user_a delete 系统模板：403 ──
        resp = await client.delete(
            f"/mother-topics/{sys_topic_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403

        # ── 16. user_a delete 自己的私有母题：200 ──
        resp = await client.delete(
            f"/mother-topics/{created['id']}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200

    await engine.dispose()
