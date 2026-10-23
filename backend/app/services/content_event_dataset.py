"""Export minimal public projections without changing event facts or labels."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.content_event_evaluation_repo import ContentEventEvaluationRepository


def _projection(item):
    assert item.owner_user_id is None
    return {
        "id": item.id,
        "owner_user_id": None,
        "title": item.title,
        "summary": (item.summary or "")[:1000],
        "source_name": item.source_name,
        "source_type": item.source_type,
        **{
            field: getattr(item, field).isoformat() if getattr(item, field) else None
            for field in ("created_at", "published_at", "crawled_at")
        },
    }


async def export_public_event_pool(
    db: AsyncSession,
    *,
    as_of: datetime,
    environment: str,
    incoming_hours: int = 24,
    lookback_days: int = 30,
    max_candidates: int = 10000,
    max_queries: int = 1000,
    source_identity: dict | None = None,
) -> dict:
    if as_of.tzinfo is None or as_of > datetime.now(UTC):
        raise ValueError("as_of must be an explicit non-future timezone-aware timestamp")
    if not environment.strip() or not 1 <= incoming_hours <= 720 or not 1 <= lookback_days <= 365:
        raise ValueError("environment and bounded time windows are required")
    if not 1 <= max_candidates <= 100000 or not 1 <= max_queries <= 10000:
        raise ValueError("dataset limits out of bounds")
    if db.in_transaction():
        raise ValueError("export requires a fresh session so READ ONLY precedes every query")
    if db.bind.dialect.name != "postgresql":
        raise ValueError("dataset export requires PostgreSQL snapshot isolation")
    async with db.begin():
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        database, server, port, isolation, read_only, snapshot_at = (
            await db.execute(
                text(
                    "SELECT current_database(), inet_server_addr()::text, inet_server_port(), "
                    "current_setting('transaction_isolation'), current_setting('transaction_read_only'), "
                    "transaction_timestamp()"
                )
            )
        ).one()
        repo = ContentEventEvaluationRepository(db)
        pool = await repo.public_canonicals(
            since=as_of - timedelta(days=lookback_days), as_of=as_of, limit=max_candidates + 1
        )
        incoming = await repo.public_incoming(
            since=as_of - timedelta(hours=incoming_hours), as_of=as_of, limit=max_queries + 1
        )
        candidates = [
            {**_projection(item), "event_id": event_id, "event_version": version}
            for item, event_id, version in pool[:max_candidates]
        ]
        queries = [
            {
                "query_id": f"content:{item.id}",
                "incoming": _projection(item),
                "expected": "unknown",
                "expected_target_ids": [],
                "target_labels_exhaustive": False,
                "label_source": "unlabeled",
            }
            for item in incoming[:max_queries]
        ]
    selection = {
        "as_of": as_of.astimezone(UTC).isoformat(),
        "incoming_hours": incoming_hours,
        "lookback_days": lookback_days,
        "max_candidates": max_candidates,
        "max_queries": max_queries,
        "canonical_order": "last_occurrence_at desc, group id desc",
        "incoming_order": "published_at asc nulls last, crawled_at asc nulls last, created_at asc, id asc",
        "pool_truncated": len(pool) > max_candidates,
        "incoming_truncated": len(incoming) > max_queries,
    }
    payload = {
        "pool_kind": "actual_public_canonical_export",
        "split": "unlabeled",
        "owner_user_id": None,
        "selection": selection,
        "provenance": {
            "declared_environment": environment,
            "database": database,
            "server_address": server,
            "server_port": port,
            "transaction_isolation": isolation,
            "transaction_read_only": read_only,
            "snapshot_at": snapshot_at.isoformat(),
            "as_of_semantics": "content eligibility cutoff; current event facts at snapshot_at, not historical replay",
            "source_identity": source_identity or {},
            "environment_independently_verified": False,
        },
        "candidates": candidates,
        "queries": queries,
        "human_holdout_verified": False,
        "write_rollout_eligible": False,
        "labeling_requirements": [
            "Keep calibration and holdout event families separate; a random query split alone does not prove independence.",
            "Use independent human review and retain reviewer/provenance records; all exported labels start unknown.",
            "A different_event label covers the entire supplied pool and requires exhaustive review.",
            "A truncated or empty canonical pool does not establish production full-pool recall.",
        ],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"dataset_id": f"public-events-{digest[:16]}", **payload}
