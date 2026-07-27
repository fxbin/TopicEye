"""Shared query-builder helpers for repositories.

These functions encapsulate repeated WHERE-clause patterns so that
individual repositories stay thin and behavior stays consistent.

All helpers are **statement transformers**: they accept a SQLAlchemy
``select`` / ``update`` statement and return a new statement with the
relevant filters applied.  Callers that need to keep a count statement
in sync simply call the helper twice (once for the data stmt, once for
the count stmt).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, or_
from sqlalchemy.sql import Select

# ── Filter dict → WHERE clauses ─────────────────────────────────

def apply_filters(
    stmt: Select,
    model: Any,
    filters: dict[str, Any] | None,
) -> Select:
    """Apply exact-match or ilike filters from a ``{field: value}`` dict.

    Behaviour (must stay identical to the inline loops it replaces):

    - ``value is None`` → skip
    - ``field`` not on model → skip
    - ``str`` value containing ``%`` or ``_`` → ``col.ilike(value)``
    - everything else → ``col == value``
    """
    if not filters:
        return stmt
    for field, value in filters.items():
        if value is None:
            continue
        col = getattr(model, field, None)
        if col is None:
            continue
        if isinstance(value, str) and ("%" in value or "_" in value):
            stmt = stmt.where(col.ilike(value))
        else:
            stmt = stmt.where(col == value)
    return stmt


# ── Visibility scope ────────────────────────────────────────────

def apply_visibility(
    stmt: Select,
    model: Any,
    *,
    visible_user_id: int | None = None,
    public_only: bool = False,
) -> Select:
    """Apply ADR 0001 content visibility filter.

    - ``public_only=True``    → ``owner_user_id IS NULL``
    - ``visible_user_id`` set → ``OR(owner_user_id IS NULL, owner_user_id == visible_user_id)``
    - neither set             → no filter (internal / batch callers)
    """
    if public_only:
        return stmt.where(model.owner_user_id.is_(None))
    if visible_user_id is not None:
        return stmt.where(
            or_(
                model.owner_user_id.is_(None),
                model.owner_user_id == visible_user_id,
            )
        )
    return stmt


def visibility_clauses(
    model: Any,
    *,
    visible_user_id: int | None = None,
    public_only: bool = False,
) -> list[ColumnElement[bool]]:
    """Return a list of WHERE clause(s) for visibility.

    Convenience for callers that need the raw clauses (e.g. to apply
    the same clause to multiple statements).  Prefer ``apply_visibility``
    when operating on a single statement.
    """
    if public_only:
        return [model.owner_user_id.is_(None)]
    if visible_user_id is not None:
        return [
            or_(
                model.owner_user_id.is_(None),
                model.owner_user_id == visible_user_id,
            )
        ]
    return []


# ── Content scope (exclude / time) ──────────────────────────────

def apply_content_scope(
    stmt: Select,
    model: Any,
    *,
    exclude_ids: set | None = None,
    exclude_source_types: set[str] | None = None,
    time_cutoff: datetime | None = None,
) -> Select:
    """Apply content-scoping filters shared across scoring / listing queries.

    - ``exclude_ids``          → ``id NOT IN (exclude_ids)``
    - ``exclude_source_types`` → ``source_type NOT IN (exclude_source_types)``
    - ``time_cutoff``          → ``crawled_at >= time_cutoff``
    """
    if exclude_ids:
        stmt = stmt.where(model.id.notin_(exclude_ids))
    if exclude_source_types:
        stmt = stmt.where(model.source_type.notin_(exclude_source_types))
    if time_cutoff:
        stmt = stmt.where(model.crawled_at >= time_cutoff)
    return stmt
