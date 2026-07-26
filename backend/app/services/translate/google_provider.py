"""Google Translate 免费 web API 引擎。

无需 API key，通过 translate.googleapis.com 公开端点翻译。
单次请求上限 ~5000 字符，超长文本自动分段并发翻译。
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.services.translate.base import TranslateResult

logger = logging.getLogger(__name__)

_GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
_MAX_CHUNK_SIZE = 4500
_MAX_CONCURRENT = 5
_BLOCK_SEPARATOR = "\n@@SEP@@\n"


class GoogleTranslateProvider:
    """Google Translate 免费 web API 引擎。"""

    @property
    def name(self) -> str:
        return "google"

    def is_available(self) -> bool:
        return True  # 无需任何配置，始终可用

    async def _translate_chunk(self, text: str, client: httpx.AsyncClient) -> str:
        """翻译单段文本。失败返回空字符串。"""
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
            if isinstance(data, list) and data and isinstance(data[0], list):
                return "".join(seg[0] for seg in data[0] if isinstance(seg, list) and seg)
            return ""
        except Exception as exc:
            logger.warning("Google Translate request failed: %s", exc)
            return ""

    def _split_text(self, text: str, max_size: int = _MAX_CHUNK_SIZE) -> list[str]:
        """将长文本按段落边界分块。"""
        if len(text) <= max_size:
            return [text]

        chunks: list[str] = []
        paragraphs = text.split("\n")
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 1 <= max_size:
                current = current + "\n" + para if current else para
            else:
                if current:
                    chunks.append(current)
                while len(para) > max_size:
                    chunks.append(para[:max_size])
                    para = para[max_size:]
                current = para
        if current:
            chunks.append(current)
        return chunks

    async def _translate_long_text(self, text: str) -> str | None:
        """翻译任意长度文本，自动分块并发。"""
        chunks = self._split_text(text)
        if not chunks:
            return None

        semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        results: list[str] = [""] * len(chunks)

        async def _translate_one(idx: int, chunk: str) -> None:
            async with semaphore:
                for attempt in range(2):
                    async with httpx.AsyncClient() as client:
                        result = await self._translate_chunk(chunk, client)
                    if result:
                        results[idx] = result
                        return
                    if attempt == 0:
                        await asyncio.sleep(0.5)

        await asyncio.gather(*[_translate_one(i, c) for i, c in enumerate(chunks)])

        translated = "\n".join(r for r in results if r)
        return translated or None

    async def translate(self, text: str, blocks: list[dict] | None = None) -> TranslateResult | None:
        """执行翻译。成功返回 TranslateResult，失败返回 None。"""
        if blocks:
            # 合并 blocks 文本，用分隔符标记边界
            texts_with_idx: list[tuple[int, str]] = [
                (i, b.get("text", "")) for i, b in enumerate(blocks) if b.get("text", "").strip()
            ]
            if not texts_with_idx:
                return TranslateResult(text=text, blocks=[dict(b) for b in blocks], provider=self.name)

            combined = _BLOCK_SEPARATOR.join(t for _, t in texts_with_idx)
            translated = await self._translate_long_text(combined)
            if translated is None:
                return None

            parts = translated.split("@@SEP@@")
            if len(parts) != len(texts_with_idx):
                logger.warning(
                    "Google block translation split mismatch: expected %d, got %d",
                    len(texts_with_idx),
                    len(parts),
                )
                return None

            trans_map: dict[int, str] = {}
            for (idx, _), part in zip(texts_with_idx, parts, strict=False):
                trans_map[idx] = part.strip()

            translated_blocks = []
            for i, block in enumerate(blocks):
                new_block = dict(block)
                if i in trans_map and trans_map[i]:
                    new_block["text"] = trans_map[i]
                translated_blocks.append(new_block)

            full_text = "\n\n".join(str(b.get("text", "")) for b in translated_blocks if b.get("text"))
            return TranslateResult(text=full_text, blocks=translated_blocks, provider=self.name)

        # 纯文本翻译
        translated = await self._translate_long_text(text)
        if translated is None:
            return None
        return TranslateResult(text=translated, provider=self.name)
