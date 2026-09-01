from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import AuthenticationError, ConnectionError, ProviderError, ProviderResponse, RateLimitError, TimeoutError


class OpenAICompatibleProvider:
    def __init__(self, provider: str, base_url: str, api_key: str, timeout_seconds: float = 30):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def chat(self, messages: list[dict[str, str]], model: str, *, tools: list[dict] | None = None, stream: bool = False, analysis_result: dict | None = None) -> ProviderResponse:
        payload: dict[str, object] = {"model": model, "messages": messages, "stream": stream}
        if tools:
            payload["tools"] = tools
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
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
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("模型服务返回内容格式无效。") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("模型服务没有返回可显示内容。")
        return ProviderResponse(content=content, provider=self.provider, model=model, usage=body.get("usage"))
