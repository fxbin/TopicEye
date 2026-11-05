"""文稿检测入口——发布前违禁词 / 广告法极限词扫描，附 AI 痕迹启发式统计。

入口层只做三件事：路由、schema 校验、调 service（`sensitive_word_service.scan`
与 `ai_trace_service.analyze` 纯函数）。无 ORM、无 session。认证用
`Depends(get_current_user)` 防匿名刷大文本（与 skill.py 同模式）；限流由
`/api/v1` 前缀的全局中间件自动覆盖，无需单列规则。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.auth import get_current_user
from app.schemas.content_check import (
    AiTracesCheckRequest,
    AiTracesReport,
    SensitiveCheckRequest,
    SensitiveCheckResponse,
)
from app.services.ai_trace_service import analyze as analyze_ai_traces
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


@router.post(
    "/ai-traces",
    response_model=AiTracesReport,
    summary="文稿 AI 痕迹启发式统计",
    description=(
        "统计文稿的「AI 味」写作风格信号：AI 高频词/黑话命中（buzzword，含原文"
        "字符偏移）、套话连接词命中（connective）、句式均匀度（句长变异系数分档）。"
        "这是启发式统计，不是模型检测，不输出「AI 率/AI 概率」，也不影响违禁词"
        "检测的把关结论。句数不足 3 句时句式维度返回 insufficient。"
        "单次最多 20000 字符，超出返回 422。"
    ),
)
async def check_ai_traces(payload: AiTracesCheckRequest) -> AiTracesReport:
    return AiTracesReport(**analyze_ai_traces(payload.text))
