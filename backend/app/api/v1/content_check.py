"""文稿检测入口——发布前违禁词 / 广告法极限词扫描。

入口层只做三件事：路由、schema 校验、调 service（`sensitive_word_service.scan`
纯函数）。无 ORM、无 session。认证用 `Depends(get_current_user)` 防匿名刷大文本
（与 skill.py 同模式）；限流由 `/api/v1` 前缀的全局中间件自动覆盖，无需单列规则。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.auth import get_current_user
from app.schemas.content_check import SensitiveCheckRequest, SensitiveCheckResponse
from app.services.sensitive_word_service import scan

router = APIRouter(prefix="/content-check", tags=["content-check"], dependencies=[Depends(get_current_user)])


@router.post(
    "/sensitive",
    response_model=SensitiveCheckResponse,
    summary="文稿违禁词/广告法极限词检测",
    description=(
        "粘贴文稿原文，返回违禁词/极限词命中清单：含原文字符偏移（start/end）、"
        "分类（advertising_extreme / political_adult / platform_throttle）、"
        "严重度（high/medium/low）与替换建议。单次最多 20000 字符，超出返回 422。"
    ),
)
async def check_sensitive(payload: SensitiveCheckRequest) -> SensitiveCheckResponse:
    hits = scan(payload.text)
    return SensitiveCheckResponse(
        total=len(hits),
        hits=[{**hit} for hit in hits],
    )
