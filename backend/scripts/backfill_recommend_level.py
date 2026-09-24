"""一次性幂等脚本：回填 ai_analyses.recommend_level。

背景：推荐等级此前只在前端即时计算，服务端无法按等级筛选。迁移
c5e2a7f90b14 增加了 ai_analyses.recommend_level 列，新分析写入时由
services/recommendation_level.py 判定填充；本脚本负责回填存量行。

用法（在 backend/ 目录下，容器内或本地 venv；需先跑 alembic upgrade）：
    python scripts/backfill_recommend_level.py            # dry-run，只打印统计
    python scripts/backfill_recommend_level.py --apply     # 真写库

特性：
- 幂等：已等于分类器结果的行跳过，可安全重复运行。
- 阈值调整后重跑本脚本即可刷新全量等级。
- 分批 commit（每 500 行一次）。
"""

from __future__ import annotations  # noqa: E402

import argparse  # noqa: E402
import asyncio  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import logging  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.analysis import AiAnalysis  # noqa: E402
from app.services.recommendation_level import classify_recommendation_level  # noqa: E402

logger = logging.getLogger("backfill_recommend_level")
logging.basicConfig(level=logging.INFO, format="%(message)s")

BATCH_SIZE = 500


def _text_signal(row: AiAnalysis) -> bool:
    return bool(row.recommendation or row.summary or row.key_points or row.creator_angles)


async def main(*, apply: bool) -> None:
    if apply:
        logger.info("== 开始回填（--apply）==")
    else:
        logger.info("== dry-run 模式，不写库 ==")

    changed = 0
    scanned = 0
    last_id = 0
    while True:
        result = await async_session().execute(
            select(AiAnalysis).where(AiAnalysis.id > last_id).order_by(AiAnalysis.id).limit(BATCH_SIZE)
        )
        rows = result.scalars().all()
        if not rows:
            break

        updates: list[tuple[int, str]] = []
        for row in rows:
            last_id = row.id
            scanned += 1
            level = classify_recommendation_level(
                quality_score=row.quality_score,
                hot_score=row.hot_score,
                freshness_score=row.freshness_score,
                creator_score=row.creator_score,
                viral_score=row.viral_score,
                risk_score=row.risk_score,
                curation_score=row.curation_score or 0.0,
                has_text_signal=_text_signal(row),
            )
            if row.recommend_level != level:
                updates.append((row.id, level))

        if apply and updates:
            for row_id, level in updates:
                await async_session().execute(
                    update(AiAnalysis).where(AiAnalysis.id == row_id).values(recommend_level=level)
                )
            await async_session().commit()
        changed += len(updates)

    action = "已重写" if apply else "将重写（dry-run，加 --apply 真写库）"
    logger.info("ai_analyses: 扫描 %d 行，%s %d 行", scanned, action, changed)
    logger.info("== 完成 ==")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回填 ai_analyses.recommend_level")
    parser.add_argument("--apply", action="store_true", help="真写库（默认 dry-run）")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
