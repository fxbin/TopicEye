from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class PlanTierResponse(BaseModel):
    key: str
    name: str
    price_label: str
    positioning: str
    highlight: str
    features: list[str]
    limits: dict[str, Any]
    cta: str
    recommended: bool = False


class PlanCatalogResponse(BaseModel):
    tiers: list[PlanTierResponse]
    free_area: list[str]
    paid_area: list[str]
    currency: str
    source: str
    current_plan: str = "free"
    current_tier: PlanTierResponse | None = None
