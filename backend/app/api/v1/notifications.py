"""
站内通知 API（per-user 隔离版）。

所有端点按 current_user.id 隔离：
- list / unread-count: 只看当前用户可见 + 未读
- mark read / mark all read: 写当前用户的 NotificationRead
- delete: 只能删除定向到当前用户的通知
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.auth import get_current_user
from app.models.user import User
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_notifications(
    unread: bool = Query(False, description="只看未读"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
):
    """获取通知列表（per-user 隔离）。"""
    notifications = await notification_service.get_notifications(
        current_user.id,
        unread_only=unread,
        limit=limit,
        offset=offset,
    )
    return {
        "count": len(notifications),
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "category": n.category,
                "title": n.title,
                "message": n.message,
                "is_read": False,  # per-user 语义：list 出来的都是未读
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
    }


@router.get("/unread-count")
async def unread_count(current_user: User = Depends(get_current_user)):
    """获取未读通知数量（per-user）。"""
    count = await notification_service.get_unread_count(current_user.id)
    return {"count": count}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
):
    """标记单条通知为当前用户已读。"""
    ok = await notification_service.mark_read(current_user.id, notification_id)
    return {"success": ok}


@router.post("/read-all")
async def mark_all_read(current_user: User = Depends(get_current_user)):
    """将当前用户所有可见未读通知标记为已读。"""
    count = await notification_service.mark_all_read(current_user.id)
    return {"marked": count}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
):
    """删除定向到当前用户的通知（广播通知不能被个人删除）。"""
    ok = await notification_service.delete_notification(current_user.id, notification_id)
    return {"success": ok}
