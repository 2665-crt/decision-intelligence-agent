from __future__ import annotations

import pytest

from studio_api.llm.base import ModelNotFoundError, ProviderError
from studio_api.llm.config import ProviderConfigStore
from studio_api.llm.gateway import LLMGateway
from studio_api.llm.registry import list_models
from studio_api.llm.simulated import SimulatedProvider


def test_public_provider_status_masks_key_and_writes_env(tmp_path):
    config = ProviderConfigStore(tmp_path / ".env")

    config.save("deepseek", {"api_key": "secret-value", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"})

    status = config.public_status()["deepseek"]
    assert status["configured"] is True
    assert status["api_key_masked"] == "secr…alue"
    assert "secret-value" not in str(status)
    assert "DEEPSEEK_API_KEY=secret-value" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_registry_groups_models_by_provider_and_gateway_uses_simulation():
    assert [item["id"] for item in list_models("deepseek")] == ["deepseek-chat", "deepseek-reasoner"]
    gateway = LLMGateway({"simulated": SimulatedProvider()})

    response = gateway.chat(
        provider="simulated",
        model="analysis-sim",
        messages=[{"role": "user", "content": "分析营业收入"}],
        analysis_result={"answer": "营业收入上升", "findings": [{"conclusion": "2025 年上升"}]},
    )

    assert response.content == "已基于受控分析结果：营业收入上升"
    assert response.provider == "simulated"


def test_gateway_returns_actionable_model_and_provider_errors():
    gateway = LLMGateway({"simulated": SimulatedProvider()})

    with pytest.raises(ModelNotFoundError):
        gateway.chat(provider="simulated", model="missing", messages=[])
    with pytest.raises(ProviderError, match="模拟 Provider 请求失败"):
        gateway.chat(provider="simulated", model="analysis-sim-error", messages=[])


def test_openai_compatible_adapter_normalizes_chat_completion_endpoint():
    from studio_api.llm.openai_compatible import OpenAICompatibleProvider

    assert OpenAICompatibleProvider("openai", "https://api.openai.com/v1", "key").endpoint == "https://api.openai.com/v1/chat/completions"
    assert OpenAICompatibleProvider("deepseek", "https://api.deepseek.com", "key").endpoint == "https://api.deepseek.com/chat/completions"


def test_config_builds_only_adapters_with_a_local_key(tmp_path):
    config = ProviderConfigStore(tmp_path / ".env")
    config.save("openai", {"api_key": "local-key", "base_url": ""})

    adapters = config.build_adapters()

    assert set(adapters) == {"simulated", "openai"}
