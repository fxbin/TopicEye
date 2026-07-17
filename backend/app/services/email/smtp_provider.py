"""自定义 SMTP 邮件 Provider 实现。

通过标准 SMTP 协议发送事务邮件，支持任意 SMTP 服务器
（腾讯企业邮、Gmail、自建 Postfix 等）。
适用于 admin 已有企业邮箱的场景，到达率比第三方 API 更可控。
"""
# author: fxbin

from __future__ import annotations

import logging
from email.message import EmailMessage

from app.services.email.base import EmailProvider, EmailSendError

logger = logging.getLogger(__name__)

# SMTP 连接超时时间（秒）
_SMTP_TIMEOUT_SECONDS = 15.0

# 邮件主题
_EMAIL_SUBJECT = "【TopicEye】邮箱验证码"


class SmtpProvider(EmailProvider):
    """自定义 SMTP 邮件发送 Provider。

    通过 aiosmtplib 异步发送邮件，支持 SSL（465）与 STARTTLS（587）。
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool,
        from_email: str,
        from_name: str,
    ) -> None:
        """初始化 SMTP Provider。

        参数:
            host: SMTP 服务器主机名（如 smtp.qq.com）
            port: 端口（SSL 通常 465，STARTTLS 通常 587）
            username: SMTP 认证用户名（通常为发件人邮箱）
            password: SMTP 认证密码或授权码
            use_ssl: True 使用 SSL 直连（465），False 使用 STARTTLS（587）
            from_email: 发件人邮箱
            from_name: 发件人显示名称
        """
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_ssl = use_ssl
        self._from_email = from_email
        self._from_name = from_name

    @property
    def name(self) -> str:
        return "smtp"

    async def send_verification_code(self, to_email: str, code: str) -> None:
        """通过 SMTP 发送验证码邮件。

        参数:
            to_email: 收件人邮箱
            code: 6 位数字验证码

        异常:
            EmailSendError: 依赖缺失、连接或认证失败时抛出
        """
        # 延迟导入：aiosmtplib 仅在 SMTP 模式实际发送时需要，
        # 避免未安装该依赖时影响 Brevo 模式与应用启动
        try:
            import aiosmtplib
        except ImportError as exc:
            raise EmailSendError("SMTP 依赖未安装，请执行 pip install aiosmtplib") from exc

        message = EmailMessage()
        message["Subject"] = _EMAIL_SUBJECT
        message["From"] = f"{self._from_name} <{self._from_email}>"
        message["To"] = to_email
        message.set_content(_build_verification_email_text(code))
        message.add_alternative(_build_verification_email_html(code), subtype="html")

        try:
            await aiosmtplib.send(
                message,
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                start_tls=not self._use_ssl,
                use_tls=self._use_ssl,
                timeout=_SMTP_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.exception("SMTP 发送失败: host=%s port=%s", self._host, self._port)
            raise EmailSendError("邮件发送失败，请检查 SMTP 配置或网络") from exc


def _build_verification_email_text(code: str) -> str:
    """构造验证码邮件纯文本内容（兼容不渲染 HTML 的客户端）。

    参数:
        code: 验证码明文

    返回:
        纯文本邮件正文
    """
    return (
        "TopicEye 邮箱验证码\n\n"
        f"你的验证码是：{code}\n\n"
        "验证码 10 分钟内有效。如非本人操作，请忽略此邮件。\n"
    )


def _build_verification_email_html(code: str) -> str:
    """构造验证码邮件 HTML 内容。

    与 Brevo Provider 保持一致的视觉风格。

    参数:
        code: 验证码明文

    返回:
        HTML 邮件正文
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
