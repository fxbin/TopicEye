"""分层翻译服务包。

设计：
- 翻译能力抽象为 TranslateProvider 协议，每个引擎独立实现
- TranslateChain 按 priority 顺序尝试，首个成功即返回
- 新增引擎只需实现协议 + 注册到 chain，不改动调用方

当前引擎：
  1. Google Translate（免费 web API，~1-2s，无需 key）
  2. Azure Translator（官方 API，需 key，预留）
  3. LLM（质量最高，~15-60s，降级兜底）

调用方只需：
    from app.services.translate import translate_text, translate_blocks
"""

from app.services.translate.chain import translate_blocks, translate_text

__all__ = ["translate_text", "translate_blocks"]
