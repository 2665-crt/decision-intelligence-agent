from __future__ import annotations

import os
from pathlib import Path


FIELD_NAMES = {
    "openai": {"api_key": "OPENAI_API_KEY", "base_url": "OPENAI_BASE_URL", "model": "OPENAI_MODEL"},
    "anthropic": {"api_key": "ANTHROPIC_API_KEY", "base_url": "ANTHROPIC_BASE_URL", "model": "ANTHROPIC_MODEL"},
    "gemini": {"api_key": "GEMINI_API_KEY", "base_url": "GEMINI_BASE_URL", "model": "GEMINI_MODEL"},
    "deepseek": {"api_key": "DEEPSEEK_API_KEY", "base_url": "DEEPSEEK_BASE_URL", "model": "DEEPSEEK_MODEL"},
    "qwen": {"api_key": "QWEN_API_KEY", "base_url": "QWEN_BASE_URL", "model": "QWEN_MODEL"},
    "kimi": {"api_key": "KIMI_API_KEY", "base_url": "KIMI_BASE_URL", "model": "KIMI_MODEL"},
    "glm": {"api_key": "GLM_API_KEY", "base_url": "GLM_BASE_URL", "model": "GLM_MODEL"},
    "minimax": {"api_key": "MINIMAX_API_KEY", "base_url": "MINIMAX_BASE_URL", "model": "MINIMAX_MODEL"},
    "openai-compatible": {"name": "OPENAI_COMPATIBLE_NAME", "api_key": "OPENAI_COMPATIBLE_API_KEY", "base_url": "OPENAI_COMPATIBLE_BASE_URL", "model": "OPENAI_COMPATIBLE_MODEL"},
}

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "minimax": "https://api.minimaxi.com/v1",
    "openai-compatible": "",
}

DEFAULT_MODELS = {
    "openai": "gpt-5.6-terra",
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-3.7-flash",
    "deepseek": "deepseek-v4-flash",
    "qwen": "qwen3.8-flash",
    "kimi": "kimi-k3",
    "glm": "glm-5.3",
    "minimax": "MiniMax-M2.7",
    "openai-compatible": "custom",
}

MODEL_MIGRATIONS = {
    "openai": {"gpt-5": "gpt-5.6-terra", "gpt-5-mini": "gpt-5.6-luna"},
    "deepseek": {"deepseek-chat": "deepseek-v4-flash", "deepseek-reasoner": "deepseek-v4-pro"},
    "kimi": {"kimi-k2.5": "kimi-k3", "kimi-latest": "kimi-k3", "moonshot-v1-8k": "kimi-k3", "moonshot-v1-32k": "kimi-k3", "moonshot-v1-128k": "kimi-k3"},
}


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]}"


def normalize_model(provider: str, model: str) -> str:
    return MODEL_MIGRATIONS.get(provider, {}).get(model, model)


class ProviderConfigStore:
    def __init__(self, path: Path, legacy_paths: tuple[Path, ...] = ()):
        self.path = path
        self.legacy_paths = tuple(item for item in legacy_paths if item.resolve() != path.resolve())

    def load(self) -> dict[str, dict[str, str]]:
        values = self._read_file()
        loaded = {
            provider: {field: os.getenv(env_name, values.get(env_name, "")) for field, env_name in fields.items()}
            for provider, fields in FIELD_NAMES.items()
        }
        for provider, fields in loaded.items():
            fields["model"] = normalize_model(provider, fields.get("model", ""))
        return loaded

    def save(self, provider: str, values: dict[str, str]) -> None:
        fields = FIELD_NAMES.get(provider)
        if fields is None:
            raise KeyError(provider)
        existing = self._read_file()
        for field, env_name in fields.items():
            value = str(values[field]) if field in values else existing.get(env_name, "")
            if field == "model":
                value = normalize_model(provider, value)
            if field in values or (field == "model" and value != existing.get(env_name, "")):
                existing[env_name] = value.replace("\r", "").replace("\n", "")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text("".join(f"{key}={value}\n" for key, value in sorted(existing.items())), encoding="utf-8")
        temporary.replace(self.path)

    def public_status(self) -> dict[str, dict[str, object]]:
        return {
            provider: {
                "configured": bool(values.get("api_key")),
                "api_key_masked": mask(values.get("api_key", "")),
                "base_url": values.get("base_url", "") or DEFAULT_BASE_URLS[provider],
                "model": values.get("model", "") or DEFAULT_MODELS[provider],
            }
            for provider, values in self.load().items()
        }

    def configured_models(self) -> dict[str, str]:
        return {provider: values["model"] for provider, values in self.public_status().items()}

    def build_adapters(self) -> dict:
        from .native import AnthropicMessagesProvider, GeminiInteractionsProvider, OpenAIResponsesProvider
        from .openai_compatible import OpenAICompatibleProvider
        from .simulated import SimulatedProvider

        adapters: dict[str, object] = {"simulated": SimulatedProvider()}
        for provider, values in self.load().items():
            key = values.get("api_key", "")
            base_url = values.get("base_url", "") or DEFAULT_BASE_URLS[provider]
            if not key or not base_url:
                continue
            if provider == "openai":
                adapters[provider] = OpenAIResponsesProvider(provider, base_url, key)
            elif provider == "anthropic":
                adapters[provider] = AnthropicMessagesProvider(provider, base_url, key)
            elif provider == "gemini":
                adapters[provider] = GeminiInteractionsProvider(provider, base_url, key)
            else:
                adapters[provider] = OpenAICompatibleProvider(provider, base_url, key)
        return adapters

    def _read_file(self) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for source in (*self.legacy_paths, self.path):
            if not source.exists():
                continue
            for line in source.read_text(encoding="utf-8").splitlines():
                if line and not line.lstrip().startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    parsed[key.strip()] = value
        return parsed
