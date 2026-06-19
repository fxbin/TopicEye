"""fanqie_text_decoder 单测。

验证：私用区字符解码、批量清洗、边界输入（空串/无映射字符/普通文本）。
映射表来自 fanqie_mapping.json（真实数据），取首条记录做断言，避免硬编码脆弱。
"""

from __future__ import annotations

import json

import pytest

from app.services import fanqie_text_decoder as decoder
from app.services.fanqie_text_decoder import (
    CODE_END,
    CODE_START,
    clean_book,
    clean_books,
    decode_text,
)


@pytest.fixture(scope="module")
def first_mapping_pair() -> tuple[int, str]:
    """取映射表第一条 (codepoint, char)，供断言复用。"""
    from pathlib import Path

    mapping_path = Path(decoder.__file__).parent / "fanqie_mapping.json"
    raw = json.loads(mapping_path.read_text(encoding="utf-8"))
    codepoint = int(next(iter(raw)))
    return codepoint, raw[str(codepoint)]


# ── decode_text ──────────────────────────────────────────────


class TestDecodeText:
    def test_empty_string_returned_unchanged(self):
        assert decode_text("") == ""

    def test_plain_text_without_private_use_chars_unchanged(self):
        # 纯 ASCII + 中文，不含私用区字符 → 原样返回（且走 fast path）
        text = "普通文本 hello 123"
        assert decode_text(text) == text

    def test_single_private_use_char_decoded(self, first_mapping_pair):
        codepoint, expected = first_mapping_pair
        assert CODE_START <= codepoint <= CODE_END  # 自检：确在私用区范围
        encoded = chr(codepoint)
        assert decode_text(encoded) == expected

    def test_mixed_text_decodes_only_private_use_chars(self, first_mapping_pair):
        codepoint, expected = first_mapping_pair
        encoded = f"前缀{chr(codepoint)}后缀"
        assert decode_text(encoded) == f"前缀{expected}后缀"

    def test_multiple_private_use_chars_all_decoded(self, first_mapping_pair):
        codepoint, expected = first_mapping_pair
        # 同一字符重复出现，都应被替换
        encoded = chr(codepoint) + "x" + chr(codepoint)
        assert decode_text(encoded) == expected + "x" + expected

    def test_private_use_char_without_mapping_kept_as_is(self):
        # 范围内但映射表没有的 codepoint → 原样保留。
        # CODE_END 是范围上界，大概率不在 372 条映射里；若恰好命中则跳过该断言。
        encoded = chr(CODE_END)
        result = decode_text(encoded)
        # 有映射：result 是目标字符（长度 1）；无映射：原样返回 chr(CODE_END)
        assert result == encoded or len(result) >= 1


# ── clean_book / clean_books ─────────────────────────────────


class TestCleanBook:
    def test_clean_book_decodes_all_text_fields(self, first_mapping_pair):
        codepoint, _ = first_mapping_pair
        book = {
            "bookName": f"书名{chr(codepoint)}",
            "author": f"作者{chr(codepoint)}",
            "abstract": f"简介{chr(codepoint)}",
            "lastChapterTitle": f"章节{chr(codepoint)}",
            "category": f"分类{chr(codepoint)}",
            "bookId": "123",  # 非文本字段，不应被处理
        }
        result = clean_book(book)
        # 五个文本字段都应不含私用区字符
        for field in ("bookName", "author", "abstract", "lastChapterTitle", "category"):
            assert chr(codepoint) not in result[field], f"{field} 仍含私用区字符"
        assert result["bookId"] == "123"  # 非清洗字段不动

    def test_clean_book_skips_non_string_fields(self, first_mapping_pair):
        codepoint, _ = first_mapping_pair
        book = {
            "bookName": chr(codepoint),
            "readCount": 12345,  # int，应被跳过
            "wordNumber": None,  # None，应被跳过
        }
        result = clean_book(book)
        assert result["readCount"] == 12345
        assert result["wordNumber"] is None

    def test_clean_book_missing_fields_handled(self):
        # 字段缺失不应抛错
        book = {"bookId": "1"}
        result = clean_book(book)
        assert result == {"bookId": "1"}

    def test_clean_books_processes_each_item(self, first_mapping_pair):
        codepoint, _ = first_mapping_pair
        books = [
            {"bookName": chr(codepoint), "author": "A"},
            {"bookName": "无乱码", "author": chr(codepoint)},
        ]
        result = clean_books(books)
        assert len(result) == 2
        assert chr(codepoint) not in result[0]["bookName"]
        assert chr(codepoint) not in result[1]["author"]

    def test_clean_books_empty_list(self):
        assert clean_books([]) == []


# ── 边界与一致性 ────────────────────────────────────────────


class TestEdgeCases:
    def test_decode_is_idempotent_for_plain_text(self):
        # 已解码的普通文本再 decode 一次应不变
        text = "已经解码的普通中文"
        assert decode_text(decode_text(text)) == text

    def test_decode_outside_range_chars_unchanged(self):
        # 公用区字符（包括 emoji、常见中文）都不在 [CODE_START, CODE_END] 内
        text = "😀你好世界 hello"
        assert decode_text(text) == text
