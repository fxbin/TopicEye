"""
母题相关 API。
提供母题的 CRUD、关键词打分、内容匹配接口。

多租户模型（路线 C：系统模板库 + 用户 fork）：
- owner_user_id IS NULL  → 系统模板，admin 维护，用户只读
- owner_user_id = <uid>   → 用户私有 fork，用户可自由改/加/停用
- 新用户首次访问时调 POST /fork-defaults 复制一份系统模板到自己名下
- 打分接口按「系统模板 + 当前用户的 fork」过滤，确保用户改了能生效
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.mother_topic import MotherTopic
from app.models.user import User
from app.repositories.content_repo import ContentRepo
from app.repositories.mother_topic_repo import MotherTopicRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mother-topics", tags=["母题"])


# ── Pydantic 请求/响应模型 ─────────────────────────────────────────────


class MotherTopicBase(BaseModel):
    name: str
    description: str | None = None
    keywords: list[str] = []
    weight: float = 1.0
    content_type: str | None = None
    target_reader: str | None = None
    is_active: bool = True
    display_order: int = 0


class MotherTopicCreate(MotherTopicBase):
    pass


class MotherTopicUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    keywords: list[str] | None = None
    weight: float | None = None
    content_type: str | None = None
    target_reader: str | None = None
    is_active: bool | None = None
    display_order: int | None = None


class MotherTopicOut(MotherTopicBase):
    id: int
    owner_user_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj) -> MotherTopicOut:
        """Convert SQLAlchemy model to dict, serializing datetimes."""
        d = {
            "id": obj.id,
            "name": obj.name,
            "description": obj.description,
            "keywords": obj.keywords,
            "weight": obj.weight,
            "content_type": obj.content_type,
            "target_reader": obj.target_reader,
            "is_active": obj.is_active,
            "display_order": obj.display_order,
            "owner_user_id": obj.owner_user_id,
            "created_at": obj.created_at.isoformat() if obj.created_at else None,
            "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
        }
        return cls(**d)


class ContentScoringRequest(BaseModel):
    title: str
    summary: str | None = ""
    source: str | None = None
    hot_value: int = 0


class ContentScoringResult(BaseModel):
    title: str
    topic_scores: list[dict]  # [{name, score, weight, final}]
    top_topic: str | None
    final_score: float


# ── helpers ───────────────────────────────────────────────────────────


async def _load_visible_topics(db: AsyncSession, user_id: int, active_only: bool = False) -> list[MotherTopic]:
    """加载当前用户可见的母题列表。"""
    repo = MotherTopicRepository(db)
    return list(await repo.list_visible_for_user(user_id=user_id, active_only=active_only))


def _assert_can_modify(topic: MotherTopic, current_user: User) -> None:
    """校验当前用户是否有权修改/删除该母题。

    - 系统模板（owner_user_id IS NULL）：仅 admin 可改
    - 用户私有 fork：仅 owner 可改
    """
    if topic.owner_user_id is None:
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="系统模板不可修改，请先 fork 到自己的母题")
    elif topic.owner_user_id != current_user.id:
        # Mask as 404 to avoid leaking existence (与 sources /me 模式一致)
        raise HTTPException(status_code=404, detail="母题不存在")


# ── 路由 ─────────────────────────────────────────────────────────────


@router.get("", response_model=list[MotherTopicOut], include_in_schema=False)
@router.get("/", response_model=list[MotherTopicOut])
async def list_mother_topics(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户可见的母题（系统模板 + 自己的 fork）。

    admin 可看到全量（含其他用户的私有母题）用于审计；active_only=false
    不再是 admin-only —— 普通用户也能看自己名下的停用母题。
    """
    repo = MotherTopicRepository(db)
    if current_user.role == "admin":
        # admin 看全量（含其他用户的私有 fork，用于审计）
        topics = await repo.list_all_for_admin(active_only=active_only)
    else:
        topics = await repo.list_visible_for_user(user_id=current_user.id, active_only=active_only)
    return [MotherTopicOut.from_orm_model(t) for t in topics]


@router.post("", response_model=MotherTopicOut, include_in_schema=False)
@router.post("/", response_model=MotherTopicOut)
async def create_mother_topic(
    topic_in: MotherTopicCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建母题。

    - admin 创建系统模板（owner_user_id=None）
    - 普通用户创建私有 fork（owner_user_id=current_user.id）
    """
    # 普通用户创建私有母题；admin 创建系统模板
    owner_user_id = None if current_user.role == "admin" else current_user.id

    # 同 scope 内 name 唯一性校验（DB 层有 unique constraint 兜底，这里提前拦截给更好的错误信息）
    repo = MotherTopicRepository(db)
    existing = await repo.find_by_name_in_scope(name=topic_in.name, owner_user_id=owner_user_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"母题「{topic_in.name}」已存在")

    topic = MotherTopic(
        name=topic_in.name,
        description=topic_in.description,
        keywords=topic_in.keywords,
        weight=topic_in.weight,
        content_type=topic_in.content_type,
        target_reader=topic_in.target_reader,
        is_active=topic_in.is_active,
        display_order=topic_in.display_order,
        owner_user_id=owner_user_id,
    )
    repo.add_instance(topic)
    await db.commit()
    await db.refresh(topic)
    return MotherTopicOut.from_orm_model(topic)


@router.post("/fork-defaults")
async def fork_default_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把系统模板（owner_user_id IS NULL）复制一份到当前用户名下。

    幂等：用户已有的同名母题会被跳过。admin 调用无意义（admin 本就能改系统模板），
    但不强制拦截 —— 便于测试。
    """
    repo = MotherTopicRepository(db)
    if current_user.role == "admin":
        # admin 不需要 fork，直接返回当前系统模板数
        templates = await repo.list_system_templates()
        return {"forked": 0, "skipped": len(templates), "message": "管理员无需 fork，可直接维护系统模板"}

    # 加载所有系统模板
    templates = await repo.list_system_templates()

    # 加载用户已有的母题名，用于跳过
    user_names = await repo.list_user_topic_names(current_user.id)

    forked = 0
    skipped = 0
    for tpl in templates:
        if tpl.name in user_names:
            skipped += 1
            continue
        fork = MotherTopic(
            name=tpl.name,
            description=tpl.description,
            keywords=list(tpl.keywords or []),
            weight=tpl.weight,
            content_type=tpl.content_type,
            target_reader=tpl.target_reader,
            is_active=tpl.is_active,
            display_order=tpl.display_order,
            owner_user_id=current_user.id,
        )
        repo.add_instance(fork)
        forked += 1

    if forked > 0:
        await db.commit()

    return {
        "forked": forked,
        "skipped": skipped,
        "message": f"已 fork {forked} 个系统母题" + (f"，跳过 {skipped} 个已存在" if skipped else ""),
    }


@router.put("/{topic_id}", response_model=MotherTopicOut)
async def update_mother_topic(
    topic_id: int,
    update_in: MotherTopicUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新母题。

    - 系统模板（owner IS NULL）：仅 admin 可改
    - 用户私有 fork：仅 owner 可改
    """
    repo = MotherTopicRepository(db)
    topic = await repo.get_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="母题不存在")
    _assert_can_modify(topic, current_user)

    payload = update_in.model_dump(exclude_unset=True)
    # 不允许通过 update 修改 owner_user_id（防越权）
    payload.pop("owner_user_id", None)

    # 如果改了 name，校验同 scope 内不重名
    if "name" in payload and payload["name"] != topic.name:
        dup = await repo.find_duplicate_name_excluding_id(
            name=payload["name"],
            owner_user_id=topic.owner_user_id,
            exclude_id=topic_id,
        )
        if dup:
            raise HTTPException(status_code=409, detail=f"母题「{payload['name']}」已存在")

    for field, value in payload.items():
        if value is not None:
            setattr(topic, field, value)
    await db.commit()
    await db.refresh(topic)
    return MotherTopicOut.from_orm_model(topic)


@router.delete("/{topic_id}")
async def delete_mother_topic(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除母题（软删除：is_active=False）。

    - 系统模板（owner IS NULL）：仅 admin 可删
    - 用户私有 fork：仅 owner 可删
    """
    repo = MotherTopicRepository(db)
    topic = await repo.get_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="母题不存在")
    _assert_can_modify(topic, current_user)
    topic.is_active = False
    await db.commit()
    return {"ok": True, "message": "母题已停用"}


@router.post("/score", response_model=ContentScoringResult)
async def score_content(
    req: ContentScoringRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    对单条内容按母题打分。
    用于：选题候选打分、我的母题页过滤。

    打分范围：系统模板 + 当前用户的 fork（用户改了母题能立即生效）。
    """
    text = f"{req.title} {req.summary or ''}"

    topics = await _load_visible_topics(db, current_user.id, active_only=True)

    if not topics:
        return ContentScoringResult(
            title=req.title,
            topic_scores=[],
            top_topic=None,
            final_score=0.0,
        )

    topic_scores = []
    for topic in topics:
        keyword_score = topic.match_score(text)
        # 来源新鲜度（简化：直接用 hot_value / 1000 作为基础分）
        freshness = min(1.0, req.hot_value / 10000)
        # 母题匹配分 × 权重 + 新鲜度加成（0.0 ~ 1.1）
        raw = keyword_score * topic.weight + freshness * 0.1
        # 归一化到 0-100，理论上限约 110
        final = round(min(raw * (100 / 1.1), 100), 1)
        topic_scores.append(
            {
                "name": topic.name,
                "keyword_score": round(keyword_score, 3),
                "weight": topic.weight,
                "freshness": round(freshness, 3),
                "final": final,
            }
        )

    # 按最终分数排序
    topic_scores.sort(key=lambda x: x["final"], reverse=True)
    top = topic_scores[0] if topic_scores else None

    final_score = top["final"] if top else 0.0

    return ContentScoringResult(
        title=req.title,
        topic_scores=topic_scores,
        top_topic=top["name"] if top else None,
        final_score=final_score,
    )


class BatchScoringRequest(BaseModel):
    items: list[ContentScoringRequest]


class BatchScoringResult(BaseModel):
    results: list[ContentScoringResult]


@router.post("/score-batch", response_model=BatchScoringResult)
async def score_content_batch(
    req: BatchScoringRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    批量对多条内容按母题打分。
    只查一次 DB 获取所有活跃母题（系统模板 + 当前用户的 fork），然后循环打分。
    """
    topics = await _load_visible_topics(db, current_user.id, active_only=True)

    if not topics:
        return BatchScoringResult(
            results=[
                ContentScoringResult(
                    title=item.title,
                    topic_scores=[],
                    top_topic=None,
                    final_score=0.0,
                )
                for item in req.items
            ]
        )

    results: list[ContentScoringResult] = []
    for item in req.items:
        text = f"{item.title} {item.summary or ''}"
        freshness = min(1.0, item.hot_value / 10000)

        topic_scores = []
        for topic in topics:
            keyword_score = topic.match_score(text)
            raw = keyword_score * topic.weight + freshness * 0.1
            final = round(min(raw * (100 / 1.1), 100), 1)
            topic_scores.append(
                {
                    "name": topic.name,
                    "keyword_score": round(keyword_score, 3),
                    "weight": topic.weight,
                    "freshness": round(freshness, 3),
                    "final": final,
                }
            )

        topic_scores.sort(key=lambda x: x["final"], reverse=True)
        top = topic_scores[0] if topic_scores else None
        final_score = top["final"] if top else 0.0

        results.append(
            ContentScoringResult(
                title=item.title,
                topic_scores=topic_scores,
                top_topic=top["name"] if top else None,
                final_score=final_score,
            )
        )

    return BatchScoringResult(results=results)


@router.get("/match/{content_id}")
async def match_content_to_topics(
    content_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对已入库的内容重新匹配母题。"""
    content = await ContentRepo(db).get_by_id(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")

    text = f"{content.title} {content.summary or ''}"

    topics = await _load_visible_topics(db, current_user.id, active_only=True)

    topic_scores = []
    for topic in topics:
        keyword_score = topic.match_score(text)
        final = round(keyword_score * topic.weight, 3)
        topic_scores.append(
            {
                "name": topic.name,
                "keyword_score": round(keyword_score, 3),
                "weight": topic.weight,
                "final": final,
            }
        )

    topic_scores.sort(key=lambda x: x["final"], reverse=True)
    top = topic_scores[0] if topic_scores else None

    return {
        "content_id": content_id,
        "title": content.title,
        "top_topic": top["name"] if top else None,
        "top_score": top["final"] if top else 0.0,
        "all_scores": topic_scores,
    }
