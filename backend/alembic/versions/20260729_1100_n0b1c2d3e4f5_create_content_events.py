"""create canonical content event tables

Revision ID: n0b1c2d3e4f5
Revises: m9a0b1c2d3e4
Create Date: 2026-07-29 11:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "n0b1c2d3e4f5"
down_revision = "m9a0b1c2d3e4"
branch_labels = None
depends_on = None


def _create_canonical_member_guards() -> None:
    """Keep each content identity in either the canonical or member role."""
    dialect_name = op.get_bind().dialect.name

    if dialect_name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_content_event_member_not_canonical_insert
            BEFORE INSERT ON content_event_members
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1
                FROM content_event_groups
                WHERE canonical_content_id = NEW.content_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'canonical content cannot also be an event member'
                );
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_content_event_member_not_canonical_update
            BEFORE UPDATE OF event_group_id, content_id ON content_event_members
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1
                FROM content_event_groups
                WHERE canonical_content_id = NEW.content_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'canonical content cannot also be an event member'
                );
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_content_event_canonical_not_member_insert
            BEFORE INSERT ON content_event_groups
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1
                FROM content_event_members
                WHERE content_id = NEW.canonical_content_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'event member cannot become canonical before member removal'
                );
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_content_event_canonical_not_member_update
            BEFORE UPDATE OF canonical_content_id ON content_event_groups
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1
                FROM content_event_members
                WHERE content_id = NEW.canonical_content_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'event member cannot become canonical before member removal'
                );
            END
            """
        )
        return

    if dialect_name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION enforce_content_event_canonical_member_disjoint()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                current_canonical_content_id integer;
            BEGIN
                IF TG_TABLE_NAME = 'content_event_groups' THEN
                    PERFORM 1
                    FROM content_items
                    WHERE id = NEW.canonical_content_id
                    FOR UPDATE;
                    IF EXISTS (
                        SELECT 1
                        FROM content_event_members
                        WHERE content_id = NEW.canonical_content_id
                    ) THEN
                        RAISE EXCEPTION
                            'event member cannot become canonical before member removal'
                            USING ERRCODE = '23514';
                    END IF;
                ELSE
                    PERFORM 1
                    FROM content_items
                    WHERE id = NEW.content_id
                    FOR UPDATE;
                    SELECT canonical_content_id
                    INTO current_canonical_content_id
                    FROM content_event_groups
                    WHERE canonical_content_id = NEW.content_id;
                    IF current_canonical_content_id = NEW.content_id THEN
                        RAISE EXCEPTION
                            'canonical content cannot also be an event member'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_content_event_member_not_canonical
            BEFORE INSERT OR UPDATE OF event_group_id, content_id
            ON content_event_members
            FOR EACH ROW
            EXECUTE FUNCTION enforce_content_event_canonical_member_disjoint()
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_content_event_canonical_not_member
            BEFORE INSERT OR UPDATE OF canonical_content_id
            ON content_event_groups
            FOR EACH ROW
            EXECUTE FUNCTION enforce_content_event_canonical_member_disjoint()
            """
        )


def _drop_canonical_member_guards() -> None:
    dialect_name = op.get_bind().dialect.name

    if dialect_name == "sqlite":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_content_event_canonical_not_member_update"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_content_event_canonical_not_member_insert"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_content_event_member_not_canonical_update"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_content_event_member_not_canonical_insert"
        )
        return

    if dialect_name == "postgresql":
        op.execute(
            """
            DROP TRIGGER IF EXISTS trg_content_event_canonical_not_member
            ON content_event_groups
            """
        )
        op.execute(
            """
            DROP TRIGGER IF EXISTS trg_content_event_member_not_canonical
            ON content_event_members
            """
        )
        op.execute(
            """
            DROP FUNCTION IF EXISTS
            enforce_content_event_canonical_member_disjoint()
            """
        )


def upgrade() -> None:
    op.create_table(
        "content_event_groups",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "owner_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "canonical_content_id",
            sa.Integer,
            sa.ForeignKey("content_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "canonical_policy",
            sa.String(30),
            nullable=False,
            server_default="earliest",
        ),
        sa.Column("canonical_reason", sa.Text, nullable=True),
        sa.Column(
            "canonical_locked",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "canonical_locked_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "canonical_locked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "first_occurrence_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_occurrence_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(8),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "version",
            sa.Integer,
            nullable=False,
            server_default="1",
        ),
        sa.Column("classifier_version", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "canonical_content_id",
            name="uq_content_event_groups_canonical_content",
        ),
        sa.CheckConstraint(
            "first_occurrence_at <= last_occurrence_at",
            name="ck_content_event_groups_occurrence_order",
        ),
        sa.CheckConstraint(
            "canonical_policy IN ('earliest', 'manual')",
            name="ck_content_event_groups_canonical_policy",
        ),
        sa.CheckConstraint(
            "status IN ('shadow', 'active', 'archived')",
            name="ck_content_event_groups_status",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_content_event_groups_version",
        ),
    )
    op.create_index(
        "ix_content_event_groups_owner_last",
        "content_event_groups",
        ["owner_user_id", sa.text("last_occurrence_at DESC")],
    )
    op.create_index(
        "ix_content_event_groups_locked",
        "content_event_groups",
        ["canonical_locked"],
    )

    op.create_table(
        "content_event_members",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "event_group_id",
            sa.Integer,
            sa.ForeignKey("content_event_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_id",
            sa.Integer,
            sa.ForeignKey("content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "relation_type",
            sa.String(13),
            nullable=False,
            server_default="duplicate",
        ),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("match_method", sa.String(50), nullable=False),
        sa.Column("detector_version", sa.String(100), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "review_status",
            sa.String(9),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "matched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "content_id",
            name="uq_content_event_members_content",
        ),
        sa.UniqueConstraint(
            "event_group_id",
            "content_id",
            name="uq_content_event_members_group_content",
        ),
        sa.CheckConstraint(
            "relation_type IN ('duplicate', 'corroboration', 'update')",
            name="ck_content_event_members_relation_type",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_content_event_members_confidence",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'auto', 'confirmed', 'rejected')",
            name="ck_content_event_members_review_status",
        ),
    )
    op.create_index(
        "ix_content_event_members_group_relation_matched",
        "content_event_members",
        ["event_group_id", "relation_type", "matched_at"],
    )
    _create_canonical_member_guards()


def downgrade() -> None:
    _drop_canonical_member_guards()
    op.drop_index(
        "ix_content_event_members_group_relation_matched",
        table_name="content_event_members",
    )
    op.drop_table("content_event_members")
    op.drop_index(
        "ix_content_event_groups_locked",
        table_name="content_event_groups",
    )
    op.drop_index(
        "ix_content_event_groups_owner_last",
        table_name="content_event_groups",
    )
    op.drop_table("content_event_groups")
