"""Readable source evidence and conservative titles for link-only feed entries.

Only captured source fields count here. An AI summary or recommendation must
never turn an otherwise empty link into evidence for its own score.
"""

from __future__ import annotations

import re

from app.services.content_summary import clean_content_summary

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>，。！？；）】]+", re.IGNORECASE)
_LINK_LABEL_RE = re.compile(
    r"(?:阅读原文|查看原文|点击阅读原文|点击查看原文|原文链接|原文|"
    r"read\s+(?:more|original|full\s+(?:article|story))|"
    r"(?:original|full)\s+(?:article|story)|(?:article|comments?)\s+url)"
    r"(?:\s*(?:via|来源|来自)\s*[\w.-]+)?",
    re.IGNORECASE,
)


def readable_source_text(value: str | None) -> str:
    """Remove markup, URLs and standalone navigation labels, keeping prose."""
    if not isinstance(value, str) or not value:
        return ""
    text = clean_content_summary(value) if "<" in value or "&" in value else value.strip()
    # Keep the label of Markdown links: an authored title can carry evidence,
    # while [Read more](url) and [url](url) cannot.
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = _URL_RE.sub("", text)
    text = text.strip(" \t\r\n🔗·|:：-—[]()<>{}")
    if _LINK_LABEL_RE.fullmatch(text) or not re.search(r"\w", text):
        return ""
    return text


def has_readable_content(title: str | None, summary: str | None = None, raw_content: str | None = None) -> bool:
    return any(readable_source_text(value) for value in (title, summary, raw_content))


def readable_content_title(
    title: str | None,
    summary: str | None = None,
    raw_content: str | None = None,
    *,
    fallback: str = "原文待补全",
) -> str:
    """Use a real feed title, else a bounded source excerpt; never AI prose."""
    if readable_source_text(title):
        return title or ""
    for value in (raw_content, summary):
        if text := readable_source_text(value):
            sentence = re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+", text, maxsplit=1)[0]
            return sentence if len(sentence) <= 120 else sentence[:119] + "…"
    return fallback
