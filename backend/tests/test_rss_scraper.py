"""RSS scraper 单测: 聚焦 arXiv 摘要前缀清理。

arXiv RSS 的 <description> 带 'arXiv:XXXX.NNNNN Announce Type: new\nAbstract: '
固定前缀，清理后 LLM 才能拿到干净摘要做分类/评分。
"""

from __future__ import annotations

from app.services.scrapers.rss import _clean_summary


def test_clean_arxiv_prefix_new():
    """arXiv 'new' 类型: 前缀被清理，保留真实摘要。"""
    raw = (
        "arXiv:2606.26155v1 Announce Type: new \n"
        "Abstract: We focus on detecting and steering away from sycophancy "
        "in language models. Code & Data: https://example.com"
    )
    cleaned = _clean_summary(raw)
    assert cleaned.startswith("We focus on detecting")
    assert "arXiv:" not in cleaned
    assert "Announce Type" not in cleaned
    assert "Abstract:" not in cleaned


def test_clean_arxiv_prefix_cross_list():
    """arXiv 'cross-list' 类型前缀同样被清理。"""
    raw = (
        "arXiv:2606.26164v1 Announce Type: cross-list \n"
        "Abstract: Finding all modes of a multimodal black-box function."
    )
    cleaned = _clean_summary(raw)
    assert cleaned == "Finding all modes of a multimodal black-box function."


def test_clean_preserves_non_arxiv_summary():
    """普通 RSS 摘要(无 arXiv 前缀)原样保留。"""
    raw = "这是一篇关于 AI 发展的深度分析文章。"
    assert _clean_summary(raw) == raw


def test_clean_empty_and_whitespace():
    """空字符串安全返回。纯空白会被 strip(无前缀时正则不匹配但 strip 生效)。"""
    assert _clean_summary("") == ""
    # 纯空白: 正则不匹配, 但 .strip() 会清掉, 符合预期
    assert _clean_summary("   ") == ""


def test_clean_arxiv_no_abstract_section():
    """arXiv 前缀但没有 Abstract: 行的异常格式 —— 原样保留(正则不匹配)。"""
    raw = "arXiv:2606.26155v1 Announce Type: new (no abstract body)"
    # 没有 'Abstract:' 分隔，正则不匹配，原样返回
    assert _clean_summary(raw) == raw.strip()


def test_clean_arxiv_preserves_latex():
    """arXiv 摘要中的 LaTeX 符号(如 \\chisao{})不被破坏。"""
    raw = (
        "arXiv:2606.26164v1 Announce Type: new \n"
        "Abstract: We introduce \\chisao{} (Convergence-Halt-Invert-Stick-And-Oscillate)."
    )
    cleaned = _clean_summary(raw)
    assert "\\chisao{}" in cleaned
    assert cleaned.startswith("We introduce")
