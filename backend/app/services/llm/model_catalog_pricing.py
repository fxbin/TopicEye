"""目录价格计费估算 fallback（models.dev，USD/百万 tokens）。

当模型配置的 input 与 output 价格**均未填写**时，用模型目录（models.dev
缓存）的价格做成本**估算**兜底。注意币种：目录价格是 USD/1M，用户自填
价格币种未知——因此只在完全未配置时介入，宁缺毋滥。

进程内 TTL 缓存（默认 300s）整表加载价格行（约 7.5K 行三列，内存可忽略），
调用方在已有 DB session 上下文里使用；加载失败静默返回 None（维持 V1
"未配置=成本记 0"的行为）。
"""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.model_catalog_repo import ModelCatalogRepository
from app.services.model_catalog_service import resolve_provider_for_lookup

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300

_pricing_rows: dict[tuple[str, str], tuple[float | None, float | None, float | None]] = {}
_pricing_loaded_at: float = 0.0
# 空目录（未同步/未 seed 的部署）也要缓存"已加载"状态，否则每条无价
# 日志都会触发一次全表 SELECT。
_pricing_loaded = False
_pricing_lock = asyncio.Lock()


def reset_catalog_pricing_cache() -> None:
    """清空价格缓存（测试与目录刷新/seed 后调用）。"""
    global _pricing_rows, _pricing_loaded_at, _pricing_loaded
    _pricing_rows = {}
    _pricing_loaded_at = 0.0
    _pricing_loaded = False


async def _ensure_pricing_loaded(db: AsyncSession) -> None:
    global _pricing_rows, _pricing_loaded_at, _pricing_loaded
    if _pricing_loaded and (time.monotonic() - _pricing_loaded_at) < _CACHE_TTL_SECONDS:
        return
    async with _pricing_lock:
        if _pricing_loaded and (time.monotonic() - _pricing_loaded_at) < _CACHE_TTL_SECONDS:
            return
        rows = await ModelCatalogRepository(db).list_pricing_rows()
        _pricing_rows = {
            (provider, model_id): (cost_in, cost_out, cost_cache_read)
            for provider, model_id, cost_in, cost_out, cost_cache_read in rows
        }
        _pricing_loaded_at = time.monotonic()
        _pricing_loaded = True


async def catalog_pricing_for_model(db: AsyncSession, *, provider: str | None, model_id: str | None) -> dict | None:
    """按 litellm provider + model_id（裸名或带前缀）查目录价格。

    返回 pricing_from_model 兼容的 dict（input/output/cache_hit，per-1M USD），
    任一方向都查不到或目录为空时返回 None。失败静默——估算兜底不能影响主链路。
    """
    if not provider or not model_id:
        return None
    try:
        await _ensure_pricing_loaded(db)
    except Exception as exc:
        logger.debug("catalog pricing cache load failed (fallback stays off): %s", exc)
        return None

    provider_id = resolve_provider_for_lookup(provider)
    bare_model_id = model_id.rsplit("/", 1)[-1]
    for key in ((provider_id, model_id), (provider_id, bare_model_id)):
        entry = _pricing_rows.get(key)
        if entry is not None:
            cost_in, cost_out, cost_cache_read = entry
            if cost_in is None and cost_out is None:
                return None
            return {"input": cost_in, "output": cost_out, "cache_hit": cost_cache_read, "cache_create": None}
    return None
