from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import AuthenticationError, ConnectionError, ProviderError, ProviderResponse, RateLimitError, TimeoutError


def _request_json(endpoint: str, payload: dict[str, object], headers: dict[str, str], timeout_seconds: float) -> dict:
    request = Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers | {"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise AuthenticationError() from exc
        if exc.code == 429:
            raise RateLimitError() from exc
        if exc.code == 408 or exc.code >= 500:
            raise TimeoutError() from exc
        raise ProviderError(f"模型服务返回 HTTP {exc.code}。") from exc
    except (URLError, OSError) as exc:
        raise ConnectionError() from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("模型服务返回内容格式无效。") from exc
    if not isinstance(body, dict):
        raise ProviderError("模型服务返回内容格式无效。")
    return body


def _response_content(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderError("模型服务没有返回可显示内容。")
    return value


class OpenAIResponsesProvider:
    def __init__(self, provider: str, base_url: str, api_key: str, timeout_seconds: float = 30):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/responses"

    def chat(self, messages: list[dict[str, str]], model: str, *, tools: list[dict] | None = None, stream: bool = False, analysis_result: dict | None = None) -> ProviderResponse:
        body = _request_json(self.endpoint, {"model": model, "input": messages, "store": False}, {"Authorization": f"Bearer {self.api_key}"}, self.timeout_seconds)
        content = body.get("output_text")
        if not content:
            output = body.get("output")
            if isinstance(output, list):
                content = "".join(
                    item.get("text", "")
                    for message in output
                    if isinstance(message, dict)
                    for item in message.get("content", [])
                    if isinstance(item, dict) and item.get("type") == "output_text"
                )
        return ProviderResponse(_response_content(content), self.provider, model, body.get("usage"))


class AnthropicMessagesProvider:
    def __init__(self, provider: str, base_url: str, api_key: str, timeout_seconds: float = 30):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/v1/messages"

    def chat(self, messages: list[dict[str, str]], model: str, *, tools: list[dict] | None = None, stream: bool = False, analysis_result: dict | None = None) -> ProviderResponse:
        system = "\n".join(item["content"] for item in messages if item.get("role") == "system")
        conversation = [{"role": item["role"], "content": item["content"]} for item in messages if item.get("role") in {"user", "assistant"}]
        payload: dict[str, object] = {"model": model, "max_tokens": 4096, "messages": conversation or [{"role": "user", "content": "连接测试"}]}
        if system:
            payload["system"] = system
        body = _request_json(self.endpoint, payload, {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, self.timeout_seconds)
        blocks = body.get("content")
        content = "".join(item.get("text", "") for item in blocks if isinstance(item, dict) and item.get("type") == "text") if isinstance(blocks, list) else ""
        return ProviderResponse(_response_content(content), self.provider, model, body.get("usage"))


class GeminiInteractionsProvider:
    def __init__(self, provider: str, base_url: str, api_key: str, timeout_seconds: float = 30):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/interactions"

    def chat(self, messages: list[dict[str, str]], model: str, *, tools: list[dict] | None = None, stream: bool = False, analysis_result: dict | None = None) -> ProviderResponse:
        input_text = "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in messages)
        body = _request_json(self.endpoint, {"model": model, "input": input_text}, {"x-goog-api-key": self.api_key}, self.timeout_seconds)
        return ProviderResponse(_response_content(body.get("output_text")), self.provider, model, body.get("usage_metadata"))
