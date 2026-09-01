from __future__ import annotations

from .base import ProviderError, ProviderResponse


class SimulatedProvider:
    def chat(self, messages: list[dict[str, str]], model: str, *, tools: list[dict] | None = None, stream: bool = False, analysis_result: dict | None = None) -> ProviderResponse:
        if model == "analysis-sim-error":
            raise ProviderError("模拟 Provider 请求失败")
        answer = str((analysis_result or {}).get("answer") or "已接收当前分析问题。")
        return ProviderResponse(content=f"[VERIFIED] 已基于受控分析结果：{answer}", provider="simulated", model=model)
