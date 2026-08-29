from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook

from studio_api.app import app


client = TestClient(app)


def make_sales_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "sales"
    sheet.append(["month", "region", "revenue"])
    for month, revenue in enumerate([100, 120, 150, 180, 220, 260, 310, 360, 420, 490, 570, 660], 1):
        sheet.append([f"2025-{month:02d}-01", "north" if month % 2 else "south", revenue])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_excel_job_produces_analysis_risks_charts_and_reports():
    create = client.post(
        "/api/jobs",
        data={"objective": "分析营收趋势并预测下一季度风险"},
        files={"file": ("sales.xlsx", make_sales_workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert create.status_code == 201
    job = create.json()
    assert job["intake"]["kind"] == "spreadsheet"
    assert job["intake"]["columns"] == ["month", "region", "revenue"]

    run = client.post(f"/api/jobs/{job['id']}/analyze")

    assert run.status_code == 200
    result = run.json()
    assert result["status"] == "succeeded"
    assert result["analysis"]["numeric_summary"]["revenue"]["max"] == 660
    assert result["charts"]
    assert {report["format"] for report in result["reports"]} == {"markdown", "html", "docx"}
    assert result["forecast"] is not None
    assert "is_recommended" in result["forecast"]
    assert result["risks"]
    assert result["options"]

    word_report = next(report for report in result["reports"] if report["format"] == "docx")
    report = client.get(word_report["download_url"])
    assert report.status_code == 200
    headings = [paragraph.text for paragraph in Document(BytesIO(report.content)).paragraphs]
    assert "文件事实" in headings
    assert "待验证建议" in headings


def test_word_job_is_reported_as_document_evidence_not_measured_data():
    document = Document()
    document.add_heading("项目风险说明", level=1)
    document.add_paragraph("供应延期可能影响交付，需要在本周确认备选方案。")
    buffer = BytesIO()
    document.save(buffer)

    create = client.post(
        "/api/jobs",
        data={"objective": "审阅项目风险并给出低损害方案"},
        files={"file": ("brief.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    job = create.json()

    run = client.post(f"/api/jobs/{job['id']}/analyze")

    assert run.status_code == 200
    result = run.json()
    assert result["status"] == "succeeded"
    assert result["analysis"]["kind"] == "document_review"
    assert result["evidence"][0]["level"] == "document_statement"
    assert "文档陈述" in result["evidence"][0]["summary"]
    assert result["reports"]


def test_unsupported_file_is_rejected():
    response = client.post(
        "/api/jobs",
        data={"objective": "分析"},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 422
    assert "只支持" in response.json()["detail"]


def test_one_dataset_can_restore_independent_analysis_sessions():
    dataset_response = client.post(
        "/api/datasets",
        files={"file": ("sales.xlsx", make_sales_workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert dataset_response.status_code == 201
    dataset = dataset_response.json()

    trend = client.post("/api/sessions", json={"dataset_id": dataset["id"], "objective": "分析营收趋势"})
    risk = client.post("/api/sessions", json={"dataset_id": dataset["id"], "objective": "检测异常订单风险"})

    assert trend.status_code == 201
    assert risk.status_code == 201
    assert trend.json()["dataset_id"] == dataset["id"]
    assert trend.json()["id"] != risk.json()["id"]
    assert trend.json()["messages"][0]["content"] == "分析营收趋势"

    listed = client.get(f"/api/sessions?dataset_id={dataset['id']}")
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()} >= {trend.json()["id"], risk.json()["id"]}

    renamed = client.patch(f"/api/sessions/{trend.json()['id']}", json={"title": "月度营收趋势"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "月度营收趋势"

    copied = client.post(f"/api/sessions/{trend.json()['id']}/copy")
    assert copied.status_code == 201
    assert copied.json()["dataset_id"] == dataset["id"]
    assert copied.json()["messages"] == []
    assert copied.json()["status"] == "ready"

    analyzed = client.post(f"/api/sessions/{trend.json()['id']}/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["status"] == "succeeded"
    assert analyzed.json()["notebook_cells"][0]["language"] == "python"
    assert client.get(f"/api/sessions/{risk.json()['id']}").json()["status"] == "ready"

    deleted = client.delete(f"/api/sessions/{copied.json()['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/sessions/{copied.json()['id']}").status_code == 404
