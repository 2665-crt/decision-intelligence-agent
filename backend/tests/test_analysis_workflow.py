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
