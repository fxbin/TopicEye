"""排序效果指标 harness。

对给定时间窗的候选集运行统一评分器，取 top-N 并计算：

- top10_worth_ratio          top-N 中标注为 worth_writing 的比例
- top10_label_coverage       top-N 中有任何标注的比例（样本量护栏）
- top10_duplicate_event_rate top-N 中作为事件非 canonical 成员的比例（重复事件）
- top10_source_coverage      top-N 的去重来源数 / N
- top10_adoption_rate        top-N 中已有采用动作（成稿或日报「写这个」）的比例

每次评测随快照持久化当时的评分配置摘要——前后对比指标时必须能回答
「这个数字是在哪套参数下测的」。

surface = today_picks_v1：非个性化的当日精选基础排序（统一评分器在
时间窗候选集上的输出，与 /contents/today-picks 的 DuckDB 公式同源，
候选可见性口径与列表一致）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.creation import CreationPlan
from app.models.pick_mark import PickMark
from app.repositories.content_label_repo import ContentLabelRepository
from app.repositories.content_repo import ContentRepo
from app.repositories.ranking_eval_repo import RankingEvalRepository
from app.services.scoring_engine import score_items
from app.services.scoring_flow import build_scoring_config_summary
from app.services.scoring_inputs import build_scoring_inputs

logger = logging.getLogger(__name__)

SURFACE_TODAY_PICKS_V1 = "today_picks_v1"

# 候选池上限：评测是离线批处理，窗口内候选全量参与百分位选择
_EVAL_CANDIDATE_LIMIT = 5000


def _round_or_none(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(value, digits)


async def _adopted_content_ids(db: AsyncSession, top_ids: list[int], top_urls: list[str]) -> set[int]:
    """采用动作：成稿工作流或日报「写这个」（按 URL 反查）。"""
    adopted: set[int] = set()
    if top_ids:
        rows = await db.execute(select(CreationPlan.content_id).where(CreationPlan.content_id.in_(top_ids)))
        adopted.update(row[0] for row in rows.all())
    if top_urls:
        rows = await db.execute(
            select(PickMark.pick_source_url).where(
                PickMark.action == "write",
                PickMark.pick_source_url.in_(top_urls),
            )
        )
        write_urls = {row[0] for row in rows.all()}
        adopted.update(url for url in write_urls)
    return adopted


async def evaluate_ranking_window(
    db: AsyncSession,
    *,
    hours: int = 168,
    top_n: int = 10,
    surface: str = SURFACE_TODAY_PICKS_V1,
) -> dict:
    """评测时间窗排序质量，返回快照 payload（未落库）。"""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    items, total = await ContentRepo(db).list_for_scoring(
        time_cutoff=cutoff,
        limit=_EVAL_CANDIDATE_LIMIT,
    )
    scoring_inputs, item_map, _ = await build_scoring_inputs(db, items)
    scored = score_items(scoring_inputs)

    top = scored[:top_n]
    top_ids = [item.content_id for _bd, item in top]
    top_urls = [item_map[item.content_id].url or "" for _bd, item in top if item_map.get(item.content_id)]

    label_map = await ContentLabelRepository(db).get_label_map(top_ids)

    # 事件重复：top 内作为 active 事件组的非 canonical 已接受成员
    duplicate_ids = await _duplicate_event_ids(db, top_ids)

    adopted_ids = await _adopted_content_ids(db, top_ids, top_urls)

    n = len(top)
    worth_count = sum(1 for cid in top_ids if (label_map.get(cid) and label_map[cid].label == "worth_writing"))
    labeled_any = sum(1 for cid in top_ids if cid in label_map)
    distinct_sources = len({item_map[cid].source_id for cid in top_ids if cid in item_map})

    metrics: dict = {
        "top_n": n,
        "candidate_total": total,
        "top10_worth_ratio": _round_or_none(worth_count / n) if n else None,
        "top10_label_coverage": _round_or_none(labeled_any / n) if n else None,
        "top10_duplicate_event_rate": _round_or_none(len(duplicate_ids) / n) if n else None,
        "top10_source_coverage": _round_or_none(distinct_sources / n) if n else None,
        "top10_adoption_rate": _round_or_none(len(adopted_ids & set(top_ids)) / n) if n else None,
        "duplicate_ids": sorted(duplicate_ids),
        "adopted_ids": sorted(adopted_ids & set(top_ids)),
    }

    item_details = [
        {
            "rank": rank + 1,
            "content_id": item.content_id,
            "title": (item_map.get(item.content_id).title if item_map.get(item.content_id) else "")[:120],
            "final_score": bd.final_score,
            "recommend_level": getattr(latest_analysis(item_map.get(item.content_id)), "recommend_level", None)
            if item_map.get(item.content_id)
            else None,
            "label": label_map[item.content_id].label if item.content_id in label_map else None,
            "label_source": label_map[item.content_id].source if item.content_id in label_map else None,
            "source_id": item.source_id,
            "adopted": item.content_id in adopted_ids,
            "duplicate_event": item.content_id in duplicate_ids,
        }
        for rank, (bd, item) in enumerate(top)
    ]

    now = datetime.now(UTC)
    return {
        "surface": surface,
        "window_start": cutoff,
        "window_end": now,
        "metrics": metrics,
        "scoring_config": build_scoring_config_summary(),
        "item_details": {"items": item_details},
    }


def latest_analysis(item):
    analyses = getattr(item, "analyses", None)
    return analyses[-1] if analyses else None


async def _duplicate_event_ids(db: AsyncSession, top_ids: list[int]) -> set[int]:
    from app.models.content_event import ContentEventGroup, ContentEventMember

    if not top_ids:
        return set()
    rows = await db.execute(
        select(ContentEventMember.content_id, ContentEventGroup.canonical_content_id)
        .join(ContentEventGroup, ContentEventGroup.id == ContentEventMember.event_group_id)
        .where(
            ContentEventMember.content_id.in_(top_ids),
            ContentEventMember.review_status.in_(("auto", "confirmed")),
            ContentEventGroup.status == "active",
        )
    )
    # 非 canonical 才算重复曝光（canonical 是该事件的代表）
    return {content_id for content_id, canonical in rows.all() if content_id != canonical}


async def evaluate_and_store(
    db: AsyncSession,
    *,
    hours: int = 168,
    top_n: int = 10,
    surface: str = SURFACE_TODAY_PICKS_V1,
):
    """评测并物化快照（同 surface+window_start 覆盖更新）。"""
    payload = await evaluate_ranking_window(db, hours=hours, top_n=top_n, surface=surface)
    snapshot = await RankingEvalRepository(db).upsert_snapshot(
        surface=payload["surface"],
        window_start=payload["window_start"],
        window_end=payload["window_end"],
        metrics=payload["metrics"],
        scoring_config=payload["scoring_config"],
        item_details=payload["item_details"],
    )
    await db.commit()
    logger.info(
        "ranking eval stored: surface=%s hours=%d top_n=%d worth_ratio=%s dup_rate=%s",
        surface,
        hours,
        top_n,
        payload["metrics"]["top10_worth_ratio"],
        payload["metrics"]["top10_duplicate_event_rate"],
    )
    return snapshot
