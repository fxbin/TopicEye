"""快速翻译服务 — 用免费 Google Translate API 做首选，LLM 降级兜底。

设计：
- Google Translate 免费 web API：无需 API key，~1-2s 完成，质量足够阅读
- 单次请求上限 ~5000 字符，超长文本自动分段并发翻译
- 失败时返回 None，调用方降级到 LLM
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Google Translate 免费 web API 端点（无需 API key）
_GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
# 单次请求字符上限（Google 限制约 5000 字符）
_MAX_CHUNK_SIZE = 4500
# 并发翻译上限
_MAX_CONCURRENT = 5


async def _translate_chunk(text: str, client: httpx.AsyncClient) -> str:
    """用 Google Translate 免费 API 翻译单段文本。

    返回翻译结果；失败返回空字符串。
    """
    if not text or not text.strip():
        return text

    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": "zh-CN",
        "dt": "t",
        "q": text,
    }
    try:
        resp = await client.get(_GOOGLE_TRANSLATE_URL, params=params, timeout=15)
        if resp.status_code != 200:
            logger.warning("Google Translate returned %d", resp.status_code)
            return ""

        data = resp.json()
        # 响应格式: [[["翻译结果","原文",...],...],...]
        # 拼接所有翻译片段
        if isinstance(data, list) and data and isinstance(data[0], list):
            return "".join(seg[0] for seg in data[0] if isinstance(seg, list) and seg)
        return ""
    except Exception as exc:
        logger.warning("Google Translate request failed: %s", exc)
        return ""


def _split_text(text: str, max_size: int = _MAX_CHUNK_SIZE) -> list[str]:
    """将长文本按段落边界分块，每块不超过 max_size 字符。"""
    if len(text) <= max_size:
        return [text]

    chunks: list[str] = []
    # 按换行符分割，尽量在段落边界切分
    paragraphs = text.split("\n")
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 1 <= max_size:
            current = current + "\n" + para if current else para
        else:
            if current:
                chunks.append(current)
            # 单段超长 → 硬切
            while len(para) > max_size:
                chunks.append(para[:max_size])
                para = para[max_size:]
            current = para
    if current:
        chunks.append(current)
    return chunks


async def translate_text_fast(text: str) -> str | None:
    """快速翻译纯文本。成功返回翻译结果，失败返回 None。

    使用 Google Translate 免费 web API，自动分块并发。
    """
    if not text or not text.strip():
        return text

    chunks = _split_text(text)
    if not chunks:
        return None

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    results: list[str] = [""] * len(chunks)

    async def _translate_one(idx: int, chunk: str) -> None:
        async with semaphore:
            # 重试一次
            for attempt in range(2):
                async with httpx.AsyncClient() as client:
                    result = await _translate_chunk(chunk, client)
                if result:
                    results[idx] = result
                    return
                if attempt == 0:
                    await asyncio.sleep(0.5)

    await asyncio.gather(*[_translate_one(i, c) for i, c in enumerate(chunks)])

    translated = "\n".join(r for r in results if r)
    if not translated:
        return None
    return translated


async def translate_blocks_fast(blocks: list[dict]) -> list[dict] | None:
    """快速翻译 content_blocks 数组，保留结构。

    成功返回带中文 text 的新 blocks 列表，失败返回 None。
    """
    if not blocks:
        return None

    # 提取需要翻译的文本
    texts_to_translate: list[tuple[int, str]] = []
    for i, block in enumerate(blocks):
        text = block.get("text", "")
        if text and text.strip():
            texts_to_translate.append((i, text))

    if not texts_to_translate:
        return [dict(b) for b in blocks]

    # 合并成大文本翻译（减少请求数），用分隔符标记边界
    SEPARATOR = "\n@@SEP@@\n"
    combined = SEPARATOR.join(t for _, t in texts_to_translate)

    translated = await translate_text_fast(combined)
    if translated is None:
        return None

    # 拆分翻译结果
    parts = translated.split("@@SEP@@")
    # 如果拆分数量不匹配，说明翻译有问题，降级
    if len(parts) != len(texts_to_translate):
        logger.warning(
            "Block translation split mismatch: expected %d, got %d",
            len(texts_to_translate),
            len(parts),
        )
        return None

    # 构建翻译后的 blocks
    translated_blocks = []
    trans_map: dict[int, str] = {}
    for (idx, _), part in zip(texts_to_translate, parts, strict=False):
        trans_map[idx] = part.strip()

    for i, block in enumerate(blocks):
        new_block = dict(block)
        if i in trans_map and trans_map[i]:
            new_block["text"] = trans_map[i]
        translated_blocks.append(new_block)

    return translated_blocks
