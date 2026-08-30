from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .questioning import QuestionPlan, normalise_label, plan_question


def analyse_spreadsheet(frame: pd.DataFrame, objective: str, directory: Path) -> dict:
    plan = plan_question(frame, objective)
    answer = build_question_answer(frame, plan, directory)
    missing = validate_answer_completeness(answer, plan)
    if missing:
        raise ValueError("；".join(missing))
    return answer


def build_question_answer(frame: pd.DataFrame, plan: QuestionPlan, directory: Path) -> dict:
    if len(plan.metric_columns) > 1:
        return _build_multi_metric_answer(frame, plan, directory)
    quality = _quality(frame)
    analysis_frame = frame.drop_duplicates().copy()
    series = _series_by_dimension(analysis_frame, plan)
    summaries = _dimension_summaries(series)
    anomaly = _largest_anomaly(series)
    forecast = _forecast(series, plan)
    business_risks = _business_risks(summaries, plan)
    sections = _sections(plan, summaries, anomaly, forecast, business_risks)
    limitations = _analysis_limitations(plan, forecast)
    data_quality = {**quality, "summary": f"{quality['rows']} 行、{quality['columns']} 列；缺失 {quality['missing_cells']} 个单元格，重复 {quality['duplicate_rows']} 行。", "limitations": _quality_limitations(frame, plan, quality)}
    core_conclusion = _core_conclusion(summaries, anomaly, forecast, business_risks, limitations, plan)
    if data_quality["limitations"]:
        core_conclusion += f" 数据限制：{data_quality['limitations'][0]}"
    charts = _charts(series, plan, forecast, directory)
    answer = {
        "analysis": {"kind": "question_driven_spreadsheet_analysis", "numeric_summary": _numeric_summary(analysis_frame), "quality": quality, "plan": {"types": list(plan.types), "time_column": plan.time_column, "metric_column": plan.metric_column, "dimension_column": plan.dimension_column}},
        "core_conclusion": core_conclusion,
        "key_metrics": _key_metrics(summaries, anomaly, forecast, business_risks),
        "sections": sections,
        "business_risks": business_risks,
        "data_quality": data_quality,
        "charts": charts,
        "forecast": forecast,
        "limitations": limitations,
    }
    evidence = [{"level": "analysis", "summary": item["text"]} for section in sections for item in section["items"]]
    suggestions = _suggestions(business_risks, anomaly)
    return answer | {"evidence": evidence, "risks": business_risks, "options": suggestions, "suggestions": suggestions}


def _build_multi_metric_answer(frame: pd.DataFrame, plan: QuestionPlan, directory: Path) -> dict:
    quality = _quality(frame)
    analysis_frame = frame.drop_duplicates().copy()
    series = _monthly_metric_series(analysis_frame, plan)
    summaries = _metric_summaries(series)
    anomalies = _metric_anomalies(series)
    anomaly = _largest_metric_anomaly(anomalies)
    sections = _multi_metric_sections(plan, series, summaries, anomalies)
    data_quality = {
        **quality,
        "summary": f"{quality['rows']} 行、{quality['columns']} 列；缺失 {quality['missing_cells']} 个单元格，重复 {quality['duplicate_rows']} 行。",
        "limitations": _quality_limitations(frame, plan, quality),
    }
    core_conclusion = _multi_metric_conclusion(plan, series, summaries, anomalies, data_quality["limitations"])
    charts = _multi_metric_charts(series, anomalies, directory)
    answer = {
        "analysis": {
            "kind": "question_driven_spreadsheet_analysis",
            "numeric_summary": _numeric_summary(analysis_frame),
            "quality": quality,
            "plan": {
                "types": list(plan.types),
                "time_column": plan.time_column,
                "metric_column": plan.metric_column,
                "metric_columns": list(plan.metric_columns),
                "dimension_column": plan.dimension_column,
                "period_start": _period(plan.period_start) if plan.period_start is not None else None,
                "period_end": _period(plan.period_end) if plan.period_end is not None else None,
            },
        },
        "core_conclusion": core_conclusion,
        "key_metrics": _multi_metric_key_metrics(summaries, anomalies),
        "sections": sections,
        "business_risks": [],
        "data_quality": data_quality,
        "charts": charts,
        "forecast": None,
        "limitations": [],
    }
    evidence = [{"level": "analysis", "summary": item["text"]} for section in sections for item in section["items"]]
    suggestions = _suggestions([], anomaly)
    return answer | {"evidence": evidence, "risks": [], "options": suggestions, "suggestions": suggestions}


def _monthly_metric_series(frame: pd.DataFrame, plan: QuestionPlan) -> pd.DataFrame:
    if plan.time_column is None:
        return pd.DataFrame(columns=["period", "metric", "value"])
    working = frame.copy()
    working["period"] = pd.to_datetime(working[plan.time_column], errors="coerce").dt.to_period("M").dt.to_timestamp()
    working = working.dropna(subset=["period"])
    if plan.period_start is not None:
        working = working.loc[working["period"] >= plan.period_start]
    if plan.period_end is not None:
        working = working.loc[working["period"] <= plan.period_end]
    series: list[pd.DataFrame] = []
    for metric in plan.metric_columns:
        revenue_column = _column_by_normalised_name(working.columns, "营业收入")
        gross_profit_column = _column_by_normalised_name(working.columns, "毛利", "毛利额")
        if metric == "毛利率" and revenue_column and gross_profit_column:
            totals = working.assign(
                _revenue=pd.to_numeric(working[revenue_column], errors="coerce"),
                _gross_profit=pd.to_numeric(working[gross_profit_column], errors="coerce"),
            ).groupby("period", as_index=False)[["_revenue", "_gross_profit"]].sum(min_count=1)
            values = totals.assign(value=totals["_gross_profit"] / totals["_revenue"], metric=metric)[["period", "metric", "value"]]
        elif metric in working.columns:
            values = working.assign(value=pd.to_numeric(working[metric], errors="coerce")).dropna(subset=["value"]).groupby("period", as_index=False)["value"].sum()
            values["metric"] = metric
            values = values[["period", "metric", "value"]]
        else:
            continue
        series.append(values.replace([np.inf, -np.inf], np.nan).dropna(subset=["value"]))
    return pd.concat(series, ignore_index=True).sort_values(["metric", "period"]) if series else pd.DataFrame(columns=["period", "metric", "value"])


def _column_by_normalised_name(columns: pd.Index, *names: str) -> str | None:
    return next((str(column) for column in columns if normalise_label(str(column)) in names), None)


def _metric_summaries(series: pd.DataFrame) -> list[dict]:
    summaries = []
    for metric, group in series.groupby("metric", sort=False):
        group = group.sort_values("period")
        if group.empty:
            continue
        first, last = float(group.iloc[0]["value"]), float(group.iloc[-1]["value"])
        change = _percent_change(last, first)
        summaries.append({"metric": metric, "first": first, "last": last, "change_pct": change, "direction": "上升" if change > 3 else "下降" if change < -3 else "稳定", "period_start": _period(group.iloc[0]["period"]), "period_end": _period(group.iloc[-1]["period"])})
    return summaries


def _metric_anomalies(series: pd.DataFrame) -> list[dict]:
    anomalies = []
    for metric, group in series.groupby("metric", sort=False):
        group = group.sort_values("period").copy()
        group["change_pct"] = group["value"].pct_change() * 100
        changes = group.dropna(subset=["change_pct"])
        if changes.empty:
            continue
        point = changes.loc[changes["change_pct"].abs().idxmax()]
        threshold = max(10.0, float(changes["change_pct"].abs().median() + 2 * changes["change_pct"].abs().std(ddof=0)))
        if abs(float(point["change_pct"])) < threshold:
            continue
        anomalies.append({"metric": metric, "period": _period(point["period"]), "value": float(point["value"]), "change_pct": round(float(point["change_pct"]), 1)})
    return anomalies


def _largest_metric_anomaly(anomalies: list[dict]) -> dict | None:
    return max(anomalies, key=lambda item: abs(item["change_pct"])) if anomalies else None


def _multi_metric_sections(plan: QuestionPlan, series: pd.DataFrame, summaries: list[dict], anomalies: list[dict]) -> list[dict]:
    sections = []
    if "trend" in plan.types:
        sections.append({"title": "趋势分析", "items": [{"text": f"{item['metric']} 在 {item['period_start']} 至 {item['period_end']} 呈{item['direction']}趋势：{_number(item['first'])} 至 {_number(item['last'])}，累计变化 {item['change_pct']:.1f}%。"} for item in summaries]})
    if "anomaly" in plan.types:
        revenue_anomaly = _financial_metric_item(anomalies, "营业收入")
        reason = _multi_metric_reason(series, revenue_anomaly["period"], plan.metric_columns) if revenue_anomaly else ""
        items = []
        for item in anomalies:
            text = f"{item['metric']} 的最大月度异常为 {item['period']}：当月 {_number(item['value'])}，环比{'下降' if item['change_pct'] < 0 else '上升'} {abs(item['change_pct']):.1f}%。"
            if revenue_anomaly is item and reason:
                text += f" 可能原因：{reason}"
            items.append({"text": text})
        sections.append({"title": "异常对象", "items": items or [{"text": "未识别到超过阈值的异常月份。"}]})
    return sections or [{"title": "关键指标", "items": [{"text": f"{item['metric']} 最新值 {_number(item['last'])}，累计变化 {item['change_pct']:.1f}%。"} for item in summaries]}]


def _multi_metric_conclusion(plan: QuestionPlan, series: pd.DataFrame, summaries: list[dict], anomalies: list[dict], quality_limitations: list[str]) -> str:
    summary_by_metric = {item["metric"]: item for item in summaries}
    anomaly_by_metric = {item["metric"]: item for item in anomalies}
    statements = []
    for metric in plan.metric_columns:
        summary = summary_by_metric.get(metric)
        if summary is None:
            continue
        statement = f"{metric} 在 {summary['period_start']} 至 {summary['period_end']} 呈{summary['direction']}趋势，从 {_number(summary['first'])} 到 {_number(summary['last'])}，累计变化 {summary['change_pct']:.1f}%"
        anomaly = anomaly_by_metric.get(metric)
        if anomaly:
            statement += f"；最大月度异常为 {anomaly['period']}，当月 {_number(anomaly['value'])}，环比{'下降' if anomaly['change_pct'] < 0 else '上升'} {abs(anomaly['change_pct']):.1f}%"
        statements.append(statement + "。")
    revenue_anomaly = _financial_metric_item(anomalies, "营业收入")
    if revenue_anomaly and all(_financial_metric_item(summaries, metric) for metric in ("营业收入", "毛利率", "营业利润")):
        reason = _multi_metric_reason(series, revenue_anomaly["period"], plan.metric_columns)
        if reason:
            statements.append(f"{revenue_anomaly['period']} 的指标联动显示：{_linked_metric_changes(series, revenue_anomaly['period'], plan.metric_columns)}；{reason}")
    if not statements:
        return "未找到可用于计算的数值指标，无法给出对象级结论。"
    return " ".join(statements)


def _financial_metric_item(items: list[dict], metric: str) -> dict | None:
    return next((item for item in items if normalise_label(item["metric"]) == metric), None)


def _linked_metric_changes(series: pd.DataFrame, period: str, metric_columns: tuple[str, ...]) -> str:
    changes = _linked_metric_change_values(series, period)
    return "、".join(f"{metric} 环比{'下降' if changes[metric] < 0 else '上升'} {abs(changes[metric]):.1f}%" for metric in metric_columns if metric in changes)


def _linked_metric_change_values(series: pd.DataFrame, period: str) -> dict[str, float]:
    changes = {}
    for metric, group in series.groupby("metric", sort=False):
        group = group.sort_values("period").copy()
        group["change_pct"] = group["value"].pct_change() * 100
        point = group.loc[group["period"].astype(str).str.startswith(period)]
        if not point.empty and pd.notna(point.iloc[0]["change_pct"]):
            changes[metric] = float(point.iloc[0]["change_pct"])
    return changes


def _multi_metric_reason(series: pd.DataFrame, period: str, metric_columns: tuple[str, ...]) -> str:
    changes = _linked_metric_change_values(series, period)
    revenue = _financial_metric_change(changes, "营业收入")
    margin = _financial_metric_change(changes, "毛利率")
    profit = _financial_metric_change(changes, "营业利润")
    if revenue is None or margin is None or profit is None:
        return "数据未提供足够的同期指标，无法判断联动原因。"
    same_direction = (revenue >= 0 and profit >= 0) or (revenue <= 0 and profit <= 0)
    if same_direction and margin >= -1:
        return "三项同向，毛利率稳定或略升，收入规模变化主导营业利润变化的可能性较高。数据未提供客户、价格或业务事件字段，不能进一步归因。"
    if same_direction:
        return "营业收入与营业利润同向，但毛利率下滑，收入规模变化与盈利效率变化共同影响营业利润的可能性较高。数据未提供客户、价格或业务事件字段，不能进一步归因。"
    if margin < -1:
        return "营业收入与营业利润反向且毛利率下滑，盈利效率变化与营业利润变化相关。数据未提供客户、价格或业务事件字段，不能进一步归因。"
    return "营业收入与营业利润反向，三项指标未呈同向变化，当前数据只能确认指标联动，不能进一步归因。"


def _financial_metric_change(changes: dict[str, float], metric: str) -> float | None:
    return next((change for name, change in changes.items() if normalise_label(name) == metric), None)


def _multi_metric_key_metrics(summaries: list[dict], anomalies: list[dict]) -> list[dict]:
    anomaly_by_metric = {item["metric"]: item for item in anomalies}
    return [{"label": item["metric"], "value": _number(item["last"]), "detail": f"{item['period_start']} 至 {item['period_end']} 累计{item['direction']} {abs(item['change_pct']):.1f}%；最大异常 {anomaly_by_metric[item['metric']]['period']} 环比 {anomaly_by_metric[item['metric']]['change_pct']:.1f}%" if item["metric"] in anomaly_by_metric else f"{item['period_start']} 至 {item['period_end']} 累计{item['direction']} {abs(item['change_pct']):.1f}%"} for item in summaries]


def _multi_metric_charts(series: pd.DataFrame, anomalies: list[dict], directory: Path) -> list[dict]:
    if series.empty:
        return []
    chart_path = directory / "charts" / "core-analysis.html"
    chart_path.parent.mkdir(exist_ok=True)
    figure = go.Figure()
    for metric, group in series.groupby("metric", sort=False):
        figure.add_trace(go.Scatter(x=group["period"], y=group["value"], mode="lines+markers", name=metric, yaxis="y2" if metric == "毛利率" else "y"))
    for anomaly in anomalies:
        point = series.loc[(series["metric"] == anomaly["metric"]) & (series["period"].astype(str).str.startswith(anomaly["period"]))]
        figure.add_trace(go.Scatter(x=point["period"], y=point["value"], mode="markers", marker={"color": "#c5443d", "size": 12, "symbol": "x"}, name=f"{anomaly['metric']}异常", yaxis="y2" if anomaly["metric"] == "毛利率" else "y"))
    figure.update_layout(title="多指标月度趋势与异常", yaxis={"title": "金额"}, yaxis2={"title": "毛利率", "overlaying": "y", "side": "right", "tickformat": ".0%"})
    figure.write_html(chart_path, include_plotlyjs="cdn")
    return [{"title": "多指标趋势与异常", "path": "charts/core-analysis.html", "download_url": "/api/jobs/{job_id}/files/charts/core-analysis.html"}]


def validate_answer_completeness(answer: dict, plan: QuestionPlan) -> list[str]:
    missing = []
    conclusion = answer.get("core_conclusion", "")
    if plan.metric_column is None:
        return [] if conclusion else ["缺少无法分析原因"]
    if not conclusion or not any(char.isdigit() for char in conclusion):
        missing.append("核心结论必须直接回答问题并包含实际数据")
    if len(plan.metric_columns) > 1:
        key_labels = {item.get("label") for item in answer.get("key_metrics", [])}
        for metric in plan.metric_columns:
            if metric not in conclusion:
                missing.append(f"核心结论缺少请求指标：{metric}")
            if metric not in key_labels:
                missing.append(f"关键数据缺少请求指标：{metric}")
    titles = {section["title"] for section in answer.get("sections", [])}
    if "trend" in plan.types and "趋势分析" not in titles:
        missing.append("趋势问题缺少趋势方向")
    if "anomaly" in plan.types and "异常对象" not in titles:
        missing.append("异常问题缺少对象和幅度")
    if len(plan.metric_columns) > 1 and "anomaly" in plan.types:
        anomaly_items = next((section["items"] for section in answer.get("sections", []) if section["title"] == "异常对象"), [])
        no_anomaly = any(item.get("text") == "未识别到超过阈值的异常月份。" for item in anomaly_items)
        complete_anomaly = any("异常" in item.get("text", "") and re.search(r"\d{4}-\d{2}", item["text"]) and "%" in item["text"] and "可能原因" in item["text"] for item in anomaly_items)
        if not no_anomaly and not complete_anomaly:
            missing.append("异常问题缺少指标、月份、幅度或可能原因")
    if "risk" in plan.types and not answer.get("business_risks"):
        missing.append("风险问题缺少最高风险对象")
    if "forecast" in plan.types and answer.get("forecast") is None:
        missing.append("预测问题缺少预测结果或不可预测原因")
    if any(kind in plan.types for kind in ("trend", "anomaly", "ranking", "risk", "forecast")) and not answer.get("charts"):
        missing.append("可视化问题缺少核心图表")
    return missing


def _quality(frame: pd.DataFrame) -> dict:
    return {"rows": int(len(frame)), "columns": int(len(frame.columns)), "duplicate_rows": int(frame.duplicated().sum()), "missing_cells": int(frame.isna().sum().sum())}


def _numeric_summary(frame: pd.DataFrame) -> dict:
    return {str(column): {"count": int(frame[column].count()), "missing": int(frame[column].isna().sum()), "mean": round(float(frame[column].mean()), 4), "min": float(frame[column].min()), "max": float(frame[column].max())} for column in frame.select_dtypes(include="number").columns}


def _series_by_dimension(frame: pd.DataFrame, plan: QuestionPlan) -> pd.DataFrame:
    if not plan.metric_column:
        return pd.DataFrame(columns=["period", "object", "value"])
    working = frame.copy()
    working["value"] = pd.to_numeric(working[plan.metric_column], errors="coerce")
    working = working.dropna(subset=["value"])
    working["period"] = pd.to_datetime(working[plan.time_column], errors="coerce") if plan.time_column else pd.RangeIndex(len(working))
    working["object"] = working[plan.dimension_column].astype(str) if plan.dimension_column else "整体"
    return working.dropna(subset=["period"]).groupby(["period", "object"], as_index=False)["value"].sum().sort_values(["object", "period"])


def _dimension_summaries(series: pd.DataFrame) -> list[dict]:
    summaries = []
    for name, group in series.groupby("object", sort=False):
        values = group["value"].to_numpy(dtype=float)
        if len(values) == 0:
            continue
        first, last = values[0], values[-1]
        change = _percent_change(last, first)
        direction = "上升" if change > 3 else "下降" if change < -3 else "稳定"
        summaries.append({"object": str(name), "first": float(first), "last": float(last), "change_pct": change, "direction": direction, "period_start": _period(group.iloc[0]["period"]), "period_end": _period(group.iloc[-1]["period"])})
    return summaries


def _largest_anomaly(series: pd.DataFrame) -> dict | None:
    candidates = []
    for name, group in series.groupby("object", sort=False):
        changes = group["value"].pct_change().dropna()
        if not changes.empty:
            index = changes.abs().idxmax()
            candidates.append({"object": str(name), "period": _period(group.loc[index, "period"]), "change_pct": round(float(changes.loc[index] * 100), 1), "value": float(group.loc[index, "value"])})
    return max(candidates, key=lambda item: abs(item["change_pct"])) if candidates else None


def _business_risks(summaries: list[dict], plan: QuestionPlan) -> list[dict]:
    if not _needs_business_risk(plan):
        return []
    declines = sorted((item for item in summaries if item["change_pct"] < -3), key=lambda item: item["change_pct"])
    if not declines and "risk" in plan.types and summaries:
        lowest = min(summaries, key=lambda item: item["change_pct"])
        declines = [lowest]
    return [{"title": f"{item['object']} 持续{plan.metric_column}下降" if item["change_pct"] < -3 else f"{item['object']} 风险最低", "object": item["object"], "level": "high" if item["change_pct"] <= -15 else "medium" if item["change_pct"] < -3 else "low", "evidence": [f"{item['period_start']} 至 {item['period_end']} 从 {_number(item['first'])} {'下降' if item['change_pct'] < 0 else '上升'}至 {_number(item['last'])}，累计变化 {item['change_pct']:.1f}%。"], "reason": f"{plan.metric_column} 在连续观测期内变化；当前数据未包含客户、价格或产品结构字段，不能归因于单一业务因素。", "mitigation": f"继续跟踪 {item['object']} 的客户、销量和价格拆分，及时识别方向反转。", "human_review_required": False} for item in declines[:3]]


def _needs_business_risk(plan: QuestionPlan) -> bool:
    downside_terms = ("下降", "下滑", "最差", "风险")
    return bool({"trend", "anomaly", "risk"}.intersection(plan.types)) or any(term in plan.objective.lower() for term in downside_terms)


def _forecast(series: pd.DataFrame, plan: QuestionPlan) -> dict | None:
    if "forecast" not in plan.types:
        return None
    if plan.time_column is None or series.empty:
        return {"prediction_interval_80": [], "limitations": ["未找到可用时间列和数值指标，无法给出可靠预测。"]}
    values = series.groupby("period", as_index=True)["value"].sum().sort_index().to_numpy(dtype=float)
    if len(values) < 8:
        return {"prediction_interval_80": [], "limitations": [f"仅有 {len(values)} 个时间点，少于预测所需的 8 个观测。"]}
    horizon = min(3, max(1, len(values) // 4))
    train, test = values[:-horizon], values[-horizon:]
    baseline = np.repeat(train[-1], horizon)
    candidate = np.polyval(np.polyfit(np.arange(len(train)), train, 1), np.arange(len(train), len(train) + horizon))
    baseline_mae, candidate_mae = float(np.mean(np.abs(test - baseline))), float(np.mean(np.abs(test - candidate)))
    recommended = candidate_mae < baseline_mae
    future = np.polyval(np.polyfit(np.arange(len(values)), values, 1), np.arange(len(values), len(values) + horizon)) if recommended else np.repeat(values[-1], horizon)
    residual = float(np.std(test - (candidate if recommended else baseline))) if len(test) > 1 else 0.0
    return {"model": "linear_trend" if recommended else "naive_baseline", "is_recommended": recommended, "baseline_mae": round(baseline_mae, 4), "candidate_mae": round(candidate_mae, 4), "prediction_interval_80": [{"step": step + 1, "value": round(float(value), 2), "lower": round(float(value - 1.28 * residual), 2), "upper": round(float(value + 1.28 * residual), 2)} for step, value in enumerate(future)], "limitations": [] if recommended else ["线性趋势模型未优于朴素基线，预测按最近值基线给出。"]}


def _sections(plan: QuestionPlan, summaries: list[dict], anomaly: dict | None, forecast: dict | None, risks: list[dict]) -> list[dict]:
    sections = []
    if "trend" in plan.types:
        sections.append({"title": "趋势分析", "items": [{"text": f"{item['object']} 在 {item['period_start']} 至 {item['period_end']} 呈{item['direction']}趋势：{_number(item['first'])} 至 {_number(item['last'])}，累计变化 {item['change_pct']:.1f}%。"} for item in summaries]})
    if "anomaly" in plan.types and anomaly:
        direction = "下降" if anomaly["change_pct"] < 0 else "上升"
        sections.extend([{"title": "异常对象", "items": [{"text": f"{anomaly['object']} 是变化幅度最大的对象。"}]}, {"title": "异常时间", "items": [{"text": f"异常发生在 {anomaly['period']}。"}]}, {"title": "异常幅度", "items": [{"text": f"{anomaly['object']} 当期 {plan.metric_column} 为 {_number(anomaly['value'])}，环比{direction} {abs(anomaly['change_pct']):.1f}%。"}]}])
    if "ranking" in plan.types:
        ranked = sorted(summaries, key=lambda item: item["last"], reverse=True)
        sections.append({"title": "地区排名" if plan.dimension_column else "指标排名", "items": [{"text": f"{index + 1}. {item['object']}：最新值 {_number(item['last'])}，累计变化 {item['change_pct']:.1f}%。"} for index, item in enumerate(ranked)]})
    if "risk" in plan.types:
        sections.append({"title": "风险评估", "items": [{"text": f"{risk['object']} 风险{risk['level']}：{risk['evidence'][0]}"} for risk in risks] or [{"text": "未发现累计下降超过 3% 的对象，当前数据中没有明确的高风险对象。"}]})
    if "forecast" in plan.types and forecast:
        text = f"下一期预测值为 {_number(forecast['prediction_interval_80'][0]['value'])}，80% 区间为 {_number(forecast['prediction_interval_80'][0]['lower'])} 至 {_number(forecast['prediction_interval_80'][0]['upper'])}。" if forecast["prediction_interval_80"] else forecast["limitations"][0]
        sections.append({"title": "预测结果", "items": [{"text": text}]})
    return sections or [{"title": "关键指标", "items": [{"text": f"{item['object']} 最新值 {_number(item['last'])}，累计变化 {item['change_pct']:.1f}%。"} for item in summaries]}]


def _key_metrics(summaries: list[dict], anomaly: dict | None, forecast: dict | None, risks: list[dict]) -> list[dict]:
    metrics = []
    if risks:
        metrics.append({"label": "最高风险对象", "value": risks[0]["object"], "detail": risks[0]["evidence"][0]})
    elif summaries:
        top = max(summaries, key=lambda item: item["last"])
        metrics.append({"label": "最新值最高对象", "value": top["object"], "detail": f"最新值 {_number(top['last'])}"})
    if anomaly:
        metrics.append({"label": "最大异常", "value": anomaly["object"], "detail": f"{anomaly['period']} 环比 {anomaly['change_pct']:.1f}%"})
    if forecast and forecast["prediction_interval_80"]:
        metrics.append({"label": "下一期预测", "value": _number(forecast["prediction_interval_80"][0]["value"]), "detail": "80% 预测区间已生成"})
    return metrics[:3]


def _core_conclusion(summaries: list[dict], anomaly: dict | None, forecast: dict | None, risks: list[dict], limitations: list[str], plan: QuestionPlan) -> str:
    if risks:
        text = f"{risks[0]['object']} 是当前风险最高的对象：{risks[0]['evidence'][0]}"
    elif summaries:
        top = max(summaries, key=lambda item: item["last"])
        text = f"当前数据中 {top['object']} 最新值最高，为 {_number(top['last'])}；在 {top['period_start']} 至 {top['period_end']} 累计{top['direction']} {abs(top['change_pct']):.1f}%。"
    else:
        text = "未找到可用于计算的数值指标，无法给出对象级结论。"
    if "anomaly" in plan.types and anomaly:
        text += f" 最大单期异常出现在 {anomaly['object']} 的 {anomaly['period']}，环比变化 {anomaly['change_pct']:.1f}%。"
    if "forecast" in plan.types and forecast and forecast["prediction_interval_80"]:
        first = forecast["prediction_interval_80"][0]
        text += f" 下一期预测为 {_number(first['value'])}，80% 区间 {_number(first['lower'])} 至 {_number(first['upper'])}。"
    return f"{text} {limitations[0]}" if limitations else text


def _analysis_limitations(plan: QuestionPlan, forecast: dict | None) -> list[str]:
    limitations = ["数据未提供地区、产品等分组字段，不能比较具体对象。"] if plan.dimension_column is None else []
    return limitations + (forecast.get("limitations", []) if forecast else [])


def _quality_limitations(frame: pd.DataFrame, plan: QuestionPlan, quality: dict) -> list[str]:
    limitations = []
    if plan.metric_column and int(frame[plan.metric_column].isna().sum()):
        missing = frame.loc[frame[plan.metric_column].isna()]
        if plan.dimension_column and plan.time_column:
            for _, row in missing[[plan.dimension_column, plan.time_column]].iterrows():
                period = _period(pd.to_datetime(row[plan.time_column], errors="coerce"))
                limitations.append(f"{row[plan.dimension_column]} 的 {period} {plan.metric_column} 缺失，不能可靠判断该对象该月的实际水平。")
        else:
            limitations.append(f"{plan.metric_column} 有 {int(frame[plan.metric_column].isna().sum())} 个缺失值，涉及这些记录的变化幅度不能可靠比较。")
    if quality["duplicate_rows"]:
        limitations.append(f"存在 {quality['duplicate_rows']} 行重复记录，已从汇总计算中排除，需确认是否代表重复业务。")
    return limitations


def _charts(series: pd.DataFrame, plan: QuestionPlan, forecast: dict | None, directory: Path) -> list[dict]:
    if series.empty:
        return []
    chart_path = directory / "charts" / "core-analysis.html"
    chart_path.parent.mkdir(exist_ok=True)
    if "forecast" in plan.types and forecast and forecast["prediction_interval_80"]:
        aggregate = series.groupby("period", as_index=False)["value"].sum()
        figure = go.Figure([go.Scatter(x=aggregate["period"], y=aggregate["value"], mode="lines+markers", name="历史")])
        future_periods = pd.date_range(aggregate["period"].max(), periods=len(forecast["prediction_interval_80"]) + 1, freq="MS")[1:]
        figure.add_trace(go.Scatter(x=future_periods, y=[item["value"] for item in forecast["prediction_interval_80"]], mode="lines+markers", name="预测"))
        figure.add_trace(go.Scatter(x=future_periods, y=[item["upper"] for item in forecast["prediction_interval_80"]], mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"))
        figure.add_trace(go.Scatter(x=future_periods, y=[item["lower"] for item in forecast["prediction_interval_80"]], mode="lines", fill="tonexty", fillcolor="rgba(23, 131, 113, .18)", line={"width": 0}, name="80% 预测区间"))
        figure.update_layout(title="历史趋势与预测区间")
        title = f"{plan.metric_column}预测"
    elif plan.dimension_column:
        figure, title = px.line(series, x="period", y="value", color="object", markers=True, title=f"对象{plan.metric_column}趋势"), f"地区{plan.metric_column}趋势"
    else:
        figure, title = px.line(series, x="period", y="value", markers=True, title="指标趋势"), "指标趋势"
    if "anomaly" in plan.types:
        anomaly = _largest_anomaly(series)
        if anomaly:
            point = series.loc[(series["object"] == anomaly["object"]) & (series["period"].astype(str).str.startswith(anomaly["period"]))]
            figure.add_trace(go.Scatter(x=point["period"], y=point["value"], mode="markers", marker={"color": "#c5443d", "size": 12, "symbol": "x"}, name="异常点"))
    figure.write_html(chart_path, include_plotlyjs="cdn")
    return [{"title": title, "path": "charts/core-analysis.html", "download_url": "/api/jobs/{job_id}/files/charts/core-analysis.html"}]


def _suggestions(risks: list[dict], anomaly: dict | None) -> list[dict]:
    if risks:
        return [{"name": f"优先处理 {risks[0]['object']}", "expected_benefit": "针对最高风险对象定位下降来源。", "cost": "中", "potential_harm": "低", "next_step": risks[0]["mitigation"]}]
    if anomaly:
        subject = anomaly.get("object") or anomaly.get("metric") or "指标"
        return [{"name": f"复核 {subject} 异常月份", "expected_benefit": "确认异常是否来自真实业务事件。", "cost": "低", "potential_harm": "低", "next_step": "核对该月原始数据和财务口径记录。"}]
    return []


def _percent_change(current: float, previous: float) -> float:
    return round((current - previous) / previous * 100, 1) if previous else 0.0


def _period(value: object) -> str:
    return value.strftime("%Y-%m") if hasattr(value, "strftime") else str(value)


def _number(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")
