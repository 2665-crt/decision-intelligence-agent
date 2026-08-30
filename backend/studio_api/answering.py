from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .questioning import QuestionPlan, plan_question


def analyse_spreadsheet(frame: pd.DataFrame, objective: str, directory: Path) -> dict:
    plan = plan_question(frame, objective)
    answer = build_question_answer(frame, plan, directory)
    missing = validate_answer_completeness(answer, plan)
    if missing:
        raise ValueError("；".join(missing))
    return answer


def build_question_answer(frame: pd.DataFrame, plan: QuestionPlan, directory: Path) -> dict:
    quality = _quality(frame)
    series = _series_by_dimension(frame, plan)
    summaries = _dimension_summaries(series)
    anomaly = _largest_anomaly(series)
    forecast = _forecast(series, plan)
    business_risks = _business_risks(summaries, plan)
    sections = _sections(plan, summaries, anomaly, forecast, business_risks)
    limitations = _analysis_limitations(plan, forecast)
    data_quality = {**quality, "summary": f"{quality['rows']} 行、{quality['columns']} 列；缺失 {quality['missing_cells']} 个单元格，重复 {quality['duplicate_rows']} 行。", "limitations": _quality_limitations(frame, plan, quality)}
    core_conclusion = _core_conclusion(summaries, anomaly, forecast, business_risks, limitations, plan)
    charts = _charts(series, plan, forecast, directory)
    answer = {
        "analysis": {"kind": "question_driven_spreadsheet_analysis", "numeric_summary": _numeric_summary(frame), "quality": quality, "plan": {"types": list(plan.types), "time_column": plan.time_column, "metric_column": plan.metric_column, "dimension_column": plan.dimension_column}},
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


def validate_answer_completeness(answer: dict, plan: QuestionPlan) -> list[str]:
    missing = []
    conclusion = answer.get("core_conclusion", "")
    if not conclusion or not any(char.isdigit() for char in conclusion):
        missing.append("核心结论必须直接回答问题并包含实际数据")
    titles = {section["title"] for section in answer.get("sections", [])}
    if "trend" in plan.types and "趋势分析" not in titles:
        missing.append("趋势问题缺少趋势方向")
    if "anomaly" in plan.types and "异常对象" not in titles:
        missing.append("异常问题缺少对象和幅度")
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
    return [{"title": f"{item['object']} 持续营收下降" if item["change_pct"] < -3 else f"{item['object']} 风险最低", "object": item["object"], "level": "high" if item["change_pct"] <= -15 else "medium" if item["change_pct"] < -3 else "low", "evidence": [f"{item['period_start']} 至 {item['period_end']} 从 {_number(item['first'])} {'下降' if item['change_pct'] < 0 else '上升'}至 {_number(item['last'])}，累计变化 {item['change_pct']:.1f}%。"], "reason": "收入指标在连续观测期内变化；当前数据未包含客户、价格或产品结构字段，不能归因于单一业务因素。", "mitigation": f"继续跟踪 {item['object']} 的客户、销量和价格拆分，及时识别方向反转。", "human_review_required": False} for item in declines[:3]]


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
        sections.extend([{"title": "异常对象", "items": [{"text": f"{anomaly['object']} 是变化幅度最大的对象。"}]}, {"title": "异常时间", "items": [{"text": f"异常发生在 {anomaly['period']}。"}]}, {"title": "异常幅度", "items": [{"text": f"{anomaly['object']} 当期营收为 {_number(anomaly['value'])}，环比{direction} {abs(anomaly['change_pct']):.1f}%。"}]}])
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
        limitations.append(f"存在 {quality['duplicate_rows']} 行重复记录，汇总前应确认是否代表重复业务。")
    return limitations


def _charts(series: pd.DataFrame, plan: QuestionPlan, forecast: dict | None, directory: Path) -> list[dict]:
    if series.empty:
        return []
    chart_path = directory / "charts" / "core-analysis.html"
    chart_path.parent.mkdir(exist_ok=True)
    if "forecast" in plan.types and forecast and forecast["prediction_interval_80"]:
        aggregate = series.groupby("period", as_index=False)["value"].sum()
        figure = go.Figure([go.Scatter(x=aggregate["period"], y=aggregate["value"], mode="lines+markers", name="历史")])
        figure.add_trace(go.Scatter(x=pd.date_range(aggregate["period"].max(), periods=len(forecast["prediction_interval_80"]) + 1, freq="MS")[1:], y=[item["value"] for item in forecast["prediction_interval_80"]], mode="lines+markers", name="预测"))
        figure.update_layout(title="历史趋势与预测区间")
        title = "营收预测"
    elif plan.dimension_column:
        figure, title = px.line(series, x="period", y="value", color="object", markers=True, title="对象营收趋势"), "地区营收趋势"
    else:
        figure, title = px.line(series, x="period", y="value", markers=True, title="指标趋势"), "指标趋势"
    figure.write_html(chart_path, include_plotlyjs="cdn")
    return [{"title": title, "path": "charts/core-analysis.html", "download_url": "/api/jobs/{job_id}/files/charts/core-analysis.html"}]


def _suggestions(risks: list[dict], anomaly: dict | None) -> list[dict]:
    if risks:
        return [{"name": f"优先处理 {risks[0]['object']}", "expected_benefit": "针对最高风险对象定位下降来源。", "cost": "中", "potential_harm": "低", "next_step": risks[0]["mitigation"]}]
    if anomaly:
        return [{"name": f"复核 {anomaly['object']} 异常月份", "expected_benefit": "确认异常是否来自真实业务事件。", "cost": "低", "potential_harm": "低", "next_step": "核对该月订单、价格和数据录入记录。"}]
    return []


def _percent_change(current: float, previous: float) -> float:
    return round((current - previous) / previous * 100, 1) if previous else 0.0


def _period(value: object) -> str:
    return value.strftime("%Y-%m") if hasattr(value, "strftime") else str(value)


def _number(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")
