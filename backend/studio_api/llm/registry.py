from __future__ import annotations

from dataclasses import asdict, dataclass

from .base import ModelNotFoundError


@dataclass(frozen=True)
class ModelCapability:
    id: str
    display_name: str
    context_window: int
    supports_tools: bool
    supports_streaming: bool
    supports_vision: bool
    supports_structured_output: bool
    visible: bool = True


MODEL_REGISTRY: dict[str, dict[str, ModelCapability]] = {
    "simulated": {
        "analysis-sim": ModelCapability("analysis-sim", "本地模拟分析", 8192, True, False, False, True),
        "analysis-sim-error": ModelCapability("analysis-sim-error", "本地模拟故障", 8192, True, False, False, True, visible=False),
    },
    "openai": {
        "gpt-5.6-sol": ModelCapability("gpt-5.6-sol", "GPT-5.6 Sol（旗舰）", 1_050_000, False, False, True, True),
        "gpt-5.6-terra": ModelCapability("gpt-5.6-terra", "GPT-5.6 Terra（均衡）", 1_050_000, False, False, True, True),
        "gpt-5.6-luna": ModelCapability("gpt-5.6-luna", "GPT-5.6 Luna（高性价比）", 1_050_000, False, False, True, True),
    },
    "anthropic": {
        "claude-opus-5": ModelCapability("claude-opus-5", "Claude Opus 5（旗舰）", 1_000_000, False, False, False, False),
        "claude-sonnet-5": ModelCapability("claude-sonnet-5", "Claude Sonnet 5（均衡）", 1_000_000, False, False, False, False),
        "claude-haiku-4-5": ModelCapability("claude-haiku-4-5", "Claude Haiku 4.5（快速）", 200_000, False, False, False, False),
    },
    "gemini": {
        "gemini-3.7-flash": ModelCapability("gemini-3.7-flash", "Gemini 3.7 Flash", 1_048_576, False, False, True, True),
        "gemini-3.6-flash": ModelCapability("gemini-3.6-flash", "Gemini 3.6 Flash", 1_048_576, False, False, True, True),
    },
    "deepseek": {
        "deepseek-v4-pro": ModelCapability("deepseek-v4-pro", "DeepSeek V4 Pro", 128_000, True, True, False, True),
        "deepseek-v4-flash": ModelCapability("deepseek-v4-flash", "DeepSeek V4 Flash", 128_000, True, True, False, True),
    },
    "qwen": {
        "qwen3.8-max": ModelCapability("qwen3.8-max", "Qwen 3.8 Max", 1_000_000, True, True, True, True),
        "qwen3.8-flash": ModelCapability("qwen3.8-flash", "Qwen 3.8 Flash", 1_000_000, True, True, True, True),
    },
    "kimi": {
        "kimi-k3": ModelCapability("kimi-k3", "Kimi K3（旗舰）", 1_000_000, True, True, True, True),
        "kimi-k2.6": ModelCapability("kimi-k2.6", "Kimi K2.6（通用）", 256_000, True, True, True, True),
    },
    "glm": {
        "glm-5.3": ModelCapability("glm-5.3", "GLM-5.3（旗舰）", 1_000_000, True, True, False, True),
        "glm-5.3-flash": ModelCapability("glm-5.3-flash", "GLM-5.3 Flash", 1_000_000, True, True, True, True),
    },
    "minimax": {
        "MiniMax-M2.7": ModelCapability("MiniMax-M2.7", "MiniMax M2.7", 204_800, True, True, False, True),
        "MiniMax-M2.7-highspeed": ModelCapability("MiniMax-M2.7-highspeed", "MiniMax M2.7 Highspeed", 204_800, True, True, False, True),
    },
    "openai-compatible": {
        "custom": ModelCapability("custom", "自定义兼容模型", 32768, True, True, False, False),
    },
}

PROVIDER_NAMES = {
    "simulated": "本地模拟",
    "openai": "OpenAI",
    "anthropic": "Anthropic Claude",
    "gemini": "Google Gemini",
    "deepseek": "DeepSeek",
    "qwen": "Qwen（阿里云百炼）",
    "kimi": "Kimi（月之暗面）",
    "glm": "智谱 GLM",
    "minimax": "MiniMax",
    "openai-compatible": "自定义 OpenAI 兼容接口",
}


def _configured_model(provider: str, model: str, configured_model: str) -> ModelCapability | None:
    if provider not in PROVIDER_NAMES or not model or model != configured_model:
        return None
    return ModelCapability(model, model, 32768, False, False, False, False)


def get_model(provider: str, model: str, configured_model: str = "") -> ModelCapability:
    capability = MODEL_REGISTRY.get(provider, {}).get(model)
    if capability is None:
        capability = _configured_model(provider, model, configured_model)
    if capability is None:
        raise ModelNotFoundError()
    return capability


def list_models(provider: str, configured_model: str = "") -> list[dict]:
    configured = _configured_model(provider, configured_model, configured_model)
    models = [configured] if configured and configured_model not in MODEL_REGISTRY.get(provider, {}) else []
    models.extend(item for item in MODEL_REGISTRY.get(provider, {}).values() if item.visible)
    return [asdict(item) for item in models]


def list_providers(configured_models: dict[str, str] | None = None) -> list[dict]:
    configured_models = configured_models or {}
    return [
        {"id": provider, "display_name": name, "models": list_models(provider, configured_models.get(provider, ""))}
        for provider, name in PROVIDER_NAMES.items()
    ]
