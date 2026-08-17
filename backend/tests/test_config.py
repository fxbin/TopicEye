import pytest
from pydantic import ValidationError

from app.core.config import Settings

_TEST_DB_URL = "postgresql+asyncpg://test:test@localhost:5432/test"


def test_admin_seed_credentials_are_not_hardcoded(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_DISPLAY_NAME", raising=False)

    settings = Settings(_env_file=None, DATABASE_URL=_TEST_DB_URL)

    assert settings.ADMIN_EMAIL is None
    assert settings.ADMIN_PASSWORD is None
    assert settings.ADMIN_DISPLAY_NAME is None


def test_database_url_required():
    """DATABASE_URL 留空时应在 Settings 初始化阶段报错。"""
    with pytest.raises(ValidationError, match="DATABASE_URL 未设置"):
        Settings(_env_file=None, DATABASE_URL="")


def test_cors_origins_defaults_empty(monkeypatch):
    """CORS_ORIGINS 默认为空字符串，cors_origins 属性返回空列表。"""
    # litellm 导入时会 load_dotenv() 把 backend/.env 写入 os.environ，
    # _env_file=None 挡得住 env 文件、挡不住进程环境，需显式清理。
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = Settings(_env_file=None, DATABASE_URL=_TEST_DB_URL)
    assert settings.CORS_ORIGINS == ""
    assert settings.cors_origins == []


def test_oauth_redirect_url_defaults_empty(monkeypatch):
    """OAUTH_FRONTEND_REDIRECT_URL 默认为空字符串。"""
    # 同上：litellm 的 load_dotenv 会污染进程环境。
    monkeypatch.delenv("OAUTH_FRONTEND_REDIRECT_URL", raising=False)
    settings = Settings(_env_file=None, DATABASE_URL=_TEST_DB_URL)
    assert settings.OAUTH_FRONTEND_REDIRECT_URL == ""


def test_oauth_redirect_url_validates_scheme():
    """OAUTH_FRONTEND_REDIRECT_URL 非 http(s) 开头时应报错。"""
    with pytest.raises(ValidationError, match="必须是 http:// 或 https://"):
        Settings(
            _env_file=None,
            DATABASE_URL=_TEST_DB_URL,
            OAUTH_FRONTEND_REDIRECT_URL="ftp://example.com/callback",
        )
