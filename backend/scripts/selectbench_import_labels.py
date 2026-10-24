"""Import independently completed public labels; default is validation-only.

Run --dry-run first. Writing requires --apply and an explicit active admin
--reviewer-user-id. That ID is an operator declaration, not proof of human
review. This tool never selects an arbitrary account or labels unknown rows.
Production execution/backup remains a separate operational decision.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text  # noqa: E402

import app.models  # noqa: E402, F401
from app.core.database import async_session  # noqa: E402
from app.models.content import ContentItem  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.repositories.content_label_repo import ContentLabelRepository  # noqa: E402

logger = logging.getLogger("selectbench_import")
_VALID = {"worth_writing", "not_worth", "uncertain"}


def _read_labels(csv_path: str) -> tuple[list[dict], str]:
    raw = Path(csv_path).read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not {"content_id", "label"} <= set(reader.fieldnames or []):
        raise ValueError("CSV requires content_id and label columns")
    labels, seen = [], set()
    for index, row in enumerate(reader, 2):
        value = (row.get("label") or "").strip()
        if not value:
            continue
        if value not in _VALID:
            raise ValueError(f"invalid label on CSV row {index}")
        try:
            content_id = int(row.get("content_id") or "")
        except ValueError as exc:
            raise ValueError(f"invalid content ID on CSV row {index}") from exc
        if content_id < 1 or content_id in seen:
            raise ValueError(f"invalid or duplicate content ID on CSV row {index}")
        seen.add(content_id)
        labels.append({"content_id": content_id, "label": value, "row_number": index, "notes": row.get("notes") or ""})
    return labels, hashlib.sha256(raw).hexdigest()


async def import_labels(csv_path: str, dry_run: bool = True, *, reviewer_user_id: int | None = None) -> dict:
    labels, digest = _read_labels(csv_path)
    if not dry_run and (type(reviewer_user_id) is not int or reviewer_user_id < 1):
        raise ValueError("apply requires an explicit reviewer_user_id")
    if not labels:
        return {"validated": 0, "written": 0, "dry_run": dry_run, "csv_sha256": digest}
    async with async_session() as db, db.begin():
        if dry_run:
            await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        if reviewer_user_id is not None:
            reviewer = await db.get(User, reviewer_user_id)
            if reviewer is None or reviewer.role != UserRole.ADMIN.value or not reviewer.is_active:
                raise ValueError("reviewer must be an active admin")
        stmt = select(ContentItem.id, ContentItem.owner_user_id).where(
            ContentItem.id.in_([row["content_id"] for row in labels])
        )
        if not dry_run:
            stmt = stmt.with_for_update()
        content = {row.id: row.owner_user_id for row in (await db.execute(stmt)).all()}
        if any(row["content_id"] not in content or content[row["content_id"]] is not None for row in labels):
            raise ValueError("every labeled article must exist in the public owner scope")
        if not dry_run:
            repo = ContentLabelRepository(db)
            for row in labels:
                await repo.set_authoritative(
                    row["content_id"],
                    row["label"],
                    source="human",
                    labeled_by=reviewer_user_id,
                    evidence={
                        "source": "selectbench_csv",
                        "csv_sha256": digest,
                        "row_number": row["row_number"],
                        "notes": row["notes"],
                        "reviewer_identity_declared_by_operator": True,
                    },
                )
    return {
        "validated": len(labels),
        "written": 0 if dry_run else len(labels),
        "dry_run": dry_run,
        "csv_sha256": digest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--reviewer-user-id", type=int)
    args = parser.parse_args()
    result = asyncio.run(import_labels(args.csv, not args.apply, reviewer_user_id=args.reviewer_user_id))
    print(result)


if __name__ == "__main__":
    main()
