"""
LLM Model configuration & evaluation API endpoints.

Model Config:
  GET    /models          — list all configured models
  POST   /models          — add a new model config
  PUT    /models/{id}     — update a model config
  DELETE /models/{id}     — delete a model config
  POST   /models/{id}/test          — test connectivity (single prompt)

Evaluation:
  POST   /evaluations/run            — run A/B evaluation across selected models
  GET    /evaluations/runs           — list all eval runs
  GET    /evaluations/runs/{run_id}  — get results for a specific run
  PUT    /evaluations/{id}/score     — human score a single eval result
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, desc, func, Integer as SAInteger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.config import settings
from app.core.database import async_session, database_profile, get_db
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.models.llm_model import LlmCallLog, LlmModel, ModelEvaluation
from app.models.user import User
from app.services.llm.model_list_cache import (
    MODEL_LIST_CACHE_HEADER,
    get_cached_model_list,
    invalidate_model_list_cache,
    set_cached_model_list,
)
from app.services.llm.provider import invalidate_model_cache
from app.services.llm.model_resolver import resolve_litellm_model
from app.services.llm.model_pricing import is_free_model, normalized_model_pricing
from app.services.llm.presets import apply_model_preset, list_model_presets
from app.services.llm_usage import extract_usage, record_llm_call_in_new_session
from app.services.plan_catalog import plan_allows_custom_ai

router = APIRouter(prefix="/models", tags=["models"])

LLM_COMPLETION_TIMEOUT_SECONDS = 25
LITELLM_COMPLETION_PARAM_KEYS = {
    "api_version",
    "custom_llm_provider",
    "default_headers",
    "drop_params",
    "extra_headers",
    "extra_query",
    "metadata",
    "num_retries",
    "organization",
    "timeout",
}


def _model_snapshot(model: LlmModel) -> SimpleNamespace:
    return SimpleNamespace(
        id=model.id,
        name=model.name,
        provider=model.provider,
        model_id=model.model_id,
        api_key=model.api_key,
        api_base=model.api_base,
        routing_group=model.routing_group,
        model_family=model.model_family,
        channel_name=model.channel_name,
        routing_priority=model.routing_priority,
        cooldown_seconds=model.cooldown_seconds,
        temperature=model.temperature,
        max_tokens=model.max_tokens,
        cost_per_1k_input=model.cost_per_1k_input,
        cost_per_1k_output=model.cost_per_1k_output,
        extra_params=model.extra_params,
    )


def _resolve_litellm_model(model: LlmModel) -> str:
    return resolve_litellm_model(model)


def _missing_explicit_api_key(model: LlmModel) -> bool:
    """OpenAI-compatible custom endpoints need an explicit key in this app."""
    return bool(model.api_base) and not bool(model.api_key)


def _normalize_evaluation_concurrency(value: Optional[int] = None) -> int:
    try:
        parsed = int(value if value is not None else settings.LLM_WORKER_CONCURRENCY)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(parsed, 8))


def _normalize_optional_config_value(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _completion_kwargs(
    model: LlmModel,
    resolved_model: str,
    messages: list[dict],
    *,
    temperature: float,
    max_tokens: int,
) -> dict:
    kwargs = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": LLM_COMPLETION_TIMEOUT_SECONDS,
    }
    extra_params = model.extra_params if isinstance(model.extra_params, dict) else {}
    litellm_params = extra_params.get("litellm_params")
    if isinstance(litellm_params, dict):
        kwargs.update(
            {
                key: value
                for key, value in litellm_params.items()
                if key in LITELLM_COMPLETION_PARAM_KEYS and value is not None
            }
        )
    if model.api_key:
        kwargs["api_key"] = model.api_key
    if model.api_base:
        kwargs["api_base"] = model.api_base
    return kwargs


def _sample_payload(sample_content: Optional[str]) -> dict:
    if not sample_content:
        return {
            "title": "OpenAI 发布 GPT-5: 多模态能力大幅提升",
            "content": "OpenAI 今日正式发布 GPT-5 模型，在多模态理解、代码生成和长文本处理方面均有显著提升。"
            "新模型在多项基准测试中刷新纪录，引发行业广泛讨论。",
        }

    try:
        parsed = json.loads(sample_content)
        if isinstance(parsed, dict):
            return {
                "title": str(parsed.get("title") or "未命名内容"),
                "content": str(parsed.get("content") or parsed.get("summary") or sample_content),
            }
    except json.JSONDecodeError:
        pass

    return {"title": sample_content[:80], "content": sample_content}


def _extract_json_candidate(content: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
    return fenced.group(1).strip() if fenced else content.strip()


def _auto_score_response(content: str) -> float:
    if not content:
        return 0.0

    auto_score = 2.0
    candidate = _extract_json_candidate(content)
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict) and parsed:
            auto_score += 2.0
            auto_score += min(len(parsed.keys()) * 0.2, 1.0)
        elif isinstance(parsed, list) and parsed:
            auto_score += 1.5
        else:
            auto_score += 0.5
    except json.JSONDecodeError:
        if len(content) > 50:
            auto_score += 1.0

    return round(min(5.0, auto_score), 1)


# ── Pydantic schemas ──────────────────────────────────────────────────


class ModelCreateRequest(BaseModel):
    preset_key: Optional[str] = None
    name: Optional[str] = Field(None, description="显示名称")
    provider: Optional[str] = Field(None, description="litellm provider")
    model_id: Optional[str] = Field(None, description="litellm model string")
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    enabled: bool = True
    routing_group: str = "default"
    model_family: Optional[str] = None
    channel_name: Optional[str] = None
    routing_priority: int = Field(100, ge=1, le=1000)
    cooldown_seconds: int = Field(300, ge=0, le=3600)
    temperature: float = Field(0.3, ge=0, le=2)
    max_tokens: int = Field(2000, ge=256, le=16000)
    requests_per_minute: int = Field(30, ge=1, le=120)
    description: Optional[str] = None
    cost_per_1k_input: Optional[float] = None
    cost_per_1k_output: Optional[float] = None
    cost_per_1m_input: Optional[float] = None
    cost_per_1m_input_cache_hit: Optional[float] = None
    cost_per_1m_output: Optional[float] = None
    extra_params: Optional[dict] = None

    @field_validator("preset_key", "api_key", "api_base", "model_family", "channel_name", mode="before")
    @classmethod
    def normalize_optional_secret(cls, value):
        return _normalize_optional_config_value(value)

    @field_validator("routing_group", mode="before")
    @classmethod
    def normalize_routing_group(cls, value):
        return _normalize_optional_config_value(value) or "default"


class ModelUpdateRequest(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model_id: Optional[str] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    enabled: Optional[bool] = None
    routing_group: Optional[str] = None
    model_family: Optional[str] = None
    channel_name: Optional[str] = None
    routing_priority: Optional[int] = Field(None, ge=1, le=1000)
    cooldown_seconds: Optional[int] = Field(None, ge=0, le=3600)
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, ge=256, le=16000)
    requests_per_minute: Optional[int] = Field(None, ge=1, le=120)
    description: Optional[str] = None
    cost_per_1k_input: Optional[float] = None
    cost_per_1k_output: Optional[float] = None
    cost_per_1m_input: Optional[float] = None
    cost_per_1m_input_cache_hit: Optional[float] = None
    cost_per_1m_output: Optional[float] = None
    extra_params: Optional[dict] = None

    @field_validator("api_key", "api_base", "model_family", "channel_name", mode="before")
    @classmethod
    def normalize_optional_secret(cls, value):
        return _normalize_optional_config_value(value)

    @field_validator("routing_group", mode="before")
    @classmethod
    def normalize_routing_group(cls, value):
        if value is None:
            return None
        return _normalize_optional_config_value(value) or "default"


class EvalRunRequest(BaseModel):
    """Request to run an A/B evaluation."""

    model_ids: list[int] = Field(..., description="要对比的模型 ID 列表")
    prompt_type: str = Field(
        "analysis", description="测评类型: analysis/daily_report/weekly_digest/classification/custom"
    )
    custom_prompt: Optional[str] = Field(None, description="自定义 prompt (prompt_type=custom 时必填)")
    sample_content: Optional[str] = Field(None, description="用于测评的内容样例(JSON)")


class ScoreRequest(BaseModel):
    quality_score: float = Field(..., ge=1, le=5, description="人工打分 1-5")
    notes: Optional[str] = None


async def _retry_write(db: AsyncSession, operation):
    async def _wrapped():
        if database_profile.is_sqlite and not db.in_transaction():
            await begin_immediate_for_sqlite(db)
        return await operation()

    return await retry_sqlite_locked(_wrapped, on_retry=db.rollback)


async def _retry_write_and_invalidate_models(db: AsyncSession, operation):
    result = await _retry_write(db, operation)
    await db.commit()
    await invalidate_model_cache()
    invalidate_model_list_cache()
    return result


def _per_1k_to_1m(value: Optional[float]) -> Optional[float]:
    return round(value * 1000, 6) if value is not None else None


def _per_1m_to_1k(value: Optional[float]) -> Optional[float]:
    return round(value / 1000, 9) if value is not None else None


def _pricing_extra_params(extra_params: Optional[dict], cache_hit_price: Optional[float]) -> Optional[dict]:
    params = dict(extra_params or {})
    if cache_hit_price is None:
        params.pop("cost_per_1m_input_cache_hit", None)
    else:
        params["cost_per_1m_input_cache_hit"] = cache_hit_price
    if any(key.startswith("cost_per_1m_") for key in params):
        params.setdefault("pricing_unit", "per_1m_tokens")
    return params or None


def _model_cost_input(req: ModelCreateRequest | ModelUpdateRequest) -> Optional[float]:
    if req.cost_per_1m_input is not None:
        return _per_1m_to_1k(req.cost_per_1m_input)
    return req.cost_per_1k_input


def _model_cost_output(req: ModelCreateRequest | ModelUpdateRequest) -> Optional[float]:
    if req.cost_per_1m_output is not None:
        return _per_1m_to_1k(req.cost_per_1m_output)
    return req.cost_per_1k_output


def _model_payload(m: LlmModel) -> dict:
    pricing = normalized_model_pricing(m)
    return {
        "id": m.id,
        "owner_user_id": m.owner_user_id,
        "scope": m.scope,
        "name": m.name,
        "provider": m.provider,
        "model_id": m.model_id,
        "resolved_model": _resolve_litellm_model(m),
        "api_base": m.api_base,
        "api_key_set": bool(m.api_key),
        "enabled": m.enabled,
        "routing_group": m.routing_group,
        "model_family": m.model_family,
        "channel_name": m.channel_name,
        "routing_priority": m.routing_priority,
        "cooldown_seconds": m.cooldown_seconds,
        "temperature": m.temperature,
        "max_tokens": m.max_tokens,
        "requests_per_minute": m.requests_per_minute,
        "description": m.description,
        "cost_per_1k_input": pricing["cost_per_1k_input"],
        "cost_per_1k_output": pricing["cost_per_1k_output"],
        "cost_per_1m_input": pricing["cost_per_1m_input"],
        "cost_per_1m_input_cache_hit": pricing["cost_per_1m_input_cache_hit"],
        "cost_per_1m_output": pricing["cost_per_1m_output"],
        "extra_params": m.extra_params,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _ensure_custom_ai_allowed(user: User) -> None:
    if not plan_allows_custom_ai(user.plan):
        raise HTTPException(status_code=403, detail="自定义 AI 配置仅对付费用户开放")


def _materialize_create_request(req: ModelCreateRequest) -> ModelCreateRequest:
    payload = req.model_dump(exclude_unset=True)
    preset_key = payload.pop("preset_key", req.preset_key)
    payload = apply_model_preset(payload, preset_key)
    missing = [field for field in ("name", "provider", "model_id") if not payload.get(field)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"模型配置缺少必填项：{', '.join(missing)}。请选择预设或补齐字段。",
        )
    return ModelCreateRequest(**payload)


def _apply_model_request(model: LlmModel, req: ModelCreateRequest | ModelUpdateRequest) -> None:
    update_data = req.model_dump(exclude_unset=True)
    for api_only_key in ("preset_key", "cost_per_1m_input", "cost_per_1m_input_cache_hit", "cost_per_1m_output"):
        update_data.pop(api_only_key, None)
    if "cost_per_1m_input" in req.model_fields_set:
        update_data["cost_per_1k_input"] = _per_1m_to_1k(req.cost_per_1m_input)
    if "cost_per_1m_output" in req.model_fields_set:
        update_data["cost_per_1k_output"] = _per_1m_to_1k(req.cost_per_1m_output)
    if "cost_per_1m_input_cache_hit" in req.model_fields_set:
        update_data["extra_params"] = _pricing_extra_params(
            update_data.get("extra_params", model.extra_params),
            req.cost_per_1m_input_cache_hit,
        )
    for key, value in update_data.items():
        setattr(model, key, value)

    if is_free_model(model.model_id):
        model.cost_per_1k_input = 0.0
        model.cost_per_1k_output = 0.0
        model.extra_params = _pricing_extra_params(model.extra_params, 0.0)


def _new_model_from_request(
    req: ModelCreateRequest,
    *,
    owner_user_id: int | None = None,
    scope: str = "system",
) -> LlmModel:
    req = _materialize_create_request(req)
    cost_per_1k_input = _model_cost_input(req)
    cost_per_1k_output = _model_cost_output(req)
    cache_hit_price = req.cost_per_1m_input_cache_hit
    if is_free_model(req.model_id):
        cost_per_1k_input = 0.0
        cost_per_1k_output = 0.0
        cache_hit_price = 0.0
    return LlmModel(
        owner_user_id=owner_user_id,
        scope=scope,
        name=req.name,
        provider=req.provider,
        model_id=req.model_id,
        api_key=req.api_key,
        api_base=req.api_base,
        enabled=req.enabled,
        routing_group=req.routing_group or "default",
        model_family=req.model_family,
        channel_name=req.channel_name,
        routing_priority=req.routing_priority,
        cooldown_seconds=req.cooldown_seconds,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        requests_per_minute=req.requests_per_minute,
        description=req.description,
        cost_per_1k_input=cost_per_1k_input,
        cost_per_1k_output=cost_per_1k_output,
        extra_params=_pricing_extra_params(req.extra_params, cache_hit_price),
    )


# ── Model Config CRUD ─────────────────────────────────────────────────


@router.get("", dependencies=[Depends(get_current_admin_user)])
async def list_models(db: AsyncSession = Depends(get_db)):
    """List all configured LLM models."""
    cached = get_cached_model_list(ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={MODEL_LIST_CACHE_HEADER: f"HIT; age={age_seconds:.3f}s"},
        )

    result = await db.execute(
        select(LlmModel)
        .where(LlmModel.owner_user_id.is_(None))
        .order_by(LlmModel.routing_group, LlmModel.routing_priority, LlmModel.id)
    )
    models = result.scalars().all()
    payload = {
        "models": [_model_payload(m) for m in models],
        "total": len(models),
    }
    content = set_cached_model_list(payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={MODEL_LIST_CACHE_HEADER: "MISS"},
    )


@router.post("", dependencies=[Depends(get_current_admin_user)])
async def create_model(req: ModelCreateRequest, db: AsyncSession = Depends(get_db)):
    """Add a new LLM model configuration."""

    async def _create():
        model = _new_model_from_request(req)
        db.add(model)
        await db.flush()
        return {"id": model.id, "name": model.name, "message": "模型配置创建成功"}

    return await _retry_write_and_invalidate_models(db, _create)


@router.get("/me")
async def list_my_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(LlmModel)
        .where(LlmModel.owner_user_id == current_user.id)
        .order_by(LlmModel.routing_group, LlmModel.routing_priority, LlmModel.id)
    )
    models = result.scalars().all()
    return {
        "models": [_model_payload(m) for m in models],
        "total": len(models),
        "custom_ai_allowed": plan_allows_custom_ai(current_user.plan),
    }


@router.post("/me")
async def create_my_model(
    req: ModelCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_custom_ai_allowed(current_user)

    async def _create():
        model = _new_model_from_request(req, owner_user_id=current_user.id, scope="user")
        db.add(model)
        await db.flush()
        return {"id": model.id, "name": model.name, "message": "自定义 AI 配置创建成功"}

    return await _retry_write_and_invalidate_models(db, _create)


@router.get("/presets")
async def get_model_presets(_current_user: User = Depends(get_current_user)):
    return list_model_presets()


@router.put("/me/{model_id}")
async def update_my_model(
    model_id: int,
    req: ModelUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_custom_ai_allowed(current_user)

    async def _update():
        result = await db.execute(
            select(LlmModel).where(LlmModel.id == model_id, LlmModel.owner_user_id == current_user.id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(404, f"Model {model_id} not found")
        _apply_model_request(model, req)
        model.scope = "user"
        model.owner_user_id = current_user.id
        await db.flush()
        return {"message": f"自定义 AI {model.name} 更新成功"}

    return await _retry_write_and_invalidate_models(db, _update)


@router.delete("/me/{model_id}")
async def delete_my_model(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    async def _delete():
        result = await db.execute(
            select(LlmModel).where(LlmModel.id == model_id, LlmModel.owner_user_id == current_user.id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(404, f"Model {model_id} not found")
        name = model.name
        await db.delete(model)
        await db.flush()
        return {"message": f"自定义 AI {name} 已删除"}

    return await _retry_write_and_invalidate_models(db, _delete)


@router.get("/usage/summary")
async def get_usage_summary(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """Summarize token usage and estimated cost from request-level LLM call logs."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(LlmCallLog, LlmModel)
        .join(LlmModel, LlmCallLog.model_id == LlmModel.id, isouter=True)
        .where(LlmCallLog.created_at >= since)
        .order_by(desc(LlmCallLog.created_at))
    )
    rows = result.all()

    by_model: dict[int, dict] = {}
    by_prompt: dict[str, dict] = {}
    totals = {
        "calls": 0,
        "success_calls": 0,
        "failed_calls": 0,
        "tokens_input": 0,
        "tokens_output": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "billable_input_tokens": 0,
        "estimated_cost": 0.0,
        "duration_ms": 0,
    }

    for call_log, model in rows:
        tokens_input = call_log.input_tokens or 0
        tokens_output = call_log.output_tokens or 0
        estimated_cost = call_log.total_cost or 0
        is_done = call_log.status == "DONE"
        is_failed = call_log.status == "FAILED"

        totals["calls"] += 1
        totals["success_calls"] += 1 if is_done else 0
        totals["failed_calls"] += 1 if is_failed else 0
        totals["tokens_input"] += tokens_input
        totals["tokens_output"] += tokens_output
        totals["cache_read_tokens"] += call_log.cache_read_tokens or 0
        totals["cache_creation_tokens"] += call_log.cache_creation_tokens or 0
        totals["billable_input_tokens"] += call_log.billable_input_tokens or 0
        totals["estimated_cost"] += estimated_cost
        totals["duration_ms"] += call_log.duration_ms or 0

        model_key = call_log.model_id or 0
        if model_key not in by_model:
            by_model[model_key] = {
                "model_id": call_log.model_id,
                "model_name": model.name if model else (call_log.model_name or call_log.actual_model or "未配置模型"),
                "provider": model.provider if model else call_log.provider,
                "calls": 0,
                "success_calls": 0,
                "failed_calls": 0,
                "tokens_input": 0,
                "tokens_output": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "billable_input_tokens": 0,
                "estimated_cost": 0.0,
                "avg_duration_ms": 0,
                "cost_per_1k_input": model.cost_per_1k_input if model else None,
                "cost_per_1k_output": model.cost_per_1k_output if model else None,
                "cost_per_1m_input": _per_1k_to_1m(model.cost_per_1k_input) if model else None,
                "cost_per_1m_input_cache_hit": (
                    model.extra_params.get("cost_per_1m_input_cache_hit")
                    if model and isinstance(model.extra_params, dict)
                    else None
                ),
                "cost_per_1m_output": _per_1k_to_1m(model.cost_per_1k_output) if model else None,
            }
        model_stats = by_model[model_key]
        model_stats["calls"] += 1
        model_stats["success_calls"] += 1 if is_done else 0
        model_stats["failed_calls"] += 1 if is_failed else 0
        model_stats["tokens_input"] += tokens_input
        model_stats["tokens_output"] += tokens_output
        model_stats["cache_read_tokens"] += call_log.cache_read_tokens or 0
        model_stats["cache_creation_tokens"] += call_log.cache_creation_tokens or 0
        model_stats["billable_input_tokens"] += call_log.billable_input_tokens or 0
        model_stats["estimated_cost"] += estimated_cost
        model_stats["avg_duration_ms"] += call_log.duration_ms or 0

        prompt_key = call_log.scene
        if prompt_key not in by_prompt:
            by_prompt[prompt_key] = {
                "prompt_type": prompt_key,
                "calls": 0,
                "success_calls": 0,
                "failed_calls": 0,
                "tokens_input": 0,
                "tokens_output": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "billable_input_tokens": 0,
                "estimated_cost": 0.0,
            }
        prompt_stats = by_prompt[prompt_key]
        prompt_stats["calls"] += 1
        prompt_stats["success_calls"] += 1 if is_done else 0
        prompt_stats["failed_calls"] += 1 if is_failed else 0
        prompt_stats["tokens_input"] += tokens_input
        prompt_stats["tokens_output"] += tokens_output
        prompt_stats["cache_read_tokens"] += call_log.cache_read_tokens or 0
        prompt_stats["cache_creation_tokens"] += call_log.cache_creation_tokens or 0
        prompt_stats["billable_input_tokens"] += call_log.billable_input_tokens or 0
        prompt_stats["estimated_cost"] += estimated_cost

    for stats in by_model.values():
        stats["estimated_cost"] = round(stats["estimated_cost"], 6)
        stats["avg_duration_ms"] = int(stats["avg_duration_ms"] / stats["calls"]) if stats["calls"] else 0

    for stats in by_prompt.values():
        stats["estimated_cost"] = round(stats["estimated_cost"], 6)

    total_tokens = totals["tokens_input"] + totals["tokens_output"]
    avg_duration = int(totals["duration_ms"] / totals["calls"]) if totals["calls"] else 0
    success_rate = round(totals["success_calls"] / totals["calls"], 4) if totals["calls"] else 0

    return {
        "days": days,
        "since": since.isoformat(),
        "total": {
            "calls": totals["calls"],
            "success_calls": totals["success_calls"],
            "failed_calls": totals["failed_calls"],
            "tokens_input": totals["tokens_input"],
            "tokens_output": totals["tokens_output"],
            "cache_read_tokens": totals["cache_read_tokens"],
            "cache_creation_tokens": totals["cache_creation_tokens"],
            "billable_input_tokens": totals["billable_input_tokens"],
            "tokens_total": total_tokens,
            "estimated_cost": round(totals["estimated_cost"], 6),
            "avg_duration_ms": avg_duration,
            "success_rate": success_rate,
        },
        "by_model": sorted(by_model.values(), key=lambda item: item["estimated_cost"], reverse=True),
        "by_prompt": sorted(by_prompt.values(), key=lambda item: item["estimated_cost"], reverse=True),
    }


@router.put("/{model_id}", dependencies=[Depends(get_current_admin_user)])
async def update_model(model_id: int, req: ModelUpdateRequest, db: AsyncSession = Depends(get_db)):
    """Update an existing model configuration."""

    async def _update():
        result = await db.execute(select(LlmModel).where(LlmModel.id == model_id, LlmModel.owner_user_id.is_(None)))
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(404, f"Model {model_id} not found")

        _apply_model_request(model, req)
        await db.flush()
        return {"message": f"模型 {model.name} 更新成功"}

    return await _retry_write_and_invalidate_models(db, _update)


@router.delete("/{model_id}", dependencies=[Depends(get_current_admin_user)])
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a model configuration."""

    async def _delete():
        result = await db.execute(select(LlmModel).where(LlmModel.id == model_id, LlmModel.owner_user_id.is_(None)))
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(404, f"Model {model_id} not found")
        name = model.name
        await db.delete(model)
        await db.flush()
        return {"message": f"模型 {name} 已删除"}

    return await _retry_write_and_invalidate_models(db, _delete)


@router.post("/{model_id}/test", dependencies=[Depends(get_current_admin_user)])
async def test_model(model_id: int, db: AsyncSession = Depends(get_db)):
    """Test a model by sending a simple prompt."""
    from litellm import completion

    result = await db.execute(select(LlmModel).where(LlmModel.id == model_id, LlmModel.owner_user_id.is_(None)))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(404, f"Model {model_id} not found")

    if _missing_explicit_api_key(model):
        return {
            "status": "failed",
            "model_name": model.name,
            "error": "模型配置缺少 API Key，请在模型配置中补充后再测试。",
            "duration_ms": 0,
        }

    resolved_model = _resolve_litellm_model(model)

    test_prompt = "请用一句话介绍你自己，包括你的模型名称。"
    kwargs = _completion_kwargs(
        model,
        resolved_model,
        [{"role": "user", "content": test_prompt}],
        temperature=0.3,
        max_tokens=200,
    )

    start = time.monotonic()
    try:
        response = await asyncio.to_thread(completion, **kwargs)
        duration_ms = int((time.monotonic() - start) * 1000)
        content = response.choices[0].message.content or ""
        usage = extract_usage(response)
        await record_llm_call_in_new_session(
            model=model,
            request_model=resolved_model,
            scene="model_test",
            status="DONE",
            duration_ms=duration_ms,
            usage=usage,
        )
        return {
            "status": "success",
            "model_name": model.name,
            "response": content,
            "duration_ms": duration_ms,
            "tokens_input": usage.input_tokens,
            "tokens_output": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_creation_tokens": usage.cache_creation_tokens,
        }
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        await record_llm_call_in_new_session(
            model=model,
            request_model=resolved_model,
            scene="model_test",
            status="FAILED",
            duration_ms=duration_ms,
            error_message=str(e),
        )
        return {
            "status": "failed",
            "model_name": model.name,
            "error": str(e),
            "duration_ms": duration_ms,
        }


# ── Evaluation A/B ────────────────────────────────────────────────────

# Standard test prompts for each type
EVAL_PROMPTS = {
    "analysis": """分析以下内容的选题价值，从创作者角度评估。

标题：{title}
内容摘要：{content}

请以 JSON 格式返回：
{{
  "creator_score": 0-100,
  "viral_score": 0-100,
  "quality_score": 0-100,
  "summary": "一句话总结",
  "recommendation": "选题建议(50字内)",
  "tags": ["标签1", "标签2", "标签3"]
}}""",
    "daily_report": """基于以下今日热门内容，生成一份创作者日报摘要。

热门内容（前5条）：
{content}

请以 JSON 格式返回：
{{
  "overview": "今日概述(100字)",
  "takeaway": "今日要点(50字)",
  "keywords": ["关键词1", "关键词2"],
  "trends": [{{"title": "趋势名", "desc": "描述"}}]
}}""",
    "weekly_digest": """基于以下本周热门内容，生成一份创作者周刊摘要。

本周热门内容：
{content}

请以 JSON 格式返回：
{{
  "overview": "本周概述(150字)",
  "takeaway": "本周要点(50字)",
  "keywords": ["关键词1", "关键词2"],
  "trends": [{{"title": "趋势名", "desc": "描述"}}],
  "top_picks": [{{"title": "选题", "reason": "推荐理由"}}]
}}""",
    "classification": """对以下内容进行分类。

标题：{title}

请返回 JSON：
{{
  "category": "分类名",
  "subcategory": "子分类",
  "confidence": 0.0-1.0
}}""",
}


async def _run_one_evaluation(
    *,
    model,
    eval_id: int,
    prompt_type: str,
    prompt_text: str,
    write_lock: Optional[asyncio.Lock] = None,
) -> None:
    from litellm import completion

    async def _run_db_write(operation):
        if write_lock is None:
            return await operation()
        async with write_lock:
            return await operation()

    if _missing_explicit_api_key(model):

        async def _write_missing_key():
            async with async_session() as eval_db:

                async def _mark_missing_key():
                    result = await eval_db.execute(select(ModelEvaluation).where(ModelEvaluation.id == eval_id))
                    current = result.scalar_one()
                    current.status = "FAILED"
                    current.error_message = "模型配置缺少 API Key，请在模型配置中补充后再测评。"
                    await eval_db.flush()

                await _retry_write(eval_db, _mark_missing_key)
                await eval_db.commit()

        await _run_db_write(_write_missing_key)
        return

    resolved_model = _resolve_litellm_model(model)
    kwargs = _completion_kwargs(
        model,
        resolved_model,
        [{"role": "user", "content": prompt_text}],
        temperature=model.temperature,
        max_tokens=model.max_tokens,
    )

    start = time.monotonic()
    try:
        response = await asyncio.to_thread(completion, **kwargs)
        duration_ms = int((time.monotonic() - start) * 1000)
        content = response.choices[0].message.content or ""
        usage = extract_usage(response)

        async def _write_done():
            async with async_session() as eval_db:

                async def _mark_done():
                    result = await eval_db.execute(select(ModelEvaluation).where(ModelEvaluation.id == eval_id))
                    current = result.scalar_one()
                    current.status = "DONE"
                    current.response_text = content
                    current.duration_ms = duration_ms
                    current.tokens_input = usage.input_tokens
                    current.tokens_output = usage.output_tokens
                    current.auto_score = _auto_score_response(content)
                    await eval_db.flush()

                await _retry_write(eval_db, _mark_done)
                await eval_db.commit()

        await _run_db_write(_write_done)
        await record_llm_call_in_new_session(
            model=model,
            request_model=resolved_model,
            scene=f"evaluation:{prompt_type}",
            status="DONE",
            duration_ms=duration_ms,
            usage=usage,
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        error_message = str(e)

        async def _write_failed():
            async with async_session() as eval_db:

                async def _mark_failed():
                    result = await eval_db.execute(select(ModelEvaluation).where(ModelEvaluation.id == eval_id))
                    current = result.scalar_one()
                    current.status = "FAILED"
                    current.error_message = error_message[:2000]
                    current.duration_ms = duration_ms
                    await eval_db.flush()

                await _retry_write(eval_db, _mark_failed)
                await eval_db.commit()

        await _run_db_write(_write_failed)
        await record_llm_call_in_new_session(
            model=model,
            request_model=resolved_model,
            scene=f"evaluation:{prompt_type}",
            status="FAILED",
            duration_ms=duration_ms,
            error_message=error_message,
        )


@router.post("/evaluations/run", dependencies=[Depends(get_current_admin_user)])
async def run_evaluation(req: EvalRunRequest, db: AsyncSession = Depends(get_db)):
    """Run an A/B evaluation across selected models with the same prompt."""
    # Fetch models
    result = await db.execute(
        select(LlmModel).where(
            LlmModel.id.in_(req.model_ids),
            LlmModel.enabled == True,
            LlmModel.owner_user_id.is_(None),
        )
    )
    models = [_model_snapshot(model) for model in result.scalars().all()]
    if not models:
        raise HTTPException(400, "没有找到启用的模型")
    await db.rollback()

    # Build prompt
    prompt_template = EVAL_PROMPTS.get(req.prompt_type)
    if req.prompt_type == "custom" and req.custom_prompt:
        prompt_template = req.custom_prompt
    if not prompt_template:
        raise HTTPException(400, f"未知的测评类型: {req.prompt_type}")

    sample = _sample_payload(req.sample_content)
    prompt_text = prompt_template.format(title=sample["title"], content=sample["content"])

    # Create eval run
    eval_run_id = f"eval_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"

    evaluations = []

    async def _create_records():
        for model in models:
            eval_record = ModelEvaluation(
                eval_run_id=eval_run_id,
                model_id=model.id,
                model_name=model.name,
                prompt_type=req.prompt_type,
                prompt_text=prompt_text[:2000],
                status="PENDING",
            )
            db.add(eval_record)
            evaluations.append((model, eval_record))
        await db.flush()

    await _retry_write(db, _create_records)
    await db.commit()

    async def _mark_all_running():
        for _model, eval_record in evaluations:
            result = await db.execute(select(ModelEvaluation).where(ModelEvaluation.id == eval_record.id))
            current = result.scalar_one()
            current.status = "RUNNING"
        await db.flush()

    await _retry_write(db, _mark_all_running)
    await db.commit()

    concurrency = min(_normalize_evaluation_concurrency(), len(evaluations))
    semaphore = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()

    async def _run_with_limit(model, eval_record):
        async with semaphore:
            await _run_one_evaluation(
                model=model,
                eval_id=eval_record.id,
                prompt_type=req.prompt_type,
                prompt_text=prompt_text,
                write_lock=write_lock,
            )

    await asyncio.gather(*(_run_with_limit(model, eval_record) for model, eval_record in evaluations))

    return {
        "eval_run_id": eval_run_id,
        "model_count": len(models),
        "message": f"测评完成，共 {len(models)} 个模型",
    }


@router.get("/evaluations/runs", dependencies=[Depends(get_current_admin_user)])
async def list_eval_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all evaluation runs with summary stats."""
    # Get distinct run IDs with stats
    result = await db.execute(
        select(
            ModelEvaluation.eval_run_id,
            ModelEvaluation.prompt_type,
            func.count(ModelEvaluation.id).label("model_count"),
            func.min(ModelEvaluation.created_at).label("created_at"),
            func.sum(func.cast(ModelEvaluation.status == "DONE", SAInteger)).label("done_count"),
            func.sum(func.cast(ModelEvaluation.status == "FAILED", SAInteger)).label("fail_count"),
        )
        .group_by(ModelEvaluation.eval_run_id, ModelEvaluation.prompt_type)
        .order_by(desc(func.min(ModelEvaluation.created_at)))
        .limit(limit)
    )
    rows = result.all()

    return {
        "runs": [
            {
                "eval_run_id": r[0],
                "prompt_type": r[1],
                "model_count": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
                "done_count": r[4],
                "fail_count": r[5],
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/evaluations/runs/{run_id}", dependencies=[Depends(get_current_admin_user)])
async def get_eval_run(run_id: str, db: AsyncSession = Depends(get_db)):
    """Get all evaluation results for a specific run."""
    result = await db.execute(
        select(ModelEvaluation).where(ModelEvaluation.eval_run_id == run_id).order_by(ModelEvaluation.model_name)
    )
    evals = result.scalars().all()

    if not evals:
        raise HTTPException(404, f"Evaluation run {run_id} not found")

    return {
        "eval_run_id": run_id,
        "prompt_type": evals[0].prompt_type,
        "results": [
            {
                "id": e.id,
                "model_id": e.model_id,
                "model_name": e.model_name,
                "status": e.status,
                "response_text": e.response_text,
                "duration_ms": e.duration_ms,
                "tokens_input": e.tokens_input,
                "tokens_output": e.tokens_output,
                "quality_score": e.quality_score,
                "auto_score": e.auto_score,
                "notes": e.notes,
                "error_message": e.error_message,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in evals
        ],
    }


@router.put("/evaluations/{eval_id}/score", dependencies=[Depends(get_current_admin_user)])
async def score_evaluation(
    eval_id: int,
    req: ScoreRequest,
    db: AsyncSession = Depends(get_db),
):
    """Human-score a single evaluation result."""
    result = await db.execute(select(ModelEvaluation).where(ModelEvaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(404, f"Evaluation {eval_id} not found")

    evaluation.quality_score = req.quality_score
    if req.notes:
        evaluation.notes = req.notes
    await db.commit()
    return {"message": "评分已保存"}
