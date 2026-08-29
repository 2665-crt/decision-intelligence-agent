from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from universal_agent.main import app


def test_confirmed_run_returns_analysis_risk_and_three_report_artifacts() -> None:
    stream = BytesIO(); workbook = Workbook(); sheet = workbook.active
    sheet.append(["month", "revenue"])
    for month in range(1, 13): sheet.append([f"2025-{month:02d}-01", month * 10])
    workbook.save(stream); stream.seek(0)
    client = TestClient(app); task = client.post("/tasks").json()["id"]
    file = client.post(f"/tasks/{task}/files", files={"file": ("series.xlsx", stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
    selection = client.post(f"/tasks/{task}/selections", json={"file_ids": [file["id"]]}).json()
    plan = client.post("/plans", json={"selection_id": selection["id"], "objective": "预测收入风险"}).json()
    client.post(f"/revisions/{plan['revision_id']}/confirm")
    result = client.post(f"/revisions/{plan['revision_id']}/runs").json()
    paths = {item["path"] for item in result["artifacts"]}
    assert {"report.md", "report.html", "report.docx"} <= {path.split("\\")[-1] for path in paths}
    assert result["risk"]["human_review_required"] is False
    assert result["forecast"]["baseline_metrics"]["mae"] >= 0
