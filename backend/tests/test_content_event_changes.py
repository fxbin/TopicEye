"""Change comparison contract tests; model calls are mocked, PG is disposable via runner."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import content_events
from app.api.v1.auth import get_current_user
from app.core.database import async_session, get_db
from app.models.content import ContentItem
from app.models.content_event import ContentEventGroup, ContentEventMember
from app.services import content_event_changes as changes
from app.services.content_event_service import ContentEventConflictError, ContentEventNotFoundError

ANCHOR = "官方宣布工具支持离线运行，尚未提供性能测试。"
TARGET = "作者在四个固定任务中实测离线运行，列出了硬件和失败案例。"


async def seed(db, *, target_body=TARGET, target_owner=None, review="confirmed"):
    now = datetime.now(UTC)
    a = ContentItem(id=1, title="工具宣布离线运行", url="https://example.test/1", raw_content=ANCHOR)
    b = ContentItem(
        id=2, title="离线实测记录", url="https://example.test/2", raw_content=target_body, owner_user_id=target_owner
    )
    db.add_all([a, b])
    await db.flush()
    group = ContentEventGroup(
        id=11, canonical_content_id=1, first_occurrence_at=now, last_occurrence_at=now, status="active", version=3
    )
    db.add(group)
    await db.flush()
    member = ContentEventMember(
        event_group_id=11,
        content_id=2,
        relation_type="corroboration",
        confidence=0.9,
        match_method="manual",
        review_status=review,
        reason="INTERNAL_SECRET",
        matched_at=now,
    )
    db.add(member)
    await db.commit()
    return group, member


def result(**overrides):
    row = {
        "content_id": 2,
        "change_type": "evidence",
        "description": "新增了固定任务与硬件条件下的实测记录，尚不能据此判断所有场景性能。",
        "quotes": [{"content_id": 1, "excerpt": ANCHOR}, {"content_id": 2, "excerpt": TARGET}],
    }
    row.update(overrides)
    return {"items": [row]}


async def run(db):
    return await changes.analyze_event_changes(
        db, 1, visible_user_id=7, expected_event_id=11, expected_version=3, member_ids=[2]
    )


@pytest.mark.asyncio
async def test_event_changes_exact_citations_server_identity_and_read_only(monkeypatch):
    calls = []

    async def llm(messages, **kwargs):
        calls.append((messages, kwargs))
        return result(url="https://evil.test", title="spoof", reason="secret")

    monkeypatch.setattr(changes, "call_llm_json", llm)
    async with async_session() as db:
        group, member = await seed(db)
        answer = await run(db)
        assert answer["status"] == "ok" and answer["anchor"]["id"] == 1
        row = answer["items"][0]
        assert row["title"] == "离线实测记录" and row["url"] == "https://example.test/2"
        assert "reason" not in row and "confidence" not in row
        assert {r["id"] for r in row["quotes"]} == {1, 2}
        assert group.version == 3 and member.review_status == "confirmed" and member.reason == "INTERNAL_SECRET"
    assert len(calls) == 1 and calls[0][1]["scene"] == "event_changes"
    assert "INTERNAL_SECRET" not in str(calls[0][0])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"quotes": [{"content_id": 1, "excerpt": ANCHOR}, {"content_id": 2, "excerpt": "捏造的测试结果与新事实"}]},
        {"quotes": [{"content_id": 1, "excerpt": ANCHOR}, {"content_id": 99, "excerpt": TARGET}]},
        {"quotes": [{"content_id": 1, "excerpt": ANCHOR}, {"content_id": 1, "excerpt": ANCHOR}]},
        {"quotes": [{"content_id": True, "excerpt": ANCHOR}, {"content_id": 2, "excerpt": TARGET}]},
        {"change_type": "unsupported"},
        {"change_type": []},
        {"change_type": {}},
        {"description": ["invalid"]},
    ],
)
async def test_event_changes_invalid_evidence_is_uncertain_not_verified(monkeypatch, bad):
    async def llm(*args, **kwargs):
        return result(**bad)

    monkeypatch.setattr(changes, "call_llm_json", llm)
    async with async_session() as db:
        await seed(db)
        answer = await run(db)
        assert answer["status"] == "partial" and answer["items"][0]["change_type"] == "uncertain"
        assert answer["items"][0]["quotes"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{}, {"items": []}, {"items": [{"content_id": 99}]}, {"items": [{"content_id": True}]}])
async def test_event_changes_unparseable_result_fails_explicitly(monkeypatch, bad):
    async def llm(*args, **kwargs):
        return bad

    monkeypatch.setattr(changes, "call_llm_json", llm)
    async with async_session() as db:
        await seed(db)
        with pytest.raises(changes.EventChangeAnalysisError):
            await run(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["anchor", "target"])
async def test_event_changes_missing_body_never_calls_model(monkeypatch, where):
    async def forbidden(*args, **kwargs):
        raise AssertionError("No material: must not pay for a model call")

    monkeypatch.setattr(changes, "call_llm_json", forbidden)
    async with async_session() as db:
        await seed(db, target_body="" if where == "target" else TARGET)
        if where == "anchor":
            a = await db.get(ContentItem, 1)
            a.raw_content = ""
            await db.commit()
        answer = await run(db)
        assert answer["status"] == "insufficient_material" and answer["items"][0]["quotes"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["private_anchor", "private_member", "pending", "wrong_version", "wrong_event"])
async def test_event_changes_permission_and_snapshot_checked_before_model(monkeypatch, case):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Invalid scope reached model")

    monkeypatch.setattr(changes, "call_llm_json", forbidden)
    async with async_session() as db:
        group, _ = await seed(
            db,
            target_owner=99 if case == "private_member" else None,
            review="pending" if case == "pending" else "confirmed",
        )
        if case == "private_anchor":
            a = await db.get(ContentItem, 1)
            a.owner_user_id = 99
            await db.commit()
        if case == "wrong_version":
            group.version = 4
            await db.commit()
        if case == "wrong_event":
            group.status = "archived"
            await db.commit()
        with pytest.raises(ContentEventNotFoundError if case == "private_anchor" else ContentEventConflictError):
            await run(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version", "member", "body", "visibility", "canonical"])
async def test_event_changes_rejects_changes_during_model_wait(monkeypatch, change):
    async with async_session() as db:
        group, member = await seed(db)

        async def llm(*args, **kwargs):
            if change == "version":
                group.version = 4
            elif change == "member":
                member.review_status = "rejected"
            elif change == "visibility":
                b = await db.get(ContentItem, 2)
                b.owner_user_id = 99
            elif change == "canonical":
                group.canonical_content_id = 2
            else:
                b = await db.get(ContentItem, 2)
                b.raw_content = "正文已更新，旧引用不能继续用。"
            await db.commit()
            return result()

        monkeypatch.setattr(changes, "call_llm_json", llm)
        with pytest.raises(ContentEventConflictError):
            await run(db)


def client(monkeypatch, service=None, authenticated=True):
    app = FastAPI()
    app.include_router(content_events.router, prefix="/api/v1")

    async def user():
        return SimpleNamespace(id=7)

    async def session():
        yield SimpleNamespace()

    if authenticated:
        app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_db] = session
    if service:
        monkeypatch.setattr(content_events, "analyze_event_changes", service)
    return TestClient(app)


@pytest.mark.parametrize("member_ids", [[2, 2], [True], ["2"], [], list(range(2, 13)), [1]])
def test_event_changes_request_validates_identity(monkeypatch, member_ids):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Invalid request reached service")

    with client(monkeypatch, forbidden) as c:
        response = c.post(
            "/api/v1/contents/1/event/changes",
            json={"expected_event_id": 11, "expected_version": 3, "member_ids": member_ids},
        )
        assert response.status_code == 422


@pytest.mark.parametrize(
    "exc,code",
    [
        (ContentEventNotFoundError("hidden"), 404),
        (ContentEventConflictError("changed"), 409),
        (changes.EventChangeAnalysisError("bad"), 502),
        (RuntimeError("unavailable"), 502),
    ],
)
def test_event_changes_api_errors_are_explicit(monkeypatch, exc, code):
    async def service(*args, **kwargs):
        raise exc

    with client(monkeypatch, service) as c:
        r = c.post(
            "/api/v1/contents/1/event/changes", json={"expected_event_id": 11, "expected_version": 3, "member_ids": [2]}
        )
        assert r.status_code == code
        assert "hidden" not in r.text and "unavailable" not in r.text


def test_event_changes_requires_login(monkeypatch):
    with client(monkeypatch, authenticated=False) as c:
        r = c.post(
            "/api/v1/contents/1/event/changes", json={"expected_event_id": 11, "expected_version": 3, "member_ids": [2]}
        )
        assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_event_changes_preserves_original_whitespace_for_quotes(monkeypatch):
    raw = "前面的原文。\n\n\n后面的原文，保留   连续空格。"

    async def llm(messages, **kwargs):
        assert "\\n\\n\\n" in messages[1]["content"]
        return result(quotes=[{"content_id": 1, "excerpt": ANCHOR}, {"content_id": 2, "excerpt": raw}])

    monkeypatch.setattr(changes, "call_llm_json", llm)
    async with async_session() as db:
        await seed(db, target_body=raw)
        answer = await run(db)
        assert answer["items"][0]["quotes"][1]["excerpt"] == raw


@pytest.mark.asyncio
async def test_event_changes_rejects_normalized_nonverbatim_quote(monkeypatch):
    raw = "前面的原文。\n\n\n后面的原文。"

    async def llm(*args, **kwargs):
        return result(
            quotes=[{"content_id": 1, "excerpt": ANCHOR}, {"content_id": 2, "excerpt": raw.replace("\n\n\n", "\n\n")}]
        )

    monkeypatch.setattr(changes, "call_llm_json", llm)
    async with async_session() as db:
        await seed(db, target_body=raw)
        answer = await run(db)
        assert answer["status"] == "partial" and answer["items"][0]["quotes"] == []


@pytest.mark.asyncio
async def test_event_relation_feedback_belongs_to_user_and_readback_keeps_context():
    from app.models.user import User
    from app.repositories.product_feedback_repo import IssueFeedbackRepository

    async with async_session() as db:
        group, member = await seed(db)
        db.add(User(id=7, email="event-feedback@example.test"))
        await db.commit()
        issue = await changes.report_event_relation(
            db,
            1,
            user_id=7,
            expected_event_id=11,
            expected_version=3,
            member_id=2,
            reason="这个实测针对另一个版本，可能关联有误。",
        )
        iid = issue.id
        assert issue.user_id == 7 and "\n问题说明：" in issue.description
        assert "\\n" not in issue.description and "INTERNAL_SECRET" not in issue.description
        assert group.version == 3 and member.review_status == "confirmed"
        await db.commit()
    async with async_session() as db:
        own = await IssueFeedbackRepository(db).list_user_issues(user_id=7, status=None, limit=20, offset=0)
        other = await IssueFeedbackRepository(db).list_user_issues(user_id=99, status=None, limit=20, offset=0)
        assert [x.id for x in own] == [iid] and other == []


@pytest.mark.asyncio
async def test_event_relation_feedback_rejects_hidden_or_changed_scope_without_writing():
    from sqlalchemy import func, select

    from app.models.product_feedback import IssueFeedback

    async with async_session() as db:
        await seed(db, target_owner=99)
        with pytest.raises(ContentEventConflictError):
            await changes.report_event_relation(
                db,
                1,
                user_id=7,
                expected_event_id=11,
                expected_version=3,
                member_id=2,
                reason="这条报道关联到了错误的事件。",
            )
        assert await db.scalar(select(func.count()).select_from(IssueFeedback)) == 0


@pytest.mark.asyncio
async def test_event_relation_feedback_expired_token_never_creates_anonymous_record(monkeypatch):
    from unittest.mock import AsyncMock

    from sqlalchemy import func, select

    from app.api.v1 import auth
    from app.models.product_feedback import IssueFeedback

    monkeypatch.setattr(auth, "get_user_for_token", AsyncMock(return_value=None))
    with client(monkeypatch, authenticated=False) as c:
        r = c.post(
            "/api/v1/contents/1/event/feedback",
            headers={"Authorization": "Bearer expired-session"},
            json={
                "expected_event_id": 11,
                "expected_version": 3,
                "member_id": 2,
                "reason": "这条报道关联到了错误的事件。",
            },
        )
        assert r.status_code == 401
    async with async_session() as db:
        assert await db.scalar(select(func.count()).select_from(IssueFeedback)) == 0
