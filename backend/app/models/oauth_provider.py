"""第三方登录（OAuth）provider 凭据，管理员后台配置。

历史上走 .env 环境变量（OAUTH_GOOGLE_*/OAUTH_GITHUB_*），#94 起改为
DB 单一事实源：管理员在后台 /admin/settings 配置 client_id / client_secret
/ 启用开关，保存后即时生效（登录链路按请求读取，无缓存）。

client_secret 落库前经 app/services/secret_store.py Fernet 加密（enc:v1: 前缀），
任何 API 都不得回传明文或密文。

本模块只保留 ORM 声明与 provider 常量，DB 读写见
app/repositories/oauth_provider_repo.py，编排见 app/services/oauth_provider_service.py。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# 当前支持的 provider 固定两档；endpoint/scope 等协议细节保留在代码里
# （services/oauth_provider_service.py 的 PROVIDER_SPECS），DB 只存凭据与开关。
SUPPORTED_OAUTH_PROVIDERS: tuple[str, ...] = ("google", "github")


class OAuthProvider(Base):
    """OAuth provider 凭据（google / github），按 provider 名为主键。"""

    __tablename__ = "oauth_providers"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    client_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # enc:v1: 前缀的 Fernet 密文；未配置时为 NULL
    client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
