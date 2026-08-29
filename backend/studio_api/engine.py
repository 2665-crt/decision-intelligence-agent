from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
from docx import Document

from .intake import read_spreadsheet


HIGH_REVIEW_TERMS = ("医疗", "病", "法律", "合同", "金融", "贷款", "化工", "施工安全", "安全事故")


def run(job: dict, directory: Path) -> dict:
    source = next(directory.glob("source.*"))
    if job["intake"]["kind"] == "document":
        result = analyse_document(source, job["objective"])
    else:
        result = analyse_spreadsheet(source, job["objective"], directory)
    result["status"] = "succeeded"
    return result


def analyse_spreadsheet(source: Path, objective: str, directory: Path) -> dict:
    frame = read_spreadsheet(source)
    numeric_columns = frame.select_dtypes(include="number").columns.tolist()
    numeric_summary = {
        str(column): {
            "count": int(frame[column].count()),
            "missing": int(frame[column].isna().sum()),
            "mean": round(float(frame[column].mean()), 4),
            "min": float(frame[column].min()),
            "max": float(frame[column].max()),
        }
        for column in numeric_columns
    }
    quality = {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "duplicate_rows": int(frame.duplicated().sum()),
        "missing_cells": int(frame.isna().sum().sum()),
    }
    evidence = [
        {"level": "data_fact", "summary": f"数据集包含 {quality['rows']} 行、{quality['columns']} 列，缺失单元格 {quality['missing_cells']} 个。"}
    ]
    for column, summary in numeric_summary.items():
        evidence.append({"level": "data_fact", "summary": f"{column} 的范围为 {summary['min']} 至 {summary['max']}，均值为 {summary['mean']}。"})

    charts = build_charts(frame, directory)
    forecast = build_forecast(frame, objective)
    risks = build_risks(objective, quality, forecast)
    return {
        "analysis": {"kind": "spreadsheet_analysis", "numeric_summary": numeric_summary, "quality": quality},
        "charts": charts,
        "forecast": forecast,
        "evidence": evidence,
        "risks": risks,
        "options": build_options(objective, risks),
        "limitations": ["结论仅基于本次上传的数据；相关性和趋势不能单独证明因果关系。"],
    }


def build_charts(frame: pd.DataFrame, directory: Path) -> list[dict]:
    charts_dir = directory / "charts"
    charts_dir.mkdir(exist_ok=True)
    number_columns = frame.select_dtypes(include="number").columns.tolist()
    if not number_columns:
        return []
    x_column = next((column for column in frame.columns if "date" in str(column).lower() or "month" in str(column).lower() or "时间" in str(column)), frame.index.name)
    if x_column is None or x_column not in frame.columns:
        plot_frame = frame.reset_index(names="row")
        x_column = "row"
    else:
        plot_frame = frame
    target = number_columns[0]
    chart_path = charts_dir / "trend.html"
    px.line(plot_frame, x=x_column, y=target, title=f"{target} 趋势").write_html(chart_path, include_plotlyjs="cdn")
    return [{"title": f"{target} 趋势", "path": "charts/trend.html", "download_url": f"/api/jobs/{{job_id}}/files/charts/trend.html"}]


def build_forecast(frame: pd.DataFrame, objective: str) -> dict | None:
    if not any(term in objective.lower() for term in ("预测", "forecast", "预估")):
        return None
    time_column = next((column for column in frame.columns if any(term in str(column).lower() for term in ("date", "month", "time", "日期", "时间"))), None)
    targets = frame.select_dtypes(include="number").columns.tolist()
    if time_column is None or not targets or len(frame) < 8:
        return {"is_recommended": False, "limitations": ["未找到足够的时间列、数值目标列或历史观测，不能进行可靠预测。"]}
    series = pd.to_numeric(frame[targets[-1]], errors="coerce").dropna().astype(float).to_numpy()
    horizon = min(3, max(1, len(series) // 4))
    train, test = series[:-horizon], series[-horizon:]
    baseline = np.repeat(train[-1], horizon)
    x = np.arange(len(train))
    candidate = np.polyval(np.polyfit(x, train, 1), np.arange(len(train), len(train) + horizon))
    baseline_mae = float(np.mean(np.abs(test - baseline)))
    candidate_mae = float(np.mean(np.abs(test - candidate)))
    recommended = candidate_mae < baseline_mae
    chosen = candidate if recommended else baseline
    residual = float(np.std(test - chosen)) if len(test) > 1 else 0.0
    future = np.polyval(np.polyfit(np.arange(len(series)), series, 1), np.arange(len(series), len(series) + horizon)) if recommended else np.repeat(series[-1], horizon)
    return {
        "time_column": str(time_column),
        "target_column": str(targets[-1]),
        "model": "linear_trend" if recommended else "naive_baseline",
        "is_recommended": recommended,
        "baseline_mae": round(baseline_mae, 4),
        "candidate_mae": round(candidate_mae, 4),
        "prediction_interval_80": [
            {"step": index + 1, "value": round(float(value), 4), "lower": round(float(value - 1.28 * residual), 4), "upper": round(float(value + 1.28 * residual), 4)}
            for index, value in enumerate(future)
        ],
        "limitations": [] if recommended else ["候选趋势模型没有优于朴素基线，结果仅保留基线作为参考。"],
    }


def build_risks(objective: str, quality: dict, forecast: dict | None) -> list[dict]:
    review_required = any(term in objective for term in HIGH_REVIEW_TERMS)
    risks = [{
        "title": "结论适用范围",
        "level": "medium",
        "evidence": ["本报告只分析已上传的数据，缺少外部对照与业务背景。"],
        "human_review_required": review_required,
        "mitigation": "在执行方案前由业务负责人核对数据口径、约束和影响对象。",
    }]
    if quality["missing_cells"] or quality["duplicate_rows"]:
        risks.append({
            "title": "数据质量风险",
            "level": "high" if quality["missing_cells"] else "medium",
            "evidence": [f"检测到 {quality['missing_cells']} 个缺失单元格、{quality['duplicate_rows']} 行重复记录。"],
            "human_review_required": review_required,
            "mitigation": "先确认缺失和重复的业务含义，再用修正后的数据复跑分析。",
        })
    if forecast is not None:
        risks.append({
            "title": "预测不确定性",
            "level": "medium",
            "evidence": ["预测使用留出集误差与 80% 区间，不能覆盖突发政策、市场或操作变化。"],
            "human_review_required": review_required,
            "mitigation": "将预测作为监测阈值，按新数据滚动复核，不作为自动决策依据。",
        })
    return risks


def build_options(objective: str, risks: list[dict]) -> list[dict]:
    options = [
        {"name": "验证后小范围试点", "expected_benefit": "在控制暴露的前提下验证分析结论", "cost": "中", "potential_harm": "低", "next_step": "选取代表性样本，预先定义成功指标和停止条件。"},
        {"name": "维持现状并补充数据", "expected_benefit": "避免在证据不足时扩大影响", "cost": "低", "potential_harm": "低", "next_step": "补齐关键字段和外部约束后再进行复评。"},
        {"name": "直接全面推广", "expected_benefit": "可能更快获得规模效益", "cost": "高", "potential_harm": "高", "next_step": "仅在负责人完成风险复核并接受剩余不确定性时考虑。"},
    ]
    return options


def analyse_document(source: Path, objective: str) -> dict:
    document = Document(source)
    statements = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    evidence = [{"level": "document_statement", "summary": f"文档陈述：{statement}"} for statement in statements[:10]]
    risks = [{
        "title": "文档主张待核验",
        "level": "medium",
        "evidence": ["DOCX 内容为文本陈述，不等同于测量数据或已验证事实。"],
        "human_review_required": any(term in objective for term in HIGH_REVIEW_TERMS),
        "mitigation": "将关键主张映射到原始数据、责任人或审计证据后再决策。",
    }]
    return {
        "analysis": {"kind": "document_review", "statement_count": len(statements)},
        "charts": [],
        "forecast": None,
        "evidence": evidence or [{"level": "document_statement", "summary": "文档没有可提取的段落文本。"}],
        "risks": risks,
        "options": build_options(objective, risks),
        "limitations": ["文档审阅不验证文本中的数字或事实；需要提供原始数据才能做统计推断。"],
    }
