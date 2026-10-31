"""用户降噪规则（/api/v1/mute-rules）的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MuteRuleType = Literal["keyword", "source", "domain"]


class MuteRuleCreate(BaseModel):
    rule_type: MuteRuleType = Field(description="keyword=标题/摘要包含；source=信源 ID 等值；domain=url host 等值")
    value: str = Field(min_length=1, max_length=255, description="匹配值；具体归一规则由 service 校验")


class MuteRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_type: MuteRuleType
    value: str
    created_at: datetime


class MuteRuleListResponse(BaseModel):
    count: int
    items: list[MuteRuleResponse]
