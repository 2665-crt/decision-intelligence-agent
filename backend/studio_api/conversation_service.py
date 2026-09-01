from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from .context_manager import ContextManager
from .conversation_store import ConversationStore
from .llm.base import ProviderError
from .llm.gateway import LLMGateway


AnalysisRunner = Callable[[dict, str], dict]


class ConversationService:
    def __init__(self, *, store: ConversationStore, gateway: LLMGateway, context_manager: ContextManager, analysis_runner: AnalysisRunner, artifact_root: Path):
        self.store = store
        self.gateway = gateway
        self.context_manager = context_manager
        self.analysis_runner = analysis_runner
        self.artifact_root = artifact_root

    def send_message(self, conversation_id: str, content: str, provider: str | None = None, model: str | None = None) -> dict:
        conversation = self.store.get_conversation(conversation_id)
        selected_provider = provider or conversation["selected_provider"]
        selected_model = model or conversation["selected_model"]
        self.store.append_message(conversation_id, "user", content, status="completed")
        try:
            result = self.analysis_runner(conversation, content)
            state = self.store.get_analysis_state(conversation_id)
            messages = self.store.list_messages(conversation_id)
            response = self.gateway.chat(
                provider=selected_provider,
                model=selected_model,
                messages=self.context_manager.build(conversation, messages, state, self._data_context(result)),
                analysis_result=result,
            )
        except ProviderError as exc:
            return self.store.append_message(
                conversation_id, "assistant", exc.user_message, selected_provider, selected_model, status="failed", error_code=exc.code
            )
        assistant = self.store.append_message(
            conversation_id, "assistant", response.content, response.provider, response.model, status="completed"
        )
        artifact = self._save_result(conversation_id, assistant["id"], result)
        self._update_state(conversation_id, content, result, artifact)
        self._update_summary(conversation_id)
        return self.store.list_messages(conversation_id)[-1]

    def regenerate_message(self, message_id: str, provider: str | None = None, model: str | None = None) -> dict:
        for conversation in self.store.list_conversations(limit=1000):
            messages = self.store.list_messages(conversation["id"])
            for index, message in enumerate(messages):
                if message["id"] == message_id and message["role"] == "assistant":
                    if index == 0 or messages[index - 1]["role"] != "user":
                        raise KeyError(message_id)
                    return self.send_message(conversation["id"], messages[index - 1]["content"], provider, model)
        raise KeyError(message_id)

    def clear_history(self) -> int:
        return self.store.clear_conversations()

    def _save_result(self, conversation_id: str, message_id: str, result: dict) -> dict:
        directory = self.artifact_root / conversation_id / "analysis"
        directory.mkdir(parents=True, exist_ok=True)
        relative_path = f"{conversation_id}/analysis/{message_id}.json"
        target = self.artifact_root / relative_path
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.store.add_artifact(conversation_id, message_id, "analysis_result", relative_path, {"answer": result.get("answer", ""), "result": result})

    def _update_state(self, conversation_id: str, content: str, result: dict, artifact: dict) -> None:
        plan = result.get("analysis", {}).get("plan", {})
        metrics = [item["name"] for item in plan.get("metrics", []) if isinstance(item, dict) and item.get("name")]
        patch: dict = {
            "current_question": content,
            "current_analysis_goal": content,
            "previous_findings": [artifact["id"]],
            "previous_calculations": [artifact["id"]],
            "previous_charts": [item.get("id") for item in result.get("chart_specs", []) if item.get("id")],
            "generated_reports": [artifact["id"]] if result.get("reports") else [],
        }
        if metrics:
            patch["metrics"] = metrics
        if plan.get("time_field"):
            patch["active_sheet"] = str(plan["time_field"])
        year = re.search(r"(20\s*\d{2})\s*年", content)
        if year and any(token in content for token in ("只看", "重点", "那", "年")):
            normalized_year = re.sub(r"\s+", "", year.group(1))
            patch["date_range"] = {"start": f"{normalized_year}-01", "end": f"{normalized_year}-12"}
        if "柱状图" in content:
            patch["chart_preference"] = "bar"
        self.store.merge_analysis_state(conversation_id, patch)

    def _update_summary(self, conversation_id: str) -> None:
        summary = self.context_manager.summary_for(self.store.list_messages(conversation_id))
        if summary:
            self.store.update_summary(conversation_id, summary)

    @staticmethod
    def _data_context(result: dict) -> dict:
        analysis = result.get("analysis", {})
        return {
            "analysis_kind": analysis.get("kind"),
            "plan": analysis.get("plan", {}),
            "findings": [{"conclusion": item.get("conclusion"), "kind": item.get("kind")} for item in result.get("findings", [])],
            "chart_ids": [item.get("id") for item in result.get("chart_specs", [])],
        }
