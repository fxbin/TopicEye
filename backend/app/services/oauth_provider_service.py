"""OAuth provider 配置编排（#94：DB 单一事实源）。

职责：
- 读取 oauth_providers 表，判定哪些 provider 可用（已启用 + 凭据齐全）
- 解密 client_secret，产出进程内使用的 OAuthProviderConfig
- 按当次请求的配置构造 authlib client

不做缓存：登录/回调/按钮列表都是低频端点，直接读库让后台改凭据即时生效，
也免去缓存失效这一类静默不一致。

历史：#94 之前 provider 在 app/core/oauth.py 里按 .env 在 import 时注册，
`ENABLED_PROVIDERS` 是进程级常量；该模块已删除，本服务是替代。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from authlib.integrations.starlette_client import OAuth
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.oauth_provider import OAuthProvider
from app.repositories.oauth_provider_repo import OAuthProviderRepository
from app.services.secret_store import decrypt_secret

logger = logging.getLogger(__name__)


# provider 协议细节（endpoint / scope）保留在代码里，DB 只存凭据与开关。
# 新增 provider 时：SUPPORTED_OAUTH_PROVIDERS 加名字 + 这里加 spec + 后台自然可配。
PROVIDER_SPECS: dict[str, dict] = {
    "google": {
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email profile"},
    },
    "github": {
        "access_token_url": "https://github.com/login/oauth/access_token",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "api_base_url": "https://api.github.com/",
        "client_kwargs": {"scope": "user:email read:user"},
    },
}


@dataclass(frozen=True)
class OAuthProviderConfig:
    """已配置且已启用的 provider 凭据。secret 为解密后明文，仅进程内使用。"""

    provider: str
    client_id: str
    client_secret: str


async def list_enabled_providers(db: AsyncSession) -> list[str]:
    """返回可直接渲染登录按钮的 provider 列表（已启用 + 凭据齐全）。

    只做形状检查不解密：解密失败（密钥轮换等）会在实际发起登录时显式报错，
    而不是让按钮列表先一步 500。
    """
    rows = await OAuthProviderRepository(db).list_all()
    return [row.provider for row in rows if row.enabled and row.client_id and row.client_secret]


async def get_active_provider_config(db: AsyncSession, provider: str) -> OAuthProviderConfig | None:
    """解析单个 provider 的可用配置；未配置 / 未启用 / 凭据不全返回 None。

    secret 解密失败会抛 ValueError（secret_store）：这属于部署级配置错误
    （如 INTEGRATION_SECRET_KEY 轮换），必须显式暴露而不是静默降级。
    """
    row: OAuthProvider | None = await OAuthProviderRepository(db).get_by_provider(provider)
    if row is None or not row.enabled:
        return None
    if not row.client_id or not row.client_secret:
        logger.warning("OAuth provider '%s' 已启用但凭据不全（client_id/secret 缺失），按未启用处理", provider)
        return None
    return OAuthProviderConfig(
        provider=provider,
        client_id=row.client_id,
        client_secret=decrypt_secret(row.client_secret) or "",
    )


def build_provider_client(provider: str, config: OAuthProviderConfig):
    """按当次请求的 DB 配置构造 authlib client。

    不复用全局注册表：authlib 的 OAuth() 会把 client 缓存在注册表里，
    后台改凭据后旧 client 不会刷新，且并发写全局注册表有竞态。这里每次
    用全新实例构造，等价于旧版「启动时注册一次」，但配置来源换成 DB。
    """
    spec = PROVIDER_SPECS.get(provider)
    if spec is None:
        raise ValueError(f"不支持的 OAuth provider: {provider}")
    registry = OAuth()
    return registry.register(
        name=provider,
        client_id=config.client_id,
        client_secret=config.client_secret,
        **spec,
    )
