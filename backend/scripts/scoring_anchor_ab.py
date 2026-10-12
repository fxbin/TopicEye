"""六维行为锚点对照跑分(#114,C3 试点)。

对同一批内容分别用「带锚点段」的当前 prompt 与「去掉锚点段」的旧 prompt
各跑一次 LLM 分析,对比六维分数与 curation_score 的分布迁移,回答三个问题:
锚点让分数整体变高/变低/收敛了吗?跨过精选门槛的条数变化多少?哪一维
移动最大?全量启用锚点前跑一次,把输出贴回 #114;线上在 admin/
scoring-dashboard 按 analyzed_at 分界观察分布迁移。

用法:
    cd backend && uv run python scripts/scoring_anchor_ab.py \
        [--limit 30] [--hours 168] [--concurrency 4] [--out anchor_ab.json]

需要 DATABASE_URL 与 LLM 配置(backend/.env)。论文(arXiv)内容跳过——
论文版是否挂锚点是独立决策,不在本次对照范围。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from statistics import median, quantiles
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import or_, select  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.content import ContentItem  # noqa: E402
from app.services.analysis import _select_analysis_prompts  # noqa: E402
from app.services.llm import call_llm_json  # noqa: E402
from app.services.llm.prompts.analysis import ANALYSIS_PROMPT_EN  # noqa: E402
from app.services.scoring_caliber import CONFIG, dimension_anchor_section  # noqa: E402
from app.utils.prompt_safety import sanitize_prompt_input  # noqa: E402

logger = logging.getLogger("scoring_anchor_ab")

SIX_DIMS = (
    "quality_score",
    "hot_score",
    "freshness_score",
    "creator_score",
    "viral_score",
    "risk_score",
)


# ── 纯函数(单测覆盖) ────────────────────────────────────────────────


def strip_anchor_section(prompt: str, section: str) -> str:
    """从已渲染 prompt 中移除锚点段落及其一组相邻空行,还原挂锚点前的版本。"""
    wrapped = f"\n\n{section}\n\n"
    if wrapped in prompt:
        return prompt.replace(wrapped, "\n\n", 1)
    if section in prompt:
        return prompt.replace(section, "", 1)
    raise ValueError("锚点段落未找到,无法构造对照(旧)prompt")


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    if len(values) >= 2:
        q = quantiles(values, n=4, method="inclusive")
        p25, p75 = round(q[0], 1), round(q[2], 1)
    else:
        p25 = p75 = round(values[0], 1)
    return {
        "n": len(values),
        "mean": round(sum(values) / len(values), 1),
        "p25": p25,
        "median": round(median(values), 1),
        "p75": p75,
    }


def summarize_dimensions(
    old_rows: list[dict[str, float | None]],
    new_rows: list[dict[str, float | None]],
) -> dict[str, Any]:
    """按维对比新旧分布;curation_score 额外做配对的门槛跨越统计。"""
    out: dict[str, Any] = {}
    for key in (*SIX_DIMS, "curation_score"):
        old_vals = [r[key] for r in old_rows if r.get(key) is not None]
        new_vals = [r[key] for r in new_rows if r.get(key) is not None]
        s_old, s_new = _stats(old_vals), _stats(new_vals)
        entry: dict[str, Any] = {"old": s_old, "new": s_new}
        if s_old.get("n") and s_new.get("n"):
            entry["mean_shift"] = round(s_new["mean"] - s_old["mean"], 1)
        out[key] = entry

    threshold = float(CONFIG["curation_threshold"])
    if old_rows and len(old_rows) == len(new_rows):
        pairs = [(o.get("curation_score"), n.get("curation_score")) for o, n in zip(old_rows, new_rows, strict=True)]
        out["_threshold"] = {
            "threshold": threshold,
            "old_selected": sum(1 for o, _ in pairs if (o or 0) >= threshold),
            "new_selected": sum(1 for _, n in pairs if (n or 0) >= threshold),
            "crossed_up": sum(1 for o, n in pairs if (o or 0) < threshold <= (n or 0)),
            "crossed_down": sum(1 for o, n in pairs if (n or 0) < threshold <= (o or 0)),
        }
    return out


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# 六维行为锚点对照跑分(#114)",
        "",
        "| 维度 | n(旧/新) | 旧 mean | 新 mean | mean 迁移 | 旧 p25-p75 | 新 p25-p75 |",
        "|---|---|---|---|---|---|---|",
    ]
    for key in (*SIX_DIMS, "curation_score"):
        e = summary[key]
        old, new = e["old"], e["new"]
        shift = e.get("mean_shift")
        lines.append(
            f"| {key} | {old['n']}/{new['n']} "
            f"| {old.get('mean', '-')} | {new.get('mean', '-')} "
            f"| {shift if shift is not None else '-'} "
            f"| {old.get('p25', '-')}-{old.get('p75', '-')} "
            f"| {new.get('p25', '-')}-{new.get('p75', '-')} |"
        )
    if "_threshold" in summary:
        t = summary["_threshold"]
        lines += [
            "",
            f"精选门槛 {t['threshold']:g}:旧版入选 {t['old_selected']} 条 → 新版 {t['new_selected']} 条"
            f"(升过门槛 {t['crossed_up']},跌出 {t['crossed_down']})",
        ]
    return "\n".join(lines)


# ── 采样与 LLM 对照 ─────────────────────────────────────────────────


async def fetch_samples(limit: int, hours: int) -> list[ContentItem]:
    """近 N 小时有点击正文的内容,按抓取时间倒序;arXiv 与无正文样本在配对阶段剔除。"""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    async with async_session() as session:
        stmt = (
            select(ContentItem)
            .where(
                ContentItem.crawled_at >= cutoff,
                or_(
                    ContentItem.raw_content.isnot(None),
                    ContentItem.summary.isnot(None),
                ),
            )
            .order_by(ContentItem.crawled_at.desc())
            .limit(limit * 3)
        )
        rows = (await session.execute(stmt)).scalars().all()

    samples: list[ContentItem] = []
    for c in rows:
        if len(samples) >= limit:
            break
        title = c.title or ""
        text = c.raw_content or c.summary or ""
        if not title or not text:
            continue
        _, _, _, is_arxiv = _select_analysis_prompts(c, title=title, content_text=text)
        if is_arxiv:
            continue
        samples.append(c)
    return samples


def build_prompt_pair(content: ContentItem) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """同一内容的 新(带锚点)/旧(去锚点) 两条 messages。"""
    title = content.title or ""
    text = content.raw_content or content.summary or ""
    truncated = text[:3000] if text else "无正文内容"
    system_prompt, tpl, _, _ = _select_analysis_prompts(content, title=title, content_text=text)
    rendered = tpl.format(
        title=sanitize_prompt_input(title, max_chars=500),
        content=sanitize_prompt_input(truncated, max_chars=3000),
    )
    section = dimension_anchor_section("en" if tpl is ANALYSIS_PROMPT_EN else "zh")
    old_rendered = strip_anchor_section(rendered, section)
    base = {"role": "system", "content": system_prompt}
    return (
        [base, {"role": "user", "content": rendered}],
        [base, {"role": "user", "content": old_rendered}],
    )


async def analyze_once(messages: list[dict[str, str]], sem: asyncio.Semaphore) -> dict[str, float | None] | None:
    async with sem:
        try:
            result = await call_llm_json(messages)
        except Exception as exc:  # 单样本失败不拖垮整批
            logger.warning("LLM 调用失败,跳过该样本: %s", exc)
            return None
    scores = result.get("scores") or {}
    curation = result.get("curation") or {}
    row: dict[str, float | None] = {k: _num(scores.get(k)) for k in SIX_DIMS}
    row["curation_score"] = _num(curation.get("curation_score"))
    return row if any(v is not None for v in row.values()) else None


async def run(limit: int, hours: int, concurrency: int, out_path: str) -> None:
    samples = await fetch_samples(limit, hours)
    if not samples:
        print("近窗口内没有可用样本,放宽 --hours 或先抓取内容。", file=sys.stderr)
        sys.exit(1)
    logger.info("采样 %d 条,开始对照跑分(并发 %d)…", len(samples), concurrency)

    sem = asyncio.Semaphore(concurrency)
    old_rows: list[dict[str, float | None]] = []
    new_rows: list[dict[str, float | None]] = []

    async def pair_one(content: ContentItem) -> None:
        new_msgs, old_msgs = build_prompt_pair(content)
        old_row, new_row = await asyncio.gather(analyze_once(old_msgs, sem), analyze_once(new_msgs, sem))
        if old_row is None or new_row is None:
            logger.warning("样本「%s」有一侧失败,整对剔除", content.title[:40])
            return
        old_rows.append(old_row)
        new_rows.append(new_row)

    await asyncio.gather(*(pair_one(c) for c in samples))
    if not old_rows:
        print("全部样本 LLM 调用失败,检查 LLM 配置。", file=sys.stderr)
        sys.exit(1)

    summary = summarize_dimensions(old_rows, new_rows)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "pairs": len(old_rows),
        "summary": summary,
        "old_rows": old_rows,
        "new_rows": new_rows,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(render_markdown(summary))
    print(f"\n明细已写入 {out_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30, help="配对样本数(默认 30)")
    parser.add_argument("--hours", type=int, default=168, help="采样窗口小时数(默认 168)")
    parser.add_argument("--concurrency", type=int, default=4, help="LLM 并发(默认 4)")
    parser.add_argument("--out", default="anchor_ab.json", help="明细输出路径")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    logger.setLevel(logging.INFO)
    asyncio.run(
        run(
            limit=args.limit,
            hours=args.hours,
            concurrency=args.concurrency,
            out_path=args.out,
        )
    )


if __name__ == "__main__":
    main()
