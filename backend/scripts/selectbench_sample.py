"""SelectBench 标注样本导出：按对照矩阵分层 + 分歧加权（v0）。

从 matrix_<date>.json 的四象限中按「分歧层超采样」配额抽标注候选，并补一层
「非 AIHOT 源全池分层」（AIHOT 信源只覆盖部分分布，金标必须含其余信源内容；
负样本从全池分位抽样，禁按被扫描的分数变量分层——方法席复核结论）。

输出 CSV 供人工标注（label 列填 worth_writing / not_worth / uncertain），
随后由 selectbench_import_labels.py 导入 content_labels（source=human）。

用法：
    uv run python scripts/selectbench_sample.py [--matrix PATH] [--total 200]
"""

from __future__ import annotations  # noqa: E402

import argparse  # noqa: E402
import asyncio  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.repositories.content_repo import ContentRepo  # noqa: E402
from app.services.scoring_engine import score_items  # noqa: E402
from app.services.scoring_inputs import build_scoring_inputs  # noqa: E402

logger = logging.getLogger("selectbench_sample")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _take(rows: list[dict], n: int, rng: random.Random) -> list[dict]:
    return rng.sample(rows, min(n, len(rows)))


async def load_non_aihot_layer(quota: int, rng: random.Random) -> list[dict]:
    """非 AIHOT 信源的全池分层样本：按最终名次分位抽（覆盖头/中/尾段）。

    用名次（而非 curation 分数）分层——curation 是扫描目标变量的一部分，
    直接按它分层会人为制造近可分金标。
    """
    async with async_session() as db:
        aihot_ids = set((await db.execute(select(Source.id).where(Source.url.ilike("%aihot%")))).scalars().all())
        items, total = await ContentRepo(db).list_for_scoring(
            time_cutoff=datetime.now(UTC) - timedelta(days=14),
            limit=5000,
        )
        scoring_inputs, item_map, _ = await build_scoring_inputs(db, items)
        scored = score_items(scoring_inputs)
        rows = []
        for rank, (bd, item) in enumerate(scored):
            if item.source_id in aihot_ids:
                continue
            analysis = item_map[item.content_id].analyses[-1] if item_map.get(item.content_id) else None
            rows.append(
                {
                    "content_id": item.content_id,
                    "title": (item_map[item.content_id].title if item_map.get(item.content_id) else "")[:100],
                    "url": item_map[item.content_id].url if item_map.get(item.content_id) else "",
                    "te_selected": bd.selected,
                    "te_rank": rank + 1,
                    "curation_score": float(analysis.curation_score)
                    if analysis and analysis.curation_score is not None
                    else None,
                    "summary_source": analysis.summary_source if analysis else None,
                }
            )
        if not rows:
            return []
        # 名次三分层（头 20% / 中 30-60% / 尾 80% 后），各抽 1/3
        n = len(rows)
        bands = (rows[: max(1, n // 5)], rows[n // 3 : n * 3 // 5], rows[n * 4 // 5 :])
        picked: list[dict] = []
        for band in bands:
            picked.extend(_take(band, quota // 3, rng))
        for row in picked:
            row["quadrant"] = "non_aihot_pool"
        logger.info("非 AIHOT 全池分层：候选 %d 条（总池 %d），抽 %d", len(rows), total, len(picked))
        return picked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", default=None, help="matrix json 路径（默认 data/selectbench/ 最新一份）")
    parser.add_argument("--total", type=int, default=200, help="标注候选总数")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="data/selectbench", help="输出目录")
    args = parser.parse_args()

    out_dir = os.path.join(_ROOT, args.out)
    if args.matrix:
        matrix_path = args.matrix
    else:
        candidates = sorted(f for f in os.listdir(out_dir) if f.startswith("matrix_") and f.endswith(".json"))
        if not candidates:
            raise SystemExit("data/selectbench/ 下没有 matrix_*.json，先跑 selectbench_matrix.py")
        matrix_path = os.path.join(out_dir, candidates[-1])
    with open(matrix_path, encoding="utf-8") as f:
        matrix = json.load(f)

    rng = random.Random(args.seed)
    detail = matrix["detail"]
    # 配额：分歧层 55%（重点）、双高 15%、双低 15%、非 AIHOT 全池 15%
    quotas = {
        "aihot_only": int(args.total * 0.30),
        "te_only": int(args.total * 0.25),
        "both": int(args.total * 0.15),
        "neither": int(args.total * 0.15),
    }
    rows: list[dict] = []
    for quadrant, quota in quotas.items():
        picked = _take(detail[quadrant], quota, rng)
        for row in picked:
            row["quadrant"] = quadrant
        rows.extend(picked)
        logger.info("%-11s 配额 %3d → 实际 %3d", quadrant, quota, len(picked))

    non_aihot_quota = args.total - len(rows)
    if non_aihot_quota > 0:
        rows.extend(asyncio.run(load_non_aihot_layer(non_aihot_quota, rng)))

    fieldnames = [
        "content_id",
        "quadrant",
        "title",
        "url",
        "aihot_selected",
        "te_selected",
        "te_rank",
        "curation_score",
        "summary_source",
        "label",
        "notes",
    ]
    out_path = os.path.join(out_dir, f"annotation_batch_{datetime.now(UTC):%Y%m%d}.csv")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    logger.info("标注候选 %d 条已导出 %s（label 列留空待人工填写）", len(rows), out_path)


if __name__ == "__main__":
    main()
