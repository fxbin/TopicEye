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


def is_active_generating(digest: Any, now: datetime) -> bool:
    """True if *digest* is in GENERATING and hasn't gone stale."""
    if digest.status != "GENERATING":
        return False
    generated_at = digest.updated_at or digest.created_at or now
    return now - generated_at < DIGEST_GENERATING_STALE_AFTER


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
