"""
User API token 测试。

覆盖：
- 创建 token / 明文只返回一次
- list_api_tokens per-user 隔离
- revoke / delete per-user 校验
- get_user_for_token 支持 API token 鉴权（fallback to API token）
- 撤销后鉴权失效
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.user import User, UserApiToken
from app.services.auth_service import (
    create_api_token,
    create_user,
    delete_api_token,
    get_user_for_token,
    list_api_tokens,
    revoke_api_token,
)


@pytest.mark.asyncio
async def test_api_token_crud_and_auth_flow():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        # ── setup two users ──
        async with session_factory() as db:
            alice = await create_user(db, email="alice@t", password="pw")
            bob = await create_user(db, email="bob@t", password="pw")
            await db.commit()
            alice_id, bob_id = alice.id, bob.id

        # ── 1. alice creates a token ──
        async with session_factory() as db:
            raw_token, record = await create_api_token(
                db,
                user_id=alice_id,
                name="CI 脚本",
            )
            await db.commit()
            assert record.id > 0
            assert record.user_id == alice_id
            assert record.name == "CI 脚本"
            assert record.revoked_at is None
            assert record.token_prefix  # 前 8 位
            assert record.token_hash != raw_token  # hash 不等于明文

        # ── 2. list: alice sees 1, bob sees 0 ──
        async with session_factory() as db:
            alice_tokens = await list_api_tokens(db, alice_id)
            bob_tokens = await list_api_tokens(db, bob_id)
            assert len(alice_tokens) == 1
            assert len(bob_tokens) == 0

        # ── 3. get_user_for_token accepts API token ──
        async with session_factory() as db:
            user = await get_user_for_token(db, raw_token)
            assert user is not None
            assert user.id == alice_id

        # ── 4. wrong token returns None ──
        async with session_factory() as db:
            assert await get_user_for_token(db, "totally-wrong-token") is None

        # ── 5. revoke: alice revokes her own ──
        async with session_factory() as db:
            token_id = (await list_api_tokens(db, alice_id))[0].id
            ok = await revoke_api_token(db, user_id=alice_id, token_id=token_id)
            assert ok is True
            await db.commit()

        # ── 6. revoked token no longer authenticates ──
        async with session_factory() as db:
            assert await get_user_for_token(db, raw_token) is None

        # ── 7. bob cannot revoke alice's token ──
        async with session_factory() as db:
            ok = await revoke_api_token(db, user_id=bob_id, token_id=token_id)
            assert ok is False

        # ── 8. alice creates another token and deletes it ──
        async with session_factory() as db:
            raw2, record2 = await create_api_token(
                db,
                user_id=alice_id,
                name="temp",
            )
            await db.commit()
            token2_id = record2.id
        async with session_factory() as db:
            ok = await delete_api_token(db, user_id=alice_id, token_id=token2_id)
            assert ok is True
            await db.commit()
        async with session_factory() as db:
            assert await get_user_for_token(db, raw2) is None  # 删除后鉴权失败

        # ── 9. last_used_at updated on auth ──
        async with session_factory() as db:
            raw3, record3 = await create_api_token(
                db,
                user_id=alice_id,
                name="track",
            )
            await db.commit()
            assert record3.last_used_at is None
        async with session_factory() as db:
            await get_user_for_token(db, raw3)
            await db.commit()
        async with session_factory() as db:
            from sqlalchemy import select

            tracked = (await db.execute(select(UserApiToken).where(UserApiToken.id == record3.id))).scalar_one()
            assert tracked.last_used_at is not None
    finally:
        await engine.dispose()
