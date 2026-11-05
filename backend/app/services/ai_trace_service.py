"""文稿「AI 痕迹」启发式统计（AI 高频词 / 套话连接词 / 句式均匀度）。

定位与口径（owning note: 2026-11-04-content-check-ai-traces.md，改动前先读）：

- **这是启发式统计，不是模型检测**：词库命中与句式节奏只描述写作风格信号，
  输出与文案不得暗示「AI 率 / AI 概率 / 检测模型」。与敏感词链路的风险把关
  语义不同——ai_traces 只给写作建议，不影响「未发现违禁词，可以发布」结论。
- 词扫描沿用敏感词链路的既有合同：全角/半角标点与空白视为分隔符
  （`[\\s\\W]` 1:1 替换为 `\\x00`，偏移不变）、每维度一个按词长降序的 union
  正则（同 start 保留最长）、start/end 是原文 codepoint 偏移、不做 NFKC。
- 两维度命中合并后按 (start 升序, 长度降序, buzzword 先于 connective) 贪心
  去重叠，结果区间两两不交——前端高亮依赖该合同。
- 句式均匀度：按中文句末标点（。！？；…及半角对应）与换行分句，句长取
  codepoint 数，用**变异系数 CV=std/mean**（无量纲，长文短文可比）而非原始
  方差；句数 < 3 时 CV 无统计意义，返回 insufficient，不编造分档。
"""

from __future__ import annotations

import functools
import json
import logging
import re
import statistics
from pathlib import Path
from typing import TypedDict

from app.core.ai_traces import (
    DIMENSION_BUZZWORD,
    DIMENSION_CONNECTIVE,
    LEVEL_HIGH,
    LEVEL_INSUFFICIENT,
    LEVEL_LOW,
    LEVEL_MEDIUM,
    WORD_DIMENSIONS,
)

logger = logging.getLogger(__name__)

# ── 分档阈值（显式常量；理由见 owning note，改阈值必须同步改测试边界断言）─────

# 密度分档（次/千字，分母是全文 codepoint 数、含标点空白）。buzzword
# （赋能/抓手类黑话）在口语化写作里几乎不出现，堆积即是强信号，阈值从宽：
# ≥3/千字起值得注意，≥8/千字判密集。connective（首先/其次类套话连接词）在
# 正常议论文里也有基础出现率，阈值压太低会误伤正常行文，故只略低半档：
# ≥2.5/千字起注意，≥6/千字判密集。
BUZZWORD_DENSITY_MEDIUM = 3.0
BUZZWORD_DENSITY_HIGH = 8.0
CONNECTIVE_DENSITY_MEDIUM = 2.5
CONNECTIVE_DENSITY_HIGH = 6.0

# 句式均匀度分档（CV=std/mean，pstdev）。CV 越小句长越均匀；自然中文写作
# 句长长短交错，CV 普遍 ≥0.4；模板化行文句长趋同，CV 明显压低。取
# CV<0.20 判 high（高度均匀），0.20≤CV<0.35 判 medium，CV≥0.35 判 low。
RHYTHM_CV_HIGH = 0.20
RHYTHM_CV_LOW = 0.35

# 句数下限：n<3 时样本太小，任何 CV 都不可信，rhythm 与整体都只给 insufficient
MIN_SENTENCES = 3

# 与敏感词链路同口径：空白 + 所有标点/符号（含全角）是分隔符，1:1 替换、偏移不变
_SEPARATOR_RE = re.compile(r"[\s\W]")
_PLACEHOLDER = "\x00"

# 分句：中文句末标点（全半角）与换行。分号在中文承担句间停顿，也作句界。
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;…\n]+")

# 跨维度决胜权重：完全同区间时黑话比连接词信号更强更具体，buzzword 优先
_DIMENSION_RANK: dict[str, int] = {DIMENSION_BUZZWORD: 0, DIMENSION_CONNECTIVE: 1}

# 分档排序权重（insufficient 不参与比较，只作整体降级信号）
_LEVEL_RANK: dict[str, int] = {LEVEL_LOW: 0, LEVEL_MEDIUM: 1, LEVEL_HIGH: 2}


class AiTraceWordHit(TypedDict):
    """一次词命中：词条、词维度与原文 codepoint 偏移。"""

    word: str
    dimension: str
    start: int
    end: int


class AiTraceDimensionStat(TypedDict):
    """词维度统计：命中数、密度（次/千字）与分档。"""

    dimension: str
    hits: int
    density_per_kilochar: float
    level: str


class AiTraceRhythmStat(TypedDict):
    """句式均匀度统计：CV；句数不足时 level=insufficient 且 cv=null。"""

    level: str
    sentence_count: int
    cv: float | None


class AiTraceReport(TypedDict):
    """整体报告：三子指标 + 总分档 + 综合建议（启发式统计口径）。"""

    level: str
    character_count: int
    buzzword: AiTraceDimensionStat
    connective: AiTraceDimensionStat
    rhythm: AiTraceRhythmStat
    hits: list[AiTraceWordHit]
    advice: str


_ADVICE: dict[str, str] = {
    LEVEL_LOW: ("未观察到密集的 AI 高频词与套话连接词，句式节奏自然，保持即可。" "启发式统计，仅供参考。"),
    LEVEL_MEDIUM: (
        "存在一定密度的 AI 高频词或套话连接词，可对照命中清单换成具体动作、" "数字或事例。启发式统计，仅供参考。"
    ),
    LEVEL_HIGH: (
        "AI 高频词/套话连接词密集，或句式过于均匀，建议逐条改写命中词、" "打散均匀的句长节奏。启发式统计，仅供参考。"
    ),
    LEVEL_INSUFFICIENT: ("文本太短（有效句数不足 3），样本不足以统计，补充更多正文后再看。" "启发式统计，仅供参考。"),
}


@functools.cache
def load_lexicon(dimension: str) -> tuple[str, ...]:
    """加载某词维度的词表（进程内缓存）。

    词条校验同敏感词：不含空白/标点、非空，非法词条显式 warning 跳过——
    静态数据出错不能安静失败，也不能拖垮接口；测试断言内置词表零跳过。
    """
    if dimension not in WORD_DIMENSIONS:
        raise ValueError(f"未知 AI 痕迹词维度: {dimension}")
    path = Path(__file__).resolve().parent.parent / "core" / "ai_traces" / "ai_lexicon.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    validated: list[str] = []
    for entry in data.get(dimension, []):
        word = str(entry.get("word", ""))
        if not word or _SEPARATOR_RE.search(word):
            logger.warning("AI 痕迹词表 %s 跳过含分隔符/空词条: %r", dimension, entry)
            continue
        validated.append(word)
    if not validated:
        raise ValueError(f"AI 痕迹词表 {dimension} 为空或全部词条非法")
    return tuple(validated)


@functools.cache
def _compiled_patterns() -> dict[str, re.Pattern[str]]:
    """每词维度一个按词长降序的 union 正则（同 start 保留最长，同敏感词合同）。"""
    patterns: dict[str, re.Pattern[str]] = {}
    for dimension in WORD_DIMENSIONS:
        words = sorted(load_lexicon(dimension), key=len, reverse=True)
        patterns[dimension] = re.compile("|".join(re.escape(w) for w in words))
    return patterns


def _band_from_density(density: float, medium_at: float, high_at: float) -> str:
    """密度越高 AI 痕迹越重：≥high_at → high；≥medium_at → medium；否则 low。"""
    if density >= high_at:
        return LEVEL_HIGH
    if density >= medium_at:
        return LEVEL_MEDIUM
    return LEVEL_LOW


def _band_from_cv(cv: float) -> str:
    """CV 越小句长越均匀（AI 痕迹越重）：<RHYTHM_CV_HIGH → high，≥RHYTHM_CV_LOW → low。"""
    if cv < RHYTHM_CV_HIGH:
        return LEVEL_HIGH
    if cv < RHYTHM_CV_LOW:
        return LEVEL_MEDIUM
    return LEVEL_LOW


def split_sentences(text: str) -> list[str]:
    """按中文句末标点与换行分句；去掉首尾空白，丢弃纯空白句。"""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def scan_words(text: str) -> list[AiTraceWordHit]:
    """扫描 buzzword/connective 命中（start 升序、区间两两不交）。

    跨维度同 start 取更长词；完全同区间时 buzzword 先于 connective。
    纯函数：同一输入恒得同一输出；空串返回空列表。
    """
    if not text:
        return []

    # 分隔符 1:1 替换为占位符：不可能跨标点命中，偏移与原文严格一致
    masked = _SEPARATOR_RE.sub(_PLACEHOLDER, text)

    raw: list[AiTraceWordHit] = []
    for dimension, pattern in _compiled_patterns().items():
        for m in pattern.finditer(masked):
            raw.append(AiTraceWordHit(word=m.group(), dimension=dimension, start=m.start(), end=m.end()))

    raw.sort(key=lambda h: (h["start"], -(h["end"] - h["start"]), _DIMENSION_RANK[h["dimension"]]))

    hits: list[AiTraceWordHit] = []
    last_end = 0
    for hit in raw:
        if hit["start"] >= last_end:
            hits.append(hit)
            last_end = hit["end"]
    return hits


def analyze_rhythm(sentences: list[str]) -> AiTraceRhythmStat:
    """句式均匀度：CV=pstdev/mean；句数 <MIN_SENTENCES 时 insufficient 不编造。"""
    if len(sentences) < MIN_SENTENCES:
        return AiTraceRhythmStat(level=LEVEL_INSUFFICIENT, sentence_count=len(sentences), cv=None)
    lengths = [len(s) for s in sentences]
    mean = statistics.mean(lengths)
    # 分句结果均已 strip 非空，mean>0 恒成立；防御异常输入按 CV=0（最均匀）处理
    cv = statistics.pstdev(lengths) / mean if mean > 0 else 0.0
    return AiTraceRhythmStat(
        level=_band_from_cv(cv),
        sentence_count=len(sentences),
        cv=round(cv, 4),
    )


def analyze(text: str) -> AiTraceReport:
    """对全文做启发式统计：三子指标分档 + 总分档 + 综合建议（纯函数）。

    总分档取可用子指标的最重档；rhythm=insufficient 只是样本不足、不参与
    抬档。仅当 rhythm 样本不足**且**词维度零命中时，整体才 insufficient——
    短到没有任何可信信号时宁可不判，也不编造「痕迹少」。词命中密集的短文本
    仍按词证据正常分档。
    """
    character_count = len(text)
    word_hits = scan_words(text)

    def dimension_stat(dimension: str) -> AiTraceDimensionStat:
        hits = sum(1 for h in word_hits if h["dimension"] == dimension)
        density = round(hits / character_count * 1000, 2) if character_count else 0.0
        if dimension == DIMENSION_BUZZWORD:
            level = _band_from_density(density, BUZZWORD_DENSITY_MEDIUM, BUZZWORD_DENSITY_HIGH)
        else:
            level = _band_from_density(density, CONNECTIVE_DENSITY_MEDIUM, CONNECTIVE_DENSITY_HIGH)
        return AiTraceDimensionStat(
            dimension=dimension,
            hits=hits,
            density_per_kilochar=density,
            level=level,
        )

    buzzword = dimension_stat(DIMENSION_BUZZWORD)
    connective = dimension_stat(DIMENSION_CONNECTIVE)
    rhythm = analyze_rhythm(split_sentences(text))

    if rhythm["level"] == LEVEL_INSUFFICIENT and not word_hits:
        level = LEVEL_INSUFFICIENT
    else:
        candidates = [buzzword["level"], connective["level"]]
        if rhythm["level"] != LEVEL_INSUFFICIENT:
            candidates.append(rhythm["level"])
        level = max(candidates, key=lambda item: _LEVEL_RANK[item])

    return AiTraceReport(
        level=level,
        character_count=character_count,
        buzzword=buzzword,
        connective=connective,
        rhythm=rhythm,
        hits=word_hits,
        advice=_ADVICE[level],
    )
