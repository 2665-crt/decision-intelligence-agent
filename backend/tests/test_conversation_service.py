from __future__ import annotations

from studio_api.context_manager import ContextManager
from studio_api.conversation_service import ConversationService
from studio_api.conversation_store import ConversationStore
from studio_api.llm.gateway import LLMGateway
from studio_api.llm.simulated import SimulatedProvider


def test_context_manager_requires_verified_and_unverified_evidence_labels():
    prompt = ContextManager().system_prompt

    assert "VERIFIED" in prompt
    assert "UNVERIFIED" in prompt


def _runner(conversation: dict, objective: str) -> dict:
    return {
        "answer": f"已计算：{objective}",
        "findings": [{"conclusion": "营业收入上升"}],
        "chart_specs": [{"id": "revenue", "type": "line"}],
        "reports": [{"format": "md"}],
        "analysis": {"plan": {"metrics": [{"name": "营业收入"}], "time_field": "月份"}},
    }


def _service(tmp_path) -> tuple[ConversationStore, ConversationService]:
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    service = ConversationService(
        store=store,
        gateway=LLMGateway({"simulated": SimulatedProvider()}),
        context_manager=ContextManager(recent_message_limit=2),
        analysis_runner=_runner,
        artifact_root=tmp_path / "artifacts",
    )
    return store, service


def test_follow_up_reuses_state_and_preserves_all_messages(tmp_path):
    store, service = _service(tmp_path)
    conversation = store.create_conversation("经营趋势", "simulated", "analysis-sim", ["dataset-1"])

    first = service.send_message(conversation["id"], "分析营业收入趋势")
    second = service.send_message(conversation["id"], "那 2025 年呢？")
    state = store.get_analysis_state(conversation["id"])

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert state["metrics"] == ["营业收入"]
    assert state["date_range"] == {"start": "2025-01", "end": "2025-12"}
    assert len(store.list_messages(conversation["id"])) == 4
    assert store.list_artifacts(conversation["id"])


def test_switching_to_error_model_keeps_user_message_and_existing_artifacts(tmp_path):
    store, service = _service(tmp_path)
    conversation = store.create_conversation("经营趋势", "simulated", "analysis-sim", ["dataset-1"])
    service.send_message(conversation["id"], "分析营业收入趋势")
    store.update_model(conversation["id"], "simulated", "analysis-sim-error")
    artifact_count = len(store.list_artifacts(conversation["id"]))

    failed = service.send_message(conversation["id"], "继续分析")

    assert failed["status"] == "failed"
    assert failed["error_code"] == "provider_error"
    assert [item["role"] for item in store.list_messages(conversation["id"])] == ["user", "assistant", "user", "assistant"]
    assert len(store.list_artifacts(conversation["id"])) == artifact_count + 1


def test_context_manager_summarizes_early_messages_without_deleting_them(tmp_path):
    store, service = _service(tmp_path)
    conversation = store.create_conversation("经营趋势", "simulated", "analysis-sim", ["dataset-1"])

    for question in ("分析营业收入趋势", "只看 2025 年", "换成柱状图"):
        service.send_message(conversation["id"], question)

    assert "分析营业收入趋势" in store.get_conversation(conversation["id"])["conversation_summary"]
    assert len(store.list_messages(conversation["id"])) == 6
