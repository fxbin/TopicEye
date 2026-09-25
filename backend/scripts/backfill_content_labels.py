"""一次性幂等脚本：回填内容选题标注（行为弱标注 + 日报 pick_mark 导入）。

标注是排序效果基准的度量基础：无标注时只能测重复事件率/来源覆盖率，
有价值密度类指标（top10 值得写率、采用率）依赖本脚本先回填。

用法（在 backend/ 目录下；生产先 alembic upgrade head）：
    python scripts/backfill_content_labels.py            # dry-run，只打印统计
    python scripts/backfill_content_labels.py --apply     # 真写库

特性：
- 幂等：human / pick_mark 标注不被覆盖；行为标注按最新证据刷新；
  证据不足时清掉过期行为行。可安全重复运行、可挂调度定期刷新。
- 权重与阈值见 services/content_labeling.py 顶部说明，调整后重跑即可。
"""

from __future__ import annotations  # noqa: E402

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core.database import async_session  # noqa: E402
from app.services.content_labeling import import_pick_mark_labels, rebuild_behavioral_labels  # noqa: E402

logger = logging.getLogger("backfill_content_labels")
logging.basicConfig(level=logging.INFO, format="%(message)s")


async def main(*, apply: bool, lookback_days: int) -> None:
    logger.info("== 标注回填（%s，回溯 %d 天）==", "apply" if apply else "dry-run", lookback_days)
    async with async_session() as db:
        # dry-run 也全量执行：标注推导是幂等写，先在事务里看统计再回滚
        behavioral = await rebuild_behavioral_labels(db, lookback_days=lookback_days)
        pick_mark = await import_pick_mark_labels(db)
        if not apply:
            await db.rollback()
            logger.info("（dry-run：已回滚，不落库；加 --apply 真写库）")
    logger.info("behavioral: %s", json.dumps(behavioral, ensure_ascii=False))
    logger.info("pick_mark:  %s", json.dumps(pick_mark, ensure_ascii=False))
    logger.info("== 完成 ==")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回填内容选题标注")
    parser.add_argument("--apply", action="store_true", help="真写库（默认 dry-run 事务回滚）")
    parser.add_argument("--lookback-days", type=int, default=30, help="行为信号回溯窗口（默认 30 天）")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply, lookback_days=args.lookback_days))
