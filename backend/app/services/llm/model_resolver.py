"""LiteLLM model name resolution helpers."""

from __future__ import annotations

from typing import Any, Optional, Protocol


class ModelLike(Protocol):
    provider: str
    model_id: str
    api_base: str | None
    extra_params: dict[str, Any] | None


def _extra_params(model: ModelLike) -> dict[str, Any]:
    params = getattr(model, "extra_params", None)
    return params if isinstance(params, dict) else {}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def resolve_litellm_model(model: ModelLike) -> str:
    """Return the model string sent to LiteLLM.

    LiteLLM routes by provider-prefixed model strings such as
    ``deepseek/deepseek-chat`` or ``openai/gpt-4.1-mini``. The app should not
    infer providers from endpoint hostnames; for custom gateways, configure the
    LiteLLM provider explicitly and keep endpoint details in ``api_base``.
    """
    params = _extra_params(model)
    litellm_params = params.get("litellm_params") if isinstance(params.get("litellm_params"), dict) else {}
    explicit_model = _clean(params.get("litellm_model") or litellm_params.get("model"))
    if explicit_model:
        return explicit_model

    model_id = _clean(model.model_id) or ""
    if "/" in model_id:
        return model_id

    provider = _clean(params.get("litellm_provider") or litellm_params.get("custom_llm_provider") or model.provider)

    if provider:
        return f"{provider}/{model_id}"

    return model_id
