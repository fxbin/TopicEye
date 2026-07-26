"""翻译 provider 协议定义。

所有翻译引擎实现此协议，由 TranslateChain 统一调度。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslateResult:
    """翻译结果。"""

    text: str
    blocks: list[dict] | None = None
    provider: str = ""


@runtime_checkable
class TranslateProvider(Protocol):
    """翻译引擎协议。

    每个引擎实现两个方法：
    - name: 引擎标识，用于日志和配置
    - is_available: 是否可用（如需 API key 但未配置则返回 False）
    - translate: 执行翻译，失败返回 None
    """

    @property
    def name(self) -> str: ...

    def is_available(self) -> bool: ...

    async def translate(self, text: str, blocks: list[dict] | None = None) -> TranslateResult | None: ...
