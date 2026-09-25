"""排序效果基准 admin API —— 标注管理 + 快照查询 + 触发评测。

路由前缀 /admin/ranking-eval，整组要求管理员身份。
标注三种来源：human（本 API 写入）、pick_mark（backfill 导入）、
behavioral（行为信号推断）；human / pick_mark 不会被行为刷新覆盖。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import User, get_current_admin_user
from app.core.database import get_db
from app.models.content import ContentItem
from app.repositories.content_label_repo import ContentLabelRepository
from app.repositories.ranking_eval_repo import RankingEvalRepository
from app.services import ranking_eval
from app.services.content_labeling import import_pick_mark_labels, rebuild_behavioral_labels

router = APIRouter(prefix="/admin/ranking-eval", dependencies=[Depends(get_current_admin_user)])

_VALID_LABELS = {"worth_writing", "not_worth", "uncertain"}


class HumanLabelRequest(BaseModel):
    label: str = Field(..., description="worth_writing | not_worth | uncertain")


class EvaluateRequest(BaseModel):
    hours: int = Field(168, ge=1, le=720)
    top_n: int = Field(10, ge=1, le=50)


@router.get("/snapshots")
async def list_snapshots(
    surface: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    snapshots = await RankingEvalRepository(db).list_snapshots(surface=surface, limit=limit)
    return {
        "items": [
            {
                "id": s.id,
                "surface": s.surface,
                "window_start": s.window_start.isoformat(),
                "window_end": s.window_end.isoformat(),
                "metrics": s.metrics,
                "scoring_config": s.scoring_config,
                "item_details": s.item_details,
                "created_at": s.created_at.isoformat(),
            }
            for s in snapshots
        ]
    }


@router.post("/evaluate")
async def evaluate(
    request: EvaluateRequest,
    db: AsyncSession = Depends(get_db),
):
    """评测当前时间窗并物化快照（同 surface+窗口起点覆盖更新）。"""
    try:
        snapshot = await ranking_eval.evaluate_and_store(db, hours=request.hours, top_n=request.top_n)
    except Exception as exc:
        raise HTTPException(503, f"ranking evaluation failed: {exc}") from exc
    return {
        "id": snapshot.id,
        "surface": snapshot.surface,
        "window_start": snapshot.window_start.isoformat(),
        "metrics": snapshot.metrics,
    }


@router.get("/labels")
async def list_labels(
    source: str | None = Query(None, pattern=r"^(human|pick_mark|behavioral)$"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    rows = await ContentLabelRepository(db).list_with_titles(source=source, limit=limit)
    return {
        "items": [
            {
                "content_id": label.content_id,
                "title": title,
                "label": label.label,
                "source": label.source,
                "confidence": label.confidence,
                "evidence": label.evidence,
                "updated_at": label.updated_at.isoformat(),
            }
            for label, title in rows
        ]
    }


@router.put("/labels/{content_id}")
async def set_human_label(
    content_id: int,
    request: HumanLabelRequest,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """人工标注（口径校准地面真值，覆盖任何已有来源）。"""
    if request.label not in _VALID_LABELS:
        raise HTTPException(422, f"label must be one of {sorted(_VALID_LABELS)}")
    item = await db.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(404, "Content not found")
    label = await ContentLabelRepository(db).set_authoritative(
        content_id,
        request.label,
        source="human",
        labeled_by=admin.id,
    )
    await db.commit()
    return {
        "content_id": content_id,
        "label": label.label,
        "source": label.source,
        "labeled_by": label.labeled_by,
    }


@router.post("/labels/rebuild")
async def rebuild_labels(db: AsyncSession = Depends(get_db)):
    """重建行为弱标注 + 导入日报 pick_mark 标注（幂等，可重复执行）。"""
    behavioral = await rebuild_behavioral_labels(db)
    pick_mark = await import_pick_mark_labels(db)
    return {"behavioral": behavioral, "pick_mark": pick_mark}
