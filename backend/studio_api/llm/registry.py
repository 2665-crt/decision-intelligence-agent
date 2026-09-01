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
        "gpt-5-mini": ModelCapability("gpt-5-mini", "GPT-5 mini", 128000, True, True, False, True),
        "gpt-5": ModelCapability("gpt-5", "GPT-5", 128000, True, True, True, True),
    },
    "deepseek": {
        "deepseek-chat": ModelCapability("deepseek-chat", "DeepSeek Chat", 64000, True, True, False, True),
        "deepseek-reasoner": ModelCapability("deepseek-reasoner", "DeepSeek Reasoner", 64000, True, True, False, True),
    },
    "openai-compatible": {
        "custom": ModelCapability("custom", "自定义兼容模型", 32768, True, True, False, False),
    },
}

PROVIDER_NAMES = {"simulated": "本地模拟", "openai": "OpenAI", "deepseek": "DeepSeek", "openai-compatible": "OpenAI Compatible"}


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
