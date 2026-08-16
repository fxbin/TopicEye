"""LLM Model Evaluation A/B subsystem.

Routes:
- POST /models/evaluations/run        Run an A/B evaluation across selected models
- GET  /models/evaluations/runs       List runs with summary stats
- GET  /models/evaluations/runs/{id}  Get all results for one run
- PUT  /models/evaluations/{id}/score Human-score one result

从 llm_models.py 拆出，共享 helper（_missing_explicit_api_key /
_completion_kwargs / _retry_write / _resolve_litellm_model / _model_snapshot）
继续从 llm_models 模块导入。
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user

# 从父模块导入共享 helper（test_model 和 evaluation 都用）
from app.api.v1.llm_models import (
    _completion_kwargs,
    _missing_explicit_api_key,
    _model_snapshot,
    _resolve_litellm_model,
)
from app.core.config import settings
from app.core.database import async_session, get_db
from app.models.llm_model import ModelEvaluation
from app.repositories.llm_evaluation_repo import ModelEvaluationRepository
from app.repositories.llm_model_repo import LlmModelRepository
from app.services.llm_usage import extract_usage, record_llm_call_in_new_session

# _retry_write 已移除——PostgreSQL 不需要应用层重试

router = APIRouter(prefix="/models", tags=["models"])


# ─── Evaluation helpers (仅此子系统使用) ──────────────────────────────


def _normalize_evaluation_concurrency(value: int | None = None) -> int:
    raw = value if value is not None else settings.LLM_WORKER_CONCURRENCY
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(parsed, 8))


def _sample_payload(sample_content: str | None) -> dict:
    if sample_content:
        return {"title": sample_content[:80], "content": sample_content[:2000]}
    return {
        "title": "深度学习在自然语言处理中的最新进展",
        "content": "近年来,Transformer 架构及其变体在多个 NLP 基准测试中刷新了 SOTA...",
    }


def _extract_json_candidate(content: str) -> str:
    match = re.search(r"\{[\s\S]*\}", content)
    return match.group(0) if match else content.strip()


def _auto_score_response(content: str) -> float:
    """Heuristic auto score for evaluation results (0-100)."""
    candidate = _extract_json_candidate(content)
    if not candidate or len(candidate) < 10:
        return 0.0
    try:
        import json

        data = json.loads(candidate)
        if not isinstance(data, dict):
            return 0.0
        scores = [v for v in data.values() if isinstance(v, int | float)]
        if scores:
            return float(min(100.0, max(0.0, sum(scores) / len(scores))))
    except Exception:
        pass
    return min(100.0, float(len(candidate)))


# ─── Standard test prompts for each type ──────────────────────────────

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


# ─── Request schemas (Evaluation-specific) ────────────────────────────


class EvalRunRequest(BaseModel):
    model_ids: list[int] = Field(..., min_length=2, description="参与测评的模型 ID 列表")
    prompt_type: str = Field(..., description="测评类型")
    custom_prompt: Optional[str] = Field(None, description="自定义 prompt")
    sample_content: Optional[str] = Field(None, description="示例内容")


class ScoreRequest(BaseModel):
    quality_score: float = Field(..., ge=0, le=100)
    notes: Optional[str] = None


# ─── Single evaluation runner ─────────────────────────────────────────


async def _run_one_evaluation(
    *,
    model,
    eval_id: int,
    prompt_type: str,
    prompt_text: str,
    write_lock: asyncio.Lock | None = None,
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
                    current = await ModelEvaluationRepository(eval_db).get_by_id(eval_id)
                    if current is None:
                        raise RuntimeError(f"Evaluation {eval_id} not found")
                    current.status = "FAILED"
                    current.error_message = "模型配置缺少 API Key，请在模型配置中补充后再测评。"
                    await eval_db.flush()

                await _mark_missing_key()
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
                    current = await ModelEvaluationRepository(eval_db).get_by_id(eval_id)
                    if current is None:
                        raise RuntimeError(f"Evaluation {eval_id} not found")
                    current.status = "DONE"
                    current.response_text = content
                    current.duration_ms = duration_ms
                    current.tokens_input = usage.input_tokens
                    current.tokens_output = usage.output_tokens
                    current.auto_score = _auto_score_response(content)
                    await eval_db.flush()

                await _mark_done()
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
                    current = await ModelEvaluationRepository(eval_db).get_by_id(eval_id)
                    if current is None:
                        raise RuntimeError(f"Evaluation {eval_id} not found")
                    current.status = "FAILED"
                    current.error_message = error_message[:2000]
                    current.duration_ms = duration_ms
                    await eval_db.flush()

                await _mark_failed()
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


# ─── Routes ──────────────────────────────────────────────────────────


@router.post("/evaluations/run", dependencies=[Depends(get_current_admin_user)])
async def run_evaluation(req: EvalRunRequest, db: AsyncSession = Depends(get_db)):
    """Run an A/B evaluation across selected models with the same prompt."""
    # Fetch models
    models = [_model_snapshot(model) for model in await LlmModelRepository(db).list_enabled_by_ids(req.model_ids)]
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
    eval_run_id = f"eval_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"

    evaluations = []

    async def _create_records():
        eval_repo = ModelEvaluationRepository(db)
        for model in models:
            eval_record = ModelEvaluation(
                eval_run_id=eval_run_id,
                model_id=model.id,
                model_name=model.name,
                prompt_type=req.prompt_type,
                prompt_text=prompt_text[:2000],
                status="PENDING",
            )
            eval_repo.add_instance(eval_record)
            evaluations.append((model, eval_record))
        await db.flush()

    await _create_records()
    await db.commit()

    async def _mark_all_running():
        eval_repo = ModelEvaluationRepository(db)
        for _model, eval_record in evaluations:
            current = await eval_repo.get_by_id(eval_record.id)
            if current is None:
                raise RuntimeError(f"Evaluation {eval_record.id} not found")
            current.status = "RUNNING"
            await db.flush()

    await _mark_all_running()
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
    rows = await ModelEvaluationRepository(db).aggregate_runs_with_stats(limit=limit)

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
    evals = await ModelEvaluationRepository(db).list_by_run_id(run_id)

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
    evaluation = await ModelEvaluationRepository(db).get_by_id(eval_id)
    if not evaluation:
        raise HTTPException(404, f"Evaluation {eval_id} not found")

    evaluation.quality_score = req.quality_score
    if req.notes:
        evaluation.notes = req.notes
    await db.commit()
    return {"message": "评分已保存"}
