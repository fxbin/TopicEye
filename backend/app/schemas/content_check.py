"""文稿检测（违禁词 / 广告法极限词）请求与响应模型。

纯 Pydantic 校验与序列化，无 ORM 导入、无 DB 访问。
`max_length=20000` 由 FastAPI 自动返回 422，service 与词库均不感知长度上限。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.sensitive_words import CATEGORIES, SEVERITIES

Severity = Literal["high", "medium", "low"]


class SensitiveCheckRequest(BaseModel):
    """POST /content-check/sensitive 请求体。"""

    text: str = Field(
        ...,
        min_length=1,
        max_length=20000,
        description="待检测文稿原文（1~20000 字符，超限返回 422）",
    )


class SensitiveHitResponse(BaseModel):
    """单条命中：word/category/severity + 原文字符偏移 start/end + 替换建议。"""

    word: str = Field(..., description="命中的词库词条")
    category: Literal["advertising_extreme", "political_adult", "platform_throttle"] = Field(
        ..., description=f"命中分类，取值 {CATEGORIES}"
    )
    severity: Severity = Field(..., description=f"严重度，取值 {SEVERITIES}")
    start: int = Field(..., ge=0, description="命中原文起始字符偏移（含）")
    end: int = Field(..., gt=0, description="命中原文结束字符偏移（不含）")
    suggestion: str | None = Field(None, description="替换建议，无则为 null")


class SensitiveCheckResponse(BaseModel):
    """POST /content-check/sensitive 响应：命中总数 + 按出现顺序排列的命中清单。"""

    total: int = Field(..., ge=0, description="命中总数")
    hits: list[SensitiveHitResponse] = Field(default_factory=list, description="命中清单（start 升序）")
