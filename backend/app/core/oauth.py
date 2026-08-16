"""OAuth provider 注册（Google / GitHub）。

未配置 client_id 的 provider 不会注册，前端据此决定是否渲染对应按钮。
"""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from app.core.config import settings

oauth = OAuth()


def _register_providers() -> list[str]:
    """根据 settings 注册已配置的 provider，返回 provider 名称列表。"""
    enabled: list[str] = []
    if settings.OAUTH_GOOGLE_CLIENT_ID and settings.OAUTH_GOOGLE_CLIENT_SECRET:
        oauth.register(
            name="google",
            client_id=settings.OAUTH_GOOGLE_CLIENT_ID,
            client_secret=settings.OAUTH_GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        enabled.append("google")
    if settings.OAUTH_GITHUB_CLIENT_ID and settings.OAUTH_GITHUB_CLIENT_SECRET:
        oauth.register(
            name="github",
            client_id=settings.OAUTH_GITHUB_CLIENT_ID,
            client_secret=settings.OAUTH_GITHUB_CLIENT_SECRET,
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "user:email read:user"},
        )
        enabled.append("github")
    return enabled


ENABLED_PROVIDERS: list[str] = _register_providers()
