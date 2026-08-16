"""Shared helpers for weekly/monthly digest services.

Both ``weekly_digest.py`` and ``monthly_digest.py`` share:
- stale GENERATING detection
- LLM result → digest field assignment
- success/failure notification push
- error-status commit pattern

This module centralises those so the two services only differ in
period calculation, prompt, and fetch logic.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

DIGEST_GENERATING_STALE_AFTER = timedelta(minutes=10)


def is_active_generating(
    digest: Any,
    now: datetime,
    *,
    generated_at: datetime | None = None,
) -> bool:
    """True if *digest* is in GENERATING and hasn't gone stale.

    Args:
        digest: The digest/report object (must have ``.status`` and
            ``.updated_at`` / ``.created_at``).
        now: Current time in the same timezone as the digest's timestamps.
        generated_at: Optional override for the generation start time.
            When ``None``, falls back to ``digest.updated_at`` then
            ``digest.created_at`` then *now*.  Callers that have a
            dedicated ``generated_at`` field (e.g. ``DailyReport``)
            should pass the resolved value here.
    """
    if digest.status != "GENERATING":
        return False
    ts = generated_at or digest.updated_at or digest.created_at or now
    return now - ts < DIGEST_GENERATING_STALE_AFTER


def apply_llm_result(digest: Any, result: dict[str, Any]) -> None:
    """Assign the 8 standard LLM result fields onto *digest*.

    Both WeeklyDigest and MonthlyDigest expose the same field set:
    overview, takeaway, keywords, trends, top_picks, category_summary,
    platform_tips, topic_clusters, action_items.
    """
    digest.overview = result.get("overview", "")
    digest.takeaway = result.get("takeaway", "")
    digest.keywords = json.dumps(result.get("keywords", []), ensure_ascii=False)
    digest.trends = json.dumps(result.get("trends", []), ensure_ascii=False)
    digest.top_picks = json.dumps(result.get("top_picks", []), ensure_ascii=False)
    digest.category_summary = json.dumps(result.get("category_summary", {}), ensure_ascii=False)
    digest.platform_tips = json.dumps(result.get("platform_tips", {}), ensure_ascii=False)
    digest.topic_clusters = json.dumps(result.get("topic_clusters", []), ensure_ascii=False)
    digest.action_items = json.dumps(result.get("action_items", []), ensure_ascii=False)


def match_picks_to_items(
    raw_picks: list[dict],
    items: list[dict],
) -> list[dict]:
    """将周报/月报 LLM 返回的 top_picks 匹配回底层素材，注入 content_id 和 source_url。

    复用日报 ``_match_picks_to_curated`` 的回引模式（source_idx 精确 → source_title
    子串 → url 兜底），但去掉了日报的 tier/brief/lifecycle/angles 兜底校验——
    周报/月报 pick 结构更简单（无 tier 区分）。

    匹配优先级：
    1. ``source_idx``（精确，1-based，与 build_items_text 的序号对齐）
    2. ``source_title`` 子串兜底（LLM 逐字复制原文标题时命中）
    3. ``title`` 子串兜底（LLM 忽略 source_title 字段时，用展示 title 匹配——
       实测 LLM 常把 title 写成接近原文的标题，此兜底命中率较高）
    4. ``source_url`` 末位兜底

    匹配成功的 pick 注入：
    - ``content_id`` = matched_item["id"]（= ContentItem.id，供前端 ReaderDrawer 取正文）
    - ``source_url`` = matched_item["url"]（修掉 fallback source_url 恒空 bug）
    匹配失败的 pick 原样保留（不丢弃，只是没有 content_id）。
    """
    # 与 build_items_text 的 1-based index 对齐
    items_by_idx = {i + 1: item for i, item in enumerate(items)}
    items_by_title = {item["title"]: item for item in items if item.get("title")}
    items_by_url = {item.get("url", ""): item for item in items if item.get("url")}
    titles = set(items_by_title)

    def _match_by_substring(query: str) -> dict | None:
        """在 titles 里找与 query 互为子串的原文标题，返回对应 item。"""
        if not query:
            return None
        hit = next(
            (t for t in titles if query and (query in t or t in query)),
            None,
        )
        return items_by_title.get(hit) if hit else None

    matched: list[dict] = []
    for pick in raw_picks:
        m: dict | None = None
        # 1. source_idx 精确
        idx = pick.get("source_idx")
        if isinstance(idx, int):
            m = items_by_idx.get(idx)
        # 2. source_title 子串
        if not m:
            m = _match_by_substring(pick.get("source_title", ""))
        # 3. title 子串兜底（LLM 未输出 source_title 时，展示 title 常接近原文）
        if not m:
            m = _match_by_substring(pick.get("title", ""))
        # 4. source_url 末位兜底
        if not m:
            url = pick.get("source_url", "")
            m = items_by_url.get(url) if url else None
        if m:
            # 注入稳定字段：content_id / source_url 由后端按匹配结果填，不信任 LLM
            pick["content_id"] = m["id"]
            if m.get("url"):
                pick["source_url"] = m["url"]
        matched.append(pick)
    return matched


def apply_llm_result_with_matching(
    digest: Any,
    result: dict[str, Any],
    items: list[dict],
) -> None:
    """先对 top_picks 跑匹配注入 content_id，再走标准 apply_llm_result 落库。

    ``items`` 必须是喂给 ``build_items_text`` 的同一批素材（已截断到 prompt 长度），
    确保 source_idx 与 prompt 序号对齐。
    """
    raw_picks = result.get("top_picks", [])
    if isinstance(raw_picks, list) and items:
        result["top_picks"] = match_picks_to_items(raw_picks, items)
    apply_llm_result(digest, result)


async def push_digest_notification(level: str, digest_type: str, title: str, message: str) -> None:
    """Push a digest notification, swallowing errors (non-critical)."""
    try:
        from app.services.notification_service import push_notification

        await push_notification(level, digest_type, title, message)
    except Exception:
        logger.warning("%s notification failed", digest_type, exc_info=True)


async def commit_digest_error(digest: Any, exc: Exception, digest_type: str, key: str, db: Any) -> None:
    """Set digest to ERROR status, commit, log, and push failure notification."""
    digest.status = "ERROR"
    digest.overview = f"生成失败: {str(exc)[:200]}"
    await db.commit()
    logger.error("%s generation failed for %s: %s", digest_type, key, exc)
    await push_digest_notification("error", digest_type, f"AI{digest_type}生成失败", str(exc)[:200])
