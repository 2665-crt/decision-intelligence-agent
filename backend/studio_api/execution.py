from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from .planning import AnalysisPlan


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


def execute_plan(tables: dict[str, pd.DataFrame], plan: AnalysisPlan) -> ExecutionResult:
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
    plan: AnalysisPlan,
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
