"""Model pricing normalization helpers."""

from __future__ import annotations

from typing import Optional, Protocol


class ModelPricingLike(Protocol):
    model_id: str
    cost_per_1k_input: float | None
    cost_per_1k_output: float | None
    extra_params: dict | None


def is_free_model(model_id: str | None) -> bool:
    return "deepseek-v4-flash-free" in (model_id or "").lower()


def normalized_model_pricing(model: ModelPricingLike) -> dict[str, float | None]:
    if is_free_model(model.model_id):
        return {
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "cost_per_1m_input": 0.0,
            "cost_per_1m_output": 0.0,
            "cost_per_1m_input_cache_hit": 0.0,
        }

    extra_params = model.extra_params if isinstance(model.extra_params, dict) else {}
    return {
        "cost_per_1k_input": model.cost_per_1k_input,
        "cost_per_1k_output": model.cost_per_1k_output,
        "cost_per_1m_input": _per_1k_to_1m(model.cost_per_1k_input),
        "cost_per_1m_output": _per_1k_to_1m(model.cost_per_1k_output),
        "cost_per_1m_input_cache_hit": extra_params.get("cost_per_1m_input_cache_hit"),
    }


def _per_1k_to_1m(value: float | None) -> float | None:
    return round(value * 1000, 6) if value is not None else None
