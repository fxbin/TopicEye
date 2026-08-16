"""邮箱验证码服务。

负责验证码的生成、发送、校验全流程。
验证码以 sha256 哈希存储，支持发送频率限制、过期清理与防重放。
"""
# author: fxbin

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.user_identity import normalize_email
from app.models.email_verification import EmailVerificationCode
from app.services.email.base import EmailSendError
from app.services.email.factory import get_email_provider

logger = logging.getLogger(__name__)

# 验证码配置常量
VERIFICATION_CODE_LENGTH = 6
VERIFICATION_CODE_TTL_MINUTES = 10
VERIFICATION_CODE_RESEND_INTERVAL_SECONDS = 60
VERIFICATION_CODE_MAX_ATTEMPTS = 5

# 过期记录清理阈值：删除 1 小时前过期的记录
_EXPIRED_CODE_CLEANUP_HOURS = 1

# 验证码字符集（纯数字，避免歧义字母）
_CODE_CHARS = "0123456789"


class VerificationError(Exception):
    """验证码流程异常基类。"""


class CodeRateLimitedError(VerificationError):
    """发送频率过高，需等待后重试。"""


class EmailNotConfiguredError(VerificationError):
    """邮件服务未配置，需管理员先在后台完成 Provider 配置。"""


class InvalidCodeError(VerificationError):
    """验证码无效、已过期或尝试次数超限。"""


def _hash_code(code: str) -> str:
    """对验证码取 sha256 哈希，存储时不保留明文。

    参数:
        code: 验证码明文

    返回:
        sha256 十六进制摘要
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    """生成指定位数的数字验证码。

    返回:
        长度为 VERIFICATION_CODE_LENGTH 的数字字符串
    """
    return "".join(secrets.choice(_CODE_CHARS) for _ in range(VERIFICATION_CODE_LENGTH))


async def send_verification_code(db: AsyncSession, email: str) -> None:
    """生成验证码并发送到指定邮箱。

    流程：
    1. 校验发送频率（同邮箱 RESEND_INTERVAL 秒内只能发一次）
    2. 获取已配置的邮件 Provider
    3. 生成验证码并持久化哈希记录
    4. 调用 Provider 发送邮件，失败则回滚

    参数:
        db: 数据库会话
        email: 收件人邮箱

    异常:
        CodeRateLimitedError: 发送过于频繁
        EmailNotConfiguredError: 邮件服务未配置
        VerificationError: 发送失败
    """
    normalized = normalize_email(email)

    # 频率限制：检查最近是否已发送
    cutoff = datetime.now(UTC) - timedelta(seconds=VERIFICATION_CODE_RESEND_INTERVAL_SECONDS)
    result = await db.execute(
        select(EmailVerificationCode)
        .where(
            EmailVerificationCode.email == normalized,
            EmailVerificationCode.created_at > cutoff,
        )
        .order_by(EmailVerificationCode.created_at.desc())
    )
    recent = result.scalars().first()
    if recent and recent.used_at is None:
        raise CodeRateLimitedError("验证码已发送，请稍后再试")

    # 获取邮件 Provider
    provider = await get_email_provider(db)
    if provider is None:
        raise EmailNotConfiguredError("邮件服务尚未配置，请联系管理员")

    # 生成验证码并持久化
    code = _generate_code()
    code_hash = _hash_code(code)
    expires_at = datetime.now(UTC) + timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES)

    record = EmailVerificationCode(
        email=normalized,
        code_hash=code_hash,
        expires_at=expires_at,
    )
    db.add(record)
    await db.flush()

    # 发送邮件：失败则回滚记录
    try:
        await provider.send_verification_code(normalized, code)
        await db.commit()
    except EmailSendError as exc:
        await db.rollback()
        raise VerificationError(str(exc)) from exc


async def verify_code(db: AsyncSession, email: str, code: str) -> None:
    """校验验证码。校验通过后标记已使用。

    参数:
        db: 数据库会话
        email: 注册邮箱
        code: 用户输入的验证码

    异常:
        InvalidCodeError: 验证码无效、已过期或尝试次数超限
    """
    normalized = normalize_email(email)
    now = datetime.now(UTC)

    result = await db.execute(
        select(EmailVerificationCode)
        .where(
            EmailVerificationCode.email == normalized,
            EmailVerificationCode.used_at.is_(None),
            EmailVerificationCode.expires_at > now,
        )
        .order_by(EmailVerificationCode.created_at.desc())
    )
    record = result.scalars().first()
    if record is None:
        raise InvalidCodeError("验证码无效或已过期")

    # 尝试次数检查
    if record.attempts >= VERIFICATION_CODE_MAX_ATTEMPTS:
        record.used_at = now
        await db.flush()
        raise InvalidCodeError("验证码尝试次数过多，请重新获取")

    # 哈希比对（常数时间比较防时序攻击）
    if not secrets.compare_digest(record.code_hash, _hash_code(code)):
        record.attempts += 1
        await db.flush()
        raise InvalidCodeError("验证码错误")

    # 校验通过
    record.used_at = now
    await db.flush()


async def cleanup_expired_codes(db: AsyncSession) -> int:
    """清理已过期的验证码记录。

    参数:
        db: 数据库会话

    返回:
        删除的记录条数
    """
    cutoff = datetime.now(UTC) - timedelta(hours=_EXPIRED_CODE_CLEANUP_HOURS)
    result = await db.execute(delete(EmailVerificationCode).where(EmailVerificationCode.expires_at < cutoff))
    await db.flush()
    return result.rowcount or 0
