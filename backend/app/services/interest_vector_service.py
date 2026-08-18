"""Interest vector service — builds and applies per-user tag preferences.

Two responsibilities:
1. **Vector building**: Aggregates user behavior signals (favorites, feedback,
   ignores) into a ``{tag: weight}`` dict stored in ``user_interest_vectors``.
2. **Similarity scoring**: Computes a personalization boost for content items
   based on Jaccard similarity between content tags and the user's interest
   vector.

Signal weights:
    great_pick      +3.0
    like            +1.5
    favorite        +2.0
    skip             -0.5
    outdated        -1.0
    dislike         -2.0
    ignore          -1.5
    not_relevant    -2.5

The boost is clamped to ±15 points to prevent personalization from
overriding the scoring engine's base ranking.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.models.favorite import FavoriteItem, FavoriteTargetType
from app.models.feedback import UserFeedback
from app.models.ignored import IgnoredItem
from app.repositories.interest_vector_repo import InterestVectorRepository

logger = logging.getLogger(__name__)

# ── Signal weights ─────────────────────────────────────────────────────

SIGNAL_WEIGHTS: dict[str, float] = {
    # Positive signals
    "favorite": 2.0,
    "feedback_great_pick": 3.0,
    "feedback_like": 1.5,
    # Negative signals
    "ignore": -1.5,
    "feedback_dislike": -2.0,
    "feedback_not_relevant": -2.5,
    "feedback_skip": -0.5,
    "feedback_outdated": -1.0,
}

# Personalization boost limits
BOOST_MAX = 15.0
BOOST_MIN = -15.0
BOOST_SCALE = 15.0  # Jaccard similarity (0..1) × scale = boost points

# Lookback window for behavior signals
DEFAULT_LOOKBACK_DAYS = 30

# Minimum tag frequency to be included in the vector
MIN_TAG_FREQUENCY = 1


async def rebuild_user_vector(
    db: AsyncSession,
    user_id: int,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Rebuild the user's interest vector from scratch.

    Scans favorites, feedback, and ignores within the lookback window,
    extracts tags from associated AiAnalysis records, and writes the
    aggregated weights to ``user_interest_vectors``.

    Returns the computed ``{tag: weight}`` dict.
    """
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    tag_scores: dict[str, float] = defaultdict(float)
    tag_sources: dict[str, str] = {}

    # ── 1. Favorites → positive signals ──────────────────────────────
    fav_result = await db.execute(
        select(FavoriteItem.target_id, FavoriteItem.created_at).where(
            FavoriteItem.user_id == user_id,
            FavoriteItem.target_type == FavoriteTargetType.CONTENT,
            FavoriteItem.target_id.isnot(None),
            FavoriteItem.created_at >= cutoff,
        )
    )
    fav_content_ids = [row[0] for row in fav_result.all()]
    if fav_content_ids:
        fav_tags = await _fetch_content_tags(db, fav_content_ids)
        for tags in fav_tags.values():
            for tag in tags:
                tag_scores[tag] += SIGNAL_WEIGHTS["favorite"]
                tag_sources[tag] = "favorite"

    # ── 2. Feedback → positive/negative signals ──────────────────────
    fb_result = await db.execute(
        select(UserFeedback.content_id, UserFeedback.feedback_type, UserFeedback.created_at).where(
            UserFeedback.user_id == user_id,
            UserFeedback.created_at >= cutoff,
        )
    )
    fb_content_ids: list[int] = []
    fb_signals: dict[int, str] = {}
    for content_id, feedback_type_str, _created_at in fb_result.all():
        fb_content_ids.append(content_id)
        fb_signals[content_id] = f"feedback_{feedback_type_str}"

    if fb_content_ids:
        fb_tags = await _fetch_content_tags(db, fb_content_ids)
        for content_id, tags in fb_tags.items():
            signal_key = fb_signals.get(content_id, "")
            weight = SIGNAL_WEIGHTS.get(signal_key, 0.0)
            if weight == 0.0:
                continue
            for tag in tags:
                tag_scores[tag] += weight
                tag_sources[tag] = signal_key

    # ── 3. Ignores → negative signals ────────────────────────────────
    ignore_result = await db.execute(
        select(IgnoredItem.content_id).where(
            IgnoredItem.created_at >= cutoff,
        )
    )
    ignore_content_ids = [row[0] for row in ignore_result.all()]
    if ignore_content_ids:
        ignore_tags = await _fetch_content_tags(db, ignore_content_ids)
        for tags in ignore_tags.values():
            for tag in tags:
                tag_scores[tag] += SIGNAL_WEIGHTS["ignore"]
                tag_sources[tag] = "ignore"

    # ── 4. TF-IDF-like normalization ─────────────────────────────────
    # Compress dominant tags to prevent a single category from monopolizing.
    total_weight = sum(abs(w) for w in tag_scores.values())
    if total_weight > 0:
        for tag in tag_scores:
            tag_scores[tag] = tag_scores[tag] / math.sqrt(total_weight) * 10.0

    # ── 5. Prune near-zero weights ───────────────────────────────────
    pruned = {tag: round(weight, 4) for tag, weight in tag_scores.items() if abs(weight) > 0.1}

    # ── 6. Persist ───────────────────────────────────────────────────
    repo = InterestVectorRepository(db)
    await repo.delete_user_vector(user_id)
    for tag, weight in pruned.items():
        await repo.upsert_tag(user_id, tag, weight, tag_sources.get(tag, "manual"))

    logger.info(
        "Rebuilt interest vector for user %s: %d tags (lookback=%dd)",
        user_id,
        len(pruned),
        lookback_days,
    )
    return pruned


async def get_user_vector(db: AsyncSession, user_id: int) -> dict[str, float]:
    """Return the cached interest vector for *user_id* (empty if none)."""
    repo = InterestVectorRepository(db)
    return await repo.get_user_vector(user_id)


def compute_personalization_boost(
    content_tags: list[str] | None,
    user_vector: dict[str, float],
    content_category: str | None = None,
) -> float:
    """Compute a personalization boost score for a single content item.

    Uses a weighted Jaccard similarity between the content's tags/category
    and the user's interest vector. The result is clamped to
    ``[BOOST_MIN, BOOST_MAX]``.

    Args:
        content_tags: Tags from AiAnalysis or ContentItem.tags.
        user_vector: ``{tag: weight}`` from the user's interest vector.
        content_category: Optional category to include as an extra tag.

    Returns:
        A float boost in ``[-15.0, +15.0]``.
    """
    if not user_vector:
        return 0.0

    # Build the content's tag set (lowercased)
    content_tag_set: set[str] = set()
    if content_tags:
        for tag in content_tags:
            tag_lower = str(tag).lower().strip()
            if tag_lower:
                content_tag_set.add(tag_lower)
    if content_category:
        content_tag_set.add(content_category.lower().strip())

    if not content_tag_set:
        return 0.0

    # Weighted Jaccard: sum of matching weights / total content tags
    matching_weight = 0.0
    matched_count = 0
    for tag in content_tag_set:
        if tag in user_vector:
            matching_weight += user_vector[tag]
            matched_count += 1

    if matched_count == 0:
        return 0.0

    # Average weight per matched tag, scaled to boost range
    avg_weight = matching_weight / len(content_tag_set)
    boost = max(BOOST_MIN, min(BOOST_MAX, avg_weight * BOOST_SCALE))

    return round(boost, 2)


async def apply_personalization_boost(
    db: AsyncSession,
    user_id: int | None,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply personalization boost to a list of today-picks items.

    Mutates each item's ``analysis.adjusted_curation_score`` and adds a
    ``personalization_boost`` field. Items are NOT re-sorted — the caller
    decides whether to re-sort.

    If *user_id* is None or the user has no interest vector, items are
    returned unchanged (with ``personalization_boost = 0``).
    """
    if user_id is None:
        for item in items:
            item["personalization_boost"] = 0.0
        return items

    user_vector = await get_user_vector(db, user_id)
    if not user_vector:
        for item in items:
            item["personalization_boost"] = 0.0
        return items

    for item in items:
        analysis = item.get("analysis") or {}
        tags = analysis.get("tags") or item.get("tags") or []
        category = item.get("category")

        boost = compute_personalization_boost(tags, user_vector, category)
        item["personalization_boost"] = boost

        # Apply boost to the adjusted curation score
        if "adjusted_curation_score" in analysis:
            analysis["adjusted_curation_score"] = round(analysis["adjusted_curation_score"] + boost, 2)

    return items


# ── Helpers ────────────────────────────────────────────────────────────


async def _fetch_content_tags(
    db: AsyncSession,
    content_ids: list[int],
) -> dict[int, list[str]]:
    """Fetch tags for the given content IDs from AiAnalysis + ContentItem.

    Returns ``{content_id: [tag1, tag2, ...]}``.
    """
    if not content_ids:
        return {}

    result = await db.execute(
        select(ContentItem.id, ContentItem.category, ContentItem.tags, AiAnalysis.tags)
        .outerjoin(AiAnalysis, AiAnalysis.content_id == ContentItem.id)
        .where(ContentItem.id.in_(content_ids))
    )

    tag_map: dict[int, list[str]] = {}
    seen_content_ids: set[int] = set()

    for content_id, category, content_tags, analysis_tags in result.all():
        if content_id in seen_content_ids:
            continue
        seen_content_ids.add(content_id)

        tags: list[str] = []
        # Prefer analysis tags, fall back to content tags
        raw_tags = analysis_tags if analysis_tags else content_tags
        if isinstance(raw_tags, str):
            try:
                import json

                raw_tags = json.loads(raw_tags)
            except (json.JSONDecodeError, ValueError):
                raw_tags = [raw_tags]
        if isinstance(raw_tags, list):
            tags = [str(t).lower().strip() for t in raw_tags if str(t).strip()]
        if category and category.lower().strip() not in tags:
            tags.append(category.lower().strip())

        tag_map[content_id] = tags

    return tag_map


# ── Background task registry for interest-vector rebuilds ────────────
# Tracks all in-flight rebuild tasks so shutdown can drain them
# and repeated signals for the same user can coalesce.

_rebuild_tasks: set[asyncio.Task] = set()
_rebuild_user_dedup: dict[int, asyncio.Task] = {}


async def drain_rebuild_tasks(timeout: float = 10.0) -> None:
    """Cancel and await all in-flight rebuild tasks during shutdown.

    Called from application lifespan on shutdown.  Each task is
    cancelled first (so it stops new DB work) and then awaited so
    that any in-flight session is rolled back and closed.
    """
    tasks = list(_rebuild_tasks)
    for task in tasks:
        task.cancel()
    if not tasks:
        return
    await asyncio.wait(tasks, timeout=timeout)
    # Clear registries after drain
    _rebuild_tasks.clear()
    _rebuild_user_dedup.clear()


def trigger_vector_rebuild(user_id: int) -> None:
    """Fire-and-forget interest vector rebuild for *user_id*.

    Creates a background asyncio task with its own DB session. Safe to
    call from request handlers — never blocks, never raises.

    Lifecycle guarantees:
    - **Deduplication**: if a rebuild for the same user is already
      in flight, the old task is cancelled and replaced by the new one.
    - **Tracking**: every task is registered in ``_rebuild_tasks`` so
      ``drain_rebuild_tasks`` can cancel/await them on shutdown.
    - **Cleanup**: the DB session always closes on success, error, or
      cancellation (``async with`` guarantees rollback on exit).
    """
    from app.core.database import async_session

    async def _rebuild():
        try:
            async with async_session() as db:
                await rebuild_user_vector(db, user_id)
                await db.commit()
        except asyncio.CancelledError:
            logger.debug("Interest vector rebuild cancelled for user %s", user_id)
            raise
        except Exception:
            logger.warning(
                "Interest vector rebuild failed for user %s",
                user_id,
                exc_info=True,
            )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — skip silently (e.g. during testing)
        return

    # Cancel any existing rebuild for this user (coalescing)
    existing = _rebuild_user_dedup.pop(user_id, None)
    if existing is not None and not existing.done():
        existing.cancel()
        _rebuild_tasks.discard(existing)

    task = loop.create_task(_rebuild())

    # Track for shutdown drain; auto-remove on completion
    _rebuild_tasks.add(task)
    _rebuild_user_dedup[user_id] = task
    task.add_done_callback(_rebuild_tasks.discard)
    task.add_done_callback(
        lambda t: _rebuild_user_dedup.pop(user_id, None) if _rebuild_user_dedup.get(user_id) is t else None
    )
