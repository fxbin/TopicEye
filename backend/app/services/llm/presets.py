from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_MODEL_PARAMETERS: dict[str, Any] = {
    "routing_group": "default",
    "routing_priority": 100,
    "cooldown_seconds": 300,
    "temperature": 0.3,
    "max_tokens": 2000,
    "requests_per_minute": 30,
    "enabled": True,
}


PARAMETER_HELP: dict[str, dict[str, Any]] = {
    "temperature": {
        "label": "稳定度",
        "default": DEFAULT_MODEL_PARAMETERS["temperature"],
        "range": [0, 2],
        "unit": "",
        "recommended": "选题分析推荐 0.3",
        "plain": "越低越稳定，越高越发散。选题分析建议保持 0.3。",
        "beginner": "默认即可",
        "when_to_change": [
            "内容太保守时可调到 0.5",
            "结果跑偏时调回 0.2-0.3",
        ],
    },
    "max_tokens": {
        "label": "输出长度",
        "default": DEFAULT_MODEL_PARAMETERS["max_tokens"],
        "range": [256, 16000],
        "unit": "tokens",
        "recommended": "创作方案和摘要推荐 2000",
        "plain": "控制单次回答最长能写多少。创作方案和摘要建议先用 2000。",
        "beginner": "不够长再调大",
        "when_to_change": [
            "回答被截断时再调大",
            "只做分类或短摘要时可调小",
        ],
    },
    "requests_per_minute": {
        "label": "请求上限",
        "default": DEFAULT_MODEL_PARAMETERS["requests_per_minute"],
        "range": [1, 120],
        "unit": "次/分钟",
        "recommended": "个人 Key 推荐 10-30",
        "plain": "限制每分钟最多调用多少次，保护个人 Key 不被同步高峰打满。",
        "beginner": "个人 Key 建议 10-30",
        "when_to_change": [
            "供应商频繁限流时调低",
            "付费额度和并发能力明确后再调高",
        ],
    },
    "cooldown_seconds": {
        "label": "失败冷却",
        "default": DEFAULT_MODEL_PARAMETERS["cooldown_seconds"],
        "range": [0, 3600],
        "unit": "秒",
        "recommended": "失败后默认冷却 300 秒",
        "plain": "模型调用失败后暂停一段时间再重试，减少连续失败和限流。",
        "beginner": "默认即可",
        "when_to_change": [
            "供应商恢复很慢时调大",
            "内部稳定网关可适当调小",
        ],
    },
}


MODEL_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "key": "openai_fast",
        "label": "OpenAI 通用快模型",
        "provider": "openai",
        "model_id": "gpt-4.1-mini",
        "api_base": None,
        "model_family": "openai",
        "channel_name": "official",
        "description": "适合日常创作方案、摘要和轻量分析，稳定优先。",
        "recommended_for": ["创作方案", "摘要生成", "轻量分析"],
        "requires": ["api_key"],
        "help": "只需要填写 OpenAI API Key；其他参数可以先保持默认。",
        "defaults": {
            **DEFAULT_MODEL_PARAMETERS,
            "name": "OpenAI 通用快模型",
            "cost_per_1m_input": None,
            "cost_per_1m_input_cache_hit": None,
            "cost_per_1m_output": None,
        },
    },
    {
        "key": "deepseek_balanced",
        "label": "DeepSeek 性价比模型",
        "provider": "deepseek",
        "model_id": "deepseek-chat",
        "api_base": None,
        "model_family": "deepseek",
        "channel_name": "official",
        "description": "适合高频内容处理和个人工作流，成本敏感时优先选它。",
        "recommended_for": ["高频生成", "内容分析", "日常工作流"],
        "requires": ["api_key"],
        "help": "填写 DeepSeek API Key 即可。请求上限默认较保守，避免个人 Key 被同步高峰打满。",
        "defaults": {
            **DEFAULT_MODEL_PARAMETERS,
            "name": "DeepSeek 性价比模型",
            "requests_per_minute": 20,
            "cost_per_1m_input": 1,
            "cost_per_1m_input_cache_hit": 0.02,
            "cost_per_1m_output": 2,
        },
    },
    {
        "key": "openai_compatible",
        "label": "OpenAI 兼容网关",
        "provider": "openai",
        "model_id": "",
        "api_base": None,
        "api_base_placeholder": "https://api.example.com/v1",
        "model_id_placeholder": "如 openrouter/anthropic/claude-3.5-sonnet",
        "model_family": None,
        "channel_name": "custom_gateway",
        "description": "适合 OpenRouter、OpenCode、智谱等兼容 OpenAI 格式的网关。",
        "recommended_for": ["自定义网关", "国内兼容渠道", "备用模型"],
        "requires": ["api_key", "api_base", "model_id"],
        "help": "Provider 保持 OpenAI，填写网关的 API Base、API Key 和模型名即可。",
        "defaults": {
            **DEFAULT_MODEL_PARAMETERS,
            "name": "OpenAI 兼容网关",
            "requests_per_minute": 15,
        },
    },
    {
        "key": "custom",
        "label": "完全自定义",
        "provider": "custom",
        "model_id": "",
        "api_base": None,
        "model_id_placeholder": "如 openai/gpt-4.1-mini",
        "model_family": None,
        "channel_name": None,
        "description": "适合熟悉 LiteLLM 路由和供应商参数的高级用户。",
        "recommended_for": ["高级配置", "特殊供应商"],
        "requires": ["provider", "model_id"],
        "help": "如果不确定怎么填，优先使用上面的推荐预设。",
        "defaults": {
            **DEFAULT_MODEL_PARAMETERS,
            "name": "自定义模型",
            "requests_per_minute": 10,
        },
    },
)


def list_model_presets() -> dict[str, Any]:
    return {
        "defaults": deepcopy(DEFAULT_MODEL_PARAMETERS),
        "parameter_help": deepcopy(PARAMETER_HELP),
        "presets": [deepcopy(item) for item in MODEL_PRESETS],
        "help": {
            "beginner_tip": "新用户优先选择推荐预设，只填写 API Key；稳定度、输出长度、请求上限和失败冷却都会自动使用默认值。",
            "defaults_tip": "不理解参数时不要手动修改。系统默认值已经按选题分析、摘要生成和高频同步做过保守配置。",
            "advanced_tip": "高级参数只在你明确知道要调整模型行为时再改。留空表示沿用当前预设默认值。",
            "rpm_tip": PARAMETER_HELP["requests_per_minute"]["plain"],
            "temperature_tip": PARAMETER_HELP["temperature"]["plain"],
            "max_tokens_tip": PARAMETER_HELP["max_tokens"]["plain"],
            "cooldown_tip": PARAMETER_HELP["cooldown_seconds"]["plain"],
        },
    }


def get_model_preset(key: str | None) -> dict[str, Any] | None:
    normalized = (key or "").strip().lower()
    if not normalized:
        return None
    for preset in MODEL_PRESETS:
        if preset["key"] == normalized:
            return deepcopy(preset)
    return None


def apply_model_preset(payload: dict[str, Any], preset_key: str | None) -> dict[str, Any]:
    preset = get_model_preset(preset_key)
    if preset is None:
        return payload

    defaults = {
        **preset.get("defaults", {}),
        "provider": preset.get("provider"),
        "model_id": preset.get("model_id"),
        "api_base": preset.get("api_base"),
        "model_family": preset.get("model_family"),
        "channel_name": preset.get("channel_name"),
        "description": preset.get("description"),
    }
    return {key: value for key, value in {**defaults, **payload}.items() if value is not None}
