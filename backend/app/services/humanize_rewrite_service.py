"""文稿「去 AI 味」改写建议：对 AI 痕迹命中密集的句子生成保留原意的口语化改写。

检测→改写闭环的服务端编排（owning note: 2026-11-04-content-check-ai-traces.md）：

- 选句是纯函数 `select_target_sentences`：复用 ai_trace_service 的分句与词扫描
  口径（services 引 services 有先例，见 angle_recommend.py）。逐句重扫与全扫在
  句内等价——句末标点属 ``_SEPARATOR_RE`` 掩码，词命中不可能跨句界。
- 只有选取出的 ≤3 句进入 LLM prompt，**全文永不进 prompt**（token 由选句上限
  天然限流，20000 字请求体不等于 20000 字 prompt）。
- 响应不信任 LLM 回显：条目必须与服务端选取句逐字对应，original 以服务端为
  准；hit_words 逐条对照该句真实 scan_words 结果过滤，徽标词都来自真实命中。
- 与 ai_trace_service 的模块合同不同：那个模块是纯启发式统计、无 IO；本模块
  有 LLM IO，故独立成模块，不并入。

口径红线：改写建议是「写作建议」，全链路文案不得出现「AI 率 / AI 概率 /
检测模型」类表述（词库命中判不了文稿来源，改写也只降套话密度）。
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from app.services.ai_trace_service import scan_words, split_sentences
from app.services.llm import call_llm_json
from app.services.llm.prompts.humanize_rewrite import SYSTEM_PROMPT, USER_TEMPLATE
from app.utils.prompt_safety import sanitize_prompt_input

logger = logging.getLogger(__name__)

# 选句上限：一次最多改写 3 句。命中数 ≥2 的句子优先，不足再补命中数 =1 的句子。
MAX_TARGET_SENTENCES = 3
# 单句进 prompt 前的清洗上限：选句已含命中词、正常远短于此，防极端长句撑爆 token。
SENTENCE_PROMPT_MAX_CHARS = 1000
# 低温改写：只许换说法，不许自由发挥；上限收紧到改写 3 句所需（provider 默认 2000）。
LLM_TEMPERATURE = 0.4
LLM_MAX_TOKENS = 1200


class HumanizeRewriteSuggestion(TypedDict):
    """一条改写建议：服务端选取的原句、改写句与该句真实命中的词。"""

    original: str
    rewritten: str
    hit_words: list[str]


class HumanizeRewriteNoTargetError(ValueError):
    """文稿没有任何 buzzword/connective 命中句，无从改写（API 映射 422）。"""


class HumanizeRewriteUnavailableError(RuntimeError):
    """LLM 输出不可解析，或没有任何能与选取句对应的有效条目（API 映射 502）。"""


def _sentence_hit_words(sentence: str) -> list[str]:
    """句内真实命中的词，按出现顺序去重（服务端过滤 hit_words 的事实源）。"""
    words: list[str] = []
    for hit in scan_words(sentence):
        if hit["word"] not in words:
            words.append(hit["word"])
    return words


def select_target_sentences(text: str, limit: int = MAX_TARGET_SENTENCES) -> list[str]:
    """选取 AI 痕迹命中最密集的句子（纯函数，复用 ai_trace_service 口径）。

    逐句 ``scan_words`` 统计句内命中数，按命中数降序取前 ``limit`` 句；零命中
    句不入选。稳定排序保证同命中数按原文顺序——命中 ≥2 的句子天然排在 =1
    之前，不足 ``limit`` 句时自动用命中数 =1 的句子补足。
    """
    scored: list[tuple[str, int]] = []
    for sentence in split_sentences(text):
        count = len(scan_words(sentence))
        if count > 0:
            scored.append((sentence, count))
    if not scored:
        return []
    scored.sort(key=lambda item: -item[1])
    return [sentence for sentence, _count in scored[:limit]]


def _build_messages(sentences: list[str]) -> list[dict[str, str]]:
    """选取句逐条 sanitize 后拼入模板；全文不进 prompt。"""
    lines = [
        f"{index}. {sanitize_prompt_input(sentence, max_chars=SENTENCE_PROMPT_MAX_CHARS)}"
        for index, sentence in enumerate(sentences, start=1)
    ]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(sentences="\n".join(lines))},
    ]


def _parse_suggestions(result: Any, selected: list[str]) -> list[HumanizeRewriteSuggestion]:
    """校验并整形 LLM 返回；original 以服务端选取句为准，hit_words 只留真实命中。

    条目必须与某个选取句逐字对应（不信回显），rewritten 必须非空；全部无效时
    抛 :class:`HumanizeRewriteUnavailableError`，不返回空建议装成功。
    输出按服务端选取顺序排列（不按 LLM 返回顺序）。
    """
    if not isinstance(result, dict):
        raise HumanizeRewriteUnavailableError("LLM 返回不是 JSON 对象")
    raw_suggestions = result.get("suggestions")
    if not isinstance(raw_suggestions, list):
        raise HumanizeRewriteUnavailableError("LLM 返回缺少 suggestions 列表")

    real_words = {sentence: _sentence_hit_words(sentence) for sentence in selected}
    rewritten_by_sentence: dict[str, tuple[str, list[str]]] = {}
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        original = item.get("original")
        rewritten = item.get("rewritten")
        if not isinstance(original, str) or original not in real_words:
            continue  # 回显与选取句对不上：丢弃，不用 LLM 的句子冒充原句
        if not isinstance(rewritten, str) or not rewritten.strip():
            continue
        truth = real_words[original]
        echoed = item.get("hit_words")
        candidates = [word for word in echoed if isinstance(word, str)] if isinstance(echoed, list) else []
        hit_words = [word for word in candidates if word in truth]
        if not hit_words:
            # LLM 未回显或全部被过滤：徽标退回该句真实命中，仍不编造
            hit_words = truth
        rewritten_by_sentence[original] = (rewritten, hit_words)

    valid = [
        HumanizeRewriteSuggestion(
            original=sentence,
            rewritten=rewritten_by_sentence[sentence][0],
            hit_words=rewritten_by_sentence[sentence][1],
        )
        for sentence in selected
        if sentence in rewritten_by_sentence
    ]
    if not valid:
        raise HumanizeRewriteUnavailableError("LLM 返回中没有可与选取句对应的有效改写")
    return valid


async def generate_humanize_rewrites(text: str) -> dict[str, list[HumanizeRewriteSuggestion]]:
    """对 AI 痕迹命中最密集的 ≤3 句生成口语化改写建议。

    选句为空抛 :class:`HumanizeRewriteNoTargetError`（API 映射 422 显式原因）；
    LLM 链路异常（熔断/容量/预算/上下文）由 provider 原样抛出，入口层映射 502。
    """
    selected = select_target_sentences(text)
    if not selected:
        raise HumanizeRewriteNoTargetError("文稿没有命中 AI 高频词或套话连接词的句子，无从生成改写建议")

    result = await call_llm_json(
        _build_messages(selected),
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        scene="humanize_rewrite",
    )
    return {"suggestions": _parse_suggestions(result, selected)}
