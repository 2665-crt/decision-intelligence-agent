from __future__ import annotations

import os
from pathlib import Path


FIELD_NAMES = {
    "openai": {"api_key": "OPENAI_API_KEY", "base_url": "OPENAI_BASE_URL", "model": "OPENAI_MODEL"},
    "deepseek": {"api_key": "DEEPSEEK_API_KEY", "base_url": "DEEPSEEK_BASE_URL", "model": "DEEPSEEK_MODEL"},
    "openai-compatible": {"name": "OPENAI_COMPATIBLE_NAME", "api_key": "OPENAI_COMPATIBLE_API_KEY", "base_url": "OPENAI_COMPATIBLE_BASE_URL", "model": "OPENAI_COMPATIBLE_MODEL"},
}


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]}"


class ProviderConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, dict[str, str]]:
        values = self._read_file()
        return {
            provider: {field: os.getenv(env_name, values.get(env_name, "")) for field, env_name in fields.items()}
            for provider, fields in FIELD_NAMES.items()
        }

    def save(self, provider: str, values: dict[str, str]) -> None:
        fields = FIELD_NAMES.get(provider)
        if fields is None:
            raise KeyError(provider)
        existing = self._read_file()
        for field, env_name in fields.items():
            if field in values:
                existing[env_name] = str(values[field]).replace("\r", "").replace("\n", "")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text("".join(f"{key}={value}\n" for key, value in sorted(existing.items())), encoding="utf-8")
        temporary.replace(self.path)

    def public_status(self) -> dict[str, dict[str, object]]:
        return {
            provider: {"configured": bool(values.get("api_key")), "api_key_masked": mask(values.get("api_key", "")), "base_url": values.get("base_url", ""), "model": values.get("model", "")}
            for provider, values in self.load().items()
        }

    def build_adapters(self) -> dict:
        from .openai_compatible import OpenAICompatibleProvider
        from .simulated import SimulatedProvider

        defaults = {
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com",
            "openai-compatible": "",
        }
        adapters: dict[str, object] = {"simulated": SimulatedProvider()}
        for provider, values in self.load().items():
            key = values.get("api_key", "")
            base_url = values.get("base_url", "") or defaults[provider]
            if key and base_url:
                adapters[provider] = OpenAICompatibleProvider(provider, base_url, key)
        return adapters

    def _read_file(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        parsed: dict[str, str] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                parsed[key.strip()] = value
        return parsed
