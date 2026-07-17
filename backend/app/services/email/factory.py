"""邮件 Provider 工厂。

根据管理员在后台配置的 email_provider_config 创建对应的 EmailProvider 实例。
配置存储在 AppSetting 表的 email_provider_config key 中（JSON 格式），
其中 api_key 字段使用 secret_store 加密存储。
"""
# author: fxbin

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.services.email.base import EmailProvider
from app.services.email.brevo_provider import BrevoProvider
from app.services.secret_store import decrypt_secret

logger = logging.getLogger(__name__)

# 默认 Provider 名称
DEFAULT_PROVIDER_NAME = "brevo"

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
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == _EMAIL_PROVIDER_CONFIG_KEY)
    )
    row = result.scalar_one_or_none()
    if not row or not row.value:
        return None

    try:
        config = json.loads(row.value)
    except json.JSONDecodeError:
        logger.error("email_provider_config JSON 解析失败")
        return None

    provider_name = config.get("provider", DEFAULT_PROVIDER_NAME)
    api_key = decrypt_secret(config.get("api_key"))
    from_email = config.get("from_email", "")
    from_name = config.get("from_name", DEFAULT_FROM_NAME)

    if not api_key or not from_email:
        return None

    if provider_name == BrevoProvider.__name__.replace("Provider", "").lower():
        return BrevoProvider(api_key=api_key, from_email=from_email, from_name=from_name)

    logger.warning("未知的邮件 Provider: %s", provider_name)
    return None
