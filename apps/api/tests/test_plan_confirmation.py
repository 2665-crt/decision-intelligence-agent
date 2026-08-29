from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from universal_agent.main import app


def workbook_bytes() -> BytesIO:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["date", "revenue"])
    worksheet.append(["2026-01-01", 100])
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def test_run_is_rejected_until_plan_is_confirmed() -> None:
    client = TestClient(app)
    task_id = client.post("/tasks").json()["id"]
    uploaded = client.post(
        f"/tasks/{task_id}/files",
        files={"file": ("sales.xlsx", workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    selection = client.post(f"/tasks/{task_id}/selections", json={"file_ids": [uploaded["id"]]}).json()

    planned = client.post("/plans", json={"selection_id": selection["id"], "objective": "分析收入趋势"})
    assert planned.status_code == 201
    revision_id = planned.json()["revision_id"]
    assert client.post(f"/revisions/{revision_id}/runs").status_code == 409
    assert client.post(f"/revisions/{revision_id}/confirm").status_code == 200
    assert client.post(f"/revisions/{revision_id}/runs").status_code == 202
