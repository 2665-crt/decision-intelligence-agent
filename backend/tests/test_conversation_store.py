from __future__ import annotations

import json

from studio_api.conversation_store import ConversationStore


def _write_legacy_session(root, session_id: str = "legacy-1") -> dict:
    session = {
        "id": session_id,
        "dataset_id": "dataset-1",
        "source_name": "sales.csv",
        "objective": "分析营业收入趋势",
        "title": "营收趋势分析",
        "status": "succeeded",
        "messages": [{"role": "user", "content": "分析营业收入趋势", "created_at": "2026-09-01T00:00:00+00:00"}],
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
    }
    directory = root / "sessions" / session_id
    directory.mkdir(parents=True)
    (directory / "session.json").write_text(json.dumps(session), encoding="utf-8")
    return session


def test_migration_imports_legacy_session_once(tmp_path):
    legacy = _write_legacy_session(tmp_path)
    store = ConversationStore(tmp_path / "conversations.sqlite3", legacy_root=tmp_path)

    assert store.migrate_legacy_sessions() == 1
    assert store.migrate_legacy_sessions() == 0

    conversation = store.get_conversation(legacy["id"])
    assert conversation["title"] == legacy["title"]
    assert conversation["file_ids"] == ["dataset-1"]
    assert [message["content"] for message in store.list_messages(legacy["id"])] == ["分析营业收入趋势"]


def test_state_merge_preserves_unmentioned_fields_and_persists_artifacts(tmp_path):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create_conversation("趋势分析", "simulated", "analysis-sim", ["dataset-1"])

    store.merge_analysis_state(
        conversation["id"],
        {"metrics": ["营业收入"], "date_range": {"start": "2024-01", "end": "2025-12"}},
    )
    state = store.merge_analysis_state(conversation["id"], {"date_range": {"start": "2025-01", "end": "2025-12"}})
    message = store.append_message(conversation["id"], "assistant", "已完成", "simulated", "analysis-sim")
    artifact = store.add_artifact(conversation["id"], message["id"], "chart", "charts/revenue.html", {"title": "营业收入"})

    assert state["metrics"] == ["营业收入"]
    assert state["date_range"] == {"start": "2025-01", "end": "2025-12"}
    assert store.list_artifacts(conversation["id"])[0]["id"] == artifact["id"]
    assert store.get_conversation(conversation["id"])["file_ids"] == ["dataset-1"]


def test_delete_and_clear_only_remove_conversation_records(tmp_path):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    first = store.create_conversation("第一个", "simulated", "analysis-sim", ["dataset-a"])
    second = store.create_conversation("第二个", "simulated", "analysis-sim", ["dataset-b"])

    assert store.delete_conversation(first["id"]) is True
    assert [item["id"] for item in store.list_conversations()] == [second["id"]]
    assert store.clear_conversations() == 1
    assert store.list_conversations() == []
