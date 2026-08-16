"""报告阅读记录 API。

端点：
- POST /read-records: 幂等上报一次阅读会话（前端在切换报告/页面隐藏/卸载时调用）。
- GET /read-records: 查询当前用户的阅读历史。

分层合规（AGENTS.md）：
- 不 import sqlalchemy（除 AsyncSession 类型注解）。
- 不 import ORM 模型类（仅 ReadTargetType 枚举允许）。
- 不写 select/db.execute/db.add，全部走 service/repo。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.read_record import ReadTargetType
from app.models.user import User
from app.schemas.read_record import (
    ReadRecordListResponse,
    ReadRecordReport,
    ReadRecordResponse,
)
from app.services import read_record_service

router = APIRouter(prefix="/read-records", tags=["read-records"])


@router.post("", response_model=ReadRecordResponse, status_code=201)
async def report_read_session(
    data: ReadRecordReport,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReadRecordResponse:
    """上报一次阅读会话。

    幂等：同一 (user, target_type, target_key) 多次上报会累加 read_count / accumulated_ms，
    不新增行。返回最新记录状态。
    """
    record = await read_record_service.report_session(db, current_user.id, data)
    await db.commit()
    await db.refresh(record)
    return ReadRecordResponse.model_validate(record)


@router.get("", response_model=ReadRecordListResponse)
async def list_read_records(
    target_type: ReadTargetType | None = Query(default=None, description="按报告类型过滤"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReadRecordListResponse:
    """查询当前用户的阅读历史（按 last_read_at DESC）。"""
    items = await read_record_service.list_history(db, current_user.id, target_type=target_type, limit=limit)
    responses = [ReadRecordResponse.model_validate(item) for item in items]
    return ReadRecordListResponse(
        items=responses,
        total=len(responses),
        page=1,
        page_size=limit,
    )
