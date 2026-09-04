"""models.dev 模型目录服务。

职责：
- 精选 provider 清单（分组展示 + models.dev → litellm provider 映射 + 默认 api_base）
- 解析 models.dev api.json / 内置快照为目录条目（字段归一，价格保持 per-1M 原值）
- 冷启动 seed（表为空时从内置快照导入，幂等）
- 每日刷新（外网拉取 → 校验 → upsert → 清理陈旧行；失败不提交，旧数据保留）
- 管理端查询 payload（providers / models）

数据边界：本服务只写 ``model_catalog_models``，永不触碰 ``llm_models``。
models.dev 数据为社区维护（MIT），仅作预填默认值与参考展示，
用户已配置价格不被覆盖。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories.model_catalog_repo import ModelCatalogRepository

logger = logging.getLogger(__name__)

# 目录条目下限守卫：解析结果低于该值视为载荷异常（截断/结构变化），拒绝入库。
MIN_CATALOG_ENTRIES = 100

SNAPSHOT_RESOURCE_PACKAGE = "app.data"
SNAPSHOT_RESOURCE_NAME = "model_catalog_snapshot.json"


# ── 精选 provider 清单 ────────────────────────────────────────────────
# 213 家 provider 中绝大多数是订阅中转 / token 计划 / 地域入口变体，全部展示
# 反而是负担；此处只精选常用项。完整目录仍在库中，可通过 include_all / 搜索
# 访问。litellm_provider 是 resolve_litellm_model 拼路由用的 provider 值；
# OpenAI 兼容网关（国内厂商/中转）统一映射为 "openai" + default_api_base。


@dataclass(frozen=True)
class FeaturedProvider:
    models_dev_id: str
    litellm_provider: str
    display_name: str
    group: str
    default_api_base: str | None = None


FEATURED_PROVIDER_GROUPS: tuple[tuple[str, str], ...] = (
    ("cn_direct", "国产直连"),
    ("overseas_official", "海外官方"),
    ("aggregator", "聚合/中转"),
    ("cloud_hosted", "云厂商托管"),
)

FEATURED_PROVIDERS: tuple[FeaturedProvider, ...] = (
    # 国产直连
    FeaturedProvider("deepseek", "deepseek", "DeepSeek", "cn_direct", "https://api.deepseek.com"),
    FeaturedProvider("zhipuai", "zhipu", "智谱 GLM", "cn_direct", "https://open.bigmodel.cn/api/paas/v4/"),
    FeaturedProvider("minimax", "minimax", "MiniMax", "cn_direct", "https://api.minimaxi.com/v1"),
    FeaturedProvider("moonshotai", "moonshot", "月之暗面 Kimi", "cn_direct", "https://api.moonshot.cn/v1"),
    FeaturedProvider(
        "alibaba", "openai", "阿里通义千问", "cn_direct", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ),
    FeaturedProvider("volcengine", "openai", "火山方舟豆包", "cn_direct", "https://ark.cn-beijing.volces.com/api/v3"),
    FeaturedProvider("stepfun", "openai", "阶跃星辰", "cn_direct", "https://api.stepfun.com/v1"),
    FeaturedProvider("xiaomi", "openai", "小米", "cn_direct"),
    # 海外官方
    FeaturedProvider("openai", "openai", "OpenAI", "overseas_official", "https://api.openai.com/v1"),
    FeaturedProvider("anthropic", "anthropic", "Anthropic", "overseas_official"),
    FeaturedProvider("google", "gemini", "Google Gemini", "overseas_official"),
    FeaturedProvider("xai", "xai", "xAI Grok", "overseas_official"),
    FeaturedProvider("mistral", "mistral", "Mistral", "overseas_official"),
    # 聚合/中转
    FeaturedProvider("openrouter", "openrouter", "OpenRouter", "aggregator", "https://openrouter.ai/api/v1"),
    FeaturedProvider("siliconflow", "openai", "硅基流动", "aggregator", "https://api.siliconflow.cn/v1"),
    FeaturedProvider("aihubmix", "openai", "AiHubMix", "aggregator", "https://aihubmix.com/v1"),
    FeaturedProvider("302ai", "openai", "302.AI", "aggregator", "https://api.302.ai/v1"),
    FeaturedProvider("deepinfra", "openai", "DeepInfra", "aggregator", "https://api.deepinfra.com/v1/openai"),
    FeaturedProvider("novita-ai", "openai", "Novita AI", "aggregator", "https://api.novita.ai/v3/openai"),
    # 云厂商托管（自部署场景少用，放最后）
    FeaturedProvider("azure", "azure", "Azure OpenAI", "cloud_hosted"),
    FeaturedProvider("amazon-bedrock", "bedrock", "AWS Bedrock", "cloud_hosted"),
    FeaturedProvider("google-vertex", "vertex_ai", "Google Vertex AI", "cloud_hosted"),
)

_FEATURED_BY_ID = {item.models_dev_id: item for item in FEATURED_PROVIDERS}
_LITELLM_TO_FEATURED: dict[str, FeaturedProvider] = {}
for _featured in FEATURED_PROVIDERS:
    # 同一 litellm provider（如多个 OpenAI 兼容网关都是 "openai"）保留第一个命中的精选项
    _LITELLM_TO_FEATURED.setdefault(_featured.litellm_provider, _featured)

_GROUP_LABELS = dict(FEATURED_PROVIDER_GROUPS)


def get_featured_provider(models_dev_id: str) -> FeaturedProvider | None:
    return _FEATURED_BY_ID.get(models_dev_id)


def resolve_provider_for_lookup(provider_param: str) -> str:
    """把 API 入参解析为 models.dev provider id。

    依次尝试：精选 id 精确匹配 → litellm provider 反查精选 → 原样返回
    （非精选 provider 直接用其 models.dev id 查询，如 chutes / groq）。
    """
    param = (provider_param or "").strip()
    if not param:
        return param
    if param in _FEATURED_BY_ID:
        return param
    featured = _LITELLM_TO_FEATURED.get(param)
    if featured is not None:
        return featured.models_dev_id
    return param


# ── models.dev 载荷解析 ──────────────────────────────────────────────


def _to_int(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _to_bool(value) -> bool | None:
    return value if isinstance(value, bool) else None


def _to_str_list(value) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [str(item) for item in value if isinstance(item, str)]


def _to_str(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()[:200]
    return cleaned or None


def _parse_model_entry(provider: str, model_id: str, raw: dict) -> dict | None:
    """把 models.dev 单个模型条目归一为 ORM 列名对齐的 dict。"""
    limit = raw.get("limit") if isinstance(raw.get("limit"), dict) else {}
    cost = raw.get("cost") if isinstance(raw.get("cost"), dict) else {}
    modalities = raw.get("modalities") if isinstance(raw.get("modalities"), dict) else {}
    return {
        "provider": provider,
        "model_id": model_id[:200],
        "name": _to_str(raw.get("name")),
        "context_window": _to_int(limit.get("context")),
        "max_output_tokens": _to_int(limit.get("output")),
        "cost_per_1m_input": _to_float(cost.get("input")),
        "cost_per_1m_output": _to_float(cost.get("output")),
        "cost_per_1m_cache_read": _to_float(cost.get("cache_read")),
        "supports_tool_call": _to_bool(raw.get("tool_call")),
        "supports_structured_output": _to_bool(raw.get("structured_output")),
        "supports_reasoning": _to_bool(raw.get("reasoning")),
        "input_modalities": _to_str_list(modalities.get("input")),
        "output_modalities": _to_str_list(modalities.get("output")),
        "open_weights": _to_bool(raw.get("open_weights")),
        "status": _to_str(raw.get("status"))[:20] if _to_str(raw.get("status")) else None,
        "release_date": _to_str(raw.get("release_date"))[:20] if _to_str(raw.get("release_date")) else None,
        "last_updated": _to_str(raw.get("last_updated"))[:20] if _to_str(raw.get("last_updated")) else None,
    }


def parse_models_dev_catalog(payload: dict) -> list[dict]:
    """解析 api.json 形状 ``{provider_id: {name, models: {model_id: {...}}}}``。

    快照文件的 ``catalog`` 字段与线上 api.json 同构，共用本解析器。
    """
    entries: list[dict] = []
    if not isinstance(payload, dict):
        return entries
    for provider_id, provider in payload.items():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for model_id, raw_model in models.items():
            if not model_id or not isinstance(raw_model, dict):
                continue
            entry = _parse_model_entry(str(provider_id), str(model_id), raw_model)
            if entry is not None:
                entries.append(entry)
    return entries


# ── 内置快照 ─────────────────────────────────────────────────────────


def load_bundled_snapshot() -> dict:
    """读取内置快照（backend/app/data/model_catalog_snapshot.json）。"""
    resource = resources.files(SNAPSHOT_RESOURCE_PACKAGE).joinpath(SNAPSHOT_RESOURCE_NAME)
    return json.loads(resource.read_text(encoding="utf-8"))


async def seed_catalog_from_snapshot(db: AsyncSession) -> int:
    """表为空时从内置快照导入目录；非空时 no-op。返回导入条数。

    幂等且不 commit——事务边界在调用方（main.py seed step）。
    """
    repo = ModelCatalogRepository(db)
    if await repo.count_all() > 0:
        return 0
    snapshot = load_bundled_snapshot()
    entries = parse_models_dev_catalog(snapshot.get("catalog", {}))
    if not entries:
        raise ValueError("bundled model catalog snapshot is empty")
    imported = await repo.upsert_entries(entries, fetched_at=datetime.now(UTC))
    _reset_pricing_cache()
    logger.info("Model catalog seeded from bundled snapshot: %d models", imported)
    return imported


# ── 每日刷新 ─────────────────────────────────────────────────────────


def _reset_pricing_cache() -> None:
    """目录数据变化后清空计费估算的价格缓存。

    延迟导入：model_catalog_pricing 依赖本模块的 resolve_provider_for_lookup，
    顶层互 import 会成环；两模块加载完成后运行时调用无碍。
    """
    from app.services.llm.model_catalog_pricing import reset_catalog_pricing_cache

    reset_catalog_pricing_cache()


async def fetch_models_dev_catalog(url: str) -> dict:
    """拉取 models.dev api.json。截断/非 JSON 载荷会在 json 解析处抛错。"""
    async with httpx.AsyncClient(
        timeout=settings.MODEL_CATALOG_REFRESH_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": "TopicEye-ModelCatalog/1.0"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def refresh_catalog(db: AsyncSession) -> dict:
    """从 models.dev 全量刷新目录。失败时不 commit，旧数据完整保留。

    全量替换语义：upsert 本批所有条目后，删除 fetched_at 早于批次时间的
    陈旧行（对应目录侧已下架的模型）。单事务，由调用方 commit。
    """
    fetched_at = datetime.now(UTC)
    payload = await fetch_models_dev_catalog(settings.MODEL_CATALOG_URL)
    entries = parse_models_dev_catalog(payload)
    if len(entries) < MIN_CATALOG_ENTRIES:
        raise ValueError(f"models.dev payload looks truncated: only {len(entries)} entries (< {MIN_CATALOG_ENTRIES})")

    repo = ModelCatalogRepository(db)
    upserted = await repo.upsert_entries(entries, fetched_at=fetched_at)
    deleted = await repo.delete_stale(fetched_before=fetched_at)
    _reset_pricing_cache()
    providers = len({entry["provider"] for entry in entries})
    logger.info("Model catalog refreshed: %d providers / %d models / %d stale removed", providers, upserted, deleted)
    return {
        "ok": True,
        "providers": providers,
        "models": upserted,
        "deleted_stale": deleted,
        "fetched_at": fetched_at.isoformat(),
    }


# ── 管理端查询 payload ───────────────────────────────────────────────


def _provider_item(featured: FeaturedProvider, model_count: int) -> dict:
    return {
        "id": featured.models_dev_id,
        "litellm_provider": featured.litellm_provider,
        "display_name": featured.display_name,
        "group": featured.group,
        "group_label": _GROUP_LABELS.get(featured.group, featured.group),
        "model_count": model_count,
        "default_api_base": featured.default_api_base,
    }


def _model_item(row) -> dict:
    return {
        "provider": row.provider,
        "model_id": row.model_id,
        "name": row.name,
        "context_window": row.context_window,
        "max_output_tokens": row.max_output_tokens,
        "cost_per_1m_input": row.cost_per_1m_input,
        "cost_per_1m_output": row.cost_per_1m_output,
        "cost_per_1m_cache_read": row.cost_per_1m_cache_read,
        "supports_tool_call": row.supports_tool_call,
        "supports_structured_output": row.supports_structured_output,
        "supports_reasoning": row.supports_reasoning,
        "input_modalities": row.input_modalities,
        "output_modalities": row.output_modalities,
        "open_weights": row.open_weights,
        "status": row.status,
        "release_date": row.release_date,
        "last_updated": row.last_updated,
    }


async def list_providers_payload(db: AsyncSession, *, include_all: bool = False) -> dict:
    """精选分组 provider 清单；include_all 时附带全部非精选 provider（按模型数倒序）。"""
    repo = ModelCatalogRepository(db)
    stats = await repo.list_provider_stats()
    fetched_at = await repo.latest_fetched_at()

    groups = []
    for group_key, group_label in FEATURED_PROVIDER_GROUPS:
        providers = [
            _provider_item(item, stats.get(item.models_dev_id, 0))
            for item in FEATURED_PROVIDERS
            if item.group == group_key
        ]
        groups.append({"key": group_key, "label": group_label, "providers": providers})

    others = []
    if include_all:
        featured_ids = set(_FEATURED_BY_ID)
        # 非精选 provider 没有维护过的 litellm 映射，直接用 models.dev id 兜底
        others = [
            {
                "id": provider_id,
                "litellm_provider": provider_id,
                "display_name": provider_id,
                "group": "other",
                "group_label": "其他",
                "model_count": count,
                "default_api_base": None,
            }
            for provider_id, count in stats.items()
            if provider_id not in featured_ids
        ]

    return {
        "groups": groups,
        "others": others,
        "featured_count": len(FEATURED_PROVIDERS),
        "total_providers": len(stats),
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
    }


async def list_models_payload(
    db: AsyncSession,
    *,
    provider: str,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """按 provider（models.dev id 或 litellm provider 名）列目录模型。"""
    resolved = resolve_provider_for_lookup(provider)
    repo = ModelCatalogRepository(db)
    items, total = await repo.list_models(provider=resolved or None, search=search, limit=limit, offset=offset)
    fetched_at = await repo.latest_fetched_at()
    return {
        "provider": resolved,
        "requested_provider": provider,
        "items": [_model_item(row) for row in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
    }
