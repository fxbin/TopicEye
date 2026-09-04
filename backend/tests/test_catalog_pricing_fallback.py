"""目录价计费估算 fallback 测试（models.dev，USD/1M）。

覆盖：未配置价格时估算、已配置不覆盖（含只配缓存命中价的边角）、
free 模型不介入、裸名/前缀名匹配、calculate_cost/pricing_from_model 形状守卫。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm import model_catalog_pricing
from app.services.llm_usage import TokenUsage, calculate_cost, pricing_from_model, record_llm_call


def _pricing_model(provider="zhipu", model_id="glm-5.2", cost_in=None, cost_out=None):
    return SimpleNamespace(
        id=1,
        name="Pricing Test",
        provider=provider,
        model_id=model_id,
        cost_per_1k_input=cost_in,
        cost_per_1k_output=cost_out,
        extra_params={},
    )


# ── 目录价计费估算 fallback ──────────────────────────────────────────


def _pricing_model(provider="zhipu", model_id="glm-5.2", cost_in=None, cost_out=None):
    return SimpleNamespace(
        id=1,
        name="Pricing Test",
        provider=provider,
        model_id=model_id,
        cost_per_1k_input=cost_in,
        cost_per_1k_output=cost_out,
        extra_params={},
    )


@pytest.mark.asyncio
class TestCatalogPricingFallback:
    async def test_unconfigured_model_uses_catalog_estimate(self, test_session_factory, monkeypatch):
        from app.repositories.model_catalog_repo import ModelCatalogRepository

        async with test_session_factory() as db:
            from datetime import UTC, datetime

            repo = ModelCatalogRepository(db)
            await repo.upsert_entries(
                [
                    {
                        "provider": "zhipuai",
                        "model_id": "glm-5.2",
                        "cost_per_1m_input": 0.75,
                        "cost_per_1m_output": 3.75,
                        "cost_per_1m_cache_read": 0.075,
                    }
                ],
                fetched_at=datetime.now(UTC),
            )
            await db.commit()

        model_catalog_pricing.reset_catalog_pricing_cache()
        async with test_session_factory() as db:
            # litellm provider "zhipu" 应反查到目录 "zhipuai"
            pricing = await model_catalog_pricing.catalog_pricing_for_model(db, provider="zhipu", model_id="glm-5.2")
            assert pricing == {"input": 0.75, "output": 3.75, "cache_hit": 0.075, "cache_create": None}

            # record_llm_call：未配置价格 → 成本按目录价估算
            log = await record_llm_call(
                db,
                model=_pricing_model(),
                request_model="zhipu/glm-5.2",
                scene="test",
                status="DONE",
                usage=TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000),
            )
            assert log.cost_per_1m_input == 0.75
            assert log.total_cost == pytest.approx(0.75 + 3.75)
        model_catalog_pricing.reset_catalog_pricing_cache()

    async def test_configured_prices_never_overridden(self, test_session_factory):
        model_catalog_pricing.reset_catalog_pricing_cache()
        async with test_session_factory() as db:
            log = await record_llm_call(
                db,
                model=_pricing_model(cost_in=0.001, cost_out=0.002),  # per-1k 已配置
                request_model="zhipu/glm-5.2",
                scene="test",
                status="DONE",
                usage=TokenUsage(input_tokens=1000, output_tokens=1000),
            )
            # per-1k×1000 = per-1m：input 1.0 / output 2.0（每百万）
            assert log.cost_per_1m_input == 1.0
            # 1000 tokens × 1.0/1M + 1000 × 2.0/1M = 0.003
            assert log.total_cost == pytest.approx(0.003)
        model_catalog_pricing.reset_catalog_pricing_cache()

    async def test_free_model_and_unknown_model_stay_zero(self, test_session_factory):
        model_catalog_pricing.reset_catalog_pricing_cache()
        async with test_session_factory() as db:
            free_log = await record_llm_call(
                db,
                model=_pricing_model(model_id="deepseek-v4-flash-free"),
                request_model="deepseek/deepseek-v4-flash-free",
                scene="test",
                status="DONE",
                usage=TokenUsage(input_tokens=1000, output_tokens=1000),
            )
            assert free_log.total_cost == 0.0

            unknown_log = await record_llm_call(
                db,
                model=_pricing_model(model_id="totally-unknown"),
                request_model="zhipu/totally-unknown",
                scene="test",
                status="DONE",
                usage=TokenUsage(input_tokens=1000, output_tokens=1000),
            )
            assert unknown_log.total_cost == 0.0  # 目录查不到 → 维持 V1 行为
        model_catalog_pricing.reset_catalog_pricing_cache()

    async def test_cache_hit_only_config_not_overridden(self, test_session_factory):
        """用户只配了缓存命中价时，目录只补 input/output，不覆盖 cache_hit。"""
        from datetime import UTC, datetime

        from app.repositories.model_catalog_repo import ModelCatalogRepository

        async with test_session_factory() as db:
            await ModelCatalogRepository(db).upsert_entries(
                [
                    {
                        "provider": "zhipuai",
                        "model_id": "glm-5.2",
                        "cost_per_1m_input": 0.75,
                        "cost_per_1m_output": 3.75,
                        "cost_per_1m_cache_read": 0.075,
                    }
                ],
                fetched_at=datetime.now(UTC),
            )
            await db.commit()

        model_catalog_pricing.reset_catalog_pricing_cache()
        async with test_session_factory() as db:
            log = await record_llm_call(
                db,
                model=SimpleNamespace(
                    id=1,
                    name="t",
                    provider="zhipu",
                    model_id="glm-5.2",
                    cost_per_1k_input=None,
                    cost_per_1k_output=None,
                    extra_params={"cost_per_1m_input_cache_hit": 0.5},
                ),
                request_model="zhipu/glm-5.2",
                scene="test",
                status="DONE",
                usage=TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000),
            )
            assert log.cost_per_1m_input == 0.75  # 目录补的
            assert log.cost_per_1m_input_cache_hit == 0.5  # 用户配置保留
            # billable input = 1M - 1M(缓存读) = 0 → 0 + 输出 3.75 + 缓存读 1M×0.5
            assert log.total_cost == pytest.approx(3.75 + 0.5)
        model_catalog_pricing.reset_catalog_pricing_cache()

    async def test_prefixed_model_id_matches_bare_catalog_entry(self, test_session_factory):
        from datetime import UTC, datetime

        from app.repositories.model_catalog_repo import ModelCatalogRepository

        async with test_session_factory() as db:
            await ModelCatalogRepository(db).upsert_entries(
                [{"provider": "zhipuai", "model_id": "glm-5.2", "cost_per_1m_input": 0.75, "cost_per_1m_output": 3.75}],
                fetched_at=datetime.now(UTC),
            )
            await db.commit()

        model_catalog_pricing.reset_catalog_pricing_cache()
        async with test_session_factory() as db:
            pricing = await model_catalog_pricing.catalog_pricing_for_model(
                db,
                provider="zhipu",
                model_id="zhipu/glm-5.2",  # 带前缀
            )
            assert pricing is not None and pricing["input"] == 0.75
        model_catalog_pricing.reset_catalog_pricing_cache()


def test_calculate_cost_unchanged_for_configured_pricing():
    # 守卫：calculate_cost 公式未被 V2 改动
    costs = calculate_cost(
        TokenUsage(input_tokens=1_000_000, output_tokens=500_000),
        {"input": 1.0, "output": 2.0, "cache_hit": 0.1, "cache_create": None},
    )
    assert costs.input_cost == 1.0
    assert costs.output_cost == 1.0
    assert costs.total_cost == pytest.approx(2.0)


def test_pricing_from_model_shape_unchanged():
    pricing = pricing_from_model(_pricing_model(cost_in=0.001, cost_out=0.002))
    assert pricing == {"input": 1.0, "output": 2.0, "cache_hit": None, "cache_create": None}
