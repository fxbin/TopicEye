"""
AI Analysis service — content analysis with optional Lite/Pro cascade.

Default mode keeps the existing Pro analysis path. When enabled, a Lite
prescreen can finalize low-risk items or escalate high-value/uncertain items
to the Pro analysis route.
"""

from __future__ import annotations

import json
import logging
import re
import asyncio
from datetime import datetime, timedelta, timezone, UTC
from typing import Any, Optional
from collections.abc import Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session
from app.core.sqlite_retry import is_sqlite_locked, retry_sqlite_locked
from app.models.content import ContentItem, ContentStatus
from app.models.analysis import AiAnalysis
from app.repositories.content_repo import ANALYSIS_STALE_MINUTES
from app.services.llm import call_llm_json, call_llm_json_with_metadata
from app.services.llm.prompts.analysis import (
    SYSTEM_PROMPT,
    ANALYSIS_PROMPT,
    SYSTEM_PROMPT_EN,
    ANALYSIS_PROMPT_EN,
    PAPER_SYSTEM_PROMPT,
    PAPER_ANALYSIS_PROMPT,
)
from app.services.content_read_cache import invalidate_content_read_caches
from app.services.analysis_normalize import (
    _clamp_score,
    _detect_lang,
    _normalize_analysis_result,
    _normalize_deep_read,
    _normalize_string_list,
    _normalize_text,
    _valid_analysis_result,
)

logger = logging.getLogger(__name__)

_ORIGINAL_CALL_LLM_JSON = call_llm_json


async def _call_llm_json_with_metadata(messages: list, **kwargs) -> tuple[dict[str, Any], dict[str, Any]]:
    if call_llm_json is not _ORIGINAL_CALL_LLM_JSON:
        return await call_llm_json(messages, **kwargs), {}
    return await call_llm_json_with_metadata(messages, **kwargs)


PRESCREEN_SYSTEM_PROMPT = """你是内容选题预筛模型。只输出 JSON，不要输出解释。"""
PRESCREEN_PROMPT = """
请对下面内容做低成本预筛，判断是否必须升级到深度分析模型。

输出 JSON 字段：
{{
  "score": 0-100,
  "confidence": 0-1,
  "should_escalate": true/false,
  "reason": "不超过80字的判断理由",
  "tags": ["最多5个标签"]
}}

升级标准：高价值、低置信、信息密度高、争议风险高、适合深挖、需要完整创作建议。

标题：{title}
内容：{content}
"""

# ── Language detection (no external deps) ─────────────────────────────




def _normalize_prescreen_result(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None

    if "raw_response" in result:
        return None

    score = _clamp_score(result.get("score"), 0)
    try:
        confidence = float(result.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    should_escalate = result.get("should_escalate")
    if not isinstance(should_escalate, bool):
        should_escalate = score >= _cascade_escalate_score() or confidence < _cascade_min_confidence()

    return {
        "score": score,
        "confidence": confidence,
        "should_escalate": should_escalate,
        "reason": _normalize_text(result.get("reason"), max_length=120),
        "tags": _normalize_string_list(result.get("tags"), max_items=5, max_length=40),
    }


def _cascade_enabled() -> bool:
    return bool(getattr(settings, "ANALYSIS_CASCADE_ENABLED", False))


def _cascade_lite_routing_group() -> str:
    return str(getattr(settings, "ANALYSIS_LITE_ROUTING_GROUP", "analysis_lite") or "analysis_lite")


def _cascade_pro_routing_group() -> str:
    return str(getattr(settings, "ANALYSIS_PRO_ROUTING_GROUP", "default") or "default")


def _cascade_escalate_score() -> float:
    return _clamp_score(getattr(settings, "ANALYSIS_CASCADE_ESCALATE_SCORE", 75.0), 75.0)


def _cascade_min_confidence() -> float:
    try:
        value = float(getattr(settings, "ANALYSIS_CASCADE_MIN_CONFIDENCE", 0.75))
    except (TypeError, ValueError):
        value = 0.75
    return max(0.0, min(1.0, value))


def _prescreen_escalation_reason(prescreen: dict[str, Any] | None) -> str | None:
    if prescreen is None:
        return "prescreen_invalid"
    if bool(prescreen.get("should_escalate")):
        return "lite_requested_escalation"
    if float(prescreen.get("score") or 0) >= _cascade_escalate_score():
        return "high_prescreen_score"
    if float(prescreen.get("confidence") or 0) < _cascade_min_confidence():
        return "low_prescreen_confidence"
    return None


def _analysis_result_from_prescreen(
    content: ContentItem,
    prescreen: dict[str, Any],
    *,
    lang: str,
) -> dict[str, Any]:
    result = _local_analysis_result(content, lang=lang)
    score = _clamp_score(prescreen.get("score"), 0)
    confidence = float(prescreen.get("confidence") or 0)
    reason = _normalize_text(prescreen.get("reason"), max_length=120)
    tags = _normalize_string_list(prescreen.get("tags"), max_items=5, max_length=40)

    result["curation"]["curation_score"] = score
    result["curation"]["info_density"] = min(100, max(35, score))
    result["curation"]["actionability"] = min(100, max(35, score - 5))
    result["scores"]["quality_score"] = min(100, max(35, score))
    result["scores"]["creator_score"] = min(100, max(35, score - 3))
    if tags:
        result["tags"] = tags
    if reason:
        result["recommendation"] = reason
    result["fallback"] = "lite_prescreen_final"
    result["prescreen_confidence"] = confidence
    return result


async def _run_lite_prescreen(
    content: ContentItem, *, title: str, truncated: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    messages = [
        {"role": "system", "content": PRESCREEN_SYSTEM_PROMPT},
        {"role": "user", "content": PRESCREEN_PROMPT.format(title=title, content=truncated[:1800])},
    ]
    result, metadata = await _call_llm_json_with_metadata(
        messages,
        temperature=0.1,
        max_tokens=500,
        scene="content_prescreen",
        routing_group=_cascade_lite_routing_group(),
    )
    return _normalize_prescreen_result(result), metadata


def _local_analysis_result(content: ContentItem, *, lang: str, is_arxiv: bool = False) -> dict[str, Any]:
    """Build a deterministic baseline analysis when the LLM response is empty."""
    text = f"{content.title}\n{content.summary or ''}\n{content.raw_content or ''}".strip()
    source = f"{content.source_name or ''} {content.source_type or ''} {content.platform or ''}".lower()
    title = content.title.strip()
    text_len = len(text)
    has_content = text_len >= 80
    is_trend_source = any(key in source for key in ("hot", "trend", "rsshub", "zhihu", "reddit", "weread"))

    quality_score = 62 if has_content else 48
    hot_score = 68 if is_trend_source else 55
    creator_score = 64 if has_content else 50
    viral_score = 58 if is_trend_source else 50
    freshness_score = 70
    risk_score = 28
    curation_score = round(
        quality_score * 0.28 + creator_score * 0.28 + hot_score * 0.18 + freshness_score * 0.14 + viral_score * 0.12,
        1,
    )

    words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_+-]{2,}", text)
    tags: list[str] = []
    for word in words:
        if word not in tags:
            tags.append(word)
        if len(tags) >= 5:
            break
    if content.category and content.category not in tags:
        tags.insert(0, content.category)

    summary = content.summary or title
    if len(summary) > 180:
        summary = summary[:180].rstrip() + "..."

    if is_arxiv:
        # 论文 LLM 兜底：用标题生成中文占位概述，避免英文原文直接展示
        summary = f"《{title}》是 arXiv 上的学术论文。LLM 暂不可用，建议查看原文获取详细方法与结论。"
        recommendation = f"这篇论文来自 arXiv，涉及前沿研究。LLM 限流未能生成详细中文解读，可先收藏待精读。"
    elif lang == "en":
        recommendation = f"这条内容来自 {content.source_name or '外部信源'}，适合作为跨市场趋势素材先观察，再结合中文语境提炼选题角度。"
    else:
        recommendation = f"这条内容来自 {content.source_name or '外部信源'}，具备基础选题信号，建议先作为素材进入观察池，再补充数据和角度判断。"

    return {
        "summary": summary,
        "key_points": [summary],
        "recommendation": recommendation,
        "creator_angles": [
            f"从创作者视角拆解「{title[:32]}」的用户关注点",
            "结合评论、搜索热度或同类案例补充证据后成稿",
        ],
        "title_suggestions": [title],
        "risk_notes": "",
        "tags": tags,
        "scores": {
            "quality_score": quality_score,
            "hot_score": hot_score,
            "freshness_score": freshness_score,
            "creator_score": creator_score,
            "viral_score": viral_score,
            "risk_score": risk_score,
        },
        "curation": {
            "curation_score": curation_score,
            "info_density": 60 if has_content else 45,
            "actionability": 58 if has_content else 45,
            "source_weight": 58 if is_trend_source else 50,
        },
        "fallback": "local_empty_llm_response",
    }


def _analysis_retryable_status_filter(stale_cutoff: datetime):
    """Return the status predicate for content eligible to enter analysis.

    stale_cutoff 在内部转 naive UTC: SQLite aiosqlite 不支持 aware datetime 作参数,
    PG 接受 naive (session 设 UTC). Python 层比较仍用 aware.
    """
    from app.core.db_backend import ensure_naive_utc

    cutoff = ensure_naive_utc(stale_cutoff)
    return (
        (ContentItem.status == ContentStatus.PENDING)
        | ((ContentItem.status == ContentStatus.ANALYZING) & (ContentItem.updated_at <= cutoff))
        | ((ContentItem.status == ContentStatus.ERROR) & (ContentItem.updated_at <= cutoff))
    )


# ── Core analysis function ───────────────────────────────────────


async def analyze_content(content: ContentItem, db: AsyncSession) -> AiAnalysis:
    """Run full AI analysis on a single content item (single LLM call)."""
    logger.info("Analyzing content id=%d: %s", content.id, content.title[:50])

    content_text = content.raw_content or content.summary or ""
    title = content.title
    truncated = content_text[:3000] if content_text else "无正文内容"

    # Select content-appropriate prompt.
    # 优先级：arXiv 论文 > 英文内容 > 中文内容
    platform_lower = (content.platform or "").lower()
    is_arxiv = "arxiv" in platform_lower or "arxiv" in (content.source_name or "").lower()
    lang = _detect_lang(title, content_text or "")

    if is_arxiv:
        system_prompt = PAPER_SYSTEM_PROMPT
        analysis_prompt = PAPER_ANALYSIS_PROMPT
        logger.info("Detected arXiv paper, using paper prompts for content id=%d", content.id)
    elif lang == "en":
        system_prompt = SYSTEM_PROMPT_EN
        analysis_prompt = ANALYSIS_PROMPT_EN
        logger.info("Detected English content, using EN prompts for content id=%d", content.id)
    else:
        system_prompt = SYSTEM_PROMPT
        analysis_prompt = ANALYSIS_PROMPT

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": analysis_prompt.format(title=title, content=truncated)},
    ]

    analysis_mode = "pro_only"
    prescreen_model = None
    final_model = _cascade_pro_routing_group()
    escalated = False
    escalation_reason = None
    prescreen_score = None
    prescreen_confidence = None
    result: dict[str, Any] | None = None

    if _cascade_enabled() and not is_arxiv:
        # 论文跳过 prescreen：结构化概述 + 精读判定需要完整论文 prompt，
        # prescreen 的 lite 简化结果无法产出 deep_read 字段。
        analysis_mode = "cascade"
        prescreen_model = _cascade_lite_routing_group()
        try:
            prescreen, prescreen_metadata = await _run_lite_prescreen(content, title=title, truncated=truncated)
            prescreen_model = prescreen_metadata.get("actual_model") or prescreen_model
        except Exception as exc:
            logger.warning("Lite prescreen failed for content id=%d, escalating to pro: %s", content.id, exc)
            prescreen = None

        if prescreen is not None:
            prescreen_score = prescreen.get("score")
            prescreen_confidence = prescreen.get("confidence")
        escalation_reason = _prescreen_escalation_reason(prescreen)
        escalated = escalation_reason is not None

        if not escalated and prescreen is not None:
            analysis_mode = "lite_only"
            final_model = prescreen_model
            result = _analysis_result_from_prescreen(content, prescreen, lang=lang)

    fallback_used = False
    if result is None:
        try:
            result, final_metadata = await _call_llm_json_with_metadata(
                messages,
                temperature=0.25,
                max_tokens=1500,
                scene="content_analysis",
                routing_group=_cascade_pro_routing_group(),
            )
            final_model = final_metadata.get("actual_model") or final_model
        except Exception as llm_exc:
            # Only CircuitOpenError (breaker tripped) triggers fallback —
            # other LLM failures (timeout, network, RuntimeError) still
            # propagate up so the caller can record ERROR status + retry.
            from app.services.llm.circuit_breaker import CircuitOpenError

            if isinstance(llm_exc, CircuitOpenError):
                logger.warning(
                    "LLM circuit breaker open for content id=%d, using local fallback",
                    content.id,
                )
                result = _local_analysis_result(content, lang=lang, is_arxiv=is_arxiv)
                fallback_used = True
            else:
                raise
        if not fallback_used and not _valid_analysis_result(result):
            logger.warning(
                "LLM analysis result invalid for content id=%d, using local fallback: %s",
                content.id,
                str(result)[:200],
            )
            result = _local_analysis_result(content, lang=lang, is_arxiv=is_arxiv)
            fallback_used = True
    result = _normalize_analysis_result(result)

    # Extract scores
    scores = result.get("scores", {})

    # Extract curation
    curation = result.get("curation", {})
    curation_score = curation.get("curation_score", 0)

    # Cross-market bonus: English content from HN/Reddit has higher signal value
    # for Chinese-speaking creators (early trend detection before mainstream coverage)
    if lang == "en":
        source_name = (content.source_name or "").lower()
        platform = (content.platform or "").lower()
        is_intl = any(kw in source_name for kw in ("hacker", "reddit", "techcrunch", "arxiv", "github"))
        is_intl = is_intl or any(kw in platform for kw in ("hacker", "reddit"))
        if is_intl and curation_score >= 55:
            bonus = min(10, 100 - curation_score)  # cap at 100
            curation_score += bonus
            logger.info(
                "Cross-market bonus +%d for content id=%d (source=%s, curation=%.0f)",
                bonus,
                content.id,
                content.source_name,
                curation_score,
            )

    # Build analysis record
    # arXiv 论文的精读判定嵌套进 enrichment.deep_read（与其他 enrichment schema 兼容）
    # 归一化：调和 worth_deep_read(deep_read_score≥70) 矛盾 + 字符串 bool 解析
    _deep_read = _normalize_deep_read(result.get("deep_read")) if is_arxiv else None
    analysis = AiAnalysis(
        content_id=content.id,
        quality_score=scores.get("quality_score", 0),
        hot_score=scores.get("hot_score", 0),
        freshness_score=scores.get("freshness_score", 0),
        creator_score=scores.get("creator_score", 0),
        viral_score=scores.get("viral_score", 0),
        risk_score=scores.get("risk_score", 0),
        summary=result.get("summary", ""),
        key_points=result.get("key_points"),
        audience_emotion="",
        recommended_reason=result.get("recommendation"),
        creator_angles=result.get("creator_angles"),
        title_suggestions=result.get("title_suggestions"),
        risk_notes={"notes": result.get("risk_notes", "") if scores.get("risk_score", 0) > 50 else ""},
        # New curation fields
        curation_score=curation_score,
        tags=result.get("tags"),
        recommendation=result.get("recommendation"),
        info_density=curation.get("info_density", 50),
        actionability=curation.get("actionability", 50),
        source_weight=curation.get("source_weight", 50),
        enrichment_status="completed" if _deep_read else "pending",
        enrichment={"deep_read": _deep_read} if _deep_read else None,
        analysis_mode=analysis_mode,
        prescreen_model=prescreen_model,
        final_model=final_model,
        escalated=escalated,
        escalation_reason=escalation_reason,
        prescreen_confidence=prescreen_confidence,
        prescreen_score=prescreen_score,
        summary_source=(
            "local_fallback" if fallback_used else "llm_lite" if analysis_mode == "lite_only" else "llm_pro"
        ),
    )

    db.add(analysis)
    content.status = ContentStatus.ANALYZED
    await db.flush()
    await db.refresh(analysis)

    logger.info(
        "Analysis id=%d: Q=%.0f C=%.0f V=%.0f R=%.0f Curation=%.0f Tags=%s",
        content.id,
        analysis.quality_score or 0,
        analysis.creator_score or 0,
        analysis.viral_score or 0,
        analysis.risk_score or 0,
        analysis.curation_score or 0,
        analysis.tags,
    )

    return analysis


async def analyze_batch(
    content_ids: list[int],
    db: AsyncSession,
) -> list[AiAnalysis]:
    """Analyze multiple content items sequentially (respecting rate limits)."""
    results = []
    stale_cutoff = datetime.now(UTC) - timedelta(minutes=ANALYSIS_STALE_MINUTES)

    result = await db.execute(
        select(ContentItem).where(
            ContentItem.id.in_(content_ids),
            _analysis_retryable_status_filter(stale_cutoff),
        )
    )
    items = result.scalars().all()

    for item in items:
        analysis = await analyze_one_claimed(item.id, db)
        if analysis is not None:
            results.append(analysis)

    return results


async def analyze_batch_concurrent(
    content_ids: list[int],
    *,
    concurrency: int | None = None,
    session_factory: Callable[[], Any] = async_session,
    assume_claimed: bool = False,
) -> list[AiAnalysis]:
    """Analyze multiple content items with bounded concurrency.

    Each worker owns its own database session. This keeps SQLAlchemy sessions
    out of shared concurrent use while LLM calls can overlap.
    """
    if not content_ids:
        return []

    limit = _normalize_analysis_concurrency(concurrency)
    semaphore = asyncio.Semaphore(limit)

    async def _run_one(content_id: int) -> AiAnalysis | None:
        async with semaphore, session_factory() as db:
            return await analyze_one_claimed(content_id, db, assume_claimed=assume_claimed)

    analyses = await asyncio.gather(*(_run_one(content_id) for content_id in content_ids))
    return [item for item in analyses if item is not None]


async def analyze_one_claimed(
    content_id: int,
    db: AsyncSession,
    *,
    assume_claimed: bool = False,
    analyzer: Callable[[ContentItem, AsyncSession], Awaitable[AiAnalysis]] | None = None,
    raise_on_failure: bool = False,
) -> AiAnalysis | None:
    """Claim and analyze one pending or stale analyzing item."""
    stale_cutoff = datetime.now(UTC) - timedelta(minutes=ANALYSIS_STALE_MINUTES)
    try:
        if not assume_claimed:

            async def _mark_analyzing() -> bool:
                result = await db.execute(
                    update(ContentItem)
                    .where(ContentItem.id == content_id)
                    .where(_analysis_retryable_status_filter(stale_cutoff))
                    .values(status=ContentStatus.ANALYZING, updated_at=datetime.now(UTC))
                )
                await db.commit()
                return result.rowcount > 0

            claimed = await retry_sqlite_locked(
                _mark_analyzing,
                attempts=3,
                base_delay=0.1,
                on_retry=db.rollback,
            )
            if not claimed:
                logger.info("Skipped analysis for content id=%d: already claimed or no longer stale", content_id)
                return None

        content = await db.get(ContentItem, content_id)
        if content is None:
            return None

        analyze = analyzer or analyze_content
        analysis = await analyze(content, db)
        await db.commit()
        invalidate_content_read_caches()
        return analysis
    except Exception as e:
        await db.rollback()
        if is_sqlite_locked(e):
            logger.warning("Skipped analysis for content id=%d: database is locked", content_id)
            if raise_on_failure:
                raise
            return None

        logger.error("Failed to analyze content id=%d: %s", content_id, e)
        try:
            content = await db.get(ContentItem, content_id)
            if content is not None:
                content.status = ContentStatus.ERROR
                content.updated_at = datetime.now(UTC)
                await db.commit()
        except Exception as status_error:
            await db.rollback()
            logger.warning(
                "Failed to mark content id=%d as error after analysis failure: %s",
                content_id,
                status_error,
            )
        if raise_on_failure:
            raise
        return None


def _normalize_analysis_concurrency(value: int | None) -> int:
    try:
        parsed = int(value if value is not None else settings.ANALYSIS_WORKER_CONCURRENCY)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(parsed, 10))
