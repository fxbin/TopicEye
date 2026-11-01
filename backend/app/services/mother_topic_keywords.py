"""自然语言兴趣描述 → 母题订阅关键词提取（issue #187）。

用户在 /my-topics/config 表单里用一句话描述想看的内容，本服务把描述交给
LLM 提取候选关键词；候选词经用户勾选后，走既有的 POST /mother-topics 或
PUT /mother-topics/{id} 落库。纯读路径：不写任何业务表，LLM 调用由既有
call_trace 基础设施记录。

边界（与 issue #187 任务书一致）：
- 兴趣描述只用于这一次提取，不存库（mother_topics.description 是
  String(200)，500 字描述写进去会超长）。
- 同一段描述重复提取会命中 LLM 响应缓存，这是预期行为，不绕过缓存。
- 数量规则：提示词要求 5-15 个；服务端清洗后最多截到 15 个，清洗后一个都
  不剩抛 ``KeywordExtractionError``。下限 5 服务端保证不了——硬凑就是编造，
  剩 1-4 个就按实际返回，由前端显示实际个数。
- LLM 链路异常（熔断/容量/预算/上下文）不捕获不折叠，原样上抛给 API 层
  显式报 502（AGENTS 2.1 禁止安静失败）。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.llm import call_llm_json
from app.services.llm.prompts.mother_topic_keywords import SYSTEM_PROMPT, USER_TEMPLATE
from app.utils.prompt_safety import sanitize_prompt_input

logger = logging.getLogger(__name__)

# 兴趣描述送入 LLM 前的截断上限（与 API 层 schema 的 1-500 字校验同口径）。
DESCRIPTION_MAX_CHARS = 500
# 单个关键词的长度上限：超过 20 字的「词」实际是句子，丢弃。
KEYWORD_MAX_CHARS = 20
# 清洗后保留的关键词数上限，与提示词要求的 5-15 个一致，防超发。
MAX_KEYWORDS = 15

# LLM 把多个词塞进一个字符串时按常见分隔符再拆一次。
_KEYWORD_SPLIT_RE = re.compile(r"[,，、;；\n]")
# 词首尾的装饰字符：空白、井号、常见引号。
_KEYWORD_STRIP_CHARS = " \t\r\n#\"'“”‘’「」『』"


class KeywordExtractionError(Exception):
    """LLM 返回无法解析出任何可用关键词时抛出（禁止折叠成假成功）。"""


def _clean_keywords(raw_keywords: list[Any]) -> list[str]:
    """清洗 LLM 返回的关键词列表。

    - 每项按 , ， 、 ; ； 换行 再拆一次，去掉首尾空白、#、引号；
    - 丢掉空串和超过 ``KEYWORD_MAX_CHARS`` 字的项；
    - 不分大小写去重并保持首次出现顺序；
    - 最多保留 ``MAX_KEYWORDS`` 个。
    """

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_keywords:
        for piece in _KEYWORD_SPLIT_RE.split(str(item)):
            word = piece.strip(_KEYWORD_STRIP_CHARS).strip()
            if not word or len(word) > KEYWORD_MAX_CHARS:
                continue
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(word)
            if len(cleaned) >= MAX_KEYWORDS:
                return cleaned
    return cleaned


async def extract_keywords_from_description(description: str) -> list[str]:
    """从一段自然语言兴趣描述提取候选订阅关键词。

    Returns:
        清洗去重后的关键词列表（1-15 个，不为空）。

    Raises:
        KeywordExtractionError: LLM 输出无法解析（含 call_llm_json 回退的
            ``{"raw_response": ...}``）或清洗后一个可用词都不剩。
        LLM 链路异常原样上抛（熔断/容量/预算/上下文等），由 API 层映射 502。
    """

    safe_description = sanitize_prompt_input(description, max_chars=DESCRIPTION_MAX_CHARS)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(description=safe_description)},
    ]
    result = await call_llm_json(
        messages,
        temperature=0.2,
        max_tokens=600,
        scene="mother_topic_keywords",
    )

    if isinstance(result, dict):
        if "raw_response" in result:
            raise KeywordExtractionError("LLM 未返回可解析的 JSON 结构")
        raw_keywords = result.get("keywords")
    elif isinstance(result, list):
        # 部分模型会无视模板直接给顶层 JSON 数组，同样接受。
        raw_keywords = result
    else:
        raise KeywordExtractionError("LLM 返回结构不可用")

    if not isinstance(raw_keywords, list):
        raise KeywordExtractionError("LLM 返回缺少 keywords 字段")

    keywords = _clean_keywords(raw_keywords)
    if not keywords:
        logger.warning("Keyword extraction cleaned out all candidates (%d raw)", len(raw_keywords))
        raise KeywordExtractionError("LLM 返回的关键词清洗后为空")
    return keywords
