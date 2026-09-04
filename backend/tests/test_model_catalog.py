"""模型目录（models.dev 缓存）服务与 API 测试。

覆盖：载荷解析归一 / upsert 幂等与查询 / 陈旧清理 / 快照 seed 幂等 /
刷新失败保留旧数据 / 最小条目守卫 / 精选映射 / API 端点（免真实网络与鉴权）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import model_catalog as model_catalog_api
from app.repositories.model_catalog_repo import ModelCatalogRepository
from app.services import model_catalog_service
from app.services.model_catalog_service import (
    MIN_CATALOG_ENTRIES,
    parse_models_dev_catalog,
    resolve_provider_for_lookup,
)


def _fixture_catalog() -> dict[str, Any]:
    """最小 api.json 形状载荷：两个 provider、三个模型（含缺字段的脏条目）。"""
    return {
        "zhipuai": {
            "name": "Zhipu AI",
            "models": {
                "glm-5.2": {
                    "name": "GLM-5.2",
                    "limit": {"context": 1050000, "output": 96000},
                    "cost": {"input": 0.75, "output": 3.75, "cache_read": 0.075},
                    "tool_call": True,
                    "structured_output": True,
                    "reasoning": False,
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                    "open_weights": False,
                    "status": "ga",
                    "release_date": "2026-03-05",
                    "last_updated": "2026-03-05",
                },
                "glm-5.2-air": {
                    "name": "GLM-5.2 Air",
                    "limit": {"context": "not-a-number"},
                    "cost": {},
                    # 全部能力字段缺失 → 应归一为 None
                },
            },
        },
        "deepseek": {
            "name": "DeepSeek",
            "models": {
                "deepseek-chat": {
                    "name": "DeepSeek Chat",
                    "limit": {"context": 128000, "output": 8192},
                    "cost": {"input": 1, "output": 2, "cache_read": 0.02},
                    "tool_call": True,
                },
            },
        },
        "not-a-provider": "garbage-entry",
    }


class TestParseModelsDevCatalog:
    def test_normalizes_entries(self):
        entries = parse_models_dev_catalog(_fixture_catalog())
        assert len(entries) == 3

        glm = next(e for e in entries if e["model_id"] == "glm-5.2")
        assert glm["provider"] == "zhipuai"
        assert glm["context_window"] == 1_050_000
        assert glm["max_output_tokens"] == 96_000
        assert glm["cost_per_1m_input"] == 0.75
        assert glm["cost_per_1m_cache_read"] == 0.075
        assert glm["supports_tool_call"] is True
        assert glm["supports_reasoning"] is False
        assert glm["input_modalities"] == ["text", "image"]
        assert glm["status"] == "ga"

    def test_dirty_fields_degrade_to_none(self):
        entries = parse_models_dev_catalog(_fixture_catalog())
        air = next(e for e in entries if e["model_id"] == "glm-5.2-air")
        assert air["context_window"] is None  # "not-a-number" → None
        assert air["cost_per_1m_input"] is None
        assert air["supports_tool_call"] is None
        assert air["status"] is None

    def test_ignores_non_object_payload(self):
        assert parse_models_dev_catalog([]) == []
        assert parse_models_dev_catalog({"p": {"models": "not-a-dict"}}) == []

    def test_featured_mapping(self):
        assert resolve_provider_for_lookup("zhipu") == "zhipuai"
        assert resolve_provider_for_lookup("moonshot") == "moonshotai"
        assert resolve_provider_for_lookup("zhipuai") == "zhipuai"
        assert resolve_provider_for_lookup("chutes") == "chutes"
        assert resolve_provider_for_lookup("") == ""


@pytest.mark.asyncio
class TestModelCatalogRepository:
    async def test_upsert_idempotent_and_query(self, test_session_factory):
        entries = parse_models_dev_catalog(_fixture_catalog())
        async with test_session_factory() as db:
            repo = ModelCatalogRepository(db)
            first = await repo.upsert_entries(entries, fetched_at=datetime.now(UTC))
            await db.commit()
            assert first == 3

            # 重复 upsert 同一批次 → 幂等
            second = await repo.upsert_entries(entries, fetched_at=datetime.now(UTC))
            await db.commit()
            assert second == 3
            assert await repo.count_all() == 3

    async def test_list_models_filter_and_search(self, test_session_factory):
        entries = parse_models_dev_catalog(_fixture_catalog())
        async with test_session_factory() as db:
            repo = ModelCatalogRepository(db)
            await repo.upsert_entries(entries, fetched_at=datetime.now(UTC))
            await db.commit()

            items, total = await repo.list_models(provider="zhipuai")
            assert total == 2
            assert {i.model_id for i in items} == {"glm-5.2", "glm-5.2-air"}

            items, total = await repo.list_models(provider="deepseek", search="chat")
            assert total == 1
            assert items[0].model_id == "deepseek-chat"

            model = await repo.get_model("zhipuai", "glm-5.2")
            assert model is not None and model.context_window == 1_050_000

    async def test_delete_stale_only_removes_old_batches(self, test_session_factory):
        now = datetime.now(UTC)
        async with test_session_factory() as db:
            repo = ModelCatalogRepository(db)
            await repo.upsert_entries(parse_models_dev_catalog(_fixture_catalog()), fetched_at=now - timedelta(days=1))
            await db.commit()
            # 新批次只包含 deepseek
            await repo.upsert_entries(
                [e for e in parse_models_dev_catalog(_fixture_catalog()) if e["provider"] == "deepseek"],
                fetched_at=now,
            )
            deleted = await repo.delete_stale(fetched_before=now - timedelta(seconds=1))
            await db.commit()
            assert deleted == 2  # zhipuai 两条旧批次被清理
            items, total = await repo.list_models()
            assert total == 1 and items[0].provider == "deepseek"

    async def test_provider_stats(self, test_session_factory):
        async with test_session_factory() as db:
            repo = ModelCatalogRepository(db)
            await repo.upsert_entries(parse_models_dev_catalog(_fixture_catalog()), fetched_at=datetime.now(UTC))
            await db.commit()
            stats = await repo.list_provider_stats()
            assert stats == {"zhipuai": 2, "deepseek": 1}


@pytest.mark.asyncio
class TestSeedAndRefresh:
    async def test_seed_from_snapshot_idempotent(self, test_session_factory, monkeypatch):
        monkeypatch.setattr(model_catalog_service, "load_bundled_snapshot", lambda: {"catalog": _fixture_catalog()})
        async with test_session_factory() as db:
            seeded = await model_catalog_service.seed_catalog_from_snapshot(db)
            await db.commit()
            assert seeded == 3
            # 表非空 → no-op
            again = await model_catalog_service.seed_catalog_from_snapshot(db)
            await db.commit()
            assert again == 0
            assert await ModelCatalogRepository(db).count_all() == 3

    async def test_refresh_failure_keeps_old_data(self, test_session_factory, monkeypatch):
        async with test_session_factory() as db:
            repo = ModelCatalogRepository(db)
            await repo.upsert_entries(parse_models_dev_catalog(_fixture_catalog()), fetched_at=datetime.now(UTC))
            await db.commit()

            async def _boom(url: str):
                raise httpx.ConnectError("network down")

            monkeypatch.setattr(model_catalog_service, "fetch_models_dev_catalog", _boom)
            with pytest.raises(httpx.ConnectError):
                await model_catalog_service.refresh_catalog(db)
            await db.rollback()

            # 失败后旧数据完整
            assert await repo.count_all() == 3

    async def test_refresh_min_entries_guard(self, test_session_factory, monkeypatch):
        async def _small(url: str):
            return _fixture_catalog()  # 3 条 < MIN_CATALOG_ENTRIES

        monkeypatch.setattr(model_catalog_service, "fetch_models_dev_catalog", _small)
        async with test_session_factory() as db:
            with pytest.raises(ValueError, match="truncated"):
                await model_catalog_service.refresh_catalog(db)

    async def test_refresh_replaces_full_catalog(self, test_session_factory, monkeypatch):
        now_catalog = {
            "deepseek": {
                "name": "DeepSeek",
                "models": {"deepseek-chat": {"name": "DeepSeek Chat", "limit": {"context": 200000, "output": 16384}}},
            }
        }

        async def _fetch(url: str):
            # 达到最小条目守卫的批量载荷
            bulk = {f"p{i}": {"models": {f"m{i}": {"name": f"M{i}"}}} for i in range(MIN_CATALOG_ENTRIES)}
            bulk["deepseek"] = now_catalog["deepseek"]
            return bulk

        monkeypatch.setattr(model_catalog_service, "fetch_models_dev_catalog", _fetch)
        async with test_session_factory() as db:
            repo = ModelCatalogRepository(db)
            await repo.upsert_entries(parse_models_dev_catalog(_fixture_catalog()), fetched_at=datetime.now(UTC))
            await db.commit()

            summary = await model_catalog_service.refresh_catalog(db)
            await db.commit()
            assert summary["ok"] is True
            assert summary["deleted_stale"] == 2  # 旧 zhipuai 两条被替换掉
            model = await repo.get_model("deepseek", "deepseek-chat")
            assert model.context_window == 200000  # 字段被新批次覆盖


@pytest_asyncio.fixture
async def catalog_api_client(test_session_factory) -> AsyncGenerator[httpx.AsyncClient, None]:
    """挂载目录路由的轻量 app：覆盖 get_db 与鉴权依赖，不依赖真实网络。"""
    app = FastAPI()
    app.include_router(model_catalog_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fake_user = SimpleNamespace(id=1, role="admin")
    app.dependency_overrides[model_catalog_api.get_db] = override_get_db
    app.dependency_overrides[model_catalog_api.get_current_user] = lambda: fake_user
    app.dependency_overrides[model_catalog_api.get_current_admin_user] = lambda: fake_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
class TestModelCatalogApi:
    async def test_providers_endpoint_groups_featured(self, catalog_api_client, test_session_factory):
        async with test_session_factory() as db:
            await ModelCatalogRepository(db).upsert_entries(
                parse_models_dev_catalog(_fixture_catalog()), fetched_at=datetime.now(UTC)
            )
            await db.commit()

        resp = await catalog_api_client.get("/models/catalog/providers")
        assert resp.status_code == 200
        payload = resp.json()
        group_keys = [g["key"] for g in payload["groups"]]
        assert group_keys == ["cn_direct", "overseas_official", "aggregator", "cloud_hosted"]
        cn = next(g for g in payload["groups"] if g["key"] == "cn_direct")
        zhipu = next(p for p in cn["providers"] if p["id"] == "zhipuai")
        assert zhipu["litellm_provider"] == "zhipu"
        assert zhipu["model_count"] == 2
        assert payload["featured_count"] == 22

    async def test_providers_include_all_lists_others(self, catalog_api_client, test_session_factory):
        async with test_session_factory() as db:
            await ModelCatalogRepository(db).upsert_entries(
                parse_models_dev_catalog(_fixture_catalog()), fetched_at=datetime.now(UTC)
            )
            await db.commit()

        resp = await catalog_api_client.get("/models/catalog/providers", params={"include_all": True})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["total_providers"] == 2
        assert {p["id"] for p in payload["others"]} == set()  # fixture 的两个 provider 都是精选

    async def test_models_endpoint_resolves_litellm_alias(self, catalog_api_client, test_session_factory):
        async with test_session_factory() as db:
            await ModelCatalogRepository(db).upsert_entries(
                parse_models_dev_catalog(_fixture_catalog()), fetched_at=datetime.now(UTC)
            )
            await db.commit()

        # litellm provider 名 "zhipu" → models.dev id "zhipuai"
        resp = await catalog_api_client.get("/models/catalog/models", params={"provider": "zhipu"})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["provider"] == "zhipuai"
        assert payload["total"] == 2
        glm = next(m for m in payload["items"] if m["model_id"] == "glm-5.2")
        assert glm["context_window"] == 1_050_000
        assert glm["cost_per_1m_input"] == 0.75

    async def test_refresh_endpoint_returns_summary(self, catalog_api_client, monkeypatch):
        captured: dict[str, Any] = {}

        async def _fake_refresh(db):
            captured["called"] = True
            return {
                "ok": True,
                "providers": 213,
                "models": 7526,
                "deleted_stale": 0,
                "fetched_at": "2026-09-04T00:00:00+00:00",
            }

        monkeypatch.setattr(model_catalog_api.model_catalog_service, "refresh_catalog", _fake_refresh)
        resp = await catalog_api_client.post("/models/catalog/refresh")
        assert resp.status_code == 200
        assert resp.json()["models"] == 7526
        assert captured.get("called") is True

    async def test_refresh_endpoint_502_on_failure(self, catalog_api_client, monkeypatch):
        async def _bad_refresh(db):
            raise httpx.ConnectError("network down")

        monkeypatch.setattr(model_catalog_api.model_catalog_service, "refresh_catalog", _bad_refresh)
        resp = await catalog_api_client.post("/models/catalog/refresh")
        assert resp.status_code == 502
        assert "旧数据保留" in resp.json()["detail"]

    async def test_models_endpoint_requires_provider(self, catalog_api_client):
        resp = await catalog_api_client.get("/models/catalog/models")
        assert resp.status_code == 422
