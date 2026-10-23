"""Export public canonical/incoming projections in a read-only repeatable-read transaction."""

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402, F401 — register ORM relationships
from app.core.database import async_session  # noqa: E402
from app.services.content_event_dataset import export_public_event_pool  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=datetime.fromisoformat)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--source-revision", help="Deployed source identity, when the runtime has no .git directory")
    parser.add_argument("--incoming-hours", type=int, default=24)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--max-candidates", type=int, default=10000)
    parser.add_argument("--max-queries", type=int, default=1000)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new export path")
    root = Path(__file__).resolve().parents[2]
    paths = [
        Path(__file__).resolve(),
        root / "backend/app/services/content_event_dataset.py",
        root / "backend/app/repositories/content_event_evaluation_repo.py",
    ]
    try:
        git_head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        git_head = None
    identity = {
        "git_head": git_head,
        "declared_source_revision": args.source_revision,
        "source_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    }

    async def run():
        async with async_session() as db:
            return await export_public_event_pool(
                db,
                as_of=args.as_of,
                environment=args.environment,
                incoming_hours=args.incoming_hours,
                lookback_days=args.lookback_days,
                max_candidates=args.max_candidates,
                max_queries=args.max_queries,
                source_identity=identity,
            )

    result = asyncio.run(run())
    with args.output.open("x") as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "dataset_id": result["dataset_id"],
                "candidates": len(result["candidates"]),
                "queries": len(result["queries"]),
                "selection": result["selection"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
