"""Regression tests for OAuth account-linking security.

Run this directory on its own with a dummy DATABASE_URL. It deliberately lives
outside backend/tests because backend/tests/conftest.py clears its test DB.
These service tests use mocks: no DB connections or provider API calls.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://dummy:dummy@localhost:5432/not_used")

from app.services import auth_service as auth  # noqa: E402


def fake_db():
    return SimpleNamespace(
        get=AsyncMock(), add=Mock(), delete=AsyncMock(),
        flush=AsyncMock(), refresh=AsyncMock(),
    )


def fake_user(*, uid=7, email="same@example.com", role="user", active=True):
    return SimpleNamespace(id=uid, email=email, role=role, is_active=active)


def stub_lookups(monkeypatch, *, binding=None, user=None):
    linked = AsyncMock(return_value=binding)
    by_email = AsyncMock(return_value=user)
    create_link = AsyncMock()
    monkeypatch.setattr(auth, "get_oauth_account", linked)
    monkeypatch.setattr(auth, "get_user_by_email", by_email)
    monkeypatch.setattr(auth, "_link_oauth_account", create_link)
    return linked, by_email, create_link


@pytest.mark.asyncio
async def test_verified_regular_user_same_email_still_auto_links(monkeypatch):
    existing = fake_user()
    db = fake_db()
    _, _, link = stub_lookups(monkeypatch, user=existing)
    result = await auth.get_or_create_oauth_user(
        db, provider="github", provider_user_id="github-1",
        email=" SAME@Example.Com ", email_verified=True,
    )
    assert result is existing
    link.assert_awaited_once()
    assert link.await_args.kwargs["user_id"] == existing.id
    assert link.await_args.kwargs["provider_email"] == "same@example.com"
    assert link.await_args.kwargs["email_verified"] is True
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_verified_new_user_created_and_linked(monkeypatch):
    db = fake_db()
    _, _, link = stub_lookups(monkeypatch)
    async def assign_id():
        db.add.call_args.args[0].id = 123
    db.flush.side_effect = assign_id
    user = await auth.get_or_create_oauth_user(
        db, provider="google", provider_user_id="google-1",
        email="NEW@example.com", email_verified=True,
    )
    assert user.id == 123
    assert user.email == "new@example.com"
    assert user.password_hash is None
    link.assert_awaited_once()
    assert link.await_args.kwargs["user_id"] == 123


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,verified", [
    ("google", False),
    ("github", False),
    ("google", None),
])
async def test_unverified_new_identity_denied_without_any_db_write(
    monkeypatch, provider, verified,
):
    db = fake_db()
    linked, by_email, link = stub_lookups(monkeypatch)
    with pytest.raises(auth.OAuthAccountConflictError, match="未经验证"):
        await auth.get_or_create_oauth_user(
            db, provider=provider, provider_user_id="third-party-id",
            email="new@example.com", email_verified=verified,
        )
    linked.assert_not_awaited()
    by_email.assert_not_awaited()
    link.assert_not_awaited()
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_unverified_previously_linked_identity_denied(monkeypatch):
    db = fake_db()
    linked, by_email, link = stub_lookups(
        monkeypatch, binding=SimpleNamespace(user_id=7),
    )
    with pytest.raises(auth.OAuthAccountConflictError, match="未经验证"):
        await auth.get_or_create_oauth_user(
            db, provider="google", provider_user_id="existing-id",
            email="same@example.com", email_verified=False,
        )
    linked.assert_not_awaited()
    by_email.assert_not_awaited()
    link.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [
    fake_user(role="admin"),
    fake_user(active=False),
    fake_user(role="admin", active=False),
])
async def test_verified_email_cannot_auto_link_admin_or_disabled(
    monkeypatch, user,
):
    db = fake_db()
    _, _, link = stub_lookups(monkeypatch, user=user)
    with pytest.raises(auth.OAuthAccountConflictError, match="不支持自动关联"):
        await auth.get_or_create_oauth_user(
            db, provider="google", provider_user_id="new-google-id",
            email=user.email, email_verified=True,
        )
    link.assert_not_awaited()
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_prelinked_identity_logs_in_without_relinking(monkeypatch):
    db = fake_db()
    user = fake_user()
    db.get.return_value = user
    linked, by_email, link = stub_lookups(
        monkeypatch, binding=SimpleNamespace(user_id=user.id),
    )
    result = await auth.get_or_create_oauth_user(
        db, provider="github", provider_user_id="already-linked",
        email="same@example.com", email_verified=True,
    )
    assert result is user
    linked.assert_awaited_once()
    by_email.assert_not_awaited()
    link.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_admin_binding_remains_usable_but_new_one_is_blocked(monkeypatch):
    db = fake_db()
    admin = fake_user(role="admin")
    db.get.return_value = admin
    _, _, link = stub_lookups(
        monkeypatch, binding=SimpleNamespace(user_id=admin.id),
    )
    assert await auth.get_or_create_oauth_user(
        db, provider="github", provider_user_id="prelinked-admin",
        email=admin.email, email_verified=True,
    ) is admin
    link.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_previously_linked_identity_denied(monkeypatch):
    db = fake_db()
    db.get.return_value = fake_user(active=False)
    _, by_email, link = stub_lookups(
        monkeypatch, binding=SimpleNamespace(user_id=7),
    )
    with pytest.raises(auth.OAuthAccountConflictError, match="停用"):
        await auth.get_or_create_oauth_user(
            db, provider="github", provider_user_id="already-linked",
            email="same@example.com", email_verified=True,
        )
    by_email.assert_not_awaited()
    link.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("email,provider_id", [
    ("", "valid"),
    ("  ", "valid"),
    ("new@example.com", ""),
])
async def test_incomplete_identity_rejected_before_lookup(
    monkeypatch, email, provider_id,
):
    db = fake_db()
    linked, by_email, link = stub_lookups(monkeypatch)
    with pytest.raises(auth.OAuthAccountConflictError, match="不完整"):
        await auth.get_or_create_oauth_user(
            db, provider="google", provider_user_id=provider_id,
            email=email, email_verified=True,
        )
    linked.assert_not_awaited()
    by_email.assert_not_awaited()
    link.assert_not_awaited()
