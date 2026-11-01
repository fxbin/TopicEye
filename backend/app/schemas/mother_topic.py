"""母题关键词提取（issue #187）的请求/响应契约。

mother_topics 路由里既有的内联 Pydantic 模型不搬到本文件；这里只放
POST /mother-topics/extract-keywords 用到的新 schema。
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

# 兴趣描述长度边界：去掉首尾空白后 1-500 字。
DESCRIPTION_MAX_LENGTH = 500


class KeywordExtractionRequest(BaseModel):
    """自然语言兴趣描述。只用于本次提取，不落库。"""

    description: str

    @field_validator("description")
    @classmethod
    def _strip_and_bound(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("描述不能为空白")
        if len(stripped) > DESCRIPTION_MAX_LENGTH:
            raise ValueError(f"描述最长 {DESCRIPTION_MAX_LENGTH} 字（不含首尾空白）")
        return stripped


class KeywordExtractionResponse(BaseModel):
    """提取出的候选关键词（1-15 个；下限不凑数，按实际个数返回）。"""

    keywords: list[str]
