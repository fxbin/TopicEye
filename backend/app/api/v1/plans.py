from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header

from app.schemas.plan import PlanCatalogResponse
from app.services.auth_service import get_user_for_token
from app.services.plan_catalog import get_plan_catalog_for_user
from app.core.database import async_session

router = APIRouter(prefix="/plans", tags=["plans"])


def _optional_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


@router.get("", response_model=PlanCatalogResponse)
async def list_plans(authorization: str | None = Header(default=None)):
    """Return product-plan boundaries for free and paid feature areas."""
    plan_key = "free"
    token = _optional_bearer_token(authorization)
    if token:
        async with async_session() as db:
            user = await get_user_for_token(db, token)
            if user:
                plan_key = user.plan
            await db.commit()
    return get_plan_catalog_for_user(plan_key)
