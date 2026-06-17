"""
番茄小说文字解码器。
基于 JSON 映射文件解码番茄小说 API 返回的加密文字（Unicode 私用区 U+E428~U+E59B）。

参考：Java 版 FanQieTextDecoder + FanQieNovelDataConverter
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Unicode 私用区范围（与 Java 版 CODE_START/CODE_END 一致）
CODE_START = 58344  # 0xE428
CODE_END = 58715  # 0xE59B

# 映射表缓存（模块级单例）
_char_mapping: Optional[dict[int, str]] = None


def _load_mapping() -> dict[int, str]:
    """加载字符映射表，只加载一次。"""
    global _char_mapping
    if _char_mapping is not None:
        return _char_mapping

    mapping_path = Path(__file__).parent / "fanqie_mapping.json"
    try:
        raw: dict[str, str] = json.loads(mapping_path.read_text(encoding="utf-8"))
        _char_mapping = {}
        for k, v in raw.items():
            try:
                _char_mapping[int(k)] = v
            except ValueError:
                pass
        logger.info("已加载番茄小说字符映射表，共 %d 个字符", len(_char_mapping))
    except Exception as e:
        logger.error("加载番茄小说字符映射表失败: %s", e)
        _char_mapping = {}

    return _char_mapping


def decode_text(text: str) -> str:
    """解码单个字符串中的加密字符。"""
    if not text:
        return text

    mapping = _load_mapping()
    if not mapping:
        return text

    # 快速路径：检查是否包含私用区字符
    result = []
    changed = False
    for ch in text:
        cp = ord(ch)
        if CODE_START <= cp <= CODE_END:
            replacement = mapping.get(cp)
            if replacement:
                result.append(replacement)
                changed = True
                continue
        result.append(ch)

    return "".join(result) if changed else text


def clean_book(book: dict) -> dict:
    """清洗单条图书记录中的乱码字段（原地修改并返回）。"""
    text_fields = [
        "bookName",
        "author",
        "abstract",
        "lastChapterTitle",
        "category",
    ]
    for field in text_fields:
        val = book.get(field)
        if val and isinstance(val, str):
            book[field] = decode_text(val)
    return book


def clean_books(book_list: list[dict]) -> list[dict]:
    """批量清洗图书列表中的乱码字段。"""
    for book in book_list:
        clean_book(book)
    return book_list
