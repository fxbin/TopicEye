"""邮件 Provider 抽象基类。

定义统一的邮件发送接口，具体实现由各 Provider（Brevo/Resend 等）完成。
新增 Provider 只需继承本类并实现 name 与 send_verification_code。
"""
# author: fxbin

from __future__ import annotations

from abc import ABC, abstractmethod


class EmailSendError(Exception):
    """邮件发送失败异常。所有 Provider 的发送错误统一包装为本异常。"""


class EmailProvider(ABC):
    """邮件发送 Provider 抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 唯一标识名称，用于配置路由与日志追踪。"""

    @abstractmethod
    async def send_verification_code(self, to_email: str, code: str) -> None:
        """发送验证码邮件到指定邮箱。

        参数:
            to_email: 收件人邮箱地址
            code: 验证码明文

        异常:
            EmailSendError: 发送失败时抛出
        """
