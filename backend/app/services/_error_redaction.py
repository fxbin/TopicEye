"""信源同步错误敏感信息脱敏（纯函数 + 常量）。

从 app.services.content_pipeline 抽出的独立纯函数模块：
- 4 个正则常量：SENSITIVE_PAIR_RE / AUTH_HEADER_RE / BEARER_RE / SENSITIVE_ENV_SUFFIXES
- redact_source_sync_error — 主入口
- _source_error_secrets — 从 os.environ 扫描实际注入的 secret

无 SQLAlchemy / 业务依赖，便于单测。
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote

_SENSITIVE_ENV_SUFFIXES = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
_SENSITIVE_PAIR_RE = re.compile(
    r"(?i)([\"']?\b(?:access[_-]?token|api[_-]?key|apikey|auth[_-]?token|"
    r"client[_-]?secret|secret|password|passwd|pwd|token|key)\b[\"']?\s*[:=]\s*[\"']?)"
    r"([^&\s,;\"'<>}]+)([\"']?)"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)([\"']?\bauthorization\b[\"']?\s*[:=]\s*[\"']?)(?!Bearer\s+\*\*\*)" r"([^,\s;\"'<>}]+)([\"']?)"
)
_BEARER_RE = re.compile(r"\bBearer\s+[^\s,;\"'<>]+", re.IGNORECASE)


def redact_source_sync_error(message: str) -> str:
    """Remove source credentials before persisting sync errors."""
    redacted = str(message or "")

    for secret in _source_error_secrets():
        redacted = redacted.replace(secret, "***")

    redacted = _BEARER_RE.sub("Bearer ***", redacted)
    redacted = _AUTH_HEADER_RE.sub(r"\1***\3", redacted)
    redacted = _SENSITIVE_PAIR_RE.sub(r"\1***\3", redacted)
    return redacted.strip() or "信源同步失败"


def _source_error_secrets() -> list[str]:
    secrets: set[str] = set()
    for name, value in os.environ.items():
        if not value or len(value.strip()) < 8:
            continue
        upper_name = name.upper()
        if upper_name.endswith(_SENSITIVE_ENV_SUFFIXES) or upper_name in {"HTTPS_PROXY", "HTTP_PROXY"}:
            stripped = value.strip()
            secrets.add(stripped)
            secrets.add(quote(stripped, safe=""))
    return sorted(secrets, key=len, reverse=True)
