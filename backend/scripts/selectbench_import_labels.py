"""SelectBench 标注导入：把人工标注完的 CSV 批量写入 content_labels（human）。

输入：selectbench_sample.py 导出、label 列已填（worth_writing / not_worth /
uncertain）的 CSV。走 ContentLabelRepository.set_authoritative（与 admin
单条标注同一写路径，human 源覆盖任何已有来源），幂等可重复执行。

用法：
    uv run python scripts/selectbench_import_labels.py --csv data/selectbench/annotation_batch_YYYYMMDD.csv [--dry-run]
"""

from __future__ import annotations  # noqa: E402

import argparse  # noqa: E402
import asyncio  # noqa: E402
import csv  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.repositories.content_label_repo import ContentLabelRepository  # noqa: E402

logger = logging.getLogger("selectbench_import")
logging.basicConfig(level=logging.INFO, format="%(message)s")

_VALID = {"worth_writing", "not_worth", "uncertain"}


async def import_labels(csv_path: str, dry_run: bool) -> None:
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    labeled = [r for r in rows if (r.get("label") or "").strip()]
    invalid = [r for r in labeled if r["label"].strip() not in _VALID]
    if invalid:
        raise SystemExit(f"非法 label 值：{[r['label'] for r in invalid[:5]]}，允许值 {sorted(_VALID)}")
    skipped = len(rows) - len(labeled)
    logger.info("CSV %d 行：待导入 %d，跳过未标注 %d", len(rows), len(labeled), skipped)

    async with async_session() as db:
        admin = (await db.execute(select(User).where(User.role == UserRole.ADMIN.value).limit(1))).scalars().first()
        labeled_by = admin.id if admin else None
        if dry_run:
            logger.info("[dry-run] 将以 labeled_by=%s 导入 %d 条", labeled_by, len(labeled))
            return
        repo = ContentLabelRepository(db)
        counts: dict[str, int] = {}
        for row in labeled:
            await repo.set_authoritative(
                int(row["content_id"]),
                row["label"].strip(),
                source="human",
                labeled_by=labeled_by,
            )
            counts[row["label"].strip()] = counts.get(row["label"].strip(), 0) + 1
        await db.commit()
    logger.info("导入完成：%s", counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(import_labels(args.csv, args.dry_run))


if __name__ == "__main__":
    main()
