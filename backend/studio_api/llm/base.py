from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    provider: str
    model: str
    usage: dict[str, int] | None = None


class ProviderError(RuntimeError):
    code = "provider_error"
    user_message = "模型服务请求失败，请稍后重试或切换模型。"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.user_message)


class AuthenticationError(ProviderError):
    code = "authentication_error"
    user_message = "API Key 无效或未配置，请在设置中检查。"


class RateLimitError(ProviderError):
    code = "rate_limit_error"
    user_message = "模型服务限流，请稍后重试或切换模型。"


class TimeoutError(ProviderError):
    code = "timeout_error"
    user_message = "模型服务连接超时，请重试或切换模型。"


class ConnectionError(ProviderError):
    code = "connection_error"
    user_message = "无法连接模型服务，请检查 Base URL 与网络。"


class ModelNotFoundError(ProviderError):
    code = "model_not_found"
    user_message = "所选模型不存在或当前 Provider 不支持它。"


class BaseLLMProvider(Protocol):
    def chat(self, messages: list[dict[str, str]], model: str, *, tools: list[dict] | None = None, stream: bool = False, analysis_result: dict | None = None) -> ProviderResponse: ...
