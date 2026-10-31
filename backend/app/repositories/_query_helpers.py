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

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func, or_
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


# ── 用户静音规则排除（#171） ─────────────────────────────────────


def _escape_like_literal(value: str) -> str:
    """转义 LIKE/ILIKE 通配符，让用户关键词按字面子串匹配。

    与 Python 侧 ``row_is_muted`` 的 lower 子串判断保持同一语义：
    关键词里的 % 或 _ 不应被当成通配符。
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def url_host_expression(model: Any):
    """SQL 侧的 url host 归一表达式（小写、去路径/查询/端口、去 www.）。

    前提：url 必须带协议（含 ``://``）。无协议的 url 经 split_part 取不到
    第二段、求值为空串，永不命中任何 domain 规则；Python 侧
    ``mute_rule_service.url_host_normalized`` 按同一前提对齐（无协议同样
    返回空串、不参与匹配），两侧不留隐性分叉。
    """
    host = func.split_part(func.split_part(func.lower(model.url), "://", 2), "/", 1)
    host = func.split_part(host, "?", 1)
    host = func.split_part(host, "#", 1)
    host = func.split_part(host, ":", 1)
    return func.regexp_replace(host, "^www\\.", "")


def apply_mute_rule_exclusions(
    stmt: Select,
    model: Any,
    *,
    exclude_keywords: Sequence[str] | None = None,
    exclude_source_ids: set[int] | None = None,
    exclude_domains: set[str] | None = None,
) -> Select:
    """Apply per-user mute-rule exclusions (keyword / source / domain).

    只排除可见项，不删除数据；与 ``exclude_ids``（ignored_items）叠加生效：

    - ``exclude_keywords``  → title/summary ILIKE %v%（多关键词任一命中即排除）
    - ``exclude_source_ids`` → source_id 精确等值集合
    - ``exclude_domains``   → url host 归一（去 www.）后等值集合

    三值逻辑注意（NULL 行不得被误杀）：

    - title/summary 可为 NULL：``NOT (title ILIKE p OR summary ILIKE p)`` 在
      summary 为 NULL 时求值为 NULL、整行被丢弃，因此每列都用
      ``col IS NULL OR col NOT ILIKE p`` 的 NULL 安全非命中式，按列 AND。
    - source_id 可为 NULL（sources 删除走 SET NULL）：``NULL NOT IN (...)``
      同样求值为 NULL，需 ``source_id IS NULL OR source_id NOT IN (...)``。
    """
    if exclude_keywords:
        for keyword in exclude_keywords:
            pattern = f"%{_escape_like_literal(keyword)}%"
            stmt = stmt.where(
                or_(model.title.is_(None), model.title.notilike(pattern, escape="\\")),
                or_(model.summary.is_(None), model.summary.notilike(pattern, escape="\\")),
            )
    if exclude_source_ids:
        stmt = stmt.where(or_(model.source_id.is_(None), model.source_id.notin_(exclude_source_ids)))
    if exclude_domains:
        stmt = stmt.where(url_host_expression(model).notin_(exclude_domains))
    return stmt
