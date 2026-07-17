"""Brevo 邮件 Provider 实现。

通过 Brevo（原 Sendinblue）REST API 发送事务邮件。
免费额度：300 封/天 ≈ 9000 封/月，无需信用卡。
官方文档：https://developers.brevo.com/docs/getting-started
"""
# author: fxbin

from __future__ import annotations

import logging

import httpx

from app.services.email.base import EmailProvider, EmailSendError

logger = logging.getLogger(__name__)

# Brevo API 基础地址与发送端点
_BREVO_API_BASE = "https://api.brevo.com/v3"
_BREVO_SEND_ENDPOINT = f"{_BREVO_API_BASE}/smtp/email"

# HTTP 请求超时时间（秒）
_BREVO_TIMEOUT_SECONDS = 10.0

# 邮件主题
_EMAIL_SUBJECT = "【TopicEye】邮箱验证码"


class BrevoProvider(EmailProvider):
    """Brevo 邮件发送 Provider。

    通过 Brevo SMTP REST API 发送验证码邮件，需要在管理员后台配置 API Key。
    """

    def __init__(self, *, api_key: str, from_email: str, from_name: str) -> None:
        """初始化 Brevo Provider。

        参数:
            api_key: Brevo API Key（以 xkeysib- 开头）
            from_email: 发件人邮箱（需在 Brevo 后台完成域名认证）
            from_name: 发件人显示名称
        """
        self._api_key = api_key
        self._from_email = from_email
        self._from_name = from_name

    @property
    def name(self) -> str:
        return "brevo"

    async def send_verification_code(self, to_email: str, code: str) -> None:
        """通过 Brevo API 发送验证码邮件。

        参数:
            to_email: 收件人邮箱
            code: 6 位数字验证码

        异常:
            EmailSendError: 网络错误或 API 返回非 2xx 时抛出
        """
        headers = {
            "api-key": self._api_key,
            "Content-Type": "application/json",
            "accept": "application/json",
        }
        payload = {
            "sender": {"email": self._from_email, "name": self._from_name},
            "to": [{"email": to_email}],
            "subject": _EMAIL_SUBJECT,
            "htmlContent": _build_verification_email_html(code),
        }

        try:
            async with httpx.AsyncClient(timeout=_BREVO_TIMEOUT_SECONDS) as client:
                response = await client.post(_BREVO_SEND_ENDPOINT, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            logger.exception("Brevo API 请求失败")
            raise EmailSendError("邮件服务暂时不可用，请稍后重试") from exc

        if response.status_code >= 400:
            logger.error(
                "Brevo API 返回错误: status=%s body=%s",
                response.status_code,
                response.text,
            )
            raise EmailSendError("邮件发送失败，请检查发件配置或稍后重试")


def _build_verification_email_html(code: str) -> str:
    """构造验证码邮件 HTML 内容。

    参数:
        code: 验证码明文

    返回:
        符合邮件客户端渲染的 HTML 字符串
    """
    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #1f2937; max-width: 480px; margin: 0 auto; padding: 24px;">
  <h2 style="font-size: 18px; font-weight: 800; margin-bottom: 16px;">TopicEye 邮箱验证码</h2>
  <p style="font-size: 14px; line-height: 1.6; color: #4b5563;">你正在注册 TopicEye 账号，验证码为：</p>
  <div style="margin: 24px 0; text-align: center;">
    <span style="display: inline-block; font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #111827; background: #f3f4f6; padding: 12px 24px; border-radius: 6px;">{code}</span>
  </div>
  <p style="font-size: 13px; line-height: 1.6; color: #6b7280;">验证码 10 分钟内有效。如非本人操作，请忽略此邮件。</p>
  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
  <p style="font-size: 12px; color: #9ca3af;">此邮件由系统自动发送，请勿回复。</p>
</body>
</html>
"""
