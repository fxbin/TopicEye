"""文稿检测（违禁词 / 广告法极限词 / AI 痕迹统计）请求与响应模型。

纯 Pydantic 校验与序列化，无 ORM 导入、无 DB 访问。
`max_length=20000` 由 FastAPI 自动返回 422，service 与词库均不感知长度上限。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.ai_traces import LEVELS, WORD_DIMENSIONS
from app.core.sensitive_words import CATEGORIES, SEVERITIES

Severity = Literal["high", "medium", "low"]

AiTraceLevel = Literal["low", "medium", "high", "insufficient"]


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


class AiTracesCheckRequest(BaseModel):
    """POST /content-check/ai-traces 请求体（与 sensitive 同长度口径）。"""

    text: str = Field(
        ...,
        min_length=1,
        max_length=20000,
        description="待统计文稿原文（1~20000 字符，超限返回 422）",
    )


class AiTraceHitResponse(BaseModel):
    """单条词命中：word/dimension + 原文字符偏移 start/end（codepoint 坐标）。"""

    word: str = Field(..., description="命中的词表词条")
    dimension: Literal["buzzword", "connective"] = Field(..., description=f"词维度，取值 {WORD_DIMENSIONS}")
    start: int = Field(..., ge=0, description="命中原文起始字符偏移（含）")
    end: int = Field(..., gt=0, description="命中原文结束字符偏移（不含）")


class AiTraceDimensionStat(BaseModel):
    """词维度统计：命中数、密度（次/千字）与分档。"""

    dimension: Literal["buzzword", "connective"]
    hits: int = Field(..., ge=0, description="命中次数")
    density_per_kilochar: float = Field(..., ge=0, description="密度（次/千字）")
    level: AiTraceLevel = Field(..., description=f"分档，取值 {LEVELS}")


class AiTraceRhythmStat(BaseModel):
    """句式均匀度统计：CV=std/mean；句数 <3 时 level=insufficient 且 cv=null。"""

    level: AiTraceLevel
    sentence_count: int = Field(..., ge=0, description="有效句数")
    cv: float | None = Field(None, description="句长变异系数；样本不足时为 null")


class AiTracesReport(BaseModel):
    """POST /content-check/ai-traces 响应.

    启发式统计（非模型检测）：不输出「AI 率/AI 概率」，不影响风险把关结论，
    只给写作建议，前端独立展示。
    """

    level: AiTraceLevel = Field(..., description=f"总分档，取值 {LEVELS}")
    character_count: int = Field(..., ge=0, description="全文 codepoint 数")
    buzzword: AiTraceDimensionStat = Field(..., description="AI 高频词统计")
    connective: AiTraceDimensionStat = Field(..., description="套话连接词统计")
    rhythm: AiTraceRhythmStat = Field(..., description="句式均匀度统计")
    hits: list[AiTraceHitResponse] = Field(default_factory=list, description="词命中清单（start 升序、区间不重叠）")
    advice: str = Field(..., description="综合建议（明示启发式统计口径）")


class HumanizeRewriteRequest(BaseModel):
    """POST /content-check/humanize-rewrite 请求体（与 sensitive 同长度口径）。

    传全文而非句列表：分句与命中口径只在后端一份，服务端自行选取命中最密集
    的 ≤3 句进模型，全文永不进 prompt。
    """

    text: str = Field(
        ...,
        min_length=1,
        max_length=20000,
        description="待改写文稿原文（1~20000 字符，超限返回 422；服务端只选取命中密集的 ≤3 句进入模型）",
    )


class HumanizeRewriteSuggestionResponse(BaseModel):
    """单条改写建议：服务端选取的原句 + 保留原意的口语化改写 + 该句真实命中词。"""

    original: str = Field(..., description="服务端选取的原句（以服务端选取为准，不取模型回显）")
    rewritten: str = Field(..., description="口语化改写建议（写作参考，需自行核对事实与数字）")
    hit_words: list[str] = Field(
        default_factory=list,
        description="该句真实命中的 AI 痕迹词（已对照词库命中过滤，不含模型编造词）",
    )


class HumanizeRewriteResponse(BaseModel):
    """POST /content-check/humanize-rewrite 响应（≤3 条，按命中密集程度排序）。"""

    suggestions: list[HumanizeRewriteSuggestionResponse] = Field(
        default_factory=list,
        description="改写建议清单；命中句不足 3 句时条数相应减少",
    )
