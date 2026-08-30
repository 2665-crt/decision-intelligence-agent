from io import BytesIO

import pandas as pd
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook

from studio_api.app import app
from studio_api.questioning import plan_question


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


def make_regional_revenue_workbook(missing_south_march: bool = False) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "regional revenue"
    sheet.append(["month", "region", "revenue"])
    north = [100, 103, 107, 110, 113, 116, 120, 123, 126, 130, 134, 138]
    south = [155, 150, 145, 137, 128, 118, 108, 98, 90, 84, 79, 74]
    east = [112, 115, 118, 92, 116, 119, 122, 121, 124, 127, 130, 133]
    for month in range(1, 13):
        for region, revenue in (("north", north[month - 1]), ("south", None if missing_south_march and month == 3 else south[month - 1]), ("east", east[month - 1])):
            sheet.append([f"2025-{month:02d}-01", region, revenue])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def analyse_uploaded(objective: str, missing_south_march: bool = False) -> dict:
    create = client.post(
        "/api/jobs",
        data={"objective": objective},
        files={"file": ("regional.xlsx", make_regional_revenue_workbook(missing_south_march), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert create.status_code == 201
    result = client.post(f"/api/jobs/{create.json()['id']}/analyze")
    assert result.status_code == 200
    return result.json()


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

    markdown_report = next(report for report in result["reports"] if report["format"] == "markdown")
    markdown = client.get(markdown_report["download_url"]).text
    assert markdown.index("## 核心结论") < markdown.index("## 数据质量与分析限制")
    assert "north" in markdown.lower() and "%" in markdown

    word_report = next(report for report in result["reports"] if report["format"] == "docx")
    report = client.get(word_report["download_url"])
    assert report.status_code == 200
    headings = [paragraph.text for paragraph in Document(BytesIO(report.content)).paragraphs]
    assert "核心结论" in headings
    assert "数据质量与分析限制" in headings


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


def test_semantic_session_titles_are_short_and_duplicates_are_numbered():
    dataset_response = client.post(
        "/api/datasets",
        files={"file": ("sales.xlsx", make_sales_workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    dataset_id = dataset_response.json()["id"]
    objective = "分析不同地区营收情况，检测异常地区并预测未来营收风险"

    first = client.post("/api/sessions", json={"dataset_id": dataset_id, "objective": objective})
    second = client.post("/api/sessions", json={"dataset_id": dataset_id, "objective": objective})

    assert first.status_code == 201
    assert first.json()["title"] == "地区营收风险"
    assert second.status_code == 201
    assert second.json()["title"] == "地区营收风险 · 2"


def test_question_plan_recognises_region_revenue_risk_request():
    frame = pd.DataFrame(
        {
            "month": ["2025-01", "2025-02"],
            "region": ["north", "south"],
            "revenue": [100, 80],
        }
    )

    plan = plan_question(frame, "检测地区营收异常风险并预测未来风险")

    assert set(plan.types) == {"anomaly", "risk", "forecast"}
    assert (plan.time_column, plan.metric_column, plan.dimension_column) == ("month", "revenue", "region")


def test_region_revenue_risk_answers_with_object_numbers_and_chart():
    result = analyse_uploaded("检测地区营收异常风险")

    assert "south" in result["core_conclusion"].lower()
    assert any(char.isdigit() for char in result["core_conclusion"])
    assert result["business_risks"][0]["object"] == "south"
    assert result["business_risks"][0]["level"] == "high"
    assert result["charts"]


def test_trend_and_anomaly_sections_include_direction_object_and_magnitude():
    result = analyse_uploaded("分析月度营收趋势，找出下降最严重地区和异常月份")

    headings = [section["title"] for section in result["sections"]]
    assert "趋势分析" in headings
    assert "异常对象" in headings
    assert any("下降" in item["text"] and "%" in item["text"] for section in result["sections"] for item in section["items"])


def test_forecast_returns_interval_or_explains_missing_time_series_conditions():
    result = analyse_uploaded("预测未来营收")

    assert result["forecast"]["prediction_interval_80"] or result["forecast"]["limitations"]


def test_quality_metadata_cannot_become_the_core_answer():
    result = analyse_uploaded("检测地区营收异常风险")

    assert result["core_conclusion"] != result["data_quality"]["summary"]
    assert result["business_risks"][0]["title"] != "数据质量风险"


def test_missing_month_that_affects_south_is_named_as_a_limited_month():
    result = analyse_uploaded("分析地区营收趋势", missing_south_march=True)

    assert any("south" in item.lower() and "2025-03" in item for item in result["data_quality"]["limitations"])


def test_forecast_question_with_sufficient_history_returns_a_numeric_interval():
    result = analyse_uploaded("预测未来营收")
    intervals = result["forecast"]["prediction_interval_80"]

    assert len(intervals) == 3
    assert all(item["lower"] <= item["value"] <= item["upper"] for item in intervals)


def test_best_performing_region_question_answers_the_leader_not_the_largest_decline():
    result = analyse_uploaded("哪个地区表现最好？")

    assert "north" in result["core_conclusion"].lower()
    assert "south" not in result["core_conclusion"].lower()
    assert "地区排名" in [section["title"] for section in result["sections"]]
