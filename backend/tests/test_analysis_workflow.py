from datetime import datetime
from io import BytesIO

import pandas as pd
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook

from studio_api.app import app
from studio_api.answering import analyse_spreadsheet
from studio_api.intake import read_spreadsheet
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


def write_financial_workbook(tmp_path):
    workbook = Workbook()
    cover = workbook.active
    cover.title = "封面"
    cover.append(["2025 年度经营分析"])

    sheet = workbook.create_sheet("财务汇总")
    sheet.append(["经营月报"])
    sheet.append(["单位：万元"])
    sheet.append([])
    sheet.append(["期间", "营业收入", "毛利率", "营业利润"])
    sheet.append(["2025-01", 100, 0.32, 15])
    sheet.append(["2025-02", 120, 0.35, 18])

    path = tmp_path / "financial.xlsx"
    workbook.save(path)
    return path


def write_multi_metric_financial_workbook(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "经营明细"
    sheet.append(["经营月报"])
    sheet.append(["单位：万元"])
    sheet.append([])
    sheet.append(["期间", "营业收入（万元）", "毛利（万元）", "营业利润（万元）"])
    sheet.append(["2023-12", 9999, 3000, 1200])
    for index, period in enumerate(pd.period_range("2024-01", "2025-12", freq="M"), 1):
        revenue = 100 + index * 10
        primary_margin, secondary_margin = 0.30, 0.20
        operating_profit = revenue * 0.15
        if str(period) == "2025-03":
            revenue = 600
            primary_margin, secondary_margin = 0.20, 0.10
            operating_profit = 2
        primary_revenue = revenue * 0.9
        secondary_revenue = revenue - primary_revenue
        sheet.append([str(period), primary_revenue, primary_revenue * primary_margin, operating_profit * 0.9])
        sheet.append([str(period), secondary_revenue, secondary_revenue * secondary_margin, operating_profit * 0.1])

    path = tmp_path / "multi-metric-financial.xlsx"
    workbook.save(path)
    return path


def write_workbook_with_repeated_detail_title(tmp_path):
    workbook = Workbook()
    detail = workbook.active
    detail.title = "经营明细"
    detail.append(["经营明细", "经营明细", "经营明细", "经营明细"])
    detail.append(["说明", "说明", "说明", "说明"])
    detail.append(["一", "二", "三", "四"])

    sheet = workbook.create_sheet("月度财务")
    sheet.append(["2025 年经营分析"])
    sheet.append(["单位：万元"])
    sheet.append([])
    sheet.append(["期间", "营业收入", "毛利率", "营业利润"])
    sheet.append(["2025-01", 100, 0.32, 15])
    sheet.append(["2025-02", 120, 0.35, 18])

    path = tmp_path / "monthly-financial.xlsx"
    workbook.save(path)
    return path


def write_workbook_with_date_and_text_only_sheet(tmp_path):
    workbook = Workbook()
    schedule = workbook.active
    schedule.title = "日程说明"
    schedule.append(["日期", "事项", "负责人", "备注"])
    schedule.append([datetime(2025, 1, 1), "启动会", "张三", "完成"])
    schedule.append([datetime(2025, 2, 1), "复盘会", "李四", "待定"])

    sheet = workbook.create_sheet("月度收入")
    sheet.append(["月度收入分析"])
    sheet.append([])
    sheet.append(["期间", "营业收入"])
    sheet.append(["2025-01", 100])
    sheet.append(["2025-02", 120])

    path = tmp_path / "date-and-text.xlsx"
    workbook.save(path)
    return path


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
    assert "整体" in markdown and "%" in markdown

    word_report = next(report for report in result["reports"] if report["format"] == "docx")
    report = client.get(word_report["download_url"])
    assert report.status_code == 200
    headings = [paragraph.text for paragraph in Document(BytesIO(report.content)).paragraphs]
    assert "核心结论" in headings
    assert "数据质量与分析限制" in headings


def test_read_spreadsheet_selects_a_monthly_table_after_cover_rows(tmp_path):
    frame = read_spreadsheet(write_financial_workbook(tmp_path))

    assert frame.attrs["source_sheet"] == "财务汇总"
    assert frame.attrs["header_row"] == 3
    assert {"期间", "营业收入", "毛利率", "营业利润"} <= set(frame.columns)


def test_read_spreadsheet_skips_repeated_merged_titles_for_valid_monthly_table(tmp_path):
    frame = read_spreadsheet(write_workbook_with_repeated_detail_title(tmp_path))

    assert frame.attrs["source_sheet"] == "月度财务"
    assert frame.attrs["header_row"] == 3
    assert pd.to_datetime(frame["期间"], errors="coerce").notna().sum() == 2
    assert pd.to_numeric(frame["营业收入"], errors="coerce").notna().sum() == 2


def test_read_spreadsheet_rejects_date_and_text_only_sheet_as_a_valid_table(tmp_path):
    frame = read_spreadsheet(write_workbook_with_date_and_text_only_sheet(tmp_path))

    assert frame.attrs["source_sheet"] == "月度收入"
    assert "营业收入" in frame.columns


def test_financial_question_answers_all_requested_metrics_with_monthly_evidence(tmp_path):
    request = "分析 2024-01 到 2025-12 的营业收入、毛利率和营业利润趋势，指出异常月份及可能原因，并引用数据证据。"

    frame = read_spreadsheet(write_multi_metric_financial_workbook(tmp_path))
    plan = plan_question(frame, request)
    result = analyse_spreadsheet(frame, request, tmp_path)

    assert plan.metric_columns == ("营业收入（万元）", "毛利率", "营业利润（万元）")
    assert str(plan.period_start)[:7] == "2024-01"
    assert str(plan.period_end)[:7] == "2025-12"
    assert all(name in result["core_conclusion"] for name in ("营业收入", "毛利率", "营业利润"))
    assert "毛利率 在 2024-01 至 2025-12 呈稳定趋势，从 0.29 到 0.29" in result["core_conclusion"]
    assert "2025-03" in result["core_conclusion"]
    assert "9999" not in result["core_conclusion"]
    assert {item["label"] for item in result["key_metrics"]} >= set(plan.metric_columns)
    assert result["charts"]
    chart = (tmp_path / result["charts"][0]["path"]).read_text(encoding="utf-8")
    assert all(name.encode("unicode_escape").decode("ascii") in chart for name in ("营业收入", "毛利率", "营业利润", "异常"))


def test_multi_metric_answer_reports_no_month_above_anomaly_threshold(tmp_path):
    frame = pd.DataFrame(
        {
            "期间": pd.period_range("2025-01", "2025-12", freq="M").astype(str),
            "营业收入": [100 + index * 2 for index in range(12)],
            "毛利额": [30 + index * 0.6 for index in range(12)],
            "营业利润": [15 + index * 0.3 for index in range(12)],
        }
    )

    result = analyse_spreadsheet(frame, "分析 2025-01 到 2025-12 的营业收入、毛利率和营业利润趋势，指出异常月份", tmp_path)

    anomaly_items = next(section["items"] for section in result["sections"] if section["title"] == "异常对象")
    assert anomaly_items == [{"text": "未识别到超过阈值的异常月份。"}]


def test_multi_metric_explanation_reflects_same_direction_margin_change(tmp_path):
    frame = pd.DataFrame(
        {
            "期间": ["2025-01", "2025-02", "2025-03", "2025-04"],
            "营业收入": [100, 101, 102, 129.54],
            "毛利额": [30, 30.3, 30.6, 39.02],
            "营业利润": [15, 15.1, 15.2, 19.38],
        }
    )

    result = analyse_spreadsheet(frame, "分析 2025-01 到 2025-04 的营业收入、毛利率和营业利润趋势，指出异常月份及可能原因", tmp_path)

    assert "2025-04 的指标联动显示：营业收入 环比上升 27.0%、毛利率 环比上升 0.4%、营业利润 环比上升 27.5%" in result["core_conclusion"]
    assert "营业收入与营业利润同向，毛利率上升" in result["core_conclusion"]
    assert "毛利率稳定或略升" not in result["core_conclusion"]


def test_multi_metric_explanation_names_a_declining_margin(tmp_path):
    frame = pd.DataFrame(
        {
            "期间": ["2025-01", "2025-02", "2025-03", "2025-04"],
            "营业收入": [100, 101, 102, 129.54],
            "毛利额": [30, 30.3, 30.6, 36.27],
            "营业利润": [15, 15.1, 15.2, 19.38],
        }
    )

    result = analyse_spreadsheet(frame, "分析 2025-01 到 2025-04 的营业收入、毛利率和营业利润趋势，指出异常月份及可能原因", tmp_path)

    assert "营业收入与营业利润同向，毛利率下降" in result["core_conclusion"]
    assert "毛利率上升" not in result["core_conclusion"] and "毛利率稳定" not in result["core_conclusion"]


def test_operating_profit_only_anomaly_has_a_possible_reason(tmp_path):
    frame = pd.DataFrame(
        {
            "期间": ["2025-01", "2025-02", "2025-03", "2025-04"],
            "营业收入": [100, 101, 102, 103],
            "毛利额": [30, 30.3, 30.6, 30.9],
            "营业利润": [15, 15.1, 15.2, 7.6],
        }
    )

    result = analyse_spreadsheet(frame, "分析 2025-01 到 2025-04 的营业收入、毛利率和营业利润趋势，指出异常月份及可能原因", tmp_path)

    anomaly_items = next(section["items"] for section in result["sections"] if section["title"] == "异常对象")
    assert len(anomaly_items) == 1
    assert "营业利润" in anomaly_items[0]["text"]
    assert "2025-04" in anomaly_items[0]["text"]
    assert "%" in anomaly_items[0]["text"] and "可能原因" in anomaly_items[0]["text"]


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
    assert first.json()["title"].startswith("地区营收风险")
    assert second.status_code == 201
    assert second.json()["title"].startswith("地区营收风险 ·")
    assert first.json()["title"] != second.json()["title"]


def test_same_question_uses_a_unique_title_across_datasets():
    first_dataset = client.post("/api/datasets", files={"file": ("first.xlsx", make_sales_workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
    second_dataset = client.post("/api/datasets", files={"file": ("second.xlsx", make_sales_workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
    objective = "检测地区营收异常风险"

    first = client.post("/api/sessions", json={"dataset_id": first_dataset["id"], "objective": objective})
    second = client.post("/api/sessions", json={"dataset_id": second_dataset["id"], "objective": objective})

    assert first.json()["title"] != second.json()["title"]
    assert second.json()["title"].startswith("地区营收风险 ·")


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


def test_question_plan_prefers_the_requested_gmv_metric_over_identifier_columns():
    frame = pd.DataFrame({"month": ["2025-01", "2025-02"], "region": ["north", "south"], "order_id": [1, 2], "GMV": [100, 80]})

    plan = plan_question(frame, "分析GMV趋势")

    assert plan.metric_column == "GMV"
    assert plan.title == "GMV趋势"


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


def test_anomaly_and_forecast_charts_expose_their_decision_evidence():
    anomaly = analyse_uploaded("检测地区营收异常风险")
    forecast = analyse_uploaded("预测未来营收")

    anomaly_html = client.get(anomaly["charts"][0]["download_url"]).text
    forecast_html = client.get(forecast["charts"][0]["download_url"]).text
    assert "\\u5f02\\u5e38\\u70b9" in anomaly_html
    assert "80% \\u9884\\u6d4b\\u533a\\u95f4" in forecast_html


def test_future_decline_question_triggers_forecast_and_names_the_at_risk_object():
    result = analyse_uploaded("哪些地区未来可能继续下滑")

    assert "forecast" in result["analysis"]["plan"]["types"]
    assert "south" in result["core_conclusion"].lower()
    assert result["forecast"]["prediction_interval_80"]


def test_non_numeric_dataset_returns_a_clear_inability_answer_not_an_internal_error():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["month", "region", "comment"])
    sheet.append(["2025-01", "south", "missing revenue"])
    buffer = BytesIO()
    workbook.save(buffer)
    create = client.post("/api/jobs", data={"objective": "分析地区营收趋势"}, files={"file": ("text.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    response = client.post(f"/api/jobs/{create.json()['id']}/analyze")

    assert response.status_code == 200
    assert "未找到可用于计算的数值指标" in response.json()["core_conclusion"]
