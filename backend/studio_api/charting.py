from __future__ import annotations

import re
from typing import Any


def build_chart_specs(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn already-validated findings into display-only chart data."""
    anomalies = _anomaly_markers(findings)
    specs: list[dict[str, Any]] = []
    trended_metrics: set[str] = set()

    for index, finding in enumerate(findings):
        if finding.get("kind") != "trend":
            continue
        metric = _metric_name(finding)
        points = _points(finding.get("value"))
        if not points:
            continue
        trended_metrics.add(metric)
        specs.append(
            {
                "id": f"trend-{_slug(metric)}-{index}",
                "title": f"{metric}趋势",
                "type": "line",
                "x_label": "期间",
                "y_label": metric,
                "series": [{"name": metric, "points": points}],
                "markers": anomalies.get(metric, []),
                "unavailable_reason": None,
            }
        )

    for index, finding in enumerate(findings):
        metric = _metric_name(finding)
        if finding.get("kind") == "anomaly" and metric not in trended_metrics:
            spec = _anomaly_spec(finding, index)
            if spec:
                specs.append(spec)
        elif finding.get("kind") == "ranking":
            spec = _ranking_spec(finding, index)
            if spec:
                specs.append(spec)
        elif finding.get("kind") == "group_comparison":
            spec = _group_comparison_spec(finding, index)
            if spec:
                specs.append(spec)

    return specs or [
        {
            "id": "unavailable",
            "title": "暂无法生成图表",
            "type": "unavailable",
            "x_label": "",
            "y_label": "",
            "series": [],
            "markers": [],
            "unavailable_reason": "当前结论缺少可用于横轴的时间或分类字段。请补充时间、类别或数值字段后重新分析。",
        }
    ]


def _anomaly_markers(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    markers: dict[str, list[dict[str, str]]] = {}
    for finding in findings:
        if finding.get("kind") != "anomaly" or not isinstance(finding.get("value"), dict):
            continue
        value = finding["value"]
        period = value.get("period")
        if period:
            markers.setdefault(_metric_name(finding), []).append(
                {"x": str(period), "label": "异常", "kind": "anomaly"}
            )
    return markers


def _anomaly_spec(finding: dict[str, Any], index: int) -> dict[str, Any] | None:
    value = finding.get("value")
    if not isinstance(value, dict) or not _number(value.get("current_value")):
        return None
    metric = _metric_name(finding)
    period = str(value.get("period") or "异常点")
    points = []
    if _number(value.get("preceding_value")):
        points.append({"x": "上期", "y": float(value["preceding_value"])})
    points.append({"x": period, "y": float(value["current_value"])})
    return {
        "id": f"anomaly-{_slug(metric)}-{index}",
        "title": f"{metric}异常变化",
        "type": "line",
        "x_label": "期间",
        "y_label": metric,
        "series": [{"name": metric, "points": points}],
        "markers": [{"x": period, "label": "异常", "kind": "anomaly"}],
        "unavailable_reason": None,
    }


def _ranking_spec(finding: dict[str, Any], index: int) -> dict[str, Any] | None:
    if not _number(finding.get("metric_value")):
        return None
    metric = _metric_name(finding)
    category = str(finding.get("value") or "结果")
    return {
        "id": f"ranking-{_slug(metric)}-{index}",
        "title": f"{metric}对比结果",
        "type": "bar",
        "x_label": "类别",
        "y_label": metric,
        "series": [{"name": metric, "points": [{"x": category, "y": float(finding["metric_value"])}]}],
        "markers": [],
        "unavailable_reason": None,
    }


def _group_comparison_spec(finding: dict[str, Any], index: int) -> dict[str, Any] | None:
    value = finding.get("value")
    if not isinstance(value, list):
        return None
    points = [
        {"x": str(item["group"]), "y": float(item["value"])}
        for item in value
        if isinstance(item, dict) and item.get("group") is not None and _number(item.get("value"))
    ]
    if not points:
        return None
    metric = _metric_name(finding)
    return {
        "id": f"comparison-{_slug(metric)}-{index}",
        "title": f"{metric}分类对比",
        "type": "bar",
        "x_label": "类别",
        "y_label": metric,
        "series": [{"name": metric, "points": points}],
        "markers": [],
        "unavailable_reason": None,
    }


def _points(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    points: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or not _number(item.get("value")):
            continue
        x = item.get("period", item.get("x"))
        if x is not None:
            points.append({"x": str(x), "y": float(item["value"])})
    return points


def _metric_name(finding: dict[str, Any]) -> str:
    context = finding.get("context") if isinstance(finding.get("context"), dict) else {}
    if context.get("metric"):
        return str(context["metric"])
    evidence = finding.get("evidence") if isinstance(finding.get("evidence"), dict) else {}
    fields = evidence.get("fields") if isinstance(evidence.get("fields"), list) else []
    return str(fields[-1]) if fields else "指标"


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "metric"
