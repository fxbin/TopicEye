"""LLM 翻译引擎 — 质量最高的降级兜底。

使用项目已配置的 LLM 路由（call_llm_json），翻译质量优于免费 API，
但速度较慢（15-60s）。作为 chain 的最后一级，前面的引擎全部失败时触发。
"""

from __future__ import annotations

import json
import logging

from app.services.translate.base import TranslateResult

logger = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 8000


class LLMTranslateProvider:
    """LLM 翻译引擎。"""

    @property
    def name(self) -> str:
        return "llm"

    def is_available(self) -> bool:
        return True  # LLM 路由已在数据库配置，始终可用

    async def translate(self, text: str, blocks: list[dict] | None = None) -> TranslateResult | None:
        """执行翻译。成功返回 TranslateResult，失败返回 None。"""
        from app.services.llm.provider import call_llm_json

        if blocks:
            blocks_for_llm = [
                {"i": i, "type": b.get("type"), "text": b.get("text", "")}
                for i, b in enumerate(blocks)
                if b.get("text")
            ]
            result = await call_llm_json(
                [
                    {
                        "role": "system",
                        "content": "你是专业翻译。把英文 block 数组翻译成中文，保留 type/level 结构。"
                        "技术术语和专有名词保留英文原文。输出 JSON 数组 [{\"i\":0,\"text\":\"中文\"},...]。只输出 JSON。",
                    },
                    {"role": "user", "content": json.dumps(blocks_for_llm, ensure_ascii=False)[:_MAX_TEXT_CHARS]},
                ],
                scene="reader_translate",
                temperature=0.3,
                max_tokens=6000,
            )

            translated_blocks = []
            if isinstance(result, list):
                trans_map = {
                    item.get("i"): item.get("text", "") for item in result if isinstance(item, dict)
                }
            elif isinstance(result, dict) and "translations" in result:
                trans_map = {
                    item.get("i"): item.get("text", "")
                    for item in result["translations"]
                    if isinstance(item, dict)
                }
            else:
                trans_map = {}

            for i, b in enumerate(blocks):
                tb = dict(b)
                if i in trans_map and trans_map[i]:
                    tb["text"] = trans_map[i]
                translated_blocks.append(tb)

            full_text = "\n\n".join(str(b.get("text", "")) for b in translated_blocks if b.get("text"))
            return TranslateResult(text=full_text, blocks=translated_blocks, provider=self.name)

        # 纯文本翻译
        result = await call_llm_json(
            [
                {
                    "role": "system",
                    "content": "你是专业翻译。把英文翻译成流畅的中文，保留技术术语和专有名词原文。只输出译文，不要解释。",
                },
                {"role": "user", "content": text[:_MAX_TEXT_CHARS]},
            ],
            scene="reader_translate",
            temperature=0.3,
            max_tokens=6000,
        )

        if isinstance(result, dict):
            translated_text = (
                result.get("translation") or result.get("text") or result.get("raw_response") or ""
            )
            if not translated_text and "raw_response" not in result:
                translated_text = str(result)
        else:
            translated_text = str(result[0]) if isinstance(result, list) and result else str(result)

        if not translated_text:
            return None
        return TranslateResult(text=translated_text, provider=self.name)
