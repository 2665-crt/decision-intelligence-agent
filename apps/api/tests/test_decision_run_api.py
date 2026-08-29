import json
from io import BytesIO
from pathlib import Path

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
    assert result["forecast"]["baseline_metrics"]["rmse"] >= 0
    assert {"ets", "arima"} <= set(result["forecast"]["candidate_metrics"])
    assert "prediction_interval_80" in result["forecast"]
    assert "residual_anomalies" in result["forecast"]
    assert result["risk"]["probability"] in {"low", "medium", "high"}
    assert result["risk"]["impact"] in {"low", "medium", "high"}
    assert result["risk"]["severity"] in {"low", "medium", "high", "critical"}
    assert result["options"]
    assert {"expected_benefit", "implementation_cost", "potential_harm", "assumptions", "validation_metric"} <= set(result["options"][0])


def test_each_execution_creates_a_new_immutable_run_directory() -> None:
    stream = BytesIO(); workbook = Workbook(); sheet = workbook.active
    sheet.append(["month", "revenue"])
    for month in range(1, 13): sheet.append([f"2025-{month:02d}-01", month * 10])
    workbook.save(stream); stream.seek(0)
    client = TestClient(app); task = client.post("/tasks").json()["id"]
    file = client.post(f"/tasks/{task}/files", files={"file": ("series.xlsx", stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
    selection = client.post(f"/tasks/{task}/selections", json={"file_ids": [file["id"]]}).json()
    plan = client.post("/plans", json={"selection_id": selection["id"], "objective": "预测收入风险"}).json()
    client.post(f"/revisions/{plan['revision_id']}/confirm")

    first = client.post(f"/revisions/{plan['revision_id']}/runs").json()
    second = client.post(f"/revisions/{plan['revision_id']}/runs").json()

    assert first["revision_id"] != second["revision_id"]
    first_dirs = {str(Path(item["path"]).parent) for item in first["artifacts"]}
    second_dirs = {str(Path(item["path"]).parent) for item in second["artifacts"]}
    assert first_dirs == {str(Path(".data") / "runs" / first["revision_id"])}
    assert second_dirs == {str(Path(".data") / "runs" / second["revision_id"])}
    assert first_dirs.isdisjoint(second_dirs)
    assert all(Path(item["path"]).exists() for item in first["artifacts"])
    manifest_path = next(Path(item["path"]) for item in first["artifacts"] if item["path"].endswith("run_manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["revision_id"] == first["revision_id"]
    assert manifest["parent_revision_id"] == plan["revision_id"]
    assert manifest["status"] == "succeeded"
