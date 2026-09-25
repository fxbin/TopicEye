"""排序效果基线脚本：评测指定时间窗并把快照落库。

首次建立基准：
    python scripts/run_ranking_baseline.py --hours 168 --apply

只看不落库：
    python scripts/run_ranking_baseline.py --hours 168

输出四类核心指标 + top-N 明细表，同时把（指标 + 当时评分配置）物化到
ranking_eval_snapshots——之后任何权重/门槛调整，都应重跑本脚本对比。
"""

from __future__ import annotations  # noqa: E402

import argparse  # noqa: E402
import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core.database import async_session  # noqa: E402
from app.services.ranking_eval import evaluate_and_store  # noqa: E402

logger = logging.getLogger("ranking_baseline")
logging.basicConfig(level=logging.INFO, format="%(message)s")

_CORE_KEYS = (
    "top10_worth_ratio",
    "top10_label_coverage",
    "top10_duplicate_event_rate",
    "top10_source_coverage",
    "top10_adoption_rate",
)


def _fmt(value) -> str:
    if value is None:
        return "  n/a"
    return f"{value * 100:5.1f}%"


async def main(*, hours: int, top_n: int, apply: bool) -> None:
    async with async_session() as db:
        snapshot = (
            await evaluate_and_store(db, hours=hours, top_n=top_n)
            if apply
            else await _eval_only(db, hours=hours, top_n=top_n)
        )

    metrics = snapshot.metrics
    logger.info("== 排序效果基线 surface=%s 窗口=%dh top=%d ==", snapshot.surface, hours, top_n)
    for key in _CORE_KEYS:
        label = {
            "top10_worth_ratio": "值得写比例   ",
            "top10_label_coverage": "标注覆盖率   ",
            "top10_duplicate_event_rate": "重复事件率   ",
            "top10_source_coverage": "来源覆盖率   ",
            "top10_adoption_rate": "采用率       ",
        }[key]
        logger.info("  %s %s", label, _fmt(metrics.get(key)))
    logger.info("  候选总数 %d", metrics.get("candidate_total", 0))

    details = (snapshot.item_details or {}).get("items", [])
    if details:
        logger.info("  ---- top-%d 明细 ----", len(details))
        for item in details:
            logger.info(
                "  #%-2d score=%-7s level=%-6s label=%-13s dup=%s adopted=%s %s",
                item["rank"],
                item["final_score"],
                item.get("recommend_level") or "-",
                f"{item['label'] or '无标注'}({item['label_source']})" if item.get("label") else "无标注",
                "Y" if item.get("duplicate_event") else "-",
                "Y" if item.get("adopted") else "-",
                (item.get("title") or "")[:44],
            )
    logger.info("== 快照已%s（id=%s）==", "落库" if apply else "未落库（加 --apply）", getattr(snapshot, "id", "-"))


async def _eval_only(db, *, hours: int, top_n: int):
    from app.services.ranking_eval import evaluate_ranking_window

    payload = await evaluate_ranking_window(db, hours=hours, top_n=top_n)

    class _View:
        pass

    view = _View()
    view.surface = payload["surface"]
    view.metrics = payload["metrics"]
    view.item_details = payload["item_details"]
    return view


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="排序效果基线评测")
    parser.add_argument("--hours", type=int, default=168, help="回溯窗口小时数（默认 168 = 7 天）")
    parser.add_argument("--top-n", type=int, default=10, help="取前 N 条（默认 10）")
    parser.add_argument("--apply", action="store_true", help="物化快照（默认只打印）")
    args = parser.parse_args()
    asyncio.run(main(hours=args.hours, top_n=args.top_n, apply=args.apply))
