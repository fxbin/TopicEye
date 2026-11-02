"""重建版本内容。默认只读计划；写入必须带备份及当前指纹。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import async_session
from app.schemas.product_feedback import ProductUpdateCreate
from app.services.product_updates import fingerprint, replace_updates, snapshot_updates


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=Path(__file__).resolve().parents[1] / "app/data/release_notes.json"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--expected-fingerprint")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--database-backup", type=Path)
    args = parser.parse_args()
    if args.apply and args.restore:
        parser.error("--apply 与 --restore 不可同时使用")
    writing = args.apply or args.restore is not None
    if writing and (not args.expected_fingerprint or not args.backup or not args.database_backup):
        parser.error("写入必须指定 --expected-fingerprint、--backup 和 --database-backup")
    if writing and (not args.database_backup.is_file() or args.database_backup.stat().st_size == 0):
        parser.error("完整数据库备份不存在或为空")
    if writing:
        with args.database_backup.open("rb") as stream:
            if stream.read(5) != b"PGDMP":
                parser.error("需要 pg_dump 自定义格式的完整数据库备份")
    source = json.loads((args.restore or args.catalog).read_text())
    records = source["rows"] if args.restore else source["records"]
    if args.restore and source.get("fingerprint") != fingerprint(records):
        parser.error("记录备份指纹不匹配，文件可能已损坏")
    if not args.restore:
        versions = [ProductUpdateCreate.model_validate(r).version for r in records]
        if not records or len(versions) != len(set(versions)):
            parser.error("整理稿不能为空，且日期版本不能重复")
        for record in records:
            ProductUpdateCreate.model_validate(record)
    async with async_session() as db, db.begin():
        before = await snapshot_updates(db, lock=bool(writing))
        current = fingerprint(before)
        if writing:
            if current != args.expected_fingerprint:
                raise ValueError("版本记录已变化，请重新生成计划")
            args.backup.parent.mkdir(parents=True, exist_ok=True)
            with args.backup.open("x") as stream:
                json.dump({"rows": before, "fingerprint": current}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            after = await replace_updates(db, records, expected=current, restore=bool(args.restore))
        else:
            after = records
        print(
            json.dumps(
                {
                    "mode": "restore" if args.restore else "apply" if writing else "plan",
                    "current_count": len(before),
                    "new_count": len(after),
                    "current_fingerprint": current,
                    "result_fingerprint": fingerprint(after) if writing else None,
                    "versions": [row["version"] for row in after],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
