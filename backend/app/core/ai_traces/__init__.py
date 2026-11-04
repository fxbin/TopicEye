"""AI 痕迹维度的 dimension / level 常量（跨层共享的纯常量放 core）。

「AI 痕迹」是**启发式统计，不是模型检测**：词库命中与句式节奏只描述写作
风格信号，任何输出与文案不得暗示「AI 率 / AI 概率 / 检测模型」口径。
词表数据与来源记录在同目录 ai_lexicon.json 的 `_meta`；分档阈值与理由见
.agents/notes/implemented/feature/2026-11-04-content-check-ai-traces.md。
"""

from __future__ import annotations

# 词维度：buzzword=AI 高频词/黑话，connective=套话连接词（各有词表）；
# rhythm=句式均匀度（无词表，按句长统计），单独成档不进 WORD_DIMENSIONS。
DIMENSION_BUZZWORD = "buzzword"
DIMENSION_CONNECTIVE = "connective"
DIMENSION_RHYTHM = "rhythm"

WORD_DIMENSIONS: tuple[str, ...] = (DIMENSION_BUZZWORD, DIMENSION_CONNECTIVE)

# 分档：high/medium/low 描述「AI 味」浓度（high=痕迹明显），insufficient=样本
# 不足宁可不判。与风险把关的 severity（high/medium/low）语义不同，不复用配色。
LEVEL_HIGH = "high"
LEVEL_MEDIUM = "medium"
LEVEL_LOW = "low"
LEVEL_INSUFFICIENT = "insufficient"

LEVELS: tuple[str, ...] = (LEVEL_HIGH, LEVEL_MEDIUM, LEVEL_LOW, LEVEL_INSUFFICIENT)
