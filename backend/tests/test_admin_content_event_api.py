from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import admin_content_events
from app.api.v1.auth import get_current_admin_user
from app.core.database import get_db
from app.services.content_event_service import ContentEventConflictError


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _client(
    *,
    session: _Session | None = None,
    is_admin: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(admin_content_events.router)
    db = session or _Session()
    app.dependency_overrides[get_db] = lambda: db

    def admin_dependency():
        if not is_admin:
            raise HTTPException(status_code=403, detail="Admin privileges required")
        return SimpleNamespace(id=77, role="admin")

    app.dependency_overrides[get_current_admin_user] = admin_dependency
    return TestClient(app)


def _group(**overrides):
    values = {
        "id": 5,
        "version": 3,
        "canonical_content_id": 9,
        "canonical_locked": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_admin_router_has_global_admin_guard():
    response = _client(is_admin=False).get("/admin/content-events/reviews")

    assert response.status_code == 403


def test_normalize_requires_idempotency_key_and_valid_scope():
    client = _client()

    missing_header = client.post(
        "/admin/content-events/normalize",
        json={"mode": "shadow", "scope": "public"},
    )
    invalid_scope = client.post(
        "/admin/content-events/normalize",
        headers={"Idempotency-Key": "job-1"},
        json={"mode": "write", "scope": "user"},
    )
    leaked_owner = client.post(
        "/admin/content-events/normalize",
        headers={"Idempotency-Key": "job-2"},
        json={"mode": "write", "scope": "public", "owner_user_id": 4},
    )

    assert missing_header.status_code == 422
    assert invalid_scope.status_code == 422
    assert leaked_owner.status_code == 422


def test_normalize_returns_202_and_commits(monkeypatch):
    session = _Session()
    calls: list[dict] = []

    async def fake_normalize(db, **kwargs):
        assert db is session
        calls.append(kwargs)
        return {"created_events": 2, "created_members": 4}

    fake_module = ModuleType("app.services.content_event_normalization")
    fake_module.normalize_recent_events_with_lease = fake_normalize
    monkeypatch.setitem(
        sys.modules,
        "app.services.content_event_normalization",
        fake_module,
    )

    response = _client(session=session).post(
        "/admin/content-events/normalize",
        headers={"Idempotency-Key": "run-20260729"},
        json={
            "hours": 48,
            "mode": "write",
            "scope": "user",
            "owner_user_id": 12,
        },
    )

    assert response.status_code == 202
    assert calls == [
        {
            "hours": 48,
            "mode": "write",
            "owner_user_id": 12,
            "idempotency_key": "run-20260729",
        }
    ]
    assert session.commits == 1
    assert response.json()["result"]["created_events"] == 2


def test_normalize_maps_lease_conflict_to_409(monkeypatch):
    async def fake_normalize(db, **kwargs):
        raise ContentEventConflictError("normalization lease is active")

    fake_module = ModuleType("app.services.content_event_normalization")
    fake_module.normalize_recent_events_with_lease = fake_normalize
    monkeypatch.setitem(
        sys.modules,
        "app.services.content_event_normalization",
        fake_module,
    )

    response = _client().post(
        "/admin/content-events/normalize",
        headers={"Idempotency-Key": "same-key"},
        json={"mode": "shadow", "scope": "public"},
    )

    assert response.status_code == 409
    assert "lease" in response.json()["detail"]


def test_review_accept_requires_relation_and_reason():
    client = _client()

    no_relation = client.patch(
        "/admin/content-events/members/4/review",
        json={"decision": "accept", "reason": "same event", "expected_version": 2},
    )
    blank_reason = client.patch(
        "/admin/content-events/members/4/review",
        json={
            "decision": "reject",
            "reason": "  ",
            "expected_version": 2,
        },
    )

    assert no_relation.status_code == 422
    assert blank_reason.status_code == 422


def test_review_calls_service_commits_and_returns_version(monkeypatch):
    session = _Session()
    calls: list[dict] = []

    class FakeService:
        def __init__(self, db):
            assert db is session

        async def review_relation(self, member_id, **kwargs):
            calls.append({"member_id": member_id, **kwargs})
            return _group()

    monkeypatch.setattr(admin_content_events, "ContentEventService", FakeService)
    response = _client(session=session).patch(
        "/admin/content-events/members/4/review",
        json={
            "decision": "accept",
            "relation_type": "corroboration",
            "reason": "independent source confirms the event",
            "expected_version": 2,
        },
    )

    assert response.status_code == 200
    assert calls[0]["reviewer_user_id"] == 77
    assert calls[0]["relation_type"] == "corroboration"
    assert session.commits == 1
    assert response.json() == {
        "event_id": 5,
        "version": 3,
        "canonical_content_id": 9,
        "canonical_locked": True,
    }


def test_canonical_change_and_unlock_are_optimistic_and_committed(monkeypatch):
    session = _Session()
    calls: list[tuple[str, dict]] = []

    class FakeService:
        def __init__(self, db):
            assert db is session

        async def set_canonical(self, event_id, canonical_content_id, **kwargs):
            calls.append(
                (
                    "set",
                    {
                        "event_id": event_id,
                        "canonical_content_id": canonical_content_id,
                        **kwargs,
                    },
                )
            )
            return _group(version=4, canonical_content_id=10)

        async def unlock_canonical(self, event_id, **kwargs):
            calls.append(("unlock", {"event_id": event_id, **kwargs}))
            return _group(version=5, canonical_content_id=7, canonical_locked=False)

    monkeypatch.setattr(admin_content_events, "ContentEventService", FakeService)
    client = _client(session=session)

    selected = client.put(
        "/admin/content-events/5/canonical",
        json={
            "canonical_content_id": 10,
            "former_canonical_relation_type": "duplicate",
            "reason": "editor verified chronology",
            "expected_version": 3,
        },
    )
    unlocked = client.post(
        "/admin/content-events/5/unlock-canonical",
        json={"expected_version": 4},
    )

    assert selected.status_code == 200
    assert unlocked.status_code == 200
    assert calls[0][1]["expected_version"] == 3
    assert calls[0][1]["actor_user_id"] == 77
    assert calls[1][1] == {
        "event_id": 5,
        "reason": "manual unlock",
        "expected_version": 4,
    }
    assert session.commits == 2


def test_review_list_response_contract_strips_unknown_fields(monkeypatch):
    timestamp = datetime(2026, 7, 29, tzinfo=UTC)

    class FakeService:
        def __init__(self, db):
            pass

        async def list_reviews(self, **kwargs):
            assert kwargs == {
                "page": 2,
                "page_size": 10,
                "review_status": "pending",
            }
            return {
                "items": [
                    {
                        "id": 3,
                        "event_id": 5,
                        "event_version": 2,
                        "content_id": 9,
                        "title": "候选消息",
                        "source_name": "source-a",
                        "relation_type": "duplicate",
                        "confidence": 0.7,
                        "review_status": "pending",
                        "reason": "semantic match",
                        "matched_at": timestamp,
                        "owner_user_id": 55,
                    }
                ],
                "total": 11,
                "page": 2,
                "page_size": 10,
            }

    monkeypatch.setattr(admin_content_events, "ContentEventService", FakeService)
    response = _client().get("/admin/content-events/reviews?page=2&page_size=10")

    assert response.status_code == 200
    assert response.json()["total"] == 11
    assert "owner_user_id" not in response.json()["items"][0]
