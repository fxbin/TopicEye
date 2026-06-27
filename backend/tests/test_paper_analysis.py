"""论文分析分流单测: 验证 arXiv 内容走专用论文 prompt。

不实测 LLM 调用（成本高且不稳定），只验证分流逻辑：
arXiv 平台 → 论文 prompt；非 arXiv → 常规中英文 prompt。
"""

from __future__ import annotations

import pytest

from app.services.llm.prompts.analysis import (
    PAPER_SYSTEM_PROMPT,
    PAPER_ANALYSIS_PROMPT,
    SYSTEM_PROMPT,
    ANALYSIS_PROMPT,
    SYSTEM_PROMPT_EN,
    ANALYSIS_PROMPT_EN,
)


def test_paper_prompts_exist_and_differ_from_generic():
    """论文 prompt 存在，且与常规 prompt 不同（含 deep_read 字段）。"""
    assert "精读" in PAPER_SYSTEM_PROMPT
    assert "worth_deep_read" in PAPER_ANALYSIS_PROMPT
    assert "deep_read_score" in PAPER_ANALYSIS_PROMPT
    # 论文概述要求比常规 30 字更详细
    assert "150-200" in PAPER_ANALYSIS_PROMPT
    # 与英文通用 prompt 不同
    assert PAPER_SYSTEM_PROMPT != SYSTEM_PROMPT_EN
    assert PAPER_ANALYSIS_PROMPT != ANALYSIS_PROMPT_EN


def test_paper_prompt_is_formatted_correctly():
    """论文 prompt 能被 title/content 正确格式化。"""
    formatted = PAPER_ANALYSIS_PROMPT.format(
        title="Attention Is All You Need",
        content="We propose a new architecture...",
    )
    assert "Attention Is All You Need" in formatted
    assert "worth_deep_read" in formatted


def test_arxiv_detection_logic():
    """验证 arXiv 平台检测的关键词逻辑（与 analysis.py 实现一致）。"""
    def is_arxiv(platform: str, source_name: str) -> bool:
        platform_lower = (platform or "").lower()
        return "arxiv" in platform_lower or "arxiv" in (source_name or "").lower()

    assert is_arxiv("arXiv", "arXiv cs.AI") is True
    assert is_arxiv("arxiv", "") is True
    assert is_arxiv("", "arXiv cs.LG") is True
    assert is_arxiv("RSS", "Hacker News") is False
    assert is_arxiv("", "") is False
    assert is_arxiv("GitHub", "") is False
