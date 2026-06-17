"""Zhihu URL normalization helpers."""

from __future__ import annotations

from typing import Optional

from urllib.parse import urlparse


_ZHIHU_HOSTS = {
    "api.zhihu.com",
    "www.zhihu.com",
    "zhihu.com",
    "m.zhihu.com",
    "zhuanlan.zhihu.com",
}


def _id_after(parts: list[str], names: set[str]) -> Optional[str]:
    for idx, part in enumerate(parts):
        if part in names and idx + 1 < len(parts):
            candidate = parts[idx + 1].strip()
            if candidate:
                return candidate
    return None


def normalize_zhihu_url(url: Optional[str]) -> str:
    """Convert Zhihu API resource URLs into browser-friendly web URLs."""
    if not url:
        return ""

    cleaned = url.strip()
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    if host not in _ZHIHU_HOSTS:
        return cleaned

    parts = [part for part in parsed.path.split("/") if part]
    question_id = _id_after(parts, {"question", "questions"})
    answer_id = _id_after(parts, {"answer", "answers"})
    article_id = _id_after(parts, {"article", "articles", "p"})

    if question_id and answer_id:
        return f"https://www.zhihu.com/question/{question_id}/answer/{answer_id}"
    if question_id:
        return f"https://www.zhihu.com/question/{question_id}"
    if answer_id:
        return f"https://www.zhihu.com/answer/{answer_id}"
    if article_id:
        return f"https://zhuanlan.zhihu.com/p/{article_id}"

    return cleaned
