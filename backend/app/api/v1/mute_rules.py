"""用户自定义降噪规则 CRUD（#171）。

- GET    /mute-rules        当前用户全量规则（新→旧）
- POST   /mute-rules        新增（每类上限 50，重复返回 409）
- DELETE /mute-rules/{id}   删除自己的规则（不存在/他人规则返回 404）

规则变更后失效列表/精选读缓存（与 ignored_items 端点同口径），
命中项只从该用户可见的 contents 列表与 today-picks 中排除。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._db_write import write_with_503_low_latency
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import AppException
from app.models.user import User
from app.schemas.mute_rule import MuteRuleCreate, MuteRuleListResponse, MuteRuleResponse
from app.services import mute_rule_service
from app.services.content_read_cache import invalidate_content_read_caches

router = APIRouter(prefix="/mute-rules", tags=["mute-rules"], dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)


@router.get("", response_model=MuteRuleListResponse)
async def list_mute_rules(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rules = await mute_rule_service.list_mute_rules(db, current_user.id)
    items = [MuteRuleResponse.model_validate(rule) for rule in rules]
    return MuteRuleListResponse(count=len(items), items=items)


@router.post("", response_model=MuteRuleResponse, status_code=201)
async def create_mute_rule(
    req: MuteRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    async def _write():
        return await mute_rule_service.create_mute_rule(
            db, user_id=current_user.id, rule_type=req.rule_type, value=req.value
        )

    try:
        rule = await write_with_503_low_latency(db, _write)
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    invalidate_content_read_caches()
    logger.info("mute rule created: user_id=%d, rule_id=%d, type=%s", current_user.id, rule.id, rule.rule_type)
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_mute_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    async def _write() -> bool:
        return await mute_rule_service.delete_mute_rule(db, user_id=current_user.id, rule_id=rule_id)

    removed = await write_with_503_low_latency(db, _write)
    if not removed:
        raise HTTPException(status_code=404, detail="规则不存在或已删除")
    invalidate_content_read_caches()
    logger.info("mute rule deleted: user_id=%d, rule_id=%d", current_user.id, rule_id)
