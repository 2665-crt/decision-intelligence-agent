from __future__ import annotations

from .base import BaseLLMProvider, ModelNotFoundError, ProviderError, ProviderResponse
from .registry import get_model


class LLMGateway:
    def __init__(self, providers: dict[str, BaseLLMProvider]):
        self.providers = providers

    def chat(self, *, provider: str, model: str, messages: list[dict[str, str]], tools: list[dict] | None = None, stream: bool = False, analysis_result: dict | None = None) -> ProviderResponse:
        capability = get_model(provider, model)
        if tools and not capability.supports_tools:
            raise ProviderError("当前模型不支持工具调用，请切换支持工具的模型。")
        if stream and not capability.supports_streaming:
            raise ProviderError("当前模型不支持流式输出，请关闭流式输出或切换模型。")
        adapter = self.providers.get(provider)
        if adapter is None:
            raise ProviderError("当前 Provider 尚未配置，请先在设置中填写 API Key 并测试连接。")
        response = adapter.chat(messages, model, tools=tools if capability.supports_tools else None, stream=stream, analysis_result=analysis_result)
        if not isinstance(response, ProviderResponse):
            raise ProviderError("Provider 返回格式无效。")
        return response

    def test(self, provider: str, model: str) -> ProviderResponse:
        return self.chat(provider=provider, model=model, messages=[{"role": "user", "content": "连接测试"}])
