from datetime import datetime
import hashlib
from io import BytesIO
import json

import pandas as pd
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook

from studio_api.app import app
from studio_api.answering import analyse_spreadsheet
from studio_api.intake import read_spreadsheet
from studio_api.questioning import plan_question


client = TestClient(app)


def test_generic_engine_returns_a_traceable_direct_ranking_answer(tmp_path):
    source = tmp_path / "measurements.csv"
    source.write_text(
        "bucket,measure_x\n"
        "A,12\n"
        "B,20\n"
        "A,15\n",
        encoding="utf-8",
    )

    from studio_api.engine import run

    result = run(
        {"objective": "哪个 bucket 的 measure_x 最高？", "intake": {"kind": "spreadsheet"}},
        tmp_path,
        source,
    )

    assert result["status"] == "succeeded"
    assert result["validation_status"] == "SUCCESS"
    assert "A" in result["answer"]
    assert "27" in result["answer"]
    assert result["findings"][0]["metric_value"] == 27.0
    assert result["findings"][0]["evidence"]["calculation"] == "groupby(bucket).sum(measure_x)"
    assert result["evidence"][0]["source"]["file_hash"]


def test_validator_rejects_a_numeric_finding_without_calculation_evidence(tmp_path):
    source = tmp_path / "measurements.csv"
    source.write_text("bucket,measure_x\nA,12\nB,20\n", encoding="utf-8")

    from studio_api.execution import ComputedFinding, ExecutionResult, FindingEvidence
    from studio_api.profiling import profile_file
    from studio_api.validation import validate_result

    invalid = ComputedFinding(
        kind="ranking",
        value="B",
        metric_value=20.0,
        conclusion="B 的 measure_x 为 20。",
        confidence=0.8,
        evidence=FindingEvidence(
            source={"file_hash": profile_file(source).file_hash, "table": "measurements"},
            fields=("bucket", "measure_x"),
            filters=(),
            grouping=("bucket",),
            calculation="",
            row_indices=(1,),
        ),
    )

    result = validate_result(ExecutionResult("SUCCESS", (invalid,), ()), profile_file(source))

    assert result.status == "INSUFFICIENT_DATA"
    assert result.findings == ()
    assert any("calculation" in limitation for limitation in result.limitations)


def test_generic_engine_explains_missing_required_fields_without_fixed_defaults(tmp_path):
    source = tmp_path / "measurements.csv"
    source.write_text("bucket,measure_x\nA,12\nB,20\n", encoding="utf-8")

    from studio_api.engine import run

    result = run(
        {"objective": "分析 measure_x 趋势", "intake": {"kind": "spreadsheet"}},
        tmp_path,
        source,
    )

    assert result["status"] == "succeeded"
    assert result["validation_status"] == "INSUFFICIENT_DATA"
    assert "time" in result["answer"]
    assert result["findings"] == []


def test_profile_classifies_nonstandard_order_fields_without_fixed_business_names(tmp_path):
    source = tmp_path / "orders.csv"
    source.write_text(
        "dt,col1,value_x\n"
        "2025-01-01,alpha,10\n"
        "2025-01-02,beta,12\n"
        "2025-01-03,alpha,11\n",
        encoding="utf-8",
    )

    from studio_api.profiling import profile_file

    profile = profile_file(source)
    columns = {column.name: column for column in profile.tables[0].columns}

    assert profile.file_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    assert columns["dt"].semantic_role == "time"
    assert columns["dt"].confidence >= 0.70
    assert columns["col1"].semantic_role == "dimension"
    assert columns["col1"].confidence >= 0.70
    assert columns["value_x"].semantic_role == "metric"
    assert columns["value_x"].confidence >= 0.70


def test_profile_serializes_nested_json_values_without_failing_unique_measurement(tmp_path):
    source = tmp_path / "events.json"
    source.write_text(
        json.dumps([{"dt": "2025-01-01", "tags": ["north", "urgent"], "value_x": 10}]),
        encoding="utf-8",
    )

    from studio_api.profiling import profile_file

    profile = profile_file(source)
    tags = next(column for column in profile.tables[0].columns if column.name == "tags")

    assert tags.semantic_role == "uncertain"
    assert tags.confidence < 0.70
    assert tags.samples == ['["north","urgent"]']
    assert tags.unique_ratio == 1.0


def test_relationships_auto_use_matching_unique_ids_across_excel_sheets(tmp_path):
    source = tmp_path / "customers.xlsx"
    workbook = Workbook()
    customers = workbook.active
    customers.title = "customers"
    customers.append(["customer_id", "name"])
    customers.append([101, "A"])
    customers.append([102, "B"])
    orders = workbook.create_sheet("orders")
    orders.append(["customer_id", "order_value"])
    orders.append([101, 10])
    orders.append([102, 20])
    workbook.save(source)

    from studio_api.profiling import profile_file
    from studio_api.relationships import discover_relationships

    candidates = discover_relationships([profile_file(source)])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.left_table == "customers"
    assert candidate.right_table == "orders"
    assert candidate.left_field == candidate.right_field == "customer_id"
    assert candidate.relation_type == "key_match"
    assert candidate.confidence >= 0.85
    assert candidate.can_auto_use is True
    assert candidate.requires_confirmation is False


def test_relationships_do_not_auto_use_similar_low_quality_keys(tmp_path):
    source = tmp_path / "ambiguous.xlsx"
    workbook = Workbook()
    left = workbook.active
    left.title = "left"
    left.append(["customer_id"])
    left.append([101])
    left.append([101])
    left.append([102])
    right = workbook.create_sheet("right")
    right.append(["customer-id"])
    right.append([101])
    right.append([103])
    right.append([103])
    workbook.save(source)

    from studio_api.profiling import profile_file
    from studio_api.relationships import discover_relationships

    candidates = discover_relationships([profile_file(source)])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.confidence < 0.85
    assert candidate.can_auto_use is False
    assert candidate.requires_confirmation is True


def test_batch_profiles_find_matching_unique_ids_in_independent_files(tmp_path):
    customers = tmp_path / "customers.csv"
    orders = tmp_path / "orders.csv"
    customers.write_text("customer_id,name\n101,A\n102,B\n", encoding="utf-8")
    orders.write_text("customer_id,order_value\n101,10\n102,20\n", encoding="utf-8")

    from studio_api.profiling import profile_files
    from studio_api.relationships import discover_relationships

    profiles = profile_files([customers, orders])
    candidates = discover_relationships(profiles)

    assert len(profiles) == 2
    assert {profile.file_hash for profile in profiles} == {
        hashlib.sha256(customers.read_bytes()).hexdigest(),
        hashlib.sha256(orders.read_bytes()).hexdigest(),
    }
    assert len(candidates) == 1
    assert candidates[0].can_auto_use is True
    assert candidates[0].left_source != candidates[0].right_source


def test_relationships_return_empty_when_no_normalized_name_or_value_overlap(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first.write_text("account_id\n101\n102\n", encoding="utf-8")
    second.write_text("device_code\n301\n302\n", encoding="utf-8")

    from studio_api.profiling import profile_files
    from studio_api.relationships import discover_relationships

    assert discover_relationships(profile_files([first, second])) == []


def test_relationships_do_not_merge_different_explicit_identifier_names(tmp_path):
    accounts = tmp_path / "accounts.csv"
    groups = tmp_path / "groups.csv"
    accounts.write_text("account_id\n101\n102\n", encoding="utf-8")
    groups.write_text("group_id\n101\n102\n", encoding="utf-8")

    from studio_api.profiling import profile_files
    from studio_api.relationships import discover_relationships

    assert discover_relationships(profile_files([accounts, groups])) == []


def test_non_identifier_field_with_id_substring_requires_confirmation(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first.write_text("paid_amount\n10\n20\n", encoding="utf-8")
    second.write_text("paid_amount\n10\n20\n", encoding="utf-8")

    from studio_api.profiling import profile_files
    from studio_api.relationships import discover_relationships

    profiles = profile_files([first, second])
    field = profiles[0].tables[0].columns[0]
    candidates = discover_relationships(profiles)

    assert field.semantic_role == "metric"
    assert len(candidates) == 1
    assert candidates[0].can_auto_use is False
    assert candidates[0].requires_confirmation is True


def test_plan_ranks_the_requested_dimension_and_metric(tmp_path):
    source = tmp_path / "orders.csv"
    frame = pd.DataFrame(
        {
            "product_name": ["A", "B", "A"],
            "sales_amount": [12, 20, 15],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.execution import execute_plan
    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    profile = profile_file(source)
    plan = build_plan(profile, "哪个产品销售额最高？")
    result = execute_plan({profile.tables[0].name: frame}, plan)

    assert plan.status == "READY"
    assert plan.operations == ("ranking",)
    assert plan.fields == {"dimension": "product_name", "metric": "sales_amount"}
    assert result.status == "SUCCESS"
    assert result.findings[0].value == "A"
    assert result.findings[0].metric_value == 27.0
    assert result.findings[0].evidence.calculation == "groupby(product_name).sum(sales_amount)"
    assert result.findings[0].evidence.source == {
        "file_hash": profile.file_hash,
        "table": profile.tables[0].name,
    }


def test_plan_matches_high_confidence_chinese_fields_from_the_question(tmp_path):
    source = tmp_path / "orders-cn.csv"
    frame = pd.DataFrame(
        {
            "产品": ["A", "B", "A"],
            "销售额": [12, 20, 15],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    plan = build_plan(profile_file(source), "哪个产品销售额最高？")

    assert plan.status == "READY"
    assert plan.operations == ("ranking",)
    assert plan.fields == {"dimension": "产品", "metric": "销售额"}


def test_plan_builds_composite_chinese_metric_analysis_from_one_profiled_table(tmp_path):
    source = tmp_path / "monthly-finance.csv"
    frame = pd.DataFrame(
        {
            "期间": ["2025-01", "2025-02", "2025-03"],
            "营业收入（万元）": [100, 120, 90],
            "毛利（万元）": [30, 36, 18],
            "营业利润（万元）": [15, 18, 6],
            "备注": ["正常", "正常", "需求回落"],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.planning import CompositeAnalysisPlan, build_plan
    from studio_api.profiling import profile_file

    plan = build_plan(
        profile_file(source),
        "按期间分析营业收入、毛利率和营业利润趋势，指出异常期间及可能原因，并引用备注证据。",
    )

    assert isinstance(plan, CompositeAnalysisPlan)
    assert plan.table == "monthly-finance"
    assert plan.time_field == "期间"
    assert plan.operations == ("trend", "anomaly", "reason_evidence")
    assert len(plan.metrics) == 3
    assert not hasattr(plan, "metric")
    assert [(metric.name, metric.kind, metric.fields) for metric in plan.metrics] == [
        ("营业收入", "direct", {"metric": "营业收入（万元）"}),
        ("毛利率", "ratio", {"numerator": "毛利（万元）", "denominator": "营业收入（万元）"}),
        ("营业利润", "direct", {"metric": "营业利润（万元）"}),
    ]
    assert plan.metrics[1].formula == "sum(毛利（万元）) / sum(营业收入（万元）)"


def test_ranking_evidence_excludes_rows_rejected_by_numeric_conversion(tmp_path):
    source = tmp_path / "orders-with-invalid-value.csv"
    frame = pd.DataFrame(
        {
            "product_name": ["A", "A", "A", "A", "A", "B", "B", "B", "B", "B"],
            "sales_amount": [12, "invalid", 15, 0, 0, 20, 1, 1, 1, 1],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.execution import execute_plan
    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    profile = profile_file(source)
    plan = build_plan(profile, "哪个产品销售额最高？")
    result = execute_plan({profile.tables[0].name: frame}, plan)

    assert result.status == "SUCCESS"
    assert result.findings[0].value == "A"
    assert result.findings[0].metric_value == 27.0
    assert result.findings[0].evidence.row_indices == (0, 2, 3, 4)


def test_prediction_without_a_time_field_returns_insufficient_data(tmp_path):
    source = tmp_path / "orders.csv"
    frame = pd.DataFrame(
        {
            "product_name": ["A", "B", "A"],
            "sales_amount": [12, 20, 15],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.execution import execute_plan
    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    profile = profile_file(source)
    plan = build_plan(profile, "预测 sales_amount 未来趋势")
    result = execute_plan({profile.tables[0].name: frame}, plan)

    assert plan.status == "INSUFFICIENT_DATA"
    assert plan.operations == ("forecast",)
    assert plan.fields == {"metric": "sales_amount"}
    assert any("时间字段" in limitation for limitation in plan.limitations)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.findings == ()


def test_generic_anomaly_question_returns_the_outlier_with_row_evidence(tmp_path):
    source = tmp_path / "measurements.csv"
    frame = pd.DataFrame(
        {
            "observed_at": pd.date_range("2025-01-01", periods=5).astype(str),
            "measure_x": [10, 11, 10, 12, 100],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.execution import execute_plan
    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    profile = profile_file(source)
    plan = build_plan(profile, "measure_x 有哪些异常值？")
    result = execute_plan({profile.tables[0].name: frame}, plan)

    assert plan.status == "READY"
    assert plan.operations == ("anomaly",)
    assert plan.fields == {"metric": "measure_x", "time": "observed_at"}
    assert result.status == "SUCCESS"
    assert result.findings[0].value == 100.0
    assert result.findings[0].evidence.calculation == "iqr_outliers(measure_x, k=1.5)"
    assert result.findings[0].evidence.row_indices == (4,)


def test_anomaly_without_optional_context_returns_partial_finding(tmp_path):
    source = tmp_path / "measurements.csv"
    frame = pd.DataFrame({"measure_x": [10, 11, 10, 12, 100]})
    frame.to_csv(source, index=False)

    from studio_api.execution import execute_plan
    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    profile = profile_file(source)
    plan = build_plan(profile, "measure_x 有哪些异常值？")
    result = execute_plan({profile.tables[0].name: frame}, plan)

    assert plan.status == "PARTIAL"
    assert any("上下文字段" in limitation for limitation in plan.limitations)
    assert result.status == "PARTIAL"
    assert result.findings[0].value == 100.0


def test_low_confidence_fields_are_not_used_for_a_ranking(tmp_path):
    source = tmp_path / "single-order.csv"
    frame = pd.DataFrame({"product_name": ["A"], "sales_amount": [12]})
    frame.to_csv(source, index=False)

    from studio_api.execution import execute_plan
    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    profile = profile_file(source)
    plan = build_plan(profile, "哪个产品销售额最高？")
    result = execute_plan({profile.tables[0].name: frame}, plan)

    assert plan.status == "INSUFFICIENT_DATA"
    assert plan.fields == {}
    assert any("置信度" in limitation for limitation in plan.limitations)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.findings == ()


def test_question_terms_select_the_requested_metric_among_profile_candidates(tmp_path):
    source = tmp_path / "orders.csv"
    frame = pd.DataFrame(
        {
            "product_name": ["A", "B", "A"],
            "sales_amount": [12, 20, 15],
            "unit_cost": [4, 7, 5],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    plan = build_plan(profile_file(source), "哪个产品销售额最高？")

    assert plan.status == "READY"
    assert plan.fields == {"dimension": "product_name", "metric": "sales_amount"}


def test_sales_volume_question_does_not_use_a_sales_amount_field(tmp_path):
    source = tmp_path / "orders.csv"
    frame = pd.DataFrame(
        {
            "product_name": ["A", "B", "A"],
            "sales_amount": [12, 20, 15],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    plan = build_plan(profile_file(source), "哪个产品销量最高？")

    assert plan.status == "INSUFFICIENT_DATA"
    assert plan.fields == {"dimension": "product_name"}


def test_question_terms_do_not_fall_back_to_unrequested_business_fields(tmp_path):
    source = tmp_path / "regional.csv"
    frame = pd.DataFrame(
        {
            "month": ["2025-01-01", "2025-02-01", "2025-03-01"],
            "region": ["north", "south", "north"],
            "revenue": [12, 20, 15],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    plan = build_plan(profile_file(source), "哪个产品利润最高？")

    assert plan.status == "INSUFFICIENT_DATA"
    assert plan.fields == {}


def test_generic_trend_uses_the_profile_selected_time_and_metric(tmp_path):
    source = tmp_path / "series.csv"
    frame = pd.DataFrame(
        {
            "dt": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "value_x": [3, 5, 4],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.execution import execute_plan
    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    profile = profile_file(source)
    plan = build_plan(profile, "value_x 随 dt 的趋势如何？")
    result = execute_plan({profile.tables[0].name: frame}, plan)

    assert plan.fields == {"time": "dt", "metric": "value_x"}
    assert result.status == "SUCCESS"
    assert result.findings[0].value == [
        {"time": "2025-01-01", "value": 3.0},
        {"time": "2025-01-02", "value": 5.0},
        {"time": "2025-01-03", "value": 4.0},
    ]
    assert result.findings[0].evidence.calculation == "groupby(dt).sum(value_x).sort_index()"


def test_generic_group_comparison_uses_mean_by_requested_dimension(tmp_path):
    source = tmp_path / "scores.csv"
    frame = pd.DataFrame(
        {
            "cohort": ["blue", "blue", "red", "red"],
            "score_value": [8, 12, 15, 25],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.execution import execute_plan
    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    profile = profile_file(source)
    plan = build_plan(profile, "比较 cohort 的 score_value 差异")
    result = execute_plan({profile.tables[0].name: frame}, plan)

    assert plan.operations == ("group_comparison",)
    assert plan.fields == {"dimension": "cohort", "metric": "score_value"}
    assert result.findings[0].value == [
        {"group": "red", "value": 20.0},
        {"group": "blue", "value": 10.0},
    ]
    assert result.findings[0].evidence.calculation == "groupby(cohort).mean(score_value)"


def test_generic_correlation_uses_two_requested_metrics(tmp_path):
    source = tmp_path / "paired.csv"
    frame = pd.DataFrame(
        {
            "value_x": [1, 2, 3, 4],
            "value_y": [2, 4, 6, 8],
        }
    )
    frame.to_csv(source, index=False)

    from studio_api.execution import execute_plan
    from studio_api.planning import build_plan
    from studio_api.profiling import profile_file

    profile = profile_file(source)
    plan = build_plan(profile, "value_x 与 value_y 是否相关？")
    result = execute_plan({profile.tables[0].name: frame}, plan)

    assert plan.operations == ("correlation",)
    assert plan.fields == {"metric": "value_x", "secondary_metric": "value_y"}
    assert result.findings[0].value == 1.0
    assert result.findings[0].evidence.calculation == "pearson_correlation(value_x, value_y)"


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


def test_dataset_upload_serializes_excel_datetime_profile_values():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "dated_metrics"
    sheet.append(["observed_at", "measure_x"])
    sheet.append([datetime(2025, 1, 1), 10])
    sheet.append([datetime(2025, 2, 1), 20])
    buffer = BytesIO()
    workbook.save(buffer)

    response = client.post(
        "/api/datasets",
        files={"file": ("dated-metrics.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 201
    profile = response.json()["intake"]["profile"]
    assert profile["tables"][0]["columns"][0]["samples"] == ["2025-01-01T00:00:00", "2025-02-01T00:00:00"]


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


def test_excel_job_returns_generic_findings_and_reports():
    create = client.post(
        "/api/jobs",
        data={"objective": "哪个 region 的 revenue 最高？"},
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
    assert result["validation_status"] == "SUCCESS"
    assert result["analysis"]["kind"] == "structured_analysis"
    assert result["findings"][0]["evidence"]["calculation"] == "groupby(region).sum(revenue)"
    assert result["findings"][0]["evidence"]["source"]["file_hash"]
    assert {report["format"] for report in result["reports"]} == {"markdown", "html", "docx"}

    markdown_report = next(report for report in result["reports"] if report["format"] == "markdown")
    markdown = client.get(markdown_report["download_url"]).text
    assert markdown.index("## 核心结论") < markdown.index("## 数据质量与分析限制")
    assert "groupby" not in markdown

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


def test_financial_anomaly_keeps_the_decline_and_grounds_its_reason_in_workbook_fields(tmp_path):
    frame = pd.DataFrame(
        {
            "期间": ["2025-01", "2025-02", "2025-03", "2025-04"],
            "销量（件）": [970, 1000, 841, 1068],
            "含税单价（元）": [100, 100, 100, 100],
            "营业收入（万元）": [97, 100, 84.1, 106.8],
            "毛利（万元）": [29.1, 30, 25.23, 32.04],
            "营业利润（万元）": [14.55, 15, 12.51, 15.95],
            "备注": ["正常经营", "正常经营", "需求回落：销量下滑", "正常经营"],
        }
    )

    result = analyse_spreadsheet(frame, "分析 2025-01 到 2025-04 的营业收入、毛利率和营业利润趋势，指出异常月份及可能原因", tmp_path)
    anomaly_text = " ".join(item["text"] for section in result["sections"] if section["title"] == "异常对象" for item in section["items"])
    answer_text = f"{result['core_conclusion']} {anomaly_text}"

    assert "2025-03" in answer_text
    assert "营业收入（万元）" in answer_text and "环比下降 15.9%" in answer_text
    assert "营业利润（万元）" in answer_text and "环比下降 16.6%" in answer_text
    assert "备注“需求回落：销量下滑”" in answer_text
    assert "销量（件）从 1,000 到 841，环比下降 15.9%" in answer_text
    assert "含税单价（元）从 100 到 100，环比稳定 0.0%" in answer_text
    assert "数据未提供客户、价格或业务事件字段" not in answer_text


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


def test_multi_metric_explanation_preserves_a_small_declining_margin(tmp_path):
    frame = pd.DataFrame(
        {
            "期间": ["2025-01", "2025-02", "2025-03", "2025-04"],
            "营业收入": [100, 101, 102, 129.54],
            "毛利额": [30, 30.3, 30.6, 38.842569],
            "营业利润": [15, 15.1, 15.2, 19.38],
        }
    )

    result = analyse_spreadsheet(frame, "分析 2025-01 到 2025-04 的营业收入、毛利率和营业利润趋势，指出异常月份及可能原因", tmp_path)

    assert "毛利率 环比下降 0.05%" in result["core_conclusion"]
    assert "营业收入与营业利润同向，毛利率下降" in result["core_conclusion"]
    assert "毛利率稳定" not in result["core_conclusion"]


def test_multi_metric_explanation_preserves_a_tiny_declining_margin(tmp_path):
    frame = pd.DataFrame(
        {
            "期间": ["2025-01", "2025-02", "2025-03", "2025-04"],
            "营业收入": [100, 101, 102, 129.54],
            "毛利额": [30, 30.3, 30.6, 38.86044552],
            "营业利润": [15, 15.1, 15.2, 19.38],
        }
    )

    result = analyse_spreadsheet(frame, "分析 2025-01 到 2025-04 的营业收入、毛利率和营业利润趋势，指出异常月份及可能原因", tmp_path)

    assert "毛利率 环比下降 0.004%" in result["core_conclusion"]
    assert "营业收入与营业利润同向，毛利率下降" in result["core_conclusion"]
    assert "毛利率 环比下降 0.00%" not in result["core_conclusion"]
    assert "毛利率稳定" not in result["core_conclusion"]


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
    assert result["validation_status"] == "SUCCESS"
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
    assert analyzed.json()["validation_status"] == "SUCCESS"
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


def test_generic_anomaly_response_keeps_executor_evidence():
    result = analyse_uploaded("检测地区营收异常风险")

    assert result["status"] == "succeeded"
    assert result["validation_status"] == "SUCCESS"
    assert result["findings"]
    assert result["findings"][0]["evidence"]["calculation"] == "iqr_outliers(revenue, k=1.5)"
    assert result["findings"][0]["evidence"]["output_value"] == result["findings"][0]["value"]


def test_generic_trend_response_contains_only_traceable_conclusions():
    result = analyse_uploaded("analysis revenue trend")

    assert result["status"] == "succeeded"
    assert result["validation_status"] == "SUCCESS"
    assert result["analysis"]["plan"]["operations"] == ["trend"]
    assert result["findings"][0]["evidence"]["calculation"] == "groupby(month).sum(revenue).sort_index()"


def test_unsupported_forecast_is_reported_as_insufficient_data():
    result = analyse_uploaded("预测未来营收")

    assert result["status"] == "succeeded"
    assert result["validation_status"] == "INSUFFICIENT_DATA"
    assert result["findings"] == []
    assert any("forecast" in limitation for limitation in result["limitations"])


def test_generic_answer_is_derived_from_validated_findings():
    result = analyse_uploaded("检测地区营收异常风险")

    assert result["core_conclusion"] != result["data_quality"]["summary"]
    assert result["core_conclusion"] == result["answer"]
    assert result["answer"] == "；".join(item["conclusion"] for item in result["findings"])


def test_generic_trend_uses_the_same_source_for_all_evidence():
    result = analyse_uploaded("分析地区营收趋势", missing_south_march=True)

    assert result["status"] == "succeeded"
    assert result["validation_status"] == "SUCCESS"
    assert all(item["source"]["table"] == "regional revenue" for item in result["evidence"])


def test_forecast_does_not_invent_numeric_output_before_executor_support_exists():
    result = analyse_uploaded("预测未来营收")
    assert result["status"] == "succeeded"
    assert result["validation_status"] == "INSUFFICIENT_DATA"
    assert not result["evidence"]


def test_generic_ranking_answers_the_executor_leader():
    result = analyse_uploaded("哪个地区表现最好？")

    assert "east" in result["core_conclusion"].lower()
    assert result["findings"][0]["metric_value"] == 1429.0
    assert result["findings"][0]["evidence"]["calculation"] == "groupby(region).sum(revenue)"


def test_generic_result_does_not_claim_a_chart_when_no_chart_executor_exists():
    anomaly = analyse_uploaded("检测地区营收异常风险")
    forecast = analyse_uploaded("预测未来营收")

    assert anomaly["charts"] == []
    assert forecast["charts"] == []


def test_future_question_preserves_unsupported_operation_as_a_limitation():
    result = analyse_uploaded("哪些地区未来可能继续下滑")

    assert result["analysis"]["plan"]["operations"] == ["forecast"]
    assert result["status"] == "succeeded"
    assert result["validation_status"] == "INSUFFICIENT_DATA"
    assert any("forecast" in limitation for limitation in result["limitations"])


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
    assert response.json()["status"] == "succeeded"
    assert response.json()["validation_status"] == "INSUFFICIENT_DATA"
    assert "metric" in response.json()["core_conclusion"]
