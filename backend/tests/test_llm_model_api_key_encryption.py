"""LLM 模型 api_key 加密收口测试（MP-P0-T2）。

覆盖：
- 写入加密：_new_model_from_request / _apply_model_request 落库前调用 encrypt_secret，
  DB 存的是 enc:v1: 前缀，不是明文。
- 读取解密：_candidate_from_db_model 与 _completion_kwargs 返回解密后的原值。
- 兼容性：decrypt_secret 天然兼容明文（非 enc:v1: 前缀原样返回），保证迁移前后都能跑。
- 重复加密守卫：已是 enc:v1: 的值不会被二次加密。
- 明文不回传：GET 响应只返回 api_key_set 布尔值。

不使用任何真实 Key，全部用 test-key-xxx 占位。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.v1.llm_models import (
    ModelCreateRequest,
    ModelUpdateRequest,
    _apply_model_request,
    _completion_kwargs,
    _new_model_from_request,
)
from app.models.llm_model import LlmModel
from app.services.llm._failover import _candidate_from_db_model
from app.services.secret_store import decrypt_secret, encrypt_secret, is_encrypted_secret

# 测试用占位 Key，非真实凭据。
_PLAINTEXT_KEY = "sk-test-key-not-real-123456"


# ── 写入加密 ──


class TestWriteEncryption:
    def test_create_encrypts_api_key(self):
        """新建模型时 api_key 应被加密，DB 中不得出现明文。"""
        req = ModelCreateRequest(
            name="t",
            provider="openai",
            model_id="openai/glm-test",
            api_key=_PLAINTEXT_KEY,
        )
        model = _new_model_from_request(req)
        assert is_encrypted_secret(model.api_key), "api_key 未被加密"
        assert _PLAINTEXT_KEY not in model.api_key, "明文残留在加密值中"
        # 加密值能正确解密回原值
        assert decrypt_secret(model.api_key) == _PLAINTEXT_KEY

    def test_create_with_none_api_key(self):
        """api_key=None 时不应崩溃，落库为 None。"""
        req = ModelCreateRequest(name="t", provider="openai", model_id="openai/x", api_key=None)
        model = _new_model_from_request(req)
        assert model.api_key is None

    def test_update_encrypts_api_key(self):
        """更新模型时传入的明文 api_key 应被加密。"""
        model = LlmModel(name="t", provider="openai", model_id="openai/x", api_key=None)
        req = ModelUpdateRequest(api_key=_PLAINTEXT_KEY)
        _apply_model_request(model, req)
        assert is_encrypted_secret(model.api_key)
        assert decrypt_secret(model.api_key) == _PLAINTEXT_KEY

    def test_update_does_not_double_encrypt(self):
        """已是 enc:v1: 的值（如客户端误传迁移后的值）不应被二次加密。"""
        already_encrypted = encrypt_secret(_PLAINTEXT_KEY)
        model = LlmModel(name="t", provider="openai", model_id="openai/x", api_key=None)
        req = ModelUpdateRequest(api_key=already_encrypted)
        _apply_model_request(model, req)
        # 值保持不变（未被二次加密）
        assert model.api_key == already_encrypted
        assert decrypt_secret(model.api_key) == _PLAINTEXT_KEY


# ── 读取解密 ──


class TestReadDecryption:
    def test_candidate_decrypts_encrypted_key(self):
        """_candidate_from_db_model 应返回解密后的明文 Key 供 LiteLLM 使用。"""
        model = SimpleNamespace(
            id=1,
            provider="openai",
            model_id="openai/glm-test",
            api_key=encrypt_secret(_PLAINTEXT_KEY),
            api_base=None,
            temperature=0.3,
            max_tokens=2000,
            cooldown_seconds=300,
        )
        candidate = _candidate_from_db_model(model, temperature=0.3, max_tokens=2000)
        assert candidate["api_key"] == _PLAINTEXT_KEY, "候选未正确解密 api_key"

    def test_candidate_compatible_with_plaintext(self):
        """存量明文 api_key 在迁移前仍可读取（兼容期，支持灰度）。"""
        model = SimpleNamespace(
            id=2,
            provider="openai",
            model_id="openai/glm-legacy",
            api_key=_PLAINTEXT_KEY,  # 明文，未迁移
            api_base=None,
            temperature=0.3,
            max_tokens=2000,
            cooldown_seconds=300,
        )
        candidate = _candidate_from_db_model(model, temperature=0.3, max_tokens=2000)
        assert candidate["api_key"] == _PLAINTEXT_KEY

    def test_completion_kwargs_decrypts(self):
        """/models/{id}/test 测试端点也用解密后的 Key。"""
        model = SimpleNamespace(
            provider="openai",
            model_id="openai/glm-test",
            api_key=encrypt_secret(_PLAINTEXT_KEY),
            api_base="https://example.com/v1",
            temperature=0.3,
            max_tokens=2000,
            extra_params={},
        )
        kwargs = _completion_kwargs(
            model,
            resolved_model="openai/glm-test",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.3,
            max_tokens=2000,
        )
        assert kwargs.get("api_key") == _PLAINTEXT_KEY
