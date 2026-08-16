from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import content_events
from app.api.v1.auth import get_optional_current_user
from app.core.database import get_db
from app.services.content_event_service import ContentEventNotFoundError


class _Session:
    pass


def _event_payload() -> dict:
    timestamp = datetime(2026, 7, 29, tzinfo=UTC)
    return {
        "id": 11,
        "canonical_id": 7,
        "owner_user_id": 99,
        "status": "active",
        "version": 3,
        "canonical_locked": False,
        "canonical_reason": "internal reason",
        "reviewer_user_id": 88,
        "canonical": {
            "id": 7,
            "title": "最早消息",
            "url": "https://example.test/7",
            "source_name": "source-a",
            "source_type": "rss",
            "platform": "web",
            "published_at": timestamp,
            "crawled_at": timestamp,
        },
        "member_count": 1,
        "source_count": 2,
        "has_more": False,
        "members": [
            {
                "id": 101,
                "content_id": 8,
                "title": "同一事件的后续消息",
                "url": "https://example.test/8",
                "source_name": "source-b",
                "source_type": "rss",
                "platform": "web",
                "published_at": timestamp,
                "crawled_at": timestamp,
                "relation_type": "update",
                "confidence": 0.93,
                "review_status": "confirmed",
                "reviewer_user_id": 88,
                "reason": "internal classifier reason",
            }
        ],
    }


def _client(*, user_id: int | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(content_events.router)
    app.dependency_overrides[get_db] = lambda: _Session()
    app.dependency_overrides[get_optional_current_user] = lambda: (
        SimpleNamespace(id=user_id) if user_id is not None else None
    )
    return TestClient(app)


def test_get_content_event_returns_additive_public_contract(monkeypatch):
    calls: list[dict] = []

    class FakeService:
        def __init__(self, db):
            assert isinstance(db, _Session)

        async def get_event_detail(self, content_id, **kwargs):
            calls.append({"content_id": content_id, **kwargs})
            return _event_payload()

    monkeypatch.setattr(content_events, "ContentEventService", FakeService)
    response = _client(user_id=42).get("/contents/7/event?member_limit=5&member_offset=1")

    assert response.status_code == 200
    assert calls == [
        {
            "content_id": 7,
            "visible_user_id": 42,
            "member_limit": 5,
            "member_offset": 1,
        }
    ]
    body = response.json()
    assert body["content_id"] == 7
    assert body["event"]["canonical_id"] == 7
    assert body["event"]["members"][0]["relation_type"] == "update"
    serialized = str(body)
    assert "owner_user_id" not in serialized
    assert "reviewer_user_id" not in serialized
    assert "canonical_reason" not in serialized
    assert "internal classifier reason" not in serialized
    assert "review_status" not in serialized


def test_get_content_event_returns_null_when_content_has_no_event(monkeypatch):
    class FakeService:
        def __init__(self, db):
            pass

        async def get_event_detail(self, content_id, **kwargs):
            return None

    monkeypatch.setattr(content_events, "ContentEventService", FakeService)

    response = _client().get("/contents/7/event")

    assert response.status_code == 200
    assert response.json() == {"content_id": 7, "event": None}


def test_get_content_event_masks_missing_and_invisible_content(monkeypatch):
    class FakeService:
        def __init__(self, db):
            pass

        async def get_event_detail(self, content_id, **kwargs):
            raise ContentEventNotFoundError("private content")

    monkeypatch.setattr(content_events, "ContentEventService", FakeService)

    response = _client().get("/contents/404/event")

    assert response.status_code == 404
    assert response.json() == {"detail": "Content not found"}


def test_content_event_openapi_exposes_explicit_nullable_event_response():
    app = FastAPI()
    app.include_router(content_events.router)

    operation = app.openapi()["paths"]["/contents/{content_id}/event"]["get"]

    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("/ContentEventLookupResponse")
    lookup_schema = app.openapi()["components"]["schemas"]["ContentEventLookupResponse"]
    assert "event" in lookup_schema["properties"]
