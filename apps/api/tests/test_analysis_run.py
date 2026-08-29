from io import BytesIO
from openpyxl import Workbook
from fastapi.testclient import TestClient
from universal_agent.main import app

def _workbook() -> BytesIO:
    workbook = Workbook(); sheet = workbook.active; sheet.append(["date", "revenue"]); sheet.append(["2026-01-01", 100]); sheet.append(["2026-01-02", 120]); stream = BytesIO(); workbook.save(stream); stream.seek(0); return stream

def test_run_binds_all_artifacts_to_confirmed_revision() -> None:
    client = TestClient(app); task_id = client.post("/tasks").json()["id"]
    uploaded = client.post(f"/tasks/{task_id}/files", files={"file": ("sales.xlsx", _workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
    selection = client.post(f"/tasks/{task_id}/selections", json={"file_ids": [uploaded["id"]]}).json()
    plan = client.post("/plans", json={"selection_id": selection["id"], "objective": "趋势"}).json(); revision_id = plan["revision_id"]
    client.post(f"/revisions/{revision_id}/confirm")
    run = client.post(f"/revisions/{revision_id}/runs")
    assert run.status_code == 202
    assert run.json()["revision_id"] != revision_id
    assert all(item["revision_id"] == run.json()["revision_id"] for item in run.json()["artifacts"])
