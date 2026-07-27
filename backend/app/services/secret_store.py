from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import DEFAULT_LOCAL_SECRET_KEY, settings

SECRET_PREFIX = "enc:v1:"


def _secret_material() -> str:
    material = (settings.INTEGRATION_SECRET_KEY or settings.APP_SECRET_KEY or "").strip()
    if not material:
        material = DEFAULT_LOCAL_SECRET_KEY
    if settings.is_production and material == DEFAULT_LOCAL_SECRET_KEY:
        raise RuntimeError("Production secret encryption requires INTEGRATION_SECRET_KEY or a custom APP_SECRET_KEY")
    return material


def _fernet() -> Fernet:
    digest = hashlib.sha256(_secret_material().encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    token = _fernet().encrypt(normalized.encode("utf-8")).decode("ascii")
    return f"{SECRET_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    stored = value.strip()
    if not stored:
        return None
    if not stored.startswith(SECRET_PREFIX):
        return stored
    token = stored[len(SECRET_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise ValueError("用户集成凭据无法解密，请检查 INTEGRATION_SECRET_KEY 配置") from exc


def is_encrypted_secret(value: str | None) -> bool:
    return bool(value and value.strip().startswith(SECRET_PREFIX))
