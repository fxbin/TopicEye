"""一次性幂等脚本：把存量标签规范化为统一键口径。

背景：content_items.tags / ai_analyses.tags 历史上未做规范化，存在
"AI" 与 "ai" 并存、复合标签（"AI安全, 联合国" 作为单个数组元素）等
脏数据，影响筛选匹配与兴趣向量聚合。写入路径已在
services/tag_normalization.py 统一规范化；本脚本负责清洗存量。

用法（在 backend/ 目录下，容器内或本地 venv）：
    python scripts/normalize_tags.py            # dry-run，只打印统计
    python scripts/normalize_tags.py --apply     # 真写库

特性：
- 幂等：已规范的行跳过（normalize_tag_list 结果与原值等价即跳过），
  可安全重复运行。
- 只重写 tags 列，不触碰其他字段。
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
from app.models.content import ContentItem  # noqa: E402
from app.services.tag_normalization import normalize_tag_list  # noqa: E402

logger = logging.getLogger("normalize_tags")
logging.basicConfig(level=logging.INFO, format="%(message)s")

BATCH_SIZE = 500


async def _normalize_table(model, label: str, *, apply: bool) -> None:
    """逐批读取 tags 列，规范化后写回有变化的行。"""
    changed = 0
    scanned = 0
    last_id = 0
    while True:
        result = await async_session().execute(
            select(model.id, model.tags).where(model.id > last_id).order_by(model.id).limit(BATCH_SIZE)
        )
        rows = result.all()
        if not rows:
            break

        updates: list[tuple[int, list[str]]] = []
        for row_id, raw_tags in rows:
            last_id = row_id
            scanned += 1
            if raw_tags is None:
                continue
            normalized = normalize_tag_list(raw_tags)
            # 幂等判定：已是规范形态（list[str] 且逐元素相等）则跳过
            if isinstance(raw_tags, list) and [str(t) for t in raw_tags] == normalized:
                continue
            if normalized != raw_tags:
                updates.append((row_id, normalized))

        if apply and updates:
            for row_id, normalized in updates:
                await async_session().execute(update(model).where(model.id == row_id).values(tags=normalized))
            await async_session().commit()
        changed += len(updates)

    action = "已重写" if apply else "将重写（dry-run，加 --apply 真写库）"
    logger.info("%s: 扫描 %d 行，%s %d 行", label, scanned, action, changed)


async def main(*, apply: bool) -> None:
    if apply:
        logger.info("== 开始回填（--apply）==")
    else:
        logger.info("== dry-run 模式，不写库 ==")
    await _normalize_table(ContentItem, "content_items", apply=apply)
    await _normalize_table(AiAnalysis, "ai_analyses", apply=apply)
    logger.info("== 完成 ==")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="存量标签规范化回填")
    parser.add_argument("--apply", action="store_true", help="真写库（默认 dry-run）")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
