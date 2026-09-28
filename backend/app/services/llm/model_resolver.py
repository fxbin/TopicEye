"""LiteLLM model name resolution helpers."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# 容器内访问宿主机回环服务的网关名（Docker Desktop 内置；Linux 需 host-gateway）。
_HOST_GATEWAY = "host.docker.internal"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

_container_env: bool | None = None
_rewrite_logged: set[str] = set()


@lru_cache(maxsize=1)
def _known_litellm_providers() -> frozenset[str]:
    """litellm 的 provider 注册表（StrEnum 成员可直接与 str 相等比较）。

    用于区分「用户显式给出的 litellm 路由串」与「组织/模型命名的网关模型名」：
    前者首段命中注册表（如 deepseek/），后者不命中（如 example-org/）。
    """
    try:
        import litellm

        # 成员是 (str, Enum) 混入：str(member) 是 "LlmProviders.DEEPSEEK"，
        # 与请求串可比的是 .value（"deepseek"）。
        return frozenset(str(p.value) if hasattr(p, "value") else str(p) for p in litellm.provider_list)
    except Exception:  # noqa: BLE001 — litellm 导入失败时退化为「无已知前缀」
        logger.warning("litellm provider_list unavailable; slash model ids keep legacy passthrough")
        return frozenset()


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
    provider = _clean(params.get("litellm_provider") or litellm_params.get("custom_llm_provider") or model.provider)

    if provider == "custom":
        # litellm 没有 "custom" provider，"custom/<model>" 会被解析成未知路由。
        # 选了「完全自定义」预设时唯一可行的路由是 OpenAI 兼容网关——模型名
        # 含 "/"（如组织/模型命名 example-org/example-29b）也必须走该路由：
        # 原样透传会被 litellm 把首段当 provider 解析而报 BadRequestError（#83）。
        return f"openai/{model_id}"

    if provider:
        # 显式 provider 优先；模型名已带同前缀时去重，避免 openai/openai/...。
        prefix = f"{provider}/"
        return model_id if model_id.startswith(prefix) else f"{provider}/{model_id}"

    # 无 provider 信息时的应用层兜底（#83）：
    # - 含 "/" 且首段命中 litellm 已知 provider → 视为用户显式路由串，原样返回；
    # - 含 "/" 但首段未知（组织/模型命名，或 provider 拼写错误）→ 兜底 OpenAI
    #   兼容路由。本应用的模型目录条目对这类命名几乎总是自定义网关（带
    #   api_base），litellm 的 openai/ 前缀会剥掉前缀并把剩余部分原样发给网关。
    # - 裸模型名 → 原样返回（litellm 自身把无斜杠名称默认为 openai）。
    if "/" in model_id and model_id.split("/", 1)[0] not in _known_litellm_providers():
        return f"openai/{model_id}"
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
