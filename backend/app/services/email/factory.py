"""邮件 Provider 工厂。

根据管理员在后台配置的 email_provider_config 创建对应的 EmailProvider 实例。
配置存储在 AppSetting 表的 email_provider_config key 中（JSON 格式），
其中 smtp_password 字段使用 secret_store 加密存储。

#108 起仅支持自定义 SMTP（Brevo 已移除）；存量 brevo 配置显式降级为
不可用并记 warning，管理员在后台重配 SMTP 后恢复。
"""
# author: fxbin

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.app_setting_repo import AppSettingRepository
from app.services.email.base import EmailProvider
from app.services.email.smtp_provider import SmtpProvider
from app.services.secret_store import decrypt_secret

logger = logging.getLogger(__name__)

# Provider 名称常量
PROVIDER_SMTP = "smtp"

# 唯一支持的 Provider 名称
DEFAULT_PROVIDER_NAME = PROVIDER_SMTP

# 默认发件人显示名称
DEFAULT_FROM_NAME = "TopicEye"

# AppSetting 中存储邮件配置的 key
_EMAIL_PROVIDER_CONFIG_KEY = "email_provider_config"


async def get_email_provider(db: AsyncSession) -> EmailProvider | None:
    """从 DB 读取邮件配置并创建 Provider 实例。

    未配置或配置不完整时返回 None，调用方应据此提示管理员先完成配置。

    参数:
        db: 数据库会话

    返回:
        EmailProvider 实例，或 None（未配置）
    """
    row = await AppSettingRepository(db).get_by_key(_EMAIL_PROVIDER_CONFIG_KEY)
    if not row or not row.value:
        return None

    try:
        config = json.loads(row.value)
    except json.JSONDecodeError:
        logger.error("email_provider_config JSON 解析失败")
        return None

    provider_name = config.get("provider", DEFAULT_PROVIDER_NAME)
    from_email = config.get("from_email", "")
    from_name = config.get("from_name", DEFAULT_FROM_NAME)

    if not from_email:
        return None

    if provider_name != PROVIDER_SMTP:
        # 含 #108 前的存量 brevo 配置：显式降级而非静默忽略
        logger.warning(
            "email_provider_config 的 provider=%r 已不受支持（Brevo 已于 #108 移除），"
            "邮件服务按未配置处理，请在后台改配自定义 SMTP",
            provider_name,
        )
        return None

    host = config.get("smtp_host", "")
    port = config.get("smtp_port", 587)
    username = config.get("smtp_username", "")
    password = decrypt_secret(config.get("smtp_password"))
    use_ssl = bool(config.get("smtp_use_ssl", False))
    if not host or not username or not password:
        return None
    return SmtpProvider(
        host=host,
        port=int(port),
        username=username,
        password=password,
        use_ssl=use_ssl,
        from_email=from_email,
        from_name=from_name,
    )
