"""一次性幂等脚本：回填历史日报/周报/月报 top_picks 的 content_id。

背景：站内阅读功能（ReaderDrawer 按 content_id 取正文）只对新生成的报告生效——
历史报告的 top_picks JSON 里没有 content_id 字段。本脚本按 title/source_url
反查 content_items 表，给历史 pick 注入 content_id，让旧报告也能站内阅读。

用法（在 backend/ 目录下，容器内或本地 venv）：
    python scripts/backfill_report_content_id.py            # dry-run，只打印统计
    python scripts/backfill_report_content_id.py --apply     # 真写库

特性：
- 幂等：已有 content_id 的 pick 跳过，可安全重复运行。
- 只给 pick 对象加 content_id 键，不删任何字段、不改 status。
- 分批 commit（每 20 条报告一次）。

日报三级匹配：source_title 精确 → source_item_ids 候选集子串 → source_url。
周报/月报：title 子串匹配（限制时间窗 + source 缩歧义）。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# 脚本运行时 sys.path[0] 是 scripts/ 目录，需把项目根（/app 或 backend/）加入
# 才能 import app.*。兼容容器内（/app）和本地 venv（backend/）两种场景。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import json
import logging
import sys
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, or_

from app.core.database import async_session
from app.models.content import ContentItem
from app.models.daily_report import DailyReport
from app.models.weekly_digest import WeeklyDigest
from app.models.monthly_digest import MonthlyDigest
from app.services.zhihu_url import normalize_zhihu_url

logger = logging.getLogger("backfill")
logging.basicConfig(level=logging.INFO, format="%(message)s")

BATCH_SIZE = 20


def _parse_json(val: Any) -> list:
    """容忍 None / 已是 list / JSON 字符串。"""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        return json.loads(val)
    except (ValueError, TypeError):
        return []


async def _find_content_id_by_title_exact(db, title: str) -> int | None:
    """source_title 精确匹配 content_items.title。"""
    if not title:
        return None
    result = await db.execute(
        select(ContentItem.id).where(ContentItem.title == title).limit(1)
    )
    return result.scalar_one_or_none()


async def _find_content_id_by_url(db, url: str) -> int | None:
    """source_url 精确匹配 content_items.url（先 normalize）。"""
    if not url:
        return None
    norm = normalize_zhihu_url(url)
    result = await db.execute(
        select(ContentItem.id).where(ContentItem.url == norm).limit(1)
    )
    return result.scalar_one_or_none()


async def _find_content_id_in_candidates(
    db, title: str, candidate_ids: list[int]
) -> int | None:
    """在 source_item_ids 候选集里，找 title 互为子串的 content。缩歧义。"""
    if not title or not candidate_ids:
        return None
    result = await db.execute(
        select(ContentItem.id, ContentItem.title).where(ContentItem.id.in_(candidate_ids))
    )
    rows = result.all()
    for cid, ct in rows:
        if ct and (title in ct or ct in title):
            return cid
    return None


async def _find_content_id_by_title_fuzzy(
    db,
    title: str,
    *,
    source_name: str | None = None,
    date_start: date | None = None,
    date_end: date | None = None,
) -> int | None:
    """title 子串模糊匹配 content_items.title（周报/月报用，限制时间窗+source 缩歧义）。

    互为子串（pick.title 含原文 或 原文含 pick.title），取第一条命中。
    """
    if not title or len(title) < 4:
        return None  # 太短的 title 子串匹配歧义太大
    stmt = select(ContentItem.id, ContentItem.title).where(
        or_(
            ContentItem.title.ilike(f"%{title}%"),
            # 反向：原文标题含 pick title（pick 可能是截断的）
            # ilike 无法做"列含常量子串"，用 text 占位不安全；靠上面的正向 + 候选集兜底
        )
    )
    if source_name:
        stmt = stmt.where(ContentItem.source_name == source_name)
    if date_start:
        stmt = stmt.where(ContentItem.crawled_at >= date_start)
    if date_end:
        stmt = stmt.where(ContentItem.crawled_at <= date_end)
    stmt = stmt.limit(1)
    result = await db.execute(stmt)
    row = result.first()
    return row[0] if row else None


# ── 日报回填 ──────────────────────────────────────────────


async def backfill_daily(db, *, apply: bool) -> tuple[int, int, list[str]]:
    """回填日报 top_picks 的 content_id。返回 (待回填数, 命中数, 未命中标题)。"""
    result = await db.execute(
        select(DailyReport).where(DailyReport.status == "DONE").order_by(DailyReport.id)
    )
    reports = result.scalars().all()

    total_pending = 0
    total_hit = 0
    misses: list[str] = []
    written = 0

    for report in reports:
        picks = _parse_json(report.top_picks)
        if not picks:
            continue
        changed = False
        for pick in picks:
            if pick.get("content_id") is not None:
                continue  # 幂等：已有则跳过
            total_pending += 1
            source_title = pick.get("source_title") or ""
            source_url = pick.get("source_url") or ""
            # 解析 source_item_ids 候选集
            candidate_ids = _parse_json(report.source_item_ids)

            cid = None
            # 1. source_title 精确
            cid = await _find_content_id_by_title_exact(db, source_title)
            # 2. 候选集子串兜底
            if cid is None:
                cid = await _find_content_id_in_candidates(db, source_title, candidate_ids)
            # 3. source_url 兜底
            if cid is None:
                cid = await _find_content_id_by_url(db, source_url)

            if cid is not None:
                pick["content_id"] = cid
                total_hit += 1
                changed = True
            else:
                misses.append(f"[日报 {report.report_date}] {source_title[:40] or pick.get('title','')[:40]}")

        if changed and apply:
            report.top_picks = json.dumps(picks, ensure_ascii=False)
            written += 1
            if written % BATCH_SIZE == 0:
                await db.commit()
                logger.info("  日报已提交 %d 条...", written)

    if apply and written % BATCH_SIZE != 0:
        await db.commit()
    return total_pending, total_hit, misses


# ── 周报/月报回填 ─────────────────────────────────────────


async def backfill_digest(
    db,
    model,
    *,
    apply: bool,
    label: str,
    start_attr: str,
    end_attr: str,
) -> tuple[int, int, list[str]]:
    """回填周报或月报 top_picks 的 content_id。"""
    result = await db.execute(
        select(model).where(model.status == "DONE").order_by(model.id)
    )
    reports = result.scalars().all()

    total_pending = 0
    total_hit = 0
    misses: list[str] = []
    written = 0

    for report in reports:
        picks = _parse_json(report.top_picks)
        if not picks:
            continue
        changed = False
        # 报告时间窗（缩歧义）
        date_start = getattr(report, start_attr, None)
        date_end = getattr(report, end_attr, None)
        # 转为 date 类型（放宽 7 天避免边界遗漏）
        if isinstance(date_start, str):
            try:
                date_start = date.fromisoformat(date_start) - timedelta(days=7)
            except ValueError:
                date_start = None
        if isinstance(date_end, str):
            try:
                date_end = date.fromisoformat(date_end) + timedelta(days=7)
            except ValueError:
                date_end = None

        for pick in picks:
            if pick.get("content_id") is not None:
                continue
            total_pending += 1
            title = pick.get("title") or ""
            source = pick.get("source") or None

            cid = await _find_content_id_by_title_fuzzy(
                db, title, source_name=source, date_start=date_start, date_end=date_end
            )
            if cid is not None:
                pick["content_id"] = cid
                total_hit += 1
                changed = True
            else:
                misses.append(f"[{label}] {title[:40]}")

        if changed and apply:
            report.top_picks = json.dumps(picks, ensure_ascii=False)
            written += 1
            if written % BATCH_SIZE == 0:
                await db.commit()
                logger.info("  %s 已提交 %d 条...", label, written)

    if apply and written % BATCH_SIZE != 0:
        await db.commit()
    return total_pending, total_hit, misses


async def main(apply: bool):
    mode = "APPLY（真写）" if apply else "DRY-RUN（只统计，不写库）"
    logger.info("=" * 60)
    logger.info("历史报告 content_id 回填 — %s", mode)
    logger.info("=" * 60)

    async with async_session() as db:
        logger.info("\n── 日报 ──")
        d_pending, d_hit, d_miss = await backfill_daily(db, apply=apply)
        _print_stats("日报", d_pending, d_hit, d_miss)

        logger.info("\n── 周报 ──")
        w_pending, w_hit, w_miss = await backfill_digest(
            db, WeeklyDigest, apply=apply, label="周报",
            start_attr="week_start", end_attr="week_end",
        )
        _print_stats("周报", w_pending, w_hit, w_miss)

        logger.info("\n── 月报 ──")
        m_pending, m_hit, m_miss = await backfill_digest(
            db, MonthlyDigest, apply=apply, label="月报",
            start_attr="month_start", end_attr="month_end",
        )
        _print_stats("月报", m_pending, m_hit, m_miss)

    total_p = d_pending + w_pending + m_pending
    total_h = d_hit + w_hit + m_hit
    logger.info("\n" + "=" * 60)
    logger.info("合计：待回填 %d / 命中 %d / 命中率 %.0f%%",
                total_p, total_h, (total_h / total_p * 100) if total_p else 0)
    if not apply and total_p > 0:
        logger.info("\n（dry-run 未写库。加 --apply 真写。）")
    elif apply:
        logger.info("\n（已写库。可重跑 dry-run 验证幂等。）")
    logger.info("=" * 60)


def _print_stats(label: str, pending: int, hit: int, misses: list[str]):
    rate = (hit / pending * 100) if pending else 0
    logger.info("  %s：待回填 %d / 命中 %d / 命中率 %.0f%%", label, pending, hit, rate)
    if misses:
        logger.info("  未命中 %d 条（前 10 条）:", len(misses))
        for m in misses[:10]:
            logger.info("    %s", m)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回填历史报告 content_id")
    parser.add_argument("--apply", action="store_true", help="真写库（默认 dry-run）")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
