"""
外部告警 webhook。

在关键事件（source 连续失败、scheduler 异常等）时发送通知到外部通道
（飞书/钉钉/Slack 通用 incoming webhook）。

webhook URL 来源（两条独立通道，任一启用即发）：
1. DB 配置 `notification_webhook_config`（运营通道，可在管理后台配置，支持 enable 开关）
2. 环境变量 `ALERT_WEBHOOK_URL`（运维通道，向后兼容）

消息格式兼容飞书/钉钉/Slack 的简单 text 消息。
高级推送能力（卡片消息、日报、精选内容）为后续阶段。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, UTC

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 防止告警风暴：同一 alert_key 在 _DEDUP_WINDOW 内只发一次
_LAST_SENT: dict[str, float] = {}
_DEDUP_WINDOW_SECONDS = 3600  # 1 小时内同 key 不重复发


async def _resolve_webhook_urls() -> list[str]:
    """收集所有应发送的 webhook URL。

    优先级：DB 配置（enabled=True）+ 环境变量（向后兼容）。
    DB 读取失败时静默 fallback 到 env only（告警链路不能因 DB 异常而中断）。
    """
    urls: list[str] = []

    # 1. DB 配置（运营通道）
    try:
        import json

        from sqlalchemy import select

        from app.core.database import async_session
        from app.models.app_setting import AppSetting
        from app.services.secret_store import decrypt_secret

        async with async_session() as db:
            result = await db.execute(
                select(AppSetting).where(AppSetting.key == "notification_webhook_config")
            )
            row = result.scalar_one_or_none()
            if row and row.value:
                try:
                    cfg = json.loads(row.value)
                except json.JSONDecodeError:
                    cfg = {}
                if cfg.get("enabled"):
                    plain = decrypt_secret(cfg.get("webhook_url", "")) or ""
                    if plain:
                        urls.append(plain)
    except Exception as exc:
        # DB 异常不能阻塞告警
        logger.warning("读取 notification_webhook_config 失败（non-fatal）: %s", exc)

    # 2. 环境变量（运维通道，向后兼容）
    env_url = getattr(settings, "ALERT_WEBHOOK_URL", None) or ""
    if env_url:
        urls.append(env_url)

    # 去重（DB 与 env 可能配同一个 URL）
    seen: set[str] = set()
    unique: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def _build_payload(webhook_url: str, text: str) -> dict:
    """根据 webhook URL 域名构造对应平台的 payload。"""
    # 飞书/Slack 通用 {"text": "..."} 格式
    payload = {"text": text}
    # 飞书额外需要 msg_type
    if "feishu" in webhook_url or "larksuite" in webhook_url:
        payload = {"msg_type": "text", "content": {"text": text}}
    # 钉钉
    elif "oapi.dingtalk" in webhook_url:
        payload = {"msgtype": "text", "text": {"content": text}}
    return payload


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

    Returns: True 如果发送成功或跳过（去重/未配置），False 如果所有 webhook 发送失败。
    """
    import time

    webhook_urls = await _resolve_webhook_urls()
    if not webhook_urls:
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

    # 发到所有已配置的 webhook（任一失败不影响其他）
    any_sent = False
    async with httpx.AsyncClient(timeout=10) as client:
        for webhook_url in webhook_urls:
            payload = _build_payload(webhook_url, text)
            try:
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code < 300:
                    any_sent = True
                    logger.info("Alert sent: %s (key=%s)", title, alert_key)
                else:
                    logger.warning(
                        "Alert webhook returned %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
            except Exception as exc:
                logger.warning("Alert webhook failed (non-fatal): %s", exc)
    return any_sent


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
