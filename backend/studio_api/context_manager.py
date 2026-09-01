from __future__ import annotations

import json


class ContextManager:
    def __init__(self, recent_message_limit: int = 8):
        self.recent_message_limit = recent_message_limit
        self.system_prompt = "你是数据分析工作台的回答层。仅依据提供的受控分析结果，不虚构数据或执行步骤。"

    def build(self, conversation: dict, messages: list[dict], state: dict, data_context: dict) -> list[dict[str, str]]:
        recent = messages[-self.recent_message_limit :]
        compact_context = {
            "summary": conversation.get("conversation_summary", ""),
            "analysis_state": state,
            "data_context": data_context,
        }
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": json.dumps(compact_context, ensure_ascii=False)},
            *[{"role": item["role"], "content": item["content"]} for item in recent if item["role"] in {"user", "assistant"}],
        ]

    def summary_for(self, messages: list[dict]) -> str:
        early = messages[: max(0, len(messages) - self.recent_message_limit)]
        user_questions = [item["content"].strip() for item in early if item["role"] == "user" and item["content"].strip()]
        if not user_questions:
            return ""
        return "早期对话：" + "；".join(user_questions[-4:])
