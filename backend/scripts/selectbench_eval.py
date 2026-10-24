"""SelectBench 门槛扫描：金标集上重放评分引擎，扫描 curation_percentile（v0）。

输入：content_labels（human / pick_mark 源）的标注条目 + 各自最新分析的六维
分数（重放输入）。金标批作为一个固定批次过 score_items——考卷语义：同一批
上比较参数。v0 扫 1×4 网格（curation_percentile ∈ {65,70,75,80}），每档输出
precision / recall / F1 / 选中率 + FP/FN 错例清单。

注意（v0 已知局限，正式版需补）：
- 分数取「当前最新分析」而非冻结快照——requeue 重分析会使考卷漂移；
  结果 JSON 里记录了 analysis_id 清单供追溯，金标冻结表是后续切片。
- 样本 <300 时指标噪声大于信号（F1 的 95% CI 约 ±8pp@200 条），读错例的
  定性模式，不比小数点。

用法：
    uv run python scripts/selectbench_eval.py [--percentiles 65,70,75,80] [--out DIR]
"""

from __future__ import annotations  # noqa: E402

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.content import ContentItem  # noqa: E402
from app.models.content_label import ContentLabel  # noqa: E402
from app.services import scoring_engine  # noqa: E402
from app.services.content_serialization import latest_analysis_from_item  # noqa: E402
from app.services.scoring_inputs import build_scoring_input  # noqa: E402

logger = logging.getLogger("selectbench_eval")
logging.basicConfig(level=logging.INFO, format="%(message)s")


async def load_gold_set() -> tuple[list, dict[int, str], dict[int, int]]:
    """金标 = human/pick_mark 标注的条目；返回 (items, label_map, analysis_id_map)。"""
    async with async_session() as db:
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        rows = (
            await db.execute(
                select(ContentLabel, ContentItem)
                .join(ContentItem, ContentItem.id == ContentLabel.content_id)
                .options(selectinload(ContentItem.analyses), selectinload(ContentItem.source))
                .where(ContentItem.owner_user_id.is_(None))
                .order_by(ContentItem.id)
                .where(ContentLabel.source.in_(("human", "pick_mark")))
                .where(ContentLabel.label != "uncertain")
            )
        ).all()
        items, label_map, analysis_map = [], {}, {}
        for label_row, item in rows:
            if not item.analyses:
                continue
            items.append(item)
            label_map[item.id] = label_row.label
            analysis_map[item.id] = latest_analysis_from_item(item).id
    return items, label_map, analysis_map


def _metrics(scored, label_map, inputs=()) -> dict:
    tp = fp = fn = 0
    fps, fns = [], []
    for bd, item in scored:
        truth = label_map[item.content_id]
        pred = bd.selected
        if pred and truth == "worth_writing":
            tp += 1
        elif pred and truth == "not_worth":
            fp += 1
            fps.append({"content_id": item.content_id, "final_score": bd.final_score, "title": item.title[:60]})
        elif not pred and truth == "worth_writing":
            fn += 1
            fns.append({"content_id": item.content_id, "final_score": bd.final_score, "title": item.title[:60]})
    scored_ids = {item.content_id for _, item in scored}
    input_map = {item.content_id: item for item in inputs}
    excluded_ids = sorted(set(label_map) - scored_ids)
    for content_id in excluded_ids:
        if label_map[content_id] == "worth_writing":
            fn += 1
            item = input_map.get(content_id)
            fns.append(
                {
                    "content_id": content_id,
                    "final_score": None,
                    "title": item.title[:60] if item is not None else "",
                    "excluded_from_scoring": True,
                }
            )
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    total = len(label_map)
    return {
        "n": total,
        "scored_n": len(scored),
        "excluded_content_ids": excluded_ids,
        "selected": tp + fp,
        "selection_rate": round((tp + fp) / total, 3) if total else None,
        "precision": round(precision, 3) if precision is not None else None,
        "recall": round(recall, 3) if recall is not None else None,
        "f1": round(f1, 3) if f1 is not None else None,
        "false_positives": fps,
        "false_negatives": fns,
    }


async def run(percentiles: list[int], out_dir: str) -> None:
    if (
        not percentiles
        or len(set(percentiles)) != len(percentiles)
        or any(type(p) is not int or not 0 <= p <= 100 for p in percentiles)
    ):
        raise ValueError("percentiles must be unique integers in 0..100")
    items, label_map, analysis_map = await load_gold_set()
    if not items:
        raise SystemExit(
            "content_labels 无 human/pick_mark 标注（uncertain 除外）——"
            "先跑 selectbench_sample.py 导出 → 人工标注 → selectbench_import_labels.py 导入"
        )
    inputs = [build_scoring_input(item) for item in items]
    gold_pos = sum(1 for v in label_map.values() if v == "worth_writing")
    logger.info("金标集 %d 条（正 %d / 负 %d）", len(items), gold_pos, len(items) - gold_pos)

    baseline = dict(scoring_engine.CONFIG)
    original = baseline["curation_percentile"]
    results: dict[str, dict] = {}
    try:
        for p in percentiles:
            scoring_engine.CONFIG["curation_percentile"] = p
            scored = scoring_engine.score_items(list(inputs))
            results[f"p{p}"] = _metrics(scored, label_map, inputs)
            m = results[f"p{p}"]
            logger.info(
                "percentile=%-3d 选中率 %.1f%%  P=%.3f R=%.3f F1=%.3f  FP=%d FN=%d",
                p,
                (m["selection_rate"] or 0) * 100,
                m["precision"] or 0,
                m["recall"] or 0,
                m["f1"] or 0,
                len(m["false_positives"]),
                len(m["false_negatives"]),
            )
    finally:
        scoring_engine.CONFIG["curation_percentile"] = original

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "gold_size": len(items),
        "owner_user_id": None,
        "batch_comparison_only": True,
        "independent_holdout_verified": False,
        "scoring_config": baseline,
        "label_snapshot": label_map,
        "gold_positive": gold_pos,
        "analysis_ids": analysis_map,  # 溯源：重分析漂移时定位考卷变化
        "scoring_config_baseline": {"original_percentile": original},
        "results": results,
    }
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"eval_{datetime.now(UTC):%Y%m%d_%H%M%S_%f}.json")
    with open(out_path, "x", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("结果已写入 %s（错例清单在其中）", out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--percentiles", default="65,70,75,80")
    parser.add_argument("--out", default="data/selectbench")
    args = parser.parse_args()
    asyncio.run(run([int(x) for x in args.percentiles.split(",")], args.out))


if __name__ == "__main__":
    main()
