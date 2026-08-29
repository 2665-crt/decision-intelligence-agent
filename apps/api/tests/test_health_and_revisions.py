from fastapi.testclient import TestClient

from universal_agent.main import app


def test_creating_second_revision_preserves_first_snapshot() -> None:
    client = TestClient(app)
    task = client.post("/tasks").json()
    first = client.post(f"/tasks/{task['id']}/revisions", json={"kind": "plan"}).json()
    second = client.post(f"/tasks/{task['id']}/revisions", json={"kind": "run"}).json()

    assert client.get("/health").json() == {"status": "ok"}
    assert first["id"] != second["id"]
    assert client.get(f"/revisions/{first['id']}").json()["kind"] == "plan"
