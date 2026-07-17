"""Tests for the Agent Skills discovery protocol endpoints.

These endpoints are PUBLIC (no Bearer token) because `npx skills add` must be
able to discover + download the skill before any auth exists. They must live
at /.well-known/agent-skills/ (root, not under /api/v1) per the protocol.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.api.agent_skills import router as agent_skills_router


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    app = FastAPI()
    app.include_router(agent_skills_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_index_is_public_and_well_formed(client):
    """index.json must be reachable without auth and match the protocol schema."""
    resp = await client.get("/.well-known/agent-skills/index.json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["$schema"].startswith("https://schemas.agentskills.io/")
    assert isinstance(body["skills"], list)
    assert len(body["skills"]) == 1
    skill = body["skills"][0]
    assert skill["name"] == "topiceye-reader"
    assert skill["type"] == "skill-md"
    assert skill["description"]
    assert skill["url"].endswith("/.well-known/agent-skills/topiceye-reader/SKILL.md")
    assert skill["digest"].startswith("sha256:")


@pytest.mark.asyncio
async def test_skill_markdown_has_frontmatter_and_env_vars(client):
    """SKILL.md must have YAML frontmatter and reference the two env vars."""
    resp = await client.get("/.well-known/agent-skills/topiceye-reader/SKILL.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    text = resp.text
    assert text.startswith("---\n")
    assert "name: topiceye-reader" in text
    assert "TOPICEYE_API_URL" in text
    assert "TOPICEYE_API_TOKEN" in text
    # The discovered base URL should be baked into the docs
    assert "http://testserver" in text
    # All three read endpoints documented
    for endpoint in ("/api/v1/skill/today-picks", "/api/v1/skill/daily-report", "/api/v1/skill/trends"):
        assert endpoint in text


@pytest.mark.asyncio
async def test_base_url_respects_forwarded_headers(client):
    """Behind a proxy, x-forwarded-proto/host must shape the advertised base URL."""
    resp = await client.get(
        "/.well-known/agent-skills/index.json",
        headers={"x-forwarded-proto": "https", "x-forwarded-host": "topiceye.example.com"},
    )
    skill = resp.json()["skills"][0]
    assert skill["url"] == "https://topiceye.example.com/.well-known/agent-skills/topiceye-reader/SKILL.md"
