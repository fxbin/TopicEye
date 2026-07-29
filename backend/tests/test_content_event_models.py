from sqlalchemy import CheckConstraint, UniqueConstraint

from app.core.database import Base
from app.models.content_event import (
    ContentEventGroup,
    ContentEventMember,
    EventRelationType,
    EventReviewStatus,
    EventStatus,
)


def _constraint_names(model, constraint_type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, constraint_type) and constraint.name
    }


def test_content_event_tables_are_registered_in_metadata():
    assert Base.metadata.tables["content_event_groups"] is ContentEventGroup.__table__
    assert Base.metadata.tables["content_event_members"] is ContentEventMember.__table__


def test_content_event_enum_values_are_stable():
    assert {status.value for status in EventStatus} == {
        "shadow",
        "active",
        "archived",
    }
    assert {relation.value for relation in EventRelationType} == {
        "duplicate",
        "corroboration",
        "update",
    }
    assert {status.value for status in EventReviewStatus} == {
        "pending",
        "auto",
        "confirmed",
        "rejected",
    }


def test_content_event_group_constraints_and_indexes_are_declared():
    assert _constraint_names(ContentEventGroup, UniqueConstraint) == {
        "uq_content_event_groups_canonical_content",
    }
    assert _constraint_names(ContentEventGroup, CheckConstraint) == {
        "ck_content_event_groups_canonical_policy",
        "ck_content_event_groups_occurrence_order",
        "ck_content_event_groups_status",
        "ck_content_event_groups_version",
    }
    assert {index.name for index in ContentEventGroup.__table__.indexes} == {
        "ix_content_event_groups_owner_last",
        "ix_content_event_groups_locked",
    }


def test_content_event_member_constraints_and_indexes_are_declared():
    assert _constraint_names(ContentEventMember, UniqueConstraint) == {
        "uq_content_event_members_content",
        "uq_content_event_members_group_content",
    }
    assert _constraint_names(ContentEventMember, CheckConstraint) == {
        "ck_content_event_members_relation_type",
        "ck_content_event_members_confidence",
        "ck_content_event_members_review_status",
    }
    assert {index.name for index in ContentEventMember.__table__.indexes} == {
        "ix_content_event_members_group_relation_matched",
    }


def test_content_event_defaults_are_explicit():
    group_columns = ContentEventGroup.__table__.c
    member_columns = ContentEventMember.__table__.c

    assert group_columns.canonical_policy.default.arg == "earliest"
    assert group_columns.canonical_locked.default.arg is False
    assert group_columns.status.default.arg is EventStatus.ACTIVE
    assert group_columns.version.default.arg == 1
    assert member_columns.relation_type.default.arg is EventRelationType.DUPLICATE
    assert member_columns.review_status.default.arg is EventReviewStatus.PENDING


def test_content_event_enum_storage_lengths_match_values():
    group_columns = ContentEventGroup.__table__.c
    member_columns = ContentEventMember.__table__.c

    assert group_columns.status.type.length == 8
    assert member_columns.relation_type.type.length == 13
    assert member_columns.review_status.type.length == 9


def test_content_event_foreign_key_delete_policies_are_explicit():
    group_columns = ContentEventGroup.__table__.c
    member_columns = ContentEventMember.__table__.c

    assert next(iter(group_columns.owner_user_id.foreign_keys)).ondelete == "CASCADE"
    assert next(iter(group_columns.canonical_content_id.foreign_keys)).ondelete == "RESTRICT"
    assert (
        next(iter(group_columns.canonical_locked_by_user_id.foreign_keys)).ondelete
        == "SET NULL"
    )
    assert next(iter(member_columns.event_group_id.foreign_keys)).ondelete == "CASCADE"
    assert next(iter(member_columns.content_id.foreign_keys)).ondelete == "CASCADE"
