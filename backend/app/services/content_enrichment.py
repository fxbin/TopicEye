"""Ingest-time full-text capture for reader-heavy hosts.

站内阅读在点击时才外呼源站，掘金等按 IP 频率限流的站点会把点击时的
抓取挡在 WAF 挑战页外（见 #160）。入库阶段是调度可控、频率可限的时机：
去重后、落库前对缺正文的候选条目预抓一次原文，重建为受控的结构化 HTML
存进 ``raw_content``，站内阅读即可优先走 ingested 路径、点击时零外呼。

抓取复用 article_reader 的分层抓取与提取（SSRF 校验、robots、体积上限、
反爬挑战识别全部继承）；任何失败只跳过该条目，绝不阻断入库（fail-open）。
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings
from app.services import article_reader

logger = logging.getLogger(__name__)

# raw_content 短于该值视为「没有正文」（掘金推荐流的 brief 只有约 90 字）
_MIN_RAW_CONTENT_CHARS = 200
# 进程级最小抓取间隔：多个信源并发入库时也不会密集外呼同一源站
_MIN_FETCH_INTERVAL_SECONDS = 2.0

_fetch_lock = asyncio.Lock()
_last_fetch_monotonic = 0.0


def _target_hosts() -> tuple[str, ...]:
    return tuple(host.strip().lower() for host in settings.INGEST_FULLTEXT_HOSTS.split(",") if host.strip())


def _host_matches(url: str, hosts: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in hosts)


def _blocks_to_safe_html(blocks: list[dict[str, Any]]) -> str:
    """把提取出的结构块重建为受控 HTML 存入 raw_content。

    只使用 article_reader 能重新解析的安全原语（heading/p/list_item/quote/
    pre/img），文本全部转义；ingested 路径读取时可完整还原结构块，不继承
    第三方页面的任何标记。
    """
    parts: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        text = html.escape(str(block.get("text") or ""))
        if block_type == "heading":
            level = min(6, max(1, int(block.get("level") or 2)))
            parts.append(f"<h{level}>{text}</h{level}>")
        elif block_type == "list_item":
            parts.append(f"<li>{text}</li>")
        elif block_type == "quote":
            parts.append(f"<blockquote>{text}</blockquote>")
        elif block_type == "code":
            parts.append(f"<pre><code>{text}</code></pre>")
        elif block_type == "image":
            src = html.escape(str(block.get("src") or ""), quote=True)
            alt = html.escape(str(block.get("alt") or ""), quote=True)
            parts.append(f'<img src="{src}" alt="{alt}">')
        elif text:
            parts.append(f"<p>{text}</p>")
    return "\n".join(parts)


async def _throttled_fetch_safe_html(url: str) -> str | None:
    """限速抓一次原文并重建结构化 HTML；任何失败返回 None（fail-open）。"""
    global _last_fetch_monotonic
    async with _fetch_lock:
        wait_seconds = _last_fetch_monotonic + _MIN_FETCH_INTERVAL_SECONDS - time.monotonic()
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        try:
            extracted = await article_reader.fetch_readable_article(url)
        except article_reader.ArticleReaderError as exc:
            logger.info("全文补全跳过 %s：%s", url, exc.code)
            return None
        except Exception:  # noqa: BLE001 — 补全失败永不阻断入库
            logger.warning("全文补全失败 %s", url, exc_info=True)
            return None
        finally:
            _last_fetch_monotonic = time.monotonic()
    return _blocks_to_safe_html(extracted.content_blocks) or None


async def enrich_new_entries(entries: list[dict[str, Any]]) -> int:
    """对命中信源域名且缺正文的入库候选补全文，返回补全条数。

    只处理去重后的新候选（调用方保证），避免对已知内容重复外呼。
    """
    hosts = _target_hosts()
    if not hosts or not entries:
        return 0

    cap = settings.INGEST_FULLTEXT_MAX_PER_SYNC
    enriched = 0
    for entry in entries:
        if enriched >= cap:
            break
        if len(str(entry.get("raw_content") or "")) >= _MIN_RAW_CONTENT_CHARS:
            continue
        url = str(entry.get("url") or "")
        if not _host_matches(url, hosts):
            continue
        safe_html = await _throttled_fetch_safe_html(url)
        if safe_html:
            entry["raw_content"] = safe_html
            enriched += 1
    if enriched:
        logger.info("全文补全：本批捕获 %d 条", enriched)
    return enriched
