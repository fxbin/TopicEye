"""Prompt injection sanitisation utilities.

When user-generated or crawled content is interpolated into LLM prompts via
``.format()``, two risks exist:

1. **Format-string breakage** — a literal ``{`` or ``}`` in the content
   raises ``KeyError`` / ``IndexError`` during ``str.format()``.
2. **Prompt injection** — adversarial text like ``"Ignore previous
   instructions and ..."`` can manipulate the LLM's behaviour.

This module provides :func:`sanitize_prompt_input` which:

- Strips control characters (``\\x00-\\x1f``, ``\\x7f``) that break JSON
  serialisation and prompt formatting.
- Collapses excessive whitespace to keep prompt token usage bounded.
- Truncates to a caller-specified ``max_chars`` ceiling.
- Escapes ``{`` / ``}`` to ``{{`` / ``}}`` so the value is safe to pass
  through ``str.format()`` without raising or being interpreted as a
  placeholder.

Typical usage::

    from app.utils.prompt_safety import sanitize_prompt_input

    prompt = TEMPLATE.format(
        title=sanitize_prompt_input(content.title, max_chars=500),
        body=sanitize_prompt_input(content.raw_content, max_chars=3000),
    )
"""

from __future__ import annotations

import re

# Control chars: \x00-\x1f (C0) + \x7f (DEL), excluding \t \n \r which are
# legitimate whitespace in prompt text.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Collapse 3+ consecutive newlines → 2, and 3+ spaces → 2.
_COLLAPSE_WS_RE = re.compile(r"\n{3,}")
_COLLAPSE_SP_RE = re.compile(r" {3,}")


def sanitize_prompt_input(
    value: str | None,
    *,
    max_chars: int = 3000,
    escape_braces: bool = True,
) -> str:
    """Sanitise external content before interpolating into a ``.format()`` prompt.

    Parameters
    ----------
    value
        Raw input string (typically ``content.title``, ``content.raw_content``,
        etc.).  ``None`` is treated as an empty string.
    max_chars
        Hard ceiling on output length.  Default 3000 chars (~1000 tokens).
    escape_braces
        When ``True`` (default), escapes ``{`` → ``{{`` and ``}`` → ``}}``
        so the result is safe to use as a ``str.format()`` argument.

    Returns
    -------
    str
        Sanitised, truncated, brace-safe string.
    """
    if not value:
        return ""

    text = str(value)

    # 1. Strip control characters (keep \t \n \r)
    text = _CONTROL_RE.sub("", text)

    # 2. Collapse excessive whitespace
    text = _COLLAPSE_WS_RE.sub("\n\n", text)
    text = _COLLAPSE_SP_RE.sub("  ", text)

    # 3. Truncate
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…(truncated)"

    # 4. Escape braces so .format() treats the value as literal text
    if escape_braces:
        text = text.replace("{", "{{").replace("}", "}}")

    return text
