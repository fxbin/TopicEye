"""文稿检测入口——发布前违禁词 / 广告法极限词扫描，附 AI 痕迹启发式统计与改写建议。

入口层只做三件事：路由、schema 校验、调 service（`sensitive_word_service.scan`
与 `ai_trace_service.analyze` 纯函数、`humanize_rewrite_service` 的 LLM 编排）。
无 ORM、无 session。认证用 `Depends(get_current_user)` 防匿名刷大文本（与
skill.py 同模式）；限流由 `/api/v1` 前缀的全局中间件自动覆盖，无需单列规则。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.auth import get_current_user
from app.schemas.content_check import (
    AiTracesCheckRequest,
    AiTracesReport,
    HumanizeRewriteRequest,
    HumanizeRewriteResponse,
    SensitiveCheckRequest,
    SensitiveCheckResponse,
)
from app.services.ai_trace_service import analyze as analyze_ai_traces
from app.services.humanize_rewrite_service import (
    HumanizeRewriteNoTargetError,
    HumanizeRewriteUnavailableError,
    generate_humanize_rewrites,
)
from app.services.llm.budget_guard import LlmBudgetExceededError
from app.services.llm.circuit_breaker import CircuitOpenError
from app.services.llm.provider import LlmCapacityUnavailableError, LlmContextWindowExceededError
from app.services.sensitive_word_service import scan

logger = logging.getLogger(__name__)

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


@router.post(
    "/humanize-rewrite",
    response_model=HumanizeRewriteResponse,
    summary="文稿「去 AI 味」改写建议",
    description=(
        "对 AI 痕迹命中最密集的句子（≤3 句）生成保留原意的口语化改写建议："
        "服务端分句选句，只有选取句进入模型，全文不进 prompt。响应 original 是"
        "服务端选取句，hit_words 已对照词库真实命中过滤。这是写作建议，不是"
        "「AI 检测/降 AI 率」工具，不承诺改变文稿来源判定；事实与数字是否保留"
        "需作者自行核对。单次最多 20000 字符，超出返回 422；无任何命中句时返回"
        " 422 并说明原因。"
    ),
)
async def check_humanize_rewrite(payload: HumanizeRewriteRequest) -> HumanizeRewriteResponse:
    try:
        result = await generate_humanize_rewrites(payload.text)
    except HumanizeRewriteNoTargetError as exc:
        raise HTTPException(
            status_code=422,
            detail="没有可改写的句子：文稿未命中 AI 高频词或套话连接词，请先参考 AI 痕迹统计。",
        ) from exc
    except HumanizeRewriteUnavailableError as exc:
        logger.warning("Humanize rewrite unparsable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="改写建议生成失败：模型返回结构不可用，请稍后重试",
        ) from exc
    except (
        CircuitOpenError,
        LlmCapacityUnavailableError,
        LlmBudgetExceededError,
        LlmContextWindowExceededError,
    ) as exc:
        # LLM 链路失败 → 502 显式文案；不折叠成 200 假成功（AGENTS 2.1，模式同 content_events）。
        details = {
            CircuitOpenError: "改写建议生成失败：模型链路熔断中，请稍后重试",
            LlmCapacityUnavailableError: "改写建议生成失败：模型服务暂不可用，请稍后重试",
            LlmBudgetExceededError: "改写建议生成失败：模型预算已耗尽，请稍后重试",
            LlmContextWindowExceededError: "改写建议生成失败：句子长度超出模型上下文，请稍后重试",
        }
        detail = next(
            (text for exc_type, text in details.items() if isinstance(exc, exc_type)), "改写建议生成失败，请稍后重试"
        )
        logger.warning("Humanize rewrite LLM failure: %s", type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
    except Exception as exc:
        # 超时、全部候选耗尽等末路异常的兜底：也走 502 中文文案，
        # 不落到全局 500 英文裸错（模式同 content_events / mother_topics）。
        logger.warning("Humanize rewrite failed unexpectedly", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="改写建议生成失败，请稍后重试",
        ) from exc
    return HumanizeRewriteResponse(**result)
