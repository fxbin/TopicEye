"""SelectBench 对照矩阵：TopicEye 评分 × AIHOT 精选信号（v0 一次性对照实验）。

同一池内容（AIHOT all feed 已在 TopicEye 信源内），把「TopicEye 引擎是否精选」
与「AIHOT 是否精选」（/feed.xml guid）对齐成四象限：

    双高一致（都选）   → 高置信正样本候选
    分歧 1（AIHOT 选、TopicEye 未选）→ 人工重点标注（漏选归因）
    分歧 2（TopicEye 选、AIHOT 未选）→ 人工重点标注（口径差异归因）
    未在有限精选feed中观察到 → 待人工判断，不是负样本

用途边界（所有者决定，2026-10-11）：AIHOT 精选信号仅用于内部一致性对照与
标注样本排序——不作为金标标签、不导入为新数据源、不分发其内容、不用于
模型训练。两项目均为开源（AIHOT MIT / TopicEye Apache-2.0），所有者评估
后决定以此边界使用、不做额外的用途确认（评估记录见 roundtable Memory：
selectbench-gold-source）。

用法：
    uv run python scripts/selectbench_matrix.py [--days 7] [--out DIR]

输出：stdout 报告 + <out>/matrix_<date>.json（明细供 sample.py 分层抽样）。
"""

from __future__ import annotations  # noqa: E402

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import httpx  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.repositories.content_repo import ContentRepo  # noqa: E402
from app.services.content_serialization import latest_analysis_from_item  # noqa: E402
from app.services.scoring_engine import CONFIG, score_items  # noqa: E402
from app.services.scoring_inputs import build_scoring_inputs  # noqa: E402

logger = logging.getLogger("selectbench_matrix")
logging.basicConfig(level=logging.INFO, format="%(message)s")

FEED_URL = "https://aihot.news/feed.xml"
_ORIGINAL_URL_RE = re.compile(r'href="(https?://[^"]+)"[^>]*>阅读原文')


async def fetch_aihot_selected() -> list[dict]:
    """拉精选 feed（最近 50 条），返回 guid/标题/发布时间/原文链接。"""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(FEED_URL, headers={"User-Agent": "TopicEye-SelectBench/0.1 (internal calibration)"})
        resp.raise_for_status()
    root = ET.fromstring(resp.text)
    items: list[dict] = []
    for node in root.findall("./channel/item"):
        guid = (node.findtext("guid") or "").strip()
        if not guid:
            continue
        original = ""
        if (desc := node.findtext("description")) and (m := _ORIGINAL_URL_RE.search(desc)):
            original = m.group(1)
        items.append(
            {
                "guid": guid,
                "title": (node.findtext("title") or "").strip(),
                "published": node.findtext("pubDate") or "",
                "original_url": original,
                "category": node.findtext("category") or "",
            }
        )
    return items


def _parse_rss_date(value: str) -> datetime | None:
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(value)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        return None


async def build_matrix(days: int, out_dir: str) -> dict:
    if not 1 <= days <= 365:
        raise ValueError("days must be 1..365")
    as_of = datetime.now(UTC)
    feed_items = await fetch_aihot_selected()
    if not feed_items:
        raise SystemExit("AIHOT 精选 feed 为空，中止")
    pub_dates = [d for d in (_parse_rss_date(i["published"]) for i in feed_items) if d]
    window_start = min(pub_dates) - timedelta(days=1) if pub_dates else datetime.now(UTC) - timedelta(days=days)
    selected_guids = {i["guid"] for i in feed_items}
    logger.info(
        "AIHOT 精选 feed：%d 条，pubDate 跨度 %s ~ %s",
        len(feed_items),
        min(pub_dates).date() if pub_dates else "?",
        max(pub_dates).date() if pub_dates else "?",
    )

    async with async_session() as db:
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        aihot_sources = (await db.execute(select(Source).where(Source.url.ilike("%aihot%")))).scalars().all()
        if not aihot_sources:
            raise SystemExit("信源表中未找到 AIHOT 信源（url 含 aihot）")
        aihot_source_ids = {s.id for s in aihot_sources}

        # 全池重放：窗口内全部分析完成内容过一遍引擎，得到 selected 集合与名次
        repo = ContentRepo(db)
        items, total = await repo.list_for_scoring(
            time_cutoff=window_start,
            limit=5000,
            public_only=True,
        )
        scoring_inputs, item_map, _ = await build_scoring_inputs(db, items)
        scored = score_items(scoring_inputs)
        rank_by_id = {item.content_id: rank + 1 for rank, (_bd, item) in enumerate(scored)}
        selected_ids = {item.content_id for bd, item in scored if bd.selected}
        logger.info(
            "TopicEye 全池重放：%d 条候选（窗口 %.1f 天），selected %d 条",
            total,
            (datetime.now(UTC) - window_start).total_seconds() / 86400,
            len(selected_ids),
        )

        # AIHOT 源内容：guid 对齐（content url 尾段）+ 象限归类
        quadrants = {"both": [], "aihot_only": [], "te_only": [], "neither": [], "outside_feed_window": []}
        aihot_items = [it for it in items if it.source_id in aihot_source_ids]
        matched_guids: set[str] = set()
        for it in aihot_items:
            guid = (it.url or "").rsplit("/", 1)[-1]
            if guid in selected_guids:
                matched_guids.add(guid)
            aihot_sel = guid in selected_guids
            te_sel = it.id in selected_ids
            # 「AIHOT 未选」只有在内容入库时间落在 feed 覆盖窗口内才可判定：
            # 窗口外的内容它可能还没评到、或评过但已滚出最近 50 条——归为
            # 未知，不进四象限（单次 feed 快照的 v0 已知局限）。
            created = (
                it.created_at.replace(tzinfo=UTC) if it.created_at and it.created_at.tzinfo is None else it.created_at
            )
            if not aihot_sel and created and created < window_start:
                quadrant = "outside_feed_window"
            elif aihot_sel and te_sel:
                quadrant = "both"
            elif aihot_sel:
                quadrant = "aihot_only"
            elif te_sel:
                quadrant = "te_only"
            else:
                quadrant = "neither"
            analysis = latest_analysis_from_item(it)
            row = {
                "content_id": it.id,
                "guid": guid,
                "title": (it.title or "")[:100],
                "aihot_selected": True if aihot_sel else None,
                "aihot_observation": "selected" if aihot_sel else "not_observed_in_finite_feed",
                "te_selected": te_sel,
                "te_rank": rank_by_id.get(it.id),
                "curation_score": float(analysis.curation_score)
                if analysis and analysis.curation_score is not None
                else None,
                "summary_source": analysis.summary_source if analysis else None,
            }
            quadrants[quadrant].append(row)

    feed_only = selected_guids - matched_guids  # AIHOT 精选但库内未对齐（空窗/回溯）
    n_aihot = len(aihot_items)
    n_scored = n_aihot - len(quadrants["outside_feed_window"])
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "feed_items": len(feed_items),
        "feed_window_start": window_start.isoformat(),
        "aihot_pool_items": n_aihot,
        "matched_selected": len(matched_guids),
        "feed_only_unmatched": sorted(feed_only),
        "quadrants": {k: len(v) for k, v in quadrants.items()},
        "agreement_rate": None,
        "observed_positive_overlap_rate": len(quadrants["both"]) / len(matched_guids) if matched_guids else None,
        "aihot_absence_is_unknown": True,
        "owner_user_id": None,
        "pool_total": total,
        "pool_loaded": len(items),
        "pool_truncated": total > len(items),
        "as_of": as_of.isoformat(),
        "scoring_config": dict(CONFIG),
        "gold_labels_verified": False,
        "n_in_window": n_scored,
        "detail": quadrants,
    }

    logger.info("=" * 56)
    logger.info("四象限（AIHOT 源内容 %d 条）：", n_aihot)
    for key, desc in (
        ("both", "双高一致（都选）→ 正样本候选"),
        ("aihot_only", "分歧：AIHOT 选、TopicEye 未选 → 漏选归因重点"),
        ("te_only", "分歧：TopicEye 选、AIHOT 未选 → 口径差异重点"),
        ("neither", "未观察到精选且TE未选 → 仍须人工判断"),
        ("outside_feed_window", "窗口外（AIHOT 判定未知，不计入一致率）"),
    ):
        logger.info("  %-11s %4d 条  %s", key, len(quadrants[key]), desc)
    logger.info("一致率：%s", report["agreement_rate"])
    if feed_only:
        logger.info("AIHOT 精选但库内未对齐 %d 条（抓取空窗/回溯补选）", len(feed_only))

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"matrix_{datetime.now(UTC):%Y%m%d_%H%M%S_%f}.json")
    with open(out_path, "x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info("明细已写入 %s", out_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="feed 窗口不足时的回退天数")
    parser.add_argument("--out", default="data/selectbench", help="输出目录")
    args = parser.parse_args()
    asyncio.run(build_matrix(args.days, args.out))


if __name__ == "__main__":
    main()
