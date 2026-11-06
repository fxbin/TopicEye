"""Bounded, read-only change comparisons with exact citations and fresh event identity."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.content_event_change_repo import ContentEventChangeRepository
from app.services.content_event_service import ContentEventConflictError, ContentEventNotFoundError
from app.services.llm import call_llm_json
from app.services.llm.prompts.event_changes import SYSTEM_PROMPT, USER_TEMPLATE
from app.utils.prompt_safety import sanitize_prompt_input

logger = logging.getLogger(__name__)
MAX_TARGETS = 10
TEXT_LIMIT = 1400
CHANGE_TYPES = {"no_new_material", "fact", "evidence", "opinion", "uncertain"}


class EventChangeAnalysisError(Exception):
    pass


@dataclass(frozen=True)
class _Snapshot:
    event_id: int
    version: int
    canonical_id: int
    anchor: dict
    targets: tuple[dict, ...]


def _material(row: dict) -> dict:
    title = sanitize_prompt_input(row["title"][:300], max_chars=300, escape_braces=False)
    # JSON encoding handles control/whitespace characters without altering quotations.
    body = (row["raw_content"] or row["summary"] or "")[:TEXT_LIMIT]
    return {
        "id": row["id"],
        "title": title,
        "url": row["url"],
        "source_name": row["source_name"],
        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
        "text": body,
        "has_body": bool(body.strip()),
    }


async def _snapshot(repo, content_id, user_id, event_id, version, ids) -> _Snapshot:
    if not await repo.visible_content(content_id, user_id):
        raise ContentEventNotFoundError("content not found")
    group = await repo.group_state(content_id, user_id)
    if not group or group["event_id"] != event_id or group["version"] != version:
        raise ContentEventConflictError("event changed; reload coverage")
    rows = await repo.materials(group, [content_id, *ids], user_id)
    materials = {row["id"]: _material(row) for row in rows}
    if set(materials) != {content_id, *ids}:
        raise ContentEventConflictError("visible accepted membership changed; reload coverage")
    return _Snapshot(
        group["event_id"],
        group["version"],
        group["canonical_id"],
        materials[content_id],
        tuple(materials[cid] for cid in ids),
    )


def _ref(article: dict) -> dict:
    return {key: article[key] for key in ("id", "title", "url", "source_name", "published_at")}


def _uncertain(article: dict, reason: str) -> dict:
    return {**_ref(article), "change_type": "uncertain", "description": reason, "quotes": []}


def _parse(result, anchor: dict, targets: list[dict]) -> dict[int, dict]:
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        raise EventChangeAnalysisError("missing comparison items")
    expected = {a["id"]: a for a in targets}
    parsed = {}
    repeated = set()
    for row in result["items"]:
        if not isinstance(row, dict):
            continue
        cid = row.get("content_id")
        if type(cid) is not int or cid not in expected:
            continue
        if cid in parsed:
            repeated.add(cid)
            continue
        target = expected[cid]
        fallback = _uncertain(target, "未能从提供的片段核对差异，请查看原文。")
        parsed[cid] = fallback
        kind, desc = row.get("change_type"), row.get("description")
        if kind == "uncertain":
            continue
        if (
            not isinstance(kind, str)
            or kind not in CHANGE_TYPES
            or not isinstance(desc, str)
            or not desc.strip()
            or len(desc) > 300
        ):
            continue
        quotes = row.get("quotes")
        if not isinstance(quotes, list) or len(quotes) != 2:
            continue
        references = []
        for quote in quotes:
            if not isinstance(quote, dict) or type(quote.get("content_id")) is not int:
                break
            source = {anchor["id"]: anchor, cid: target}.get(quote["content_id"])
            excerpt = quote.get("excerpt")
            if (
                source is None
                or not isinstance(excerpt, str)
                or not 4 <= len(excerpt) <= 280
                or excerpt not in source["text"]
            ):
                break
            references.append({**_ref(source), "excerpt": excerpt})
        if len(references) == 2 and {r["id"] for r in references} == {anchor["id"], cid}:
            parsed[cid] = {**_ref(target), "change_type": kind, "description": desc.strip(), "quotes": references}
    if not parsed:
        raise EventChangeAnalysisError("no comparison target could be parsed")
    for cid in repeated:
        parsed[cid] = _uncertain(expected[cid], "返回了冲突的对照结果，请查看原文或重新对照。")
    return parsed


async def analyze_event_changes(
    db: AsyncSession,
    content_id: int,
    *,
    visible_user_id: int,
    expected_event_id: int,
    expected_version: int,
    member_ids: list[int],
) -> dict:
    # Also defend non-HTTP callers; do not rely only on the request schema.
    if not 1 <= len(member_ids) <= MAX_TARGETS or len(set(member_ids)) != len(member_ids) or content_id in member_ids:
        raise ValueError("invalid comparison members")
    repo = ContentEventChangeRepository(db)
    snap = await _snapshot(repo, content_id, visible_user_id, expected_event_id, expected_version, member_ids)
    initial = {
        a["id"]: _uncertain(
            a,
            "正文片段不足，无法核对变化，请查看原文。"
            if not a["has_body"] or not snap.anchor["has_body"]
            else "尚未取得可核对的对照结果，请查看原文或重试。",
        )
        for a in snap.targets
    }
    usable = [a for a in snap.targets if a["has_body"]]
    if snap.anchor["has_body"] and usable:
        # Trusted identity/meta + exact bounded text; no internal relation reasons.
        def prompt_material(a):
            return {k: v for k, v in a.items() if k != "has_body"}

        materials = {"anchor": prompt_material(snap.anchor), "targets": [prompt_material(a) for a in usable]}
        result = await call_llm_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_TEMPLATE.format(materials=json.dumps(materials, ensure_ascii=False))},
            ],
            scene="event_changes",
            temperature=0.1,
            max_tokens=3500,
        )
        initial.update(_parse(result, snap.anchor, usable))
        status = "partial" if any(a["change_type"] == "uncertain" for a in initial.values()) else "ok"
    else:
        status = "insufficient_material"
    # Column projections avoid stale ORM identity-map values after a slow model call.
    current = await _snapshot(repo, content_id, visible_user_id, expected_event_id, expected_version, member_ids)
    if current != snap:
        raise ContentEventConflictError("comparison material changed; reload coverage")
    logger.info(
        "Event changes content=%s event=%s version=%s targets=%s status=%s",
        content_id,
        snap.event_id,
        snap.version,
        len(member_ids),
        status,
    )
    return {
        "status": status,
        "event_id": snap.event_id,
        "version": snap.version,
        "anchor": _ref(snap.anchor),
        "member_ids": member_ids,
        "items": [initial[cid] for cid in member_ids],
    }


async def report_event_relation(
    db: AsyncSession,
    content_id: int,
    *,
    user_id: int,
    expected_event_id: int,
    expected_version: int,
    member_id: int,
    reason: str,
):
    """Authenticated feedback only; never apply a public relationship correction."""
    from app.models.product_feedback import IssueFeedback, IssueFeedbackStatus
    from app.repositories.product_feedback_repo import IssueFeedbackRepository

    if member_id == content_id or not 5 <= len(reason.strip()) <= 1500:
        raise ValueError("invalid relation feedback")
    snap = await _snapshot(
        ContentEventChangeRepository(db), content_id, user_id, expected_event_id, expected_version, [member_id]
    )
    member = snap.targets[0]
    description = (
        f"关联报道：{member['title']}\n问题说明：{reason.strip()}\n\n"
        f"定位信息：事件 {snap.event_id}，版本 {snap.version}；"
        f"当前报道 {content_id}，关联报道 {member_id}。"
    )
    issue = IssueFeedback(
        user_id=user_id,
        title="报道关联有误",
        description=description,
        area="content-events",
        severity="medium",
        status=IssueFeedbackStatus.open,
    )
    IssueFeedbackRepository(db).add_instance(issue)
    await db.flush()
    await db.refresh(issue)
    return issue
