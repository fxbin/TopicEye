"""Safely backfill legacy ``duplicate_of`` chains into content events.

Usage from ``backend/``::

    python scripts/backfill_content_events.py
    python scripts/backfill_content_events.py --apply

The default is a read-only dry run.  Before ``--apply`` on a real database,
run ``./scripts/backup_db.sh``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core.database import async_session  # noqa: E402
from app.services.content_event_service import ContentEventService  # noqa: E402

logger = logging.getLogger("backfill_content_events")
logging.basicConfig(level=logging.INFO, format="%(message)s")


async def run_backfill(*, apply: bool) -> dict[str, int]:
    async with async_session() as db:
        service = ContentEventService(db)
        report = await service.backfill_legacy_duplicates(apply=apply)
        if apply:
            await db.commit()
        else:
            await db.rollback()
        return report.as_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="把 content_items.duplicate_of 幂等回填为内容事件真源")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际写库；默认仅 dry-run 扫描",
    )
    args = parser.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    if args.apply:
        logger.warning("【APPLY】请确认已执行 ./scripts/backup_db.sh")
    report = asyncio.run(run_backfill(apply=args.apply))
    logger.info("[%s] %s", mode, json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
