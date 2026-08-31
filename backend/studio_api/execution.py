from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from .planning import AnalysisPlan, CompositeAnalysisPlan, MetricAnalysisPlan


@dataclass(frozen=True)
class FindingEvidence:
    source: dict[str, str]
    fields: tuple[str, ...]
    filters: tuple[str, ...]
    grouping: tuple[str, ...]
    calculation: str
    row_indices: tuple[Any, ...]


@dataclass(frozen=True)
class ComputedFinding:
    kind: str
    value: Any
    metric_value: float | None
    conclusion: str
    confidence: float
    evidence: FindingEvidence
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    findings: tuple[ComputedFinding, ...]
    limitations: tuple[str, ...]


def execute_plan(tables: dict[str, pd.DataFrame], plan: AnalysisPlan | CompositeAnalysisPlan) -> ExecutionResult:
    if isinstance(plan, CompositeAnalysisPlan):
        return _execute_composite_plan(tables, plan)
    if plan.status == "INSUFFICIENT_DATA":
        return ExecutionResult(status="INSUFFICIENT_DATA", findings=(), limitations=plan.limitations)
    if plan.table is None or plan.table not in tables:
        return ExecutionResult(
            status="INSUFFICIENT_DATA",
            findings=(),
            limitations=plan.limitations + ("计划引用的数据表不存在。",),
        )

    frame = tables[plan.table]
    missing_columns = tuple(column for column in plan.fields.values() if column not in frame.columns)
    if missing_columns:
        return ExecutionResult(
            status="INSUFFICIENT_DATA",
            findings=(),
            limitations=plan.limitations + ("计划引用的字段不存在：" + "、".join(missing_columns),),
        )

    executors: dict[str, Callable[[pd.DataFrame, AnalysisPlan], tuple[ComputedFinding, ...]]] = {
        "ranking": _execute_ranking,
        "trend": _execute_trend,
        "anomaly": _execute_anomaly,
        "group_comparison": _execute_group_comparison,
        "correlation": _execute_correlation,
    }
    findings: list[ComputedFinding] = []
    limitations = list(plan.limitations)
    for operation in plan.operations:
        executor = executors.get(operation)
        if executor is None:
            limitations.append(f"算子 {operation} 不在当前基础白名单中。")
            continue
        try:
            findings.extend(executor(frame, plan))
        except ValueError as exc:
            limitations.append(str(exc))

    if not findings:
        return ExecutionResult(status="INSUFFICIENT_DATA", findings=(), limitations=tuple(limitations))
    status = "PARTIAL" if plan.status == "PARTIAL" or len(findings) < len(plan.operations) else "SUCCESS"
    return ExecutionResult(status=status, findings=tuple(findings), limitations=tuple(limitations))


@dataclass(frozen=True)
class _CompositeSeries:
    metric: MetricAnalysisPlan
    values: pd.Series
    fields: tuple[str, ...]
    calculation: str
    row_indices: tuple[Any, ...]
    period_rows: dict[pd.Period, tuple[Any, ...]]


def _execute_composite_plan(
    tables: dict[str, pd.DataFrame], plan: CompositeAnalysisPlan
) -> ExecutionResult:
    if plan.status == "INSUFFICIENT_DATA":
        return ExecutionResult("INSUFFICIENT_DATA", (), plan.limitations)
    if plan.table is None or plan.table not in tables:
        return ExecutionResult("INSUFFICIENT_DATA", (), plan.limitations + ("计划引用的数据表不存在。",))
    if plan.time_field is None:
        return ExecutionResult("INSUFFICIENT_DATA", (), plan.limitations + ("复合分析缺少时间字段。",))

    frame = tables[plan.table]
    required_columns = {plan.time_field}
    for metric in plan.metrics:
        if not metric.missing_fields:
            required_columns.update(metric.fields.values())
    missing_columns = tuple(column for column in sorted(required_columns) if column not in frame.columns)
    if missing_columns:
        return ExecutionResult(
            "INSUFFICIENT_DATA", (), plan.limitations + ("计划引用的字段不存在：" + "、".join(missing_columns),)
        )

    limitations = list(plan.limitations)
    findings: list[ComputedFinding] = []
    for metric in plan.metrics:
        if metric.missing_fields:
            continue
        series, limitation = _aggregate_monthly_metric(frame, plan.time_field, metric)
        if limitation:
            limitations.append(f"{metric.name}：{limitation}")
            continue
        assert series is not None
        if "trend" in plan.operations:
            trend, limitation = _composite_trend_finding(plan, series)
            if limitation:
                limitations.append(f"{metric.name}：{limitation}")
            else:
                findings.append(trend)
        if "anomaly" in plan.operations:
            anomaly_findings, limitation = _composite_anomaly_findings(plan, series)
            findings.extend(anomaly_findings)
            if limitation:
                limitations.append(f"{metric.name}：{limitation}")

    if not findings:
        return ExecutionResult("INSUFFICIENT_DATA", (), tuple(limitations))
    status = "PARTIAL" if plan.status == "PARTIAL" or limitations else "SUCCESS"
    return ExecutionResult(status, tuple(findings), tuple(limitations))


def _aggregate_monthly_metric(
    frame: pd.DataFrame, time: str, metric: MetricAnalysisPlan
) -> tuple[_CompositeSeries | None, str | None]:
    source_fields = tuple(metric.fields.values())
    working = pd.DataFrame({time: pd.to_datetime(frame[time], errors="coerce")}, index=frame.index)
    for field_name in source_fields:
        working[field_name] = pd.to_numeric(frame[field_name], errors="coerce")
    working = working.dropna()
    if working.empty:
        return None, "没有可解析的时间和数值记录。"
    working["_period"] = working[time].dt.to_period("M")
    period_rows = {
        period: tuple(group.index.tolist()) for period, group in working.groupby("_period", sort=True)
    }
    if metric.kind == "direct":
        field_name = metric.fields["metric"]
        values = working.groupby("_period", sort=True)[field_name].sum(min_count=1).dropna()
        calculation = f"monthly_sum({field_name})"
        row_indices = tuple(working.index.tolist())
    else:
        numerator = metric.fields["numerator"]
        denominator = metric.fields["denominator"]
        grouped = working.groupby("_period", sort=True)[[numerator, denominator]].sum(min_count=1).dropna()
        values = (grouped[numerator] / grouped[denominator]).replace([np.inf, -np.inf], np.nan).dropna()
        calculation = f"monthly_sum({numerator}) / monthly_sum({denominator})"
        period_rows = {period: period_rows[period] for period in values.index}
        row_indices = tuple(row_index for rows in period_rows.values() for row_index in rows)
    if values.empty:
        return None, "按月聚合后没有有效数值。"
    return _CompositeSeries(metric, values, (time, *source_fields), calculation, row_indices, period_rows), None


def _composite_trend_finding(
    plan: CompositeAnalysisPlan, series: _CompositeSeries
) -> tuple[ComputedFinding | None, str | None]:
    if len(series.values) < 2:
        return None, "趋势计算至少需要两个按月聚合的有效期间。"
    points = [{"period": str(period), "value": float(value)} for period, value in series.values.items()]
    changes = _adjacent_changes(series.values)
    first, last = float(series.values.iloc[0]), float(series.values.iloc[-1])
    context = {
        "metric": series.metric.name,
        "time_granularity": "month",
        "first_to_last_change_pct": _percent_change(first, last),
        "maximum": float(series.values.max()),
        "minimum": float(series.values.min()),
        "adjacent_period_changes": changes,
    }
    return (
        ComputedFinding(
            kind="trend",
            value=points,
            metric_value=last,
            conclusion=f"{series.metric.name} 月度汇总值从 {first:g} 变化到 {last:g}。",
            confidence=_composite_confidence(plan, series.metric),
            evidence=_evidence(
                plan,
                fields=series.fields,
                grouping=(plan.time_field or "",),
                calculation=series.calculation,
                row_indices=series.row_indices,
            ),
            context=context,
        ),
        None,
    )


def _composite_anomaly_findings(
    plan: CompositeAnalysisPlan, series: _CompositeSeries
) -> tuple[tuple[ComputedFinding, ...], str | None]:
    changes = _adjacent_changes(series.values)
    if len(changes) < 4:
        return (), "按月聚合后不足五个期间，无法基于相邻期间变化执行 IQR 异常检测。"
    change_values = pd.Series([item["change_pct"] for item in changes], dtype="float64")
    first_quartile = float(change_values.quantile(0.25))
    third_quartile = float(change_values.quantile(0.75))
    spread = third_quartile - first_quartile
    lower, upper = first_quartile - 1.5 * spread, third_quartile + 1.5 * spread
    threshold = {"method": "IQR", "multiplier": 1.5, "lower": round(lower, 4), "upper": round(upper, 4)}
    calculation = f"iqr_outliers(monthly_percent_change({series.metric.name}), k=1.5)"
    outliers = [item for item in changes if item["change_pct"] < lower or item["change_pct"] > upper]
    if not outliers:
        return (
            (
                ComputedFinding(
                    kind="anomaly",
                    value=[],
                    metric_value=None,
                    conclusion=f"{series.metric.name} 的月度相邻期间变化未发现超过 IQR 阈值的异常。",
                    confidence=_composite_confidence(plan, series.metric),
                    evidence=_evidence(
                        plan, fields=series.fields, grouping=(plan.time_field or "",), calculation=calculation, row_indices=series.row_indices
                    ),
                    context={"metric": series.metric.name, "time_granularity": "month", "method": "IQR", "threshold": threshold},
                ),
            ),
            None,
        )
    findings = []
    for item in outliers:
        period = pd.Period(item["period"], freq="M")
        preceding_period = series.values.index[series.values.index.get_loc(period) - 1]
        findings.append(
            ComputedFinding(
                kind="anomaly",
                value=item,
                metric_value=item["current_value"],
                conclusion=f"{series.metric.name} 在 {item['period']} 的月度汇总值为 {item['current_value']:g}，较上期变化 {item['change_pct']:g}%。",
                confidence=_composite_confidence(plan, series.metric),
                evidence=_evidence(
                    plan,
                    fields=series.fields,
                    grouping=(plan.time_field or "",),
                    calculation=calculation,
                    row_indices=series.period_rows[preceding_period] + series.period_rows[period],
                ),
                context={
                    "metric": series.metric.name,
                    "time_granularity": "month",
                    "period": item["period"],
                    "method": "IQR",
                    "threshold": threshold,
                },
            )
        )
    return tuple(findings), None


def _adjacent_changes(values: pd.Series) -> list[dict[str, float | str]]:
    changes = []
    for index in range(1, len(values)):
        preceding = float(values.iloc[index - 1])
        current = float(values.iloc[index])
        if preceding == 0:
            continue
        changes.append(
            {
                "period": str(values.index[index]),
                "current_value": current,
                "preceding_value": preceding,
                "change_pct": _percent_change(preceding, current),
            }
        )
    return changes


def _percent_change(preceding: float, current: float) -> float | None:
    if preceding == 0:
        return None
    return round((current - preceding) / abs(preceding) * 100, 4)


def _execute_ranking(frame: pd.DataFrame, plan: AnalysisPlan) -> tuple[ComputedFinding, ...]:
    dimension = plan.fields["dimension"]
    metric = plan.fields["metric"]
    working = pd.DataFrame({dimension: frame[dimension], metric: pd.to_numeric(frame[metric], errors="coerce")}).dropna()
    grouped = working.groupby(dimension, dropna=True)[metric].sum(min_count=1).dropna()
    if grouped.empty:
        raise ValueError("排名所需的分组或数值记录不足。")
    leader = grouped.idxmin() if plan.parameters.get("direction") == "ascending" else grouped.idxmax()
    metric_value = float(grouped.loc[leader])
    row_indices = tuple(working.index[working[dimension] == leader].tolist())
    return (
        ComputedFinding(
            kind="ranking",
            value=_scalar(leader),
            metric_value=metric_value,
            conclusion=f"{dimension} 中的 {leader} 对应 {metric} 汇总值为 {metric_value:g}。",
            confidence=_confidence(plan, "dimension", "metric"),
            evidence=_evidence(
                plan,
                fields=(dimension, metric),
                grouping=(dimension,),
                calculation=f"groupby({dimension}).sum({metric})",
                row_indices=row_indices,
            ),
        ),
    )


def _execute_trend(frame: pd.DataFrame, plan: AnalysisPlan) -> tuple[ComputedFinding, ...]:
    time = plan.fields["time"]
    metric = plan.fields["metric"]
    working = pd.DataFrame(
        {time: pd.to_datetime(frame[time], errors="coerce"), metric: pd.to_numeric(frame[metric], errors="coerce")}
    ).dropna()
    grouped = working.groupby(time, dropna=True)[metric].sum(min_count=1).sort_index().dropna()
    if len(grouped) < 2:
        raise ValueError("趋势计算至少需要两个有效时间点。")
    points = [{"time": _time_label(index), "value": float(value)} for index, value in grouped.items()]
    return (
        ComputedFinding(
            kind="trend",
            value=points,
            metric_value=float(grouped.iloc[-1]),
            conclusion=f"{metric} 从 {points[0]['value']:g} 变化到 {points[-1]['value']:g}。",
            confidence=_confidence(plan, "time", "metric"),
            evidence=_evidence(
                plan,
                fields=(time, metric),
                grouping=(time,),
                calculation=f"groupby({time}).sum({metric}).sort_index()",
                row_indices=tuple(working.index.tolist()),
            ),
        ),
    )


def _execute_anomaly(frame: pd.DataFrame, plan: AnalysisPlan) -> tuple[ComputedFinding, ...]:
    metric = plan.fields["metric"]
    numeric = pd.to_numeric(frame[metric], errors="coerce").dropna()
    if len(numeric) < 4:
        raise ValueError("异常检测至少需要四条有效数值记录。")
    first_quartile = float(numeric.quantile(0.25))
    third_quartile = float(numeric.quantile(0.75))
    spread = third_quartile - first_quartile
    if not np.isfinite(spread) or spread <= 0:
        raise ValueError("数值分布没有足够离散度，无法执行 IQR 异常检测。")
    lower = first_quartile - 1.5 * spread
    upper = third_quartile + 1.5 * spread
    outliers = numeric[(numeric < lower) | (numeric > upper)]
    calculation = f"iqr_outliers({metric}, k=1.5)"
    if outliers.empty:
        return (
            ComputedFinding(
                kind="anomaly",
                value=[],
                metric_value=None,
                conclusion=f"{metric} 未发现超过 1.5 倍 IQR 阈值的异常值。",
                confidence=_confidence(plan, "metric"),
                evidence=_evidence(
                    plan,
                    fields=tuple(plan.fields.values()),
                    grouping=(),
                    calculation=calculation,
                    row_indices=tuple(numeric.index.tolist()),
                ),
            ),
        )
    findings: list[ComputedFinding] = []
    for row_index, value in outliers.items():
        context = {
            role: _scalar(frame.at[row_index, column])
            for role, column in plan.fields.items()
            if role != "metric" and not pd.isna(frame.at[row_index, column])
        }
        findings.append(
            ComputedFinding(
                kind="anomaly",
                value=float(value),
                metric_value=float(value),
                conclusion=f"{metric} 在第 {row_index} 行的值 {float(value):g} 超出 IQR 阈值。",
                confidence=_confidence(plan, "metric"),
                evidence=_evidence(
                    plan,
                    fields=tuple(plan.fields.values()),
                    grouping=(),
                    calculation=calculation,
                    row_indices=(row_index,),
                ),
                context=context,
            )
        )
    return tuple(findings)


def _execute_group_comparison(frame: pd.DataFrame, plan: AnalysisPlan) -> tuple[ComputedFinding, ...]:
    dimension = plan.fields["dimension"]
    metric = plan.fields["metric"]
    working = pd.DataFrame({dimension: frame[dimension], metric: pd.to_numeric(frame[metric], errors="coerce")}).dropna()
    grouped = working.groupby(dimension, dropna=True)[metric].mean().dropna().sort_values(ascending=False)
    if len(grouped) < 2:
        raise ValueError("分组比较至少需要两个含有效数值的分组。")
    values = [{"group": _scalar(group), "value": float(value)} for group, value in grouped.items()]
    return (
        ComputedFinding(
            kind="group_comparison",
            value=values,
            metric_value=float(grouped.iloc[0]),
            conclusion=f"{dimension} 的 {metric} 分组均值最高为 {values[0]['group']}：{values[0]['value']:g}。",
            confidence=_confidence(plan, "dimension", "metric"),
            evidence=_evidence(
                plan,
                fields=(dimension, metric),
                grouping=(dimension,),
                calculation=f"groupby({dimension}).mean({metric})",
                row_indices=tuple(working.index.tolist()),
            ),
        ),
    )


def _execute_correlation(frame: pd.DataFrame, plan: AnalysisPlan) -> tuple[ComputedFinding, ...]:
    first = plan.fields["metric"]
    second = plan.fields["secondary_metric"]
    pairs = pd.DataFrame(
        {first: pd.to_numeric(frame[first], errors="coerce"), second: pd.to_numeric(frame[second], errors="coerce")}
    ).dropna()
    if len(pairs) < 3 or pairs[first].nunique() < 2 or pairs[second].nunique() < 2:
        raise ValueError("相关性计算至少需要三对有效且有变化的数值。")
    correlation = float(np.corrcoef(pairs[first].to_numpy(), pairs[second].to_numpy())[0, 1])
    if not np.isfinite(correlation):
        raise ValueError("相关性计算结果不是有限数值。")
    correlation = round(correlation, 6)
    return (
        ComputedFinding(
            kind="correlation",
            value=correlation,
            metric_value=correlation,
            conclusion=f"{first} 与 {second} 的 Pearson 相关系数为 {correlation:g}。",
            confidence=_confidence(plan, "metric", "secondary_metric"),
            evidence=_evidence(
                plan,
                fields=(first, second),
                grouping=(),
                calculation=f"pearson_correlation({first}, {second})",
                row_indices=tuple(pairs.index.tolist()),
            ),
        ),
    )


def _evidence(
    plan: AnalysisPlan | CompositeAnalysisPlan,
    *,
    fields: tuple[str, ...],
    grouping: tuple[str, ...],
    calculation: str,
    row_indices: tuple[Any, ...],
) -> FindingEvidence:
    return FindingEvidence(
        source={"file_hash": plan.file_hash, "table": plan.table or ""},
        fields=fields,
        filters=(),
        grouping=grouping,
        calculation=calculation,
        row_indices=row_indices,
    )


def _confidence(plan: AnalysisPlan, *roles: str) -> float:
    values = [plan.field_confidences[role] for role in roles if role in plan.field_confidences]
    return round(min(values), 4) if values else 0.0


def _composite_confidence(plan: CompositeAnalysisPlan, metric: MetricAnalysisPlan) -> float:
    values = list(metric.field_confidences.values())
    if plan.time_confidence is not None:
        values.append(plan.time_confidence)
    return round(min(values), 4) if values else 0.0


def _time_label(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp == timestamp.normalize():
        return timestamp.date().isoformat()
    return timestamp.isoformat()


def _scalar(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value
