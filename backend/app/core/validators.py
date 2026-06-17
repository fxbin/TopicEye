"""
通用输入验证器（密码强度、字段长度等）。

集中在 schemas 中复用，避免各 schema 重复实现。
"""

from __future__ import annotations

import re


# 常用字段长度上限（防止 DoS + 合理业务限制）
MAX_EMAIL_LEN = 255
MAX_PASSWORD_LEN = 128
MIN_PASSWORD_LEN = 8
MAX_NAME_LEN = 100
MAX_TITLE_LEN = 500
MAX_URL_LEN = 1024
MAX_TEXT_LEN = 100_000  # 100KB；raw_content 等大字段

# 密码强度：至少 1 字母 + 1 数字
_PASSWORD_RE = re.compile(r"[A-Za-z]")
_PASSWORD_DIGIT_RE = re.compile(r"\d")


def validate_password_strength(password: str) -> str:
    """校验密码强度。返回原值（用于链式调用），校验失败抛 ValueError。

    要求：
    - 长度 >= MIN_PASSWORD_LEN (8)
    - 至少 1 个字母
    - 至少 1 个数字
    """
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"密码至少需要 {MIN_PASSWORD_LEN} 个字符")
    if len(password) > MAX_PASSWORD_LEN:
        raise ValueError(f"密码最多 {MAX_PASSWORD_LEN} 个字符")
    if not _PASSWORD_RE.search(password):
        raise ValueError("密码必须包含至少 1 个字母")
    if not _PASSWORD_DIGIT_RE.search(password):
        raise ValueError("密码必须包含至少 1 个数字")
    return password


def truncate_string(value: str, max_len: int, field: str = "field") -> str:
    """截断超长字符串（防止 DoS）。"""
    if value and len(value) > max_len:
        raise ValueError(f"{field} 不能超过 {max_len} 字符")
    return value
