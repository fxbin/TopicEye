"""
外部告警 webhook。

在关键事件（source 连续失败、scheduler 异常等）时发送通知到外部通道
（飞书/钉钉/Slack 通用 incoming webhook）。

webhook URL 通过 ALERT_WEBHOOK_URL 环境变量配置。未配置时静默跳过。
消息格式兼容飞书/钉钉/Slack 的简单 text 消息。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, UTC
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 防止告警风暴：同一 alert_key 在 _DEDUP_WINDOW 内只发一次
_LAST_SENT: dict[str, float] = {}
_DEDUP_WINDOW_SECONDS = 3600  # 1 小时内同 key 不重复发


async def send_alert(
    *,
    title: str,
    message: str,
    alert_key: str,
    severity: str = "warning",
) -> bool:
    """发送告警到外部 webhook。

    Parameters
    ----------
    title : 告警标题
    message : 告警详情
    alert_key : 去重 key（同 key 在 _DEDUP_WINDOW 内只发一次）
    severity : info / warning / error

    Returns: True 如果发送成功或跳过（去重），False 如果发送失败。
    """
    import time

    webhook_url = getattr(settings, "ALERT_WEBHOOK_URL", None) or ""
    if not webhook_url:
        return False  # 未配置 webhook，静默跳过

    # 去重检查
    now = time.monotonic()
    last = _LAST_SENT.get(alert_key)
    if last is not None and (now - last) < _DEDUP_WINDOW_SECONDS:
        return True  # 去重跳过

    _LAST_SENT[alert_key] = now

    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    emoji = {"info": "ℹ️", "warning": "⚠️", "error": "🚨"}.get(severity, "⚠️")
    text = f"{emoji} [{severity.upper()}] {title}\n{message}\n\n_{ts}_"

    # 飞书/钉钉/Slack 通用 payload（都支持 {"text": "..."} 格式）
    payload = {"text": text}
    # 飞书额外需要 msg_type
    if "feishu" in webhook_url or "larksuite" in webhook_url:
        payload = {"msg_type": "text", "content": {"text": text}}
    # 钉钉
    elif "oapi.dingtalk" in webhook_url:
        payload = {"msgtype": "text", "text": {"content": text}}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code < 300:
                logger.info("Alert sent: %s (key=%s)", title, alert_key)
                return True
            logger.warning(
                "Alert webhook returned %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return False
    except Exception as exc:
        logger.warning("Alert webhook failed (non-fatal): %s", exc)
        return False


async def alert_source_failures(failed_sources: list[dict]) -> None:
    """source 连续失败告警。

    failed_sources: [{"name": ..., "source_type": ..., "error": ..., "fail_count": N}]
    """
    if not failed_sources:
        return

    lines = [f"  • {s['name']} ({s.get('source_type', '?')}): {s.get('error', '?')[:100]}" for s in failed_sources[:10]]
    message = f"{len(failed_sources)} 个信源抓取连续失败:\n" + "\n".join(lines)
    if len(failed_sources) > 10:
        message += f"\n  ... 共 {len(failed_sources)} 个"

    await send_alert(
        title="信源抓取失败告警",
        message=message,
        alert_key=f"source_failures:{datetime.now(UTC).strftime('%Y-%m-%d-%H')}",
        severity="warning",
    )
