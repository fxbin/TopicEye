"""翻译 provider chain 编排器。

按 priority 顺序尝试已注册的翻译引擎，首个成功即返回。
新增引擎只需实现 TranslateProvider 协议 + 注册到 _build_chain()。

引擎优先级：
  1. Google Translate  — 免费，~1-2s，无需配置
  2. LLM               — 质量最高，~15-60s，降级兜底

新增引擎只需实现 TranslateProvider 协议 + 在 _build_chain() 注册。
"""

from __future__ import annotations

import logging

from app.services.translate.base import TranslateProvider, TranslateResult
from app.services.translate.google_provider import GoogleTranslateProvider

logger = logging.getLogger(__name__)

_chain: list[TranslateProvider] | None = None


def _build_chain() -> list[TranslateProvider]:
    """构建翻译引擎链。按优先级排序。"""
    providers: list[TranslateProvider] = []

    # 1. Google Translate（始终可用）
    providers.append(GoogleTranslateProvider())

    # 2. LLM（降级兜底，始终可用）
    from app.services.translate.llm_provider import LLMTranslateProvider

    providers.append(LLMTranslateProvider())

    return providers


def _get_chain() -> list[TranslateProvider]:
    """获取翻译引擎链（惰性初始化）。"""
    global _chain
    if _chain is None:
        _chain = _build_chain()
    return _chain


async def translate_text(text: str) -> TranslateResult | None:
    """翻译纯文本。按 chain 顺序尝试，首个成功即返回。"""
    if not text or not text.strip():
        return TranslateResult(text=text, provider="skip")

    for provider in _get_chain():
        if not provider.is_available():
            continue
        try:
            result = await provider.translate(text)
            if result is not None:
                logger.info("Translated via %s (text): %d chars", provider.name, len(result.text))
                return result
        except Exception:
            logger.warning("Provider %s failed", provider.name, exc_info=True)

    logger.error("All translation providers failed")
    return None


async def translate_blocks(blocks: list[dict]) -> TranslateResult | None:
    """翻译 content_blocks 数组。按 chain 顺序尝试，首个成功即返回。"""
    if not blocks:
        return TranslateResult(text="", blocks=[], provider="skip")

    for provider in _get_chain():
        if not provider.is_available():
            continue
        try:
            result = await provider.translate("", blocks=blocks)
            if result is not None:
                logger.info(
                    "Translated via %s (blocks): %d blocks", provider.name, len(result.blocks or [])
                )
                return result
        except Exception:
            logger.warning("Provider %s failed", provider.name, exc_info=True)

    logger.error("All translation providers failed")
    return None
