"""
Notification per-user 隔离 + NotificationRead 单元测试。

覆盖：
- 广播（target_user_ids=None）通知对所有用户可见
- 定向通知只对目标用户可见
- 标已读是 per-user 的（A 标已读不影响 B）
- 标全读是 per-user 的
- 删通知只允许删定向自己的
- 删不存在的通知返回 False
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.notification import Notification
from app.services import notification_service
from app.services.auth_service import create_user
from datetime import UTC


@pytest.mark.asyncio
async def test_per_user_visibility_and_read_isolation(monkeypatch):
    # 用独立的 :memory: 引擎，跑 metadata.create_all 建表
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 把 service 的 async_session 重定向到这个 engine
    monkeypatch.setattr(notification_service, "async_session", session_factory)

    try:
        # ── setup users ──
        async with session_factory() as db:
            alice = await create_user(db, email="alice@test", password="pw")
            bob = await create_user(db, email="bob@test", password="pw")
            admin = await create_user(db, email="admin@test", password="pw", role="admin")
            await db.commit()
            alice_id, bob_id, admin_id = alice.id, bob.id, admin.id

        # ── 1. broadcast: everyone visible ──
        await notification_service.push_notification("info", "system", "系统公告", "v1.0 上线")

        for uid in (alice_id, bob_id, admin_id):
            notifs = await notification_service.get_notifications(uid)
            assert len(notifs) == 1, f"user {uid} should see 1 broadcast"
            assert notifs[0].title == "系统公告"

        # ── 2. targeted: only that user visible ──
        await notification_service.push_notification(
            "success",
            "weekly_digest",
            "周刊已生成",
            "W12",
            target_user_ids=[admin_id],
        )

        assert len(await notification_service.get_notifications(alice_id)) == 1
        assert len(await notification_service.get_notifications(bob_id)) == 1
        assert len(await notification_service.get_notifications(admin_id)) == 2

        # ── 3. multi-target fan-out ──
        await notification_service.push_notification(
            "info",
            "system",
            "新功能",
            "快试试",
            target_user_ids=[alice_id, bob_id],
        )
        assert len(await notification_service.get_notifications(alice_id)) == 2
        assert len(await notification_service.get_notifications(bob_id)) == 2
        assert len(await notification_service.get_notifications(admin_id)) == 2

        # ── 4. read is per-user ──
        notifs = await notification_service.get_notifications(alice_id)
        first_id = notifs[0].id
        ok = await notification_service.mark_read(alice_id, first_id)
        assert ok is True

        # alice unread = 1 (broadcast marked read, alice-targeted still unread)
        # bob unread = 2 (broadcast + bob-targeted, never marked read)
        # admin unread = 2 (broadcast + admin-targeted, never marked read)
        assert await notification_service.get_unread_count(alice_id) == 1
        assert await notification_service.get_unread_count(bob_id) == 2
        assert await notification_service.get_unread_count(admin_id) == 2

        # alice's full list = 2 (no read filter), unread = 1
        assert len(await notification_service.get_notifications(alice_id, unread_only=True)) == 1
        assert len(await notification_service.get_notifications(alice_id, unread_only=False)) == 2

        # ── 5. mark_all_read only affects that user ──
        marked = await notification_service.mark_all_read(alice_id)
        assert marked == 1  # alice has 1 unread left
        assert await notification_service.get_unread_count(alice_id) == 0
        assert await notification_service.get_unread_count(bob_id) == 2  # bob unaffected

        # ── 6. delete: only allowed on targeted notifications ──
        from sqlalchemy import select

        async with session_factory() as db:
            broadcast = (
                (await db.execute(select(Notification).where(Notification.target_user_id.is_(None)))).scalars().first()
            )
            assert broadcast is not None
            ok = await notification_service.delete_notification(alice_id, broadcast.id)
            assert ok is False  # can't delete broadcast

        # alice can delete the targeted one
        async with session_factory() as db:
            targeted = (
                (await db.execute(select(Notification).where(Notification.target_user_id == alice_id)))
                .scalars()
                .first()
            )
            assert targeted is not None
            ok = await notification_service.delete_notification(alice_id, targeted.id)
            assert ok is True

        # ── 7. delete non-existent returns False ──
        ok = await notification_service.delete_notification(alice_id, 99999)
        assert ok is False

        # ── 8. mark_read on inaccessible notification returns False ──
        async with session_factory() as db:
            bob_targeted = (
                (await db.execute(select(Notification).where(Notification.target_user_id == bob_id))).scalars().first()
            )
            assert bob_targeted is not None
            # alice cannot mark bob's targeted as read
            ok = await notification_service.mark_read(alice_id, bob_targeted.id)
            assert ok is False

        # ── 9. cleanup_old_notifications removes old rows ──
        from datetime import datetime, timedelta, timezone

        async with session_factory() as db:
            old = Notification(
                type="info",
                category="system",
                title="old",
                message="m",
            )
            db.add(old)
            await db.flush()
            old.created_at = datetime.now(UTC) - timedelta(days=60)
            await db.commit()
            old_id = old.id

        deleted = await notification_service.cleanup_old_notifications(days=30)
        assert deleted >= 1
        async with session_factory() as db:
            still = (await db.execute(select(Notification).where(Notification.id == old_id))).scalar_one_or_none()
            assert still is None
    finally:
        await engine.dispose()
