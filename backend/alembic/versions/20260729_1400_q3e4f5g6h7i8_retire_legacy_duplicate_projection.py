"""retire legacy duplicate projection

Revision ID: q3e4f5g6h7i8
Revises: p2d3e4f5g6h7
Create Date: 2026-07-29 14:00:00
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision = "q3e4f5g6h7i8"
down_revision = "p2d3e4f5g6h7"
branch_labels = None
depends_on = None


def _effective_time(row: dict) -> datetime:
    return row["published_at"] or row["crawled_at"] or row["created_at"]


def _backfill_legacy_projection() -> None:
    """Move every unassigned valid legacy edge into event truth.

    Event truth wins when a content item is already assigned. Any remaining
    legacy edge with a broken target, cross-owner hop, self-link, or cycle
    aborts the migration before the compatibility columns are removed.
    """

    bind = op.get_bind()
    content = sa.table(
        "content_items",
        sa.column("id", sa.Integer),
        sa.column("owner_user_id", sa.Integer),
        sa.column("duplicate_of", sa.Integer),
        sa.column("similarity_score", sa.Float),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("crawled_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    groups = sa.table(
        "content_event_groups",
        sa.column("id", sa.Integer),
        sa.column("owner_user_id", sa.Integer),
        sa.column("canonical_content_id", sa.Integer),
        sa.column("canonical_policy", sa.String),
        sa.column("canonical_reason", sa.Text),
        sa.column("canonical_locked", sa.Boolean),
        sa.column("first_occurrence_at", sa.DateTime(timezone=True)),
        sa.column("last_occurrence_at", sa.DateTime(timezone=True)),
        sa.column("status", sa.String),
        sa.column("version", sa.Integer),
        sa.column("classifier_version", sa.String),
    )
    members = sa.table(
        "content_event_members",
        sa.column("id", sa.Integer),
        sa.column("event_group_id", sa.Integer),
        sa.column("content_id", sa.Integer),
        sa.column("relation_type", sa.String),
        sa.column("confidence", sa.Float),
        sa.column("match_method", sa.String),
        sa.column("detector_version", sa.String),
        sa.column("reason", sa.Text),
        sa.column("review_status", sa.String),
        sa.column("matched_at", sa.DateTime(timezone=True)),
    )

    # Load only rows participating in a legacy duplicate edge (source or any
    # reachable target along the chain). The previous full-table scan
    # materialized every content_items row; in production this table holds far
    # more rows than ever carried a duplicate_of link, so we scope the in-memory
    # working set to what the migration actually touches.
    edge_source_rows = bind.execute(
        sa.select(content).where(content.c.duplicate_of.is_not(None))
    ).mappings().all()
    legacy_edges = {int(row["id"]): int(row["duplicate_of"]) for row in edge_source_rows}
    if not legacy_edges:
        return

    # Walk every chain to collect the full id closure (sources + transitively
    # reachable targets, including the duplicate_of-free root at the end).
    closure: set[int] = set()
    for source_id in legacy_edges:
        current = source_id
        while current in legacy_edges and current not in closure:
            closure.add(current)
            current = legacy_edges[current]
        closure.add(current)

    content_rows = {
        int(row["id"]): dict(row)
        for row in bind.execute(
            sa.select(content).where(content.c.id.in_(closure))
        ).mappings().all()
    }

    group_rows = {
        int(row["id"]): dict(row)
        for row in bind.execute(sa.select(groups)).mappings().all()
    }
    canonical_groups = {
        int(row["canonical_content_id"]): int(row["id"])
        for row in group_rows.values()
    }
    member_rows = {
        int(row["content_id"]): dict(row)
        for row in bind.execute(sa.select(members)).mappings().all()
    }

    def assigned_group(content_id: int) -> int | None:
        canonical_group_id = canonical_groups.get(content_id)
        if canonical_group_id is not None:
            return canonical_group_id
        member = member_rows.get(content_id)
        if member is None:
            return None
        # Membership is structurally unique even when the relation is pending,
        # rejected, shadowed, or archived. Event truth therefore wins for every
        # existing member row, not only for currently served relationships.
        return int(member["event_group_id"])

    def resolve_target(content_id: int) -> tuple[int | None, int]:
        owner_user_id = content_rows[content_id]["owner_user_id"]
        current = content_id
        visited: set[int] = set()
        while current in legacy_edges:
            if current in visited:
                raise RuntimeError(
                    f"legacy duplicate cycle blocks migration at content {current}"
                )
            visited.add(current)
            target_id = legacy_edges[current]
            if target_id == current:
                raise RuntimeError(
                    f"legacy duplicate self-link blocks migration at content {current}"
                )
            target = content_rows.get(target_id)
            if target is None:
                raise RuntimeError(
                    f"legacy duplicate target {target_id} is missing for content {current}"
                )
            if target["owner_user_id"] != owner_user_id:
                raise RuntimeError(
                    f"legacy duplicate crosses owner scope: {current} -> {target_id}"
                )
            target_group_id = assigned_group(target_id)
            if target_group_id is not None:
                return target_group_id, target_id
            current = target_id
        return None, current

    pending_by_root: dict[int, list[int]] = defaultdict(list)
    pending_by_group: dict[int, list[int]] = defaultdict(list)
    for content_id in sorted(legacy_edges):
        if assigned_group(content_id) is not None:
            continue
        target_group_id, root_id = resolve_target(content_id)
        if target_group_id is None:
            pending_by_root[root_id].append(content_id)
        else:
            pending_by_group[target_group_id].append(content_id)

    for root_id, child_ids in pending_by_root.items():
        root = content_rows[root_id]
        occurrence_rows = [root, *(content_rows[child_id] for child_id in child_ids)]
        occurrence_times = [_effective_time(row) for row in occurrence_rows]
        group_id = int(
            bind.execute(
                groups.insert()
                .values(
                    owner_user_id=root["owner_user_id"],
                    canonical_content_id=root_id,
                    canonical_policy="earliest",
                    canonical_reason="migrated from retired duplicate projection",
                    canonical_locked=False,
                    first_occurrence_at=min(occurrence_times),
                    last_occurrence_at=max(occurrence_times),
                    status="active",
                    version=1,
                    classifier_version="legacy-retirement:v1",
                )
                .returning(groups.c.id)
            ).scalar_one()
        )
        canonical_groups[root_id] = group_id
        group_rows[group_id] = {
            "id": group_id,
            "owner_user_id": root["owner_user_id"],
            "canonical_content_id": root_id,
            "status": "active",
        }
        pending_by_group[group_id].extend(child_ids)

    for group_id, child_ids in pending_by_group.items():
        group = group_rows[group_id]
        occurrence_times = [
            _effective_time(content_rows[int(group["canonical_content_id"])])
        ]
        for child_id in sorted(set(child_ids)):
            if assigned_group(child_id) is not None:
                continue
            child = content_rows[child_id]
            if child["owner_user_id"] != group["owner_user_id"]:
                raise RuntimeError(
                    f"legacy duplicate crosses event owner scope: {child_id}"
                )
            confidence = child["similarity_score"]
            confidence = 1.0 if confidence is None else float(confidence)
            confidence = min(1.0, max(0.0, confidence))
            matched_at = _effective_time(child)
            bind.execute(
                members.insert().values(
                    event_group_id=group_id,
                    content_id=child_id,
                    relation_type="duplicate",
                    confidence=confidence,
                    match_method="legacy-migration",
                    detector_version="duplicate_of:v1",
                    reason="migrated from retired duplicate projection",
                    review_status="confirmed",
                    matched_at=matched_at,
                )
            )
            member_rows[child_id] = {
                "event_group_id": group_id,
                "content_id": child_id,
                "review_status": "confirmed",
            }
            occurrence_times.append(matched_at)

        bind.execute(
            groups.update()
            .where(groups.c.id == group_id)
            .values(
                first_occurrence_at=sa.case(
                    (
                        groups.c.first_occurrence_at > min(occurrence_times),
                        min(occurrence_times),
                    ),
                    else_=groups.c.first_occurrence_at,
                ),
                last_occurrence_at=sa.case(
                    (
                        groups.c.last_occurrence_at < max(occurrence_times),
                        max(occurrence_times),
                    ),
                    else_=groups.c.last_occurrence_at,
                ),
            )
        )

    assigned_ids = set(canonical_groups) | set(member_rows)
    missing = sorted(set(legacy_edges) - assigned_ids)
    if missing:
        raise RuntimeError(
            "legacy duplicate migration left unassigned content: "
            + ", ".join(str(content_id) for content_id in missing[:20])
        )


def _drop_legacy_columns() -> None:
    bind = op.get_bind()
    foreign_keys = sa.inspect(bind).get_foreign_keys("content_items")
    duplicate_fk_names = [
        fk["name"]
        for fk in foreign_keys
        if fk.get("constrained_columns") == ["duplicate_of"] and fk.get("name")
    ]
    with op.batch_alter_table("content_items") as batch_op:
        for constraint_name in duplicate_fk_names:
            batch_op.drop_constraint(constraint_name, type_="foreignkey")
        batch_op.drop_column("similarity_score")
        batch_op.drop_column("duplicate_of")


def upgrade() -> None:
    _backfill_legacy_projection()
    _drop_legacy_columns()


def downgrade() -> None:
    with op.batch_alter_table("content_items") as batch_op:
        batch_op.add_column(
            sa.Column("duplicate_of", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("similarity_score", sa.Float(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_content_items_duplicate_of_content_items",
            "content_items",
            ["duplicate_of"],
            ["id"],
            ondelete="SET NULL",
        )

    bind = op.get_bind()
    content = sa.table(
        "content_items",
        sa.column("id", sa.Integer),
        sa.column("duplicate_of", sa.Integer),
        sa.column("similarity_score", sa.Float),
    )
    groups = sa.table(
        "content_event_groups",
        sa.column("id", sa.Integer),
        sa.column("canonical_content_id", sa.Integer),
        sa.column("status", sa.String),
    )
    members = sa.table(
        "content_event_members",
        sa.column("event_group_id", sa.Integer),
        sa.column("content_id", sa.Integer),
        sa.column("relation_type", sa.String),
        sa.column("confidence", sa.Float),
        sa.column("review_status", sa.String),
    )
    rows = bind.execute(
        sa.select(
            members.c.content_id,
            groups.c.canonical_content_id,
            members.c.confidence,
        )
        .join(groups, groups.c.id == members.c.event_group_id)
        .where(
            groups.c.status == "active",
            members.c.relation_type == "duplicate",
            members.c.review_status.in_(("auto", "confirmed")),
        )
    ).all()
    for content_id, canonical_content_id, confidence in rows:
        bind.execute(
            content.update()
            .where(content.c.id == content_id)
            .values(
                duplicate_of=canonical_content_id,
                similarity_score=confidence,
            )
        )
