"""
站内通知服务（per-user 隔离版）。

投递模型：
- target_user_id = NULL → 广播（所有用户可见）
- target_user_id != NULL → 定向（仅该用户可见）

已读状态：
- Notification.is_read 字段保留作为历史兼容，但新代码不再使用
- 实际"是否已读"由 NotificationRead 表控制（per-user 复合主键）
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC

from sqlalchemy import func, select

from app.core.database import async_session
from app.models.notification import Notification, NotificationRead

logger = logging.getLogger(__name__)


async def push_notification(
    type: str,
    category: str,
    title: str,
    message: str,
    *,
    target_user_ids: Iterable[int] | None = None,
) -> list[Notification]:
    """推送站内通知。

    Parameters
    ----------
    target_user_ids
        - None: 广播（一条 Notification, target_user_id=NULL）
        - 单元素: 定向（一条 Notification, target_user_id=该 user）
        - 多元素: fan-out（每个 user 一条 Notification）
    """
    target_list = list(target_user_ids) if target_user_ids is not None else None
    async with async_session() as db:
        if target_list is None:
            notifs = [
                Notification(
                    type=type,
                    category=category,
                    title=title,
                    message=message,
                    target_user_id=None,
                )
            ]
        elif len(target_list) == 1:
            notifs = [
                Notification(
                    type=type,
                    category=category,
                    title=title,
                    message=message,
                    target_user_id=target_list[0],
                )
            ]
        else:
            notifs = [
                Notification(
                    type=type,
                    category=category,
                    title=title,
                    message=message,
                    target_user_id=uid,
                )
                for uid in target_list
            ]
        for n in notifs:
            db.add(n)
        await db.commit()
        for n in notifs:
            await db.refresh(n)
        logger.info(
            "通知推送: [%s] %s (recipients=%s)",
            type,
            title,
            "broadcast" if target_list is None else len(target_list),
        )
        return notifs


async def get_notifications(
    user_id: int,
    *,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    """获取指定用户可见的通知列表（per-user 隔离 + per-user 已读）。"""
    async with async_session() as db:
        # 可视范围：广播 OR 定向到该用户
        visibility = (Notification.target_user_id.is_(None)) | (Notification.target_user_id == user_id)
        # 排除已读：左连接 NotificationRead，未读 = 无匹配
        read_subq = select(NotificationRead.notification_id).where(NotificationRead.user_id == user_id)
        stmt = (
            select(Notification)
            .where(visibility, ~Notification.id.in_(read_subq) if unread_only else True)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if unread_only:
            stmt = stmt.where(~Notification.id.in_(read_subq))
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def get_unread_count(user_id: int) -> int:
    """获取指定用户的未读通知数。"""
    async with async_session() as db:
        visibility = (Notification.target_user_id.is_(None)) | (Notification.target_user_id == user_id)
        read_subq = select(NotificationRead.notification_id).where(NotificationRead.user_id == user_id)
        stmt = select(func.count(Notification.id)).where(visibility, ~Notification.id.in_(read_subq))
        result = await db.execute(stmt)
        return int(result.scalar() or 0)


async def mark_read(user_id: int, notification_id: int) -> bool:
    """标记指定通知为该用户已读（upsert）。"""
    async with async_session() as db:
        # 校验通知对该用户可见
        visibility = (Notification.target_user_id.is_(None)) | (Notification.target_user_id == user_id)
        notif = await db.execute(select(Notification.id).where(Notification.id == notification_id, visibility))
        if notif.scalar_one_or_none() is None:
            return False
        # 用 INSERT ... ON CONFLICT DO NOTHING (PG) 幂等写入
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(NotificationRead)
            .values(
                user_id=user_id,
                notification_id=notification_id,
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "notification_id"],
            )
        )
        await db.execute(stmt)
        await db.commit()
        return True


async def mark_all_read(user_id: int) -> int:
    """将该用户所有可见未读通知标记为已读。

    Returns: 实际新标记的条数。
    """
    async with async_session() as db:
        visibility = (Notification.target_user_id.is_(None)) | (Notification.target_user_id == user_id)
        read_subq = select(NotificationRead.notification_id).where(NotificationRead.user_id == user_id)
        unread_ids = (
            (await db.execute(select(Notification.id).where(visibility, ~Notification.id.in_(read_subq))))
            .scalars()
            .all()
        )
        if not unread_ids:
            return 0

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        records = [{"user_id": user_id, "notification_id": nid} for nid in unread_ids]
        stmt = (
            pg_insert(NotificationRead)
            .values(records)
            .on_conflict_do_nothing(index_elements=["user_id", "notification_id"])
        )
        await db.execute(stmt)
        await db.commit()
        return len(unread_ids)


async def delete_notification(user_id: int, notification_id: int) -> bool:
    """删除通知。

    只能删除定向到当前用户的通知；广播通知不能被个人删除
    （避免影响其他用户）。NotificationRead 通过 ON DELETE CASCADE 自动清理。
    """
    from sqlalchemy import delete

    async with async_session() as db:
        result = await db.execute(
            delete(Notification).where(
                Notification.id == notification_id,
                Notification.target_user_id == user_id,  # 仅允许删除定向给自己的
            )
        )
        await db.commit()
        return result.rowcount > 0


async def cleanup_old_notifications(*, days: int = 30) -> int:
    """清理超过 N 天的通知（NotificationRead 通过 CASCADE 自动清理）。"""
    from datetime import datetime, timedelta

    from sqlalchemy import delete

    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with async_session() as db:
        result = await db.execute(delete(Notification).where(Notification.created_at < cutoff))
        await db.commit()
        return result.rowcount
