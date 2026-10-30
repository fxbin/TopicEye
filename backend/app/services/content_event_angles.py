"""事件切面稀缺度分析（AI 角度缺口建议）。

对一篇内容所属的可见事件，把 canonical + 已接受成员的标题/摘要/正文节选
交给 LLM，归纳已覆盖角度、找出稀缺角度与未回答的受众问题。纯读路径：
不写任何业务表，LLM 调用由既有 call_trace 基础设施记录。

边界（与 issue #169 任务书一致）：
- 输入以 content_id 为入口，事件组 ID 是内部事实，由 ``resolve_visible_group``
  解析；内容不存在或不可见统一抛 ``ContentEventNotFoundError``（404）。
- 无事件、或事件没有已接受归并成员时返回 ``{"status": "no_event"}``，
  显式结果对象而非异常。
- LLM 链路异常不捕获不折叠，向上抛给 API 层显式报 502（AGENTS 2.1
  禁止安静失败；``angle_recommend`` 折叠为「角度生成失败」是既有行为，不沿用）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.repositories.content_event_repo import ContentEventRepository
from app.services.content_event_service import ContentEventNotFoundError
from app.services.llm import call_llm_json
from app.services.llm.prompts.event_angles import SYSTEM_PROMPT, USER_TEMPLATE
from app.utils.prompt_safety import sanitize_prompt_input

logger = logging.getLogger(__name__)

# 送入 LLM 的文章数上限；超出取最新 MAX_ARTICLES 篇并在响应标记 truncated。
MAX_ARTICLES = 30
# 单篇字段截断上限（sanitize_prompt_input 的 max_chars 口径）。
TITLE_MAX_CHARS = 200
SUMMARY_MAX_CHARS = 300
RAW_CONTENT_MAX_CHARS = 1500
# 预算极紧时的单篇正文保底，保证每篇仍有一段可读正文。
RAW_CONTENT_MIN_CHARS = 400
# 组装后完整 user message 的字符硬上限；按剩余篇数均摊收紧每篇正文预算。
TOTAL_INPUT_MAX_CHARS = 40_000
# 每篇除正文外的固定开销估计（编号行头 + 标题 + 摘要 + 截断后缀）。
_PER_ARTICLE_OVERHEAD_CHARS = 600

# 输出条数上限，与提示词中的约束一致，防单条响应撑爆 max_tokens。
MAX_COVERED_ANGLES = 8
MAX_SCARCE_ANGLES = 5
MAX_AUDIENCE_QUESTIONS = 5
MAX_REFS_PER_ANGLE = 3


class EventAngleAnalysisError(Exception):
    """LLM 返回无法解析为切面分析结构时抛出（禁止折叠成假成功）。"""


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _recency(content: ContentItem) -> float:
    """最新程度：优先发布时间，缺失时退回抓取/入库时间。"""
    for value in (content.published_at, content.crawled_at, content.created_at):
        if value is not None:
            return _timestamp(value)
    return 0.0


def _build_user_message(event_title: str, articles: list[ContentItem]) -> str:
    """拼装 user message：预算内逐篇截断，整体不超过硬上限。

    每篇正文预算 = 剩余预算 / 剩余篇数 - 固定开销，封顶 RAW_CONTENT_MAX_CHARS，
    保底 RAW_CONTENT_MIN_CHARS；预算通常已保证总量受控，最后的硬截断只作兜底，
    且必须在 ``.format()`` 之后执行——先截断可能劈开 ``{{`` 转义对导致 format 报错。
    """

    blocks: list[str] = []
    used = 0
    for index, item in enumerate(articles):
        remaining_articles = len(articles) - index
        share = (TOTAL_INPUT_MAX_CHARS - used) // remaining_articles
        raw_cap = min(
            RAW_CONTENT_MAX_CHARS,
            max(RAW_CONTENT_MIN_CHARS, share - _PER_ARTICLE_OVERHEAD_CHARS),
        )
        title = sanitize_prompt_input(item.title, max_chars=TITLE_MAX_CHARS)
        summary = sanitize_prompt_input(item.summary, max_chars=SUMMARY_MAX_CHARS)
        raw = sanitize_prompt_input(item.raw_content, max_chars=raw_cap)
        if summary or raw:
            block = f"#{item.id} | {title} | {summary} | {raw}"
        else:
            block = f"#{item.id} | {title}"
        blocks.append(block)
        used += len(block)

    content = USER_TEMPLATE.format(
        event_title=sanitize_prompt_input(event_title, max_chars=TITLE_MAX_CHARS),
        articles="\n\n".join(blocks),
    )
    if len(content) > TOTAL_INPUT_MAX_CHARS:
        logger.warning("Event angles input exceeded hard cap (%d chars); truncated", len(content))
        content = content[:TOTAL_INPUT_MAX_CHARS]
    return content


def _parse_analysis(
    result: Any,
    *,
    selected: dict[int, ContentItem],
    event_id: int,
    version: int,
    truncated: bool,
) -> dict[str, Any]:
    """校验 LLM 输出并做引用防幻觉过滤。

    - 结构不可用（含 call_llm_json 解析失败回退的 ``{"raw_response": ...}``）抛
      ``EventAngleAnalysisError``。
    - ref_content_ids 只保留输入成员集合内的编号；无有效引用的稀缺角度整条丢弃。
    """

    if not isinstance(result, dict) or "raw_response" in result:
        raise EventAngleAnalysisError("LLM 未返回可解析的 JSON 结构")
    if not any(key in result for key in ("covered_angles", "scarce_angles", "audience_questions")):
        raise EventAngleAnalysisError("LLM 返回缺少切面分析字段")

    def _strings(value: Any, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned = (str(item).strip() for item in value)
        return [item for item in cleaned if item][:limit]

    covered_angles = _strings(result.get("covered_angles"), MAX_COVERED_ANGLES)
    audience_questions = _strings(result.get("audience_questions"), MAX_AUDIENCE_QUESTIONS)

    scarce_angles: list[dict[str, Any]] = []
    raw_scarce = result.get("scarce_angles")
    if isinstance(raw_scarce, list):
        for entry in raw_scarce:
            if len(scarce_angles) >= MAX_SCARCE_ANGLES:
                break
            if not isinstance(entry, dict):
                continue
            angle = str(entry.get("angle", "")).strip()
            if not angle:
                continue
            refs: list[dict[str, Any]] = []
            seen_ids: set[int] = set()
            raw_refs = entry.get("ref_content_ids")
            if isinstance(raw_refs, list):
                for ref in raw_refs:
                    if len(refs) >= MAX_REFS_PER_ANGLE:
                        break
                    try:
                        ref_id = int(ref)
                    except (TypeError, ValueError):
                        continue
                    if ref_id in selected and ref_id not in seen_ids:
                        seen_ids.add(ref_id)
                        refs.append({"content_id": ref_id, "title": selected[ref_id].title})
            if not refs:
                # 引用防幻觉：没有落在输入成员集合内的引用，该角度不可信。
                logger.info("Dropped scarce angle without valid refs: %s", angle[:60])
                continue
            scarce_angles.append(
                {
                    "angle": angle,
                    "reason": str(entry.get("reason", "")).strip(),
                    "refs": refs,
                }
            )

    return {
        "status": "ok",
        "event_id": event_id,
        "version": version,
        "truncated": truncated,
        "analyzed_count": len(selected),
        "covered_angles": covered_angles,
        "scarce_angles": scarce_angles,
        "audience_questions": audience_questions,
    }


async def analyze_event_angles(
    db: AsyncSession,
    content_id: int,
    *,
    visible_user_id: int | None,
) -> dict[str, Any]:
    """分析 content_id 所属可见事件的报道切面稀缺度。

    Returns:
        ``{"status": "no_event"}`` 表示内容没有可见事件或事件无已接受归并成员；
        否则返回 ``{"status": "ok", "event_id", "version", "truncated",
        "analyzed_count", "covered_angles", "scarce_angles", "audience_questions"}``，
        每条稀缺角度的引用带 content_id 与 title。

    Raises:
        ContentEventNotFoundError: 内容不存在或对当前用户不可见。
        EventAngleAnalysisError: LLM 输出无法解析为可用结构。
        LLM 链路异常原样上抛（熔断/容量/预算/上下文等），由 API 层映射 502。
    """

    repo = ContentEventRepository(db)
    content = await repo.get_content(content_id)
    if content is None or (content.owner_user_id is not None and content.owner_user_id != visible_user_id):
        # 与 GET /event、/event/coverage 一致：不存在与不可见共用同一响应。
        raise ContentEventNotFoundError(f"content {content_id} not found")

    group = await repo.resolve_visible_group(content_id, visible_user_id=visible_user_id)
    if group is None:
        return {"status": "no_event"}

    member_rows = await repo.list_member_rows(group.id, include_unaccepted=False)
    if not member_rows:
        # 只有 canonical、没有任何已接受归并成员的事件没有"切面稀缺度"可言。
        return {"status": "no_event"}

    articles: dict[int, ContentItem] = {row.content.id: row.content for row in member_rows}
    canonical = await repo.get_content(group.canonical_content_id)
    if canonical is not None:
        articles.setdefault(canonical.id, canonical)

    ordered = sorted(articles.values(), key=lambda item: (-_recency(item), -item.id))
    truncated = len(ordered) > MAX_ARTICLES
    if truncated:
        ordered = ordered[:MAX_ARTICLES]
    selected = {item.id: item for item in ordered}

    event_title = canonical.title if canonical is not None else content.title
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_user_message(event_title, ordered),
        },
    ]
    result = await call_llm_json(
        messages,
        temperature=0.3,
        max_tokens=2000,
        scene="event_angles",
    )
    return _parse_analysis(
        result,
        selected=selected,
        event_id=group.id,
        version=group.version,
        truncated=truncated,
    )
