"""
趋势雷达历史快照服务。

实际调度：scheduler 每天 00:30 调一次 save_all_snapshots（见 scheduler.py），
_current_snapshot_hour 在凌晨 0-7 点归到前一天 22 点，因此每天实际只落一条
snapshot_hour≈22 的全量快照。保留 7 天（SNAPSHOT_RETENTION_DAYS），超期由
cleanup_old_snapshots 清理。

注意：scheduler 的 cleanup job 描述写"15 天"，但实际用本模块的 7 天常量；
模块头与 scheduler 描述存在历史漂移，以本模块常量为准。

用途：持续热度分析、跨时间对比、趋势变化追踪（含网文平台黑岩/点众的周报排名变化）。
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone, UTC
from typing import Optional, List, Dict

from sqlalchemy import select, delete, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trending import TrendingItem, TrendingSnapshot, TrendingSource
from app.services.trending_scrapers import get_all_trending_sources
from app.services.zhihu_url import normalize_zhihu_url

logger = logging.getLogger(__name__)

# 快照保留天数
SNAPSHOT_RETENTION_DAYS = 7

# 每天的快照时间点（小时）
SNAPSHOT_HOURS = [8, 12, 18, 22]


def _current_snapshot_hour() -> int:
    """返回当前应该存到哪个快照时间点。"""
    now_hour = datetime.now(UTC).hour
    # 找到 <= now_hour 的最大快照点
    for h in reversed(SNAPSHOT_HOURS):
        if now_hour >= h:
            return h
    # 凌晨 0-7 点归到前一天 22 点
    return 22


async def save_snapshot(db: AsyncSession, source: str) -> int:
    """
    为指定 source 保存当前时间点的快照。
    如果该 (date, hour, source) 已存在则覆盖。
    返回保存的条目数。
    """
    today = date.today()
    hour = _current_snapshot_hour()

    # 取当前最新数据
    result = await db.execute(select(TrendingItem).where(TrendingItem.source == source).order_by(TrendingItem.rank))
    items = result.scalars().all()

    if not items:
        logger.info("save_snapshot: no items for source=%s, skip", source)
        return 0

    # 序列化
    items_json = [
        {
            "rank": it.rank,
            "title": it.title,
            "url": normalize_zhihu_url(it.url),
            "hot_value": it.hot_value,
            "hot_value_raw": it.hot_value_raw,
            "trend": it.trend,
            "extra": it.extra or None,
        }
        for it in items
    ]

    # 查重：(date, hour, source)
    existing = await db.execute(
        select(TrendingSnapshot).where(
            and_(
                TrendingSnapshot.snapshot_date == today,
                TrendingSnapshot.snapshot_hour == hour,
                TrendingSnapshot.source == source,
            )
        )
    )
    record = existing.scalar_one_or_none()

    if record:
        record.items = items_json
        record.total_count = len(items_json)
        record.fetched_at = datetime.now(UTC)
        logger.info("save_snapshot: updated source=%s date=%s hour=%d count=%d", source, today, hour, len(items_json))
    else:
        record = TrendingSnapshot(
            snapshot_date=today,
            snapshot_hour=hour,
            source=source,
            category=items[0].category if items else "hot",
            items=items_json,
            total_count=len(items_json),
            fetched_at=datetime.now(UTC),
        )
        db.add(record)
        logger.info("save_snapshot: created source=%s date=%s hour=%d count=%d", source, today, hour, len(items_json))

    await db.flush()
    return len(items_json)


async def save_all_snapshots(db: AsyncSession) -> dict:
    """
    为所有有数据的 source 保存快照。
    返回 {source: count, ...}
    """
    results = {}
    for source_name in get_all_trending_sources():
        try:
            count = await save_snapshot(db, source_name)
            if count > 0:
                results[source_name] = count
        except Exception as exc:
            logger.exception("save_snapshot failed for source=%s", source_name)
            results[source_name] = 0
    return results


async def cleanup_old_snapshots(db: AsyncSession) -> int:
    """
    删除超过保留天数的快照。
    返回删除条数。
    """
    cutoff = date.today() - timedelta(days=SNAPSHOT_RETENTION_DAYS)
    # 先 count 再删
    count_result = await db.execute(
        select(func.count(TrendingSnapshot.id)).where(TrendingSnapshot.snapshot_date < cutoff)
    )
    count = count_result.scalar() or 0
    await db.execute(delete(TrendingSnapshot).where(TrendingSnapshot.snapshot_date < cutoff))
    logger.info("cleanup_old_snapshots: deleted %d snapshots before %s", count, cutoff)
    return count


async def get_snapshot_diff(db: AsyncSession, source: str) -> dict | None:
    """
    获取今日 vs 昨日的快照对比（取各自最新时间点）。
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    async def _get_latest_snap(d: date):
        result = await db.execute(
            select(TrendingSnapshot)
            .where(and_(TrendingSnapshot.snapshot_date == d, TrendingSnapshot.source == source))
            .order_by(TrendingSnapshot.snapshot_hour.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    snap_today = await _get_latest_snap(today)
    snap_yesterday = await _get_latest_snap(yesterday)

    if not snap_yesterday and not snap_today:
        return None

    def build_rank_map(snap):
        if not snap:
            return {}
        return {item["title"]: item["rank"] for item in snap.items}

    yesterday_ranks = build_rank_map(snap_yesterday)
    today_ranks = build_rank_map(snap_today)

    changes = []
    all_titles = set(yesterday_ranks.keys()) | set(today_ranks.keys())

    for title in all_titles:
        y_rank = yesterday_ranks.get(title)
        t_rank = today_ranks.get(title)
        if y_rank is None and t_rank is not None:
            change = "new"
        elif t_rank is None and y_rank is not None:
            change = "dropped"
        elif t_rank < y_rank:
            change = "up"
        elif t_rank > y_rank:
            change = "down"
        else:
            change = "same"
        changes.append(
            {
                "title": title,
                "yesterday_rank": y_rank,
                "today_rank": t_rank,
                "change": change,
            }
        )

    return {
        "yesterday_date": str(yesterday),
        "today_date": str(today),
        "yesterday_count": len(yesterday_ranks),
        "today_count": len(today_ranks),
        "changes": sorted(changes, key=lambda x: x["change"] != "new", reverse=True),
    }


# ── 持续热度分析 ──────────────────────────────────────────────────────


async def analyze_persistent_topics(
    db: AsyncSession,
    min_days: int = 2,
    min_sources: int = 1,
    days_back: int = 7,
) -> list[dict]:
    """
    分析持续在榜的话题。

    逻辑：
    1. 取最近 N 天的所有快照
    2. 按标题归一化后统计出现天数和涉及平台数
    3. 筛选连续在榜 >= min_days 且涉及平台 >= min_sources 的话题
    4. 返回按天数+平台数排序的结果

    返回: [{
        "title": str,
        "days_on_list": int,       # 在榜天数
        "snapshot_count": int,     # 出现在多少个快照中
        "total_snapshots": int,    # 总快照数（用于算占比）
        "sources": [str],          # 涉及平台列表
        "source_count": int,       # 平台数
        "avg_rank": float,         # 平均排名
        "best_rank": int,          # 最佳排名
        "hot_value_max": int,      # 最高热度
        "rank_trend": [int],       # 排名趋势（最近几天）
        "first_seen": str,         # 首次出现日期
        "last_seen": str,          # 最后出现日期
    }]
    """
    cutoff = date.today() - timedelta(days=days_back)

    # 取所有快照
    result = await db.execute(
        select(TrendingSnapshot)
        .where(TrendingSnapshot.snapshot_date >= cutoff)
        .order_by(TrendingSnapshot.snapshot_date, TrendingSnapshot.snapshot_hour)
    )
    snapshots = result.scalars().all()

    if not snapshots:
        return []

    # 统计每个快照的日期集合
    dates = sorted(set(s.snapshot_date for s in snapshots))
    total_days = len(dates)

    # 按标题聚合
    topic_data: dict[str, dict] = {}

    for snap in snapshots:
        source_name = snap.source if isinstance(snap.source, str) else snap.source.value
        for item in snap.items:
            title = item["title"].strip()
            if not title:
                continue

            if title not in topic_data:
                topic_data[title] = {
                    "dates": set(),
                    "sources": set(),
                    "ranks": [],
                    "hot_values": [],
                    "snap_count": 0,
                }

            td = topic_data[title]
            td["dates"].add(snap.snapshot_date)
            td["sources"].add(source_name)
            td["ranks"].append(item.get("rank", 0))
            td["hot_values"].append(item.get("hot_value", 0))
            td["snap_count"] += 1

    # 计算持续在榜天数（连续的，不是累计的）
    def count_consecutive_days(dates_set: set) -> int:
        if not dates_set:
            return 0
        sorted_dates = sorted(dates_set, reverse=True)
        count = 1
        for i in range(len(sorted_dates) - 1):
            if (sorted_dates[i] - sorted_dates[i + 1]).days == 1:
                count += 1
            else:
                break
        return count

    # 筛选和排序
    results = []
    for title, td in topic_data.items():
        consec_days = count_consecutive_days(td["dates"])
        source_count = len(td["sources"])

        if consec_days < min_days or source_count < min_sources:
            continue

        avg_rank = sum(td["ranks"]) / len(td["ranks"]) if td["ranks"] else 0
        best_rank = min(td["ranks"]) if td["ranks"] else 0

        # 排名趋势：取每天的最佳排名
        rank_trend = []
        for d in dates:
            day_ranks = []
            for snap in snapshots:
                if snap.snapshot_date == d:
                    for item in snap.items:
                        if item["title"].strip() == title:
                            day_ranks.append(item.get("rank", 0))
            rank_trend.append(min(day_ranks) if day_ranks else 0)

        results.append(
            {
                "title": title,
                "days_on_list": consec_days,
                "total_days": total_days,
                "snapshot_count": td["snap_count"],
                "sources": sorted(list(td["sources"])),
                "source_count": source_count,
                "avg_rank": round(avg_rank, 1),
                "best_rank": best_rank,
                "hot_value_max": max(td["hot_values"]) if td["hot_values"] else 0,
                "rank_trend": rank_trend,
                "first_seen": str(min(td["dates"])),
                "last_seen": str(max(td["dates"])),
            }
        )

    # 排序：天数降序 > 平台数降序 > 最佳排名升序
    results.sort(key=lambda x: (-x["days_on_list"], -x["source_count"], x["best_rank"]))

    return results[:50]  # 最多返回 50 条
