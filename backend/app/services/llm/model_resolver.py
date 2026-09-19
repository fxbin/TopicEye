"""LiteLLM model name resolution helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# 容器内访问宿主机回环服务的网关名（Docker Desktop 内置；Linux 需 host-gateway）。
_HOST_GATEWAY = "host.docker.internal"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

_container_env: bool | None = None
_rewrite_logged: set[str] = set()


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

    if provider == "custom":
        # litellm 没有 "custom" provider，"custom/<model>" 会被解析成未知路由
        # （对可达端点也会打出错误路径）。选了"完全自定义"预设但只填裸模型名
        # 时，唯一可行的路由是 OpenAI 兼容网关；模型名自带 "/" 的已在上面原样返回。
        return f"openai/{model_id}"

    if provider:
        return f"{provider}/{model_id}"

    return model_id


def _running_in_container() -> bool:
    global _container_env
    if _container_env is None:
        _container_env = Path("/.dockerenv").exists()
    return _container_env


def normalize_api_base(api_base: str | None) -> str | None:
    """容器内把指向回环地址的 api_base 重写到宿主机网关。

    后端通常运行在 Docker 中，配置里的 localhost/127.0.0.1 指向容器自身，
    连不上跑在宿主机上的本地推理服务（Ollama / LM Studio / MLX 网关等），
    表现为 Connection refused。这里把回环主机名替换为 host.docker.internal
    （端口、路径、userinfo 原样保留）；非容器环境原样返回。
    """
    cleaned = _clean(api_base)
    if not cleaned or not _running_in_container():
        return cleaned

    try:
        parts = urlsplit(cleaned)
        hostname = parts.hostname
    except ValueError:
        return cleaned
    if not hostname or hostname.lower() not in _LOOPBACK_HOSTS:
        return cleaned

    new_host = f"[{_HOST_GATEWAY}]" if ":" in hostname else _HOST_GATEWAY
    if parts.port is not None:
        new_host += f":{parts.port}"
    userinfo, sep, _ = parts.netloc.rpartition("@")
    if sep:
        new_host = f"{userinfo}@{new_host}"
    rewritten = urlunsplit((parts.scheme, new_host, parts.path, parts.query, parts.fragment))

    if rewritten not in _rewrite_logged:
        _rewrite_logged.add(rewritten)
        logger.warning("api_base %s 指向回环地址，后端运行在容器内，已重写为 %s", cleaned, rewritten)
    return rewritten
