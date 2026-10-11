"""邮件发送服务模块。

提供可配置的邮件 Provider 抽象，当前唯一实现为自定义 SMTP
（#108 起仅剩 SMTP，Brevo 已移除）。
新增 Provider 只需继承 EmailProvider 并在 factory 中注册。
"""
# author: fxbin

from app.services.email.base import EmailProvider, EmailSendError

__all__ = ["EmailProvider", "EmailSendError"]
