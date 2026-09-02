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


def test_legacy_provider_configuration_is_migrated_when_saved(tmp_path):
    legacy = tmp_path / ".env"
    primary = tmp_path / "data" / "providers.env"
    legacy.write_text("DEEPSEEK_API_KEY=legacy-key\nDEEPSEEK_MODEL=deepseek-chat\n", encoding="utf-8")
    config = ProviderConfigStore(primary, (legacy,))

    assert config.public_status()["deepseek"]["configured"] is True
    config.save("deepseek", {"base_url": "https://api.deepseek.com"})

    persisted = primary.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=legacy-key" in persisted
    assert "DEEPSEEK_MODEL=deepseek-v4-flash" in persisted


def test_registry_exposes_current_curated_models_and_gateway_uses_simulation():
    assert [item["id"] for item in list_models("openai")] == ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]
    assert [item["id"] for item in list_models("anthropic")] == ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]
    assert [item["id"] for item in list_models("gemini")] == ["gemini-3.7-flash", "gemini-3.6-flash"]
    assert [item["id"] for item in list_models("deepseek")] == ["deepseek-v4-pro", "deepseek-v4-flash"]
    assert [item["id"] for item in list_models("qwen")] == ["qwen3.8-max", "qwen3.8-flash"]
    assert [item["id"] for item in list_models("kimi")] == ["kimi-k3", "kimi-k2.6"]
    assert [item["id"] for item in list_models("glm")] == ["glm-5.3", "glm-5.3-flash"]
    assert [item["id"] for item in list_models("minimax")] == ["MiniMax-M2.7", "MiniMax-M2.7-highspeed"]
    assert "deepseek-chat" not in [item["id"] for item in list_models("deepseek")]
    gateway = LLMGateway({"simulated": SimulatedProvider()})

    response = gateway.chat(
        provider="simulated",
        model="analysis-sim",
        messages=[{"role": "user", "content": "分析营业收入"}],
        analysis_result={"answer": "营业收入上升", "findings": [{"conclusion": "2025 年上升"}]},
    )

    assert response.content == "[VERIFIED] 已基于受控分析结果：营业收入上升"
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


def test_openai_compatible_adapter_converts_malformed_json_to_provider_error(monkeypatch):
    from studio_api.llm import openai_compatible
    from studio_api.llm.openai_compatible import OpenAICompatibleProvider

    class InvalidJsonResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b"{not-json"

    monkeypatch.setattr(openai_compatible, "urlopen", lambda *_args, **_kwargs: InvalidJsonResponse())

    with pytest.raises(ProviderError, match="模型服务返回内容格式无效"):
        OpenAICompatibleProvider("openai", "https://example.test", "test-key").chat([], "test-model")


def test_config_builds_only_adapters_with_a_local_key(tmp_path):
    config = ProviderConfigStore(tmp_path / ".env")
    config.save("openai", {"api_key": "local-key", "base_url": ""})
    config.save("anthropic", {"api_key": "local-key", "base_url": ""})
    config.save("gemini", {"api_key": "local-key", "base_url": ""})
    config.save("kimi", {"api_key": "local-key", "base_url": ""})

    adapters = config.build_adapters()

    assert set(adapters) == {"simulated", "openai", "anthropic", "gemini", "kimi"}
    assert adapters["openai"].endpoint == "https://api.openai.com/v1/responses"
    assert adapters["anthropic"].endpoint == "https://api.anthropic.com/v1/messages"
    assert adapters["gemini"].endpoint == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert adapters["kimi"].endpoint == "https://api.moonshot.cn/v1/chat/completions"


def test_native_adapters_use_their_documented_request_protocols(monkeypatch):
    from studio_api.llm import native
    from studio_api.llm.native import AnthropicMessagesProvider, GeminiInteractionsProvider, OpenAIResponsesProvider

    class JsonResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            import json

            return json.dumps(self.body).encode("utf-8")

    captured = []
    responses = iter(
        [
            {"output": [{"content": [{"type": "output_text", "text": "OpenAI 已连接"}]}], "usage": {"input_tokens": 1}},
            {"content": [{"type": "text", "text": "Claude 已连接"}], "usage": {"input_tokens": 1, "output_tokens": 1}},
            {"output_text": "Gemini 已连接", "usage_metadata": {"prompt_token_count": 1}},
        ]
    )

    def fake_urlopen(request, **_kwargs):
        import json

        captured.append({"url": request.full_url, "headers": dict(request.header_items()), "payload": json.loads(request.data.decode("utf-8"))})
        return JsonResponse(next(responses))

    monkeypatch.setattr(native, "urlopen", fake_urlopen)
    messages = [{"role": "system", "content": "只基于受控结果回答"}, {"role": "user", "content": "连接测试"}]

    assert OpenAIResponsesProvider("openai", "https://api.openai.com/v1", "key").chat(messages, "gpt-5.6-terra").content == "OpenAI 已连接"
    assert AnthropicMessagesProvider("anthropic", "https://api.anthropic.com", "key").chat(messages, "claude-sonnet-5").content == "Claude 已连接"
    assert GeminiInteractionsProvider("gemini", "https://generativelanguage.googleapis.com/v1beta", "key").chat(messages, "gemini-3.7-flash").content == "Gemini 已连接"

    assert captured[0]["url"] == "https://api.openai.com/v1/responses"
    assert captured[0]["headers"]["Authorization"] == "Bearer key"
    assert captured[0]["payload"] == {"model": "gpt-5.6-terra", "input": messages, "store": False}
    assert captured[1]["url"] == "https://api.anthropic.com/v1/messages"
    assert captured[1]["headers"]["X-api-key"] == "key"
    assert captured[1]["payload"] == {"model": "claude-sonnet-5", "max_tokens": 4096, "system": "只基于受控结果回答", "messages": [{"role": "user", "content": "连接测试"}]}
    assert captured[2]["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert captured[2]["headers"]["X-goog-api-key"] == "key"
    assert captured[2]["payload"] == {"model": "gemini-3.7-flash", "input": "system: 只基于受控结果回答\nuser: 连接测试"}
