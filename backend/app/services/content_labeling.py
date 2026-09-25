"""内容选题标注 —— 行为弱标注推断与人工标注导入。

标注口径（可配置常量，调整后重跑 backfill 即可刷新）：
- 正例 worth_writing：合成证据分 ≥ POSITIVE_THRESHOLD；
- 负例 not_worth：合成证据分 ≤ NEGATIVE_THRESHOLD；
- 其余不留行为标注（证据不足，宁可空缺不给结论）。

信号权重（一次出现计一次，同一内容同类信号累加）：
- creation   +6  成稿工作流 = 最强采用信号
- favorite   +3  主动收藏
- great_pick +3  反馈「选得好」
- like       +2  反馈点赞
- dislike    -4  反馈点踩
- not_relevant -3 反馈不相关
- skip       -2  反馈跳过
- outdated   -1.5 反馈过时
- ignore     -1.5 用户「不感兴趣」（仅个人忽略，全局屏蔽不算）
- pick_watch +1  日报「观察」
- pick_skip  -3  日报「跳过」
- pick_write +5  日报「写这个」（人工判断，导入时直接落 pick_mark 权威行）

confidence = min(1, |score| / 6)：单个强信号（creation/pick_write 级）
即满置信，弱信号需要叠加。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.creation import CreationPlan
from app.models.favorite import FavoriteItem, FavoriteTargetType
from app.models.feedback import FeedbackType, UserFeedback
from app.models.ignored import IgnoredItem
from app.models.pick_mark import PickMark
from app.repositories.content_label_repo import ContentLabelRepository

logger = logging.getLogger(__name__)

SIGNAL_WEIGHTS: dict[str, float] = {
    "creation": 6.0,
    "favorite": 3.0,
    "great_pick": 3.0,
    "like": 2.0,
    "dislike": -4.0,
    "not_relevant": -3.0,
    "skip": -2.0,
    "outdated": -1.5,
    "ignore": -1.5,
    "pick_watch": 1.0,
    "pick_skip": -3.0,
    "pick_write": 5.0,
}

POSITIVE_THRESHOLD = 3.0
NEGATIVE_THRESHOLD = -3.0
_CONFIDENCE_SCALE = 6.0

LABEL_WORTH = "worth_writing"
LABEL_NOT_WORTH = "not_worth"


def compute_label_from_signals(signals: dict[str, int]) -> tuple[str | None, float, dict[str, int]]:
    """信号计数 → (label | None, confidence, evidence)。

    返回 None 表示证据不足，不应留行为标注。未知信号名不参与计分、
    不进入 evidence。
    """
    known = {name: count for name, count in signals.items() if name in SIGNAL_WEIGHTS and count}
    score = sum(SIGNAL_WEIGHTS[name] * count for name, count in known.items())
    evidence = known
    if score >= POSITIVE_THRESHOLD:
        return LABEL_WORTH, min(1.0, score / _CONFIDENCE_SCALE), evidence
    if score <= NEGATIVE_THRESHOLD:
        return LABEL_NOT_WORTH, min(1.0, abs(score) / _CONFIDENCE_SCALE), evidence
    return None, 0.0, evidence


async def rebuild_behavioral_labels(
    db: AsyncSession,
    *,
    lookback_days: int = 30,
) -> dict:
    """在回溯窗口内收集内容级行为信号，重建行为弱标注。

    幂等：已有 human / pick_mark 标注的内容不覆盖；证据不足的内容
    清掉过期行为行。返回统计 dict。
    """
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    repo = ContentLabelRepository(db)
    signals: dict[int, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))

    # ── creations：成稿 = 最强采用 ───────────────────────────────────
    rows = await db.execute(select(CreationPlan.content_id).where(CreationPlan.created_at >= cutoff).distinct())
    for (content_id,) in rows.all():
        signals[content_id]["creation"] += 1

    # ── favorites ────────────────────────────────────────────────────
    rows = await db.execute(
        select(FavoriteItem.target_id)
        .where(
            FavoriteItem.target_type == FavoriteTargetType.CONTENT,
            FavoriteItem.target_id.isnot(None),
            FavoriteItem.created_at >= cutoff,
        )
        .distinct()
    )
    for (content_id,) in rows.all():
        signals[content_id]["favorite"] += 1

    # ── feedback（latest-per-user 语义从简：类型计数） ────────────────
    rows = await db.execute(
        select(UserFeedback.content_id, UserFeedback.feedback_type).where(UserFeedback.created_at >= cutoff)
    )
    for content_id, feedback_type in rows.all():
        try:
            name = FeedbackType(feedback_type).name
        except ValueError:
            continue
        if content_id is not None and name in SIGNAL_WEIGHTS:
            signals[content_id][name] += 1

    # ── ignores：仅个人忽略；全局屏蔽是运营口径不是兴趣信号 ─────────
    rows = await db.execute(
        select(IgnoredItem.content_id).where(
            IgnoredItem.user_id.isnot(None),
            IgnoredItem.created_at >= cutoff,
        )
    )
    for (content_id,) in rows.all():
        signals[content_id]["ignore"] += 1

    # ── pick marks：经 pick_source_url 反查内容 ──────────────────────
    rows = await db.execute(
        select(PickMark.pick_source_url, PickMark.action).where(
            PickMark.pick_source_url.isnot(None),
            PickMark.created_at >= cutoff,
        )
    )
    url_action: dict[str, str] = {}
    for url, action in rows.all():
        url_action.setdefault(url, action)
    if url_action:
        content_rows = await db.execute(
            select(ContentItem.id, ContentItem.url).where(ContentItem.url.in_(list(url_action)))
        )
        url_to_id = {url: content_id for content_id, url in content_rows.all()}
        for url, action in url_action.items():
            content_id = url_to_id.get(url)
            if content_id is None:
                continue
            name = {"write": "pick_write", "watch": "pick_watch", "skip": "pick_skip"}.get(action)
            if name:
                signals[content_id][name] += 1

    # ── 逐内容判定并落库 ─────────────────────────────────────────────
    stats = {"scanned": len(signals), "worth_writing": 0, "not_worth": 0, "dropped": 0, "skipped_authoritative": 0}
    for content_id, counts in signals.items():
        label, confidence, evidence = compute_label_from_signals(dict(counts))
        existing = await repo.get_by_content_id(content_id)
        if existing is not None and existing.source in ("human", "pick_mark"):
            stats["skipped_authoritative"] += 1
            continue
        if label is None:
            if existing is not None:
                await repo.drop_behavioral(content_id)
                stats["dropped"] += 1
            continue
        await repo.upsert_behavioral(content_id, label, confidence, evidence)
        stats[label] += 1

    await db.commit()
    logger.info(
        "behavioral labels rebuilt: scanned=%d worth=%d not_worth=%d dropped=%d authoritative_skipped=%d",
        stats["scanned"],
        stats["worth_writing"],
        stats["not_worth"],
        stats["dropped"],
        stats["skipped_authoritative"],
    )
    return stats


async def import_pick_mark_labels(db: AsyncSession) -> dict:
    """把日报「写这个 / 跳过」导入为 pick_mark 权威标注。

    「观察」不落标注（只是关注，不构成值得写/不值得的结论），
    仅作为行为弱信号参与 rebuild_behavioral_labels。
    """
    repo = ContentLabelRepository(db)
    stats = {"matched": 0, "unmatched": 0, "skipped_watch": 0}

    rows = await db.execute(
        select(PickMark.pick_title, PickMark.action, PickMark.pick_source_url)
        .where(PickMark.pick_source_url.isnot(None))
        .order_by(PickMark.updated_at.desc())
    )
    url_action: dict[str, str] = {}
    for _title, action, url in rows.all():
        url_action.setdefault(url, action)  # 同 URL 保留最新动作
    if not url_action:
        return stats

    content_rows = await db.execute(
        select(ContentItem.id, ContentItem.url).where(ContentItem.url.in_(list(url_action)))
    )
    url_to_id = {url: content_id for content_id, url in content_rows.all()}

    for url, action in url_action.items():
        if action == "watch":
            stats["skipped_watch"] += 1
            continue
        content_id = url_to_id.get(url)
        if content_id is None:
            stats["unmatched"] += 1
            continue
        label = LABEL_WORTH if action == "write" else LABEL_NOT_WORTH
        await repo.set_authoritative(
            content_id,
            label,
            source="pick_mark",
            evidence={"pick_action": action, "pick_url": url},
        )
        stats["matched"] += 1

    await db.commit()
    logger.info(
        "pick_mark labels imported: matched=%d unmatched=%d watch_skipped=%d",
        stats["matched"],
        stats["unmatched"],
        stats["skipped_watch"],
    )
    return stats
