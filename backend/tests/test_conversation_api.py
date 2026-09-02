from __future__ import annotations

import importlib

from fastapi.testclient import TestClient
from studio_api.conversation_store import ConversationStore
from studio_api.llm.config import MODEL_MIGRATIONS


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("ANALYSIS_STUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ANALYSIS_STUDIO_ENV_FILE", str(tmp_path / ".env"))
    import studio_api.app as app_module

    return TestClient(importlib.reload(app_module).app)


def _default_config_client(monkeypatch, tmp_path, launch_directory) -> TestClient:
    monkeypatch.setenv("ANALYSIS_STUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANALYSIS_STUDIO_ENV_FILE", raising=False)
    monkeypatch.setenv("ANALYSIS_STUDIO_LEGACY_ENV_FILES", str(tmp_path / "missing-legacy.env"))
    for variable in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "OPENAI_COMPATIBLE_NAME",
        "OPENAI_COMPATIBLE_API_KEY",
        "OPENAI_COMPATIBLE_BASE_URL",
        "OPENAI_COMPATIBLE_MODEL",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.chdir(launch_directory)
    import studio_api.app as app_module
    import studio_api.store as store_module

    importlib.reload(store_module)
    return TestClient(importlib.reload(app_module).app)


def test_model_switch_does_not_clear_history_and_failed_provider_keeps_conversation(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    created = client.post("/api/conversations", json={"title": "经营趋势", "provider": "simulated", "model": "analysis-sim"})
    conversation_id = created.json()["id"]

    sent = client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "分析营业收入趋势"})
    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "2025 经营趋势"})
    changed = client.put(f"/api/conversations/{conversation_id}/model", json={"provider": "openai", "model": "gpt-5.6-terra"})
    loaded = client.get(f"/api/conversations/{conversation_id}").json()

    assert sent.status_code == 201
    assert renamed.json()["title"] == "2025 经营趋势"
    assert changed.status_code == 200
    assert len(loaded["messages"]) == 2
    assert loaded["selected_model"] == "gpt-5.6-terra"


def test_clear_history_requires_confirmation_and_provider_status_never_returns_key(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.post("/api/conversations", json={"title": "第一个"})

    saved = client.put("/api/settings/providers/deepseek", json={"api_key": "secret-value", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"})
    status = client.get("/api/settings/providers").json()["deepseek"]

    assert saved.status_code == 200
    assert status["configured"] is True
    assert "secret-value" not in str(status)
    assert client.delete("/api/conversations").status_code == 422
    assert client.delete("/api/conversations?confirm=true").status_code == 204
    assert client.get("/api/conversations").json() == []


def test_provider_settings_survive_restart_from_a_different_launch_directory(monkeypatch, tmp_path):
    first_directory = tmp_path / "first-launch"
    second_directory = tmp_path / "second-launch"
    first_directory.mkdir()
    second_directory.mkdir()

    first_client = _default_config_client(monkeypatch, tmp_path, first_directory)
    saved = first_client.put(
        "/api/settings/providers/deepseek",
        json={"api_key": "restart-safe-key", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"},
    )
    restarted_client = _default_config_client(monkeypatch, tmp_path, second_directory)
    status = restarted_client.get("/api/settings/providers").json()["deepseek"]

    assert saved.status_code == 200
    assert status["configured"] is True
    assert status["model"] == "deepseek-v4-flash"
    assert (tmp_path / "data" / "providers.env").exists()


def test_configured_model_id_is_selectable_for_its_provider(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    saved = client.put(
        "/api/settings/providers/deepseek",
        json={"api_key": "local-key", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"},
    )
    models = client.get("/api/models?provider=deepseek")
    providers = client.get("/api/providers")
    created = client.post(
        "/api/conversations",
        json={"title": "已配置模型", "provider": "deepseek", "model": "deepseek-v4-flash"},
    )

    assert saved.status_code == 200
    assert "deepseek-v4-flash" in [item["id"] for item in models.json()]
    deepseek = next(item for item in providers.json() if item["id"] == "deepseek")
    assert "deepseek-v4-flash" in [item["id"] for item in deepseek["models"]]
    assert created.status_code == 201
    assert created.json()["selected_model"] == "deepseek-v4-flash"


def test_existing_conversations_migrate_retired_model_ids(tmp_path):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create_conversation("历史会话", "deepseek", "deepseek-chat")

    changed = store.migrate_model_aliases(MODEL_MIGRATIONS)

    assert changed == 1
    assert store.get_conversation(conversation["id"])["selected_model"] == "deepseek-v4-flash"


def test_conversation_binds_and_removes_only_its_own_files(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    first = client.post("/api/datasets", files={"file": ("first.csv", b"month,revenue\n2025-01,10\n", "text/csv")}).json()
    second = client.post("/api/datasets", files={"file": ("second.csv", b"month,revenue\n2025-01,20\n", "text/csv")}).json()
    conversation = client.post("/api/conversations", json={"title": "文件隔离", "file_ids": [first["id"]]}).json()

    added = client.post(f"/api/conversations/{conversation['id']}/files", json={"dataset_id": second["id"]})
    removed = client.delete(f"/api/conversations/{conversation['id']}/files/{second['id']}")

    assert added.json()["file_ids"] == [first["id"], second["id"]]
    assert removed.status_code == 204
    assert client.get(f"/api/conversations/{conversation['id']}").json()["file_ids"] == [first["id"]]


def test_conversation_analysis_creates_reports_and_persisted_result(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    dataset = client.post(
        "/api/datasets",
        files={
            "file": (
                "trend.csv",
                b"month,revenue\n2025-01-01,100\n2025-02-01,112\n2025-03-01,124\n2025-04-01,138\n",
                "text/csv",
            )
        },
    ).json()
    conversation = client.post(
        "/api/conversations",
        json={"title": "趋势", "provider": "simulated", "model": "analysis-sim", "file_ids": [dataset["id"]]},
    ).json()

    sent = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "分析 revenue 趋势"})
    detail = client.get(f"/api/conversations/{conversation['id']}").json()

    assert sent.status_code == 201
    assert len(detail["messages"]) == 2
    assert len(detail["chart_specs"]) == 1
    assert len(detail["reports"]) == 3
    assert detail["artifacts"][-1]["kind"] == "analysis_result"
