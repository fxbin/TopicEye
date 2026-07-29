"""enforce one public evidence mark per content

Revision ID: p2d3e4f5g6h7
Revises: o1c2d3e4f5g6
Create Date: 2026-07-29 13:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "p2d3e4f5g6h7"
down_revision = "o1c2d3e4f5g6"
branch_labels = None
depends_on = None

_PUBLIC_INDEX = "uq_evidence_marks_public_content"


def _deduplicate_public_marks() -> None:
    """Keep the latest public mark and re-parent every historical link."""

    bind = op.get_bind()
    marks = sa.table(
        "content_evidence_marks",
        sa.column("id", sa.Integer),
        sa.column("content_id", sa.Integer),
        sa.column("owner_user_id", sa.Integer),
        sa.column("computed_at", sa.DateTime(timezone=True)),
    )
    links = sa.table(
        "content_evidence_links",
        sa.column("mark_id", sa.Integer),
    )
    rows = bind.execute(
        sa.select(
            marks.c.id,
            marks.c.content_id,
        )
        .where(marks.c.owner_user_id.is_(None))
        .order_by(
            marks.c.content_id.asc(),
            marks.c.computed_at.desc(),
            marks.c.id.desc(),
        )
    ).all()

    winners: dict[int, int] = {}
    losers_by_winner: dict[int, list[int]] = {}
    for mark_id, content_id in rows:
        content_key = int(content_id)
        winner_id = winners.setdefault(content_key, int(mark_id))
        if int(mark_id) != winner_id:
            losers_by_winner.setdefault(winner_id, []).append(int(mark_id))

    for winner_id, loser_ids in losers_by_winner.items():
        bind.execute(
            sa.update(links)
            .where(links.c.mark_id.in_(loser_ids))
            .values(mark_id=winner_id)
        )
        bind.execute(sa.delete(marks).where(marks.c.id.in_(loser_ids)))


def upgrade() -> None:
    _deduplicate_public_marks()
    op.create_index(
        _PUBLIC_INDEX,
        "content_evidence_marks",
        ["content_id"],
        unique=True,
        sqlite_where=sa.text("owner_user_id IS NULL"),
        postgresql_where=sa.text("owner_user_id IS NULL"),
    )


def downgrade() -> None:
    # Deduplicated rows cannot be recreated safely. Downgrade only removes the
    # additive guard and leaves the deterministic retained data untouched.
    op.drop_index(_PUBLIC_INDEX, table_name="content_evidence_marks")
