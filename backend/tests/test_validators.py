"""
Validators 单元测试。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.validators import validate_password_strength


class TestPasswordStrength:
    def test_valid_strong_password(self):
        # Returns the original value on success
        assert validate_password_strength("abc12345") == "abc12345"
        assert validate_password_strength("Hello123World") == "Hello123World"

    def test_too_short(self):
        with pytest.raises(ValueError, match="至少需要 8 个字符"):
            validate_password_strength("ab1")

    def test_too_long(self):
        with pytest.raises(ValueError, match="最多"):
            validate_password_strength("a1" + "x" * 200)

    def test_no_letter(self):
        with pytest.raises(ValueError, match="至少 1 个字母"):
            validate_password_strength("12345678")

    def test_no_digit(self):
        with pytest.raises(ValueError, match="至少 1 个数字"):
            validate_password_strength("abcdefgh")

    def test_exact_min_length_ok(self):
        # 8 chars + letter + digit
        assert validate_password_strength("abcdefg1") == "abcdefg1"


class TestAuthRegisterPasswordIntegration:
    def test_register_request_enforces_password_strength(self):
        from app.schemas.auth import AuthRegisterRequest
        # weak password should fail
        with pytest.raises(ValidationError) as exc_info:
            AuthRegisterRequest(email="user@example.com", password="weakpass")
        assert "数字" in str(exc_info.value) or "字母" in str(exc_info.value)
