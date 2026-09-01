from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from numbers import Integral
from typing import Any

from .execution import ComputedFinding, ExecutionResult
from .profiling import DatasetProfile


SUCCESS = "SUCCESS"
PARTIAL = "PARTIAL"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class ValidatedResult:
    status: str
    answer: str
    findings: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answer": self.answer,
            "findings": list(self.findings),
            "evidence": list(self.evidence),
            "limitations": list(self.limitations),
        }


def validate_result(result: ExecutionResult, profile: DatasetProfile) -> ValidatedResult:
    tables = {table.name: table for table in profile.tables}
    findings: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []
    limitations = list(result.limitations)
    rejected = 0

    for finding in result.findings:
        evidence, reason = _validate_finding(finding, profile.file_hash, tables)
        if reason:
            rejected += 1
            limitations.append(reason)
            continue
        serialized = {
            "kind": finding.kind,
            "value": _serialize(finding.value),
            "metric_value": _serialize(finding.metric_value),
            "conclusion": finding.conclusion,
            "confidence": finding.confidence,
            "context": _serialize(finding.context),
            "evidence": evidence,
        }
        findings.append(serialized)
        evidence_items.append(evidence)

    if not findings:
        status = INSUFFICIENT_DATA
        answer = "无法完成此问题：" + "；".join(limitations or ["没有可验证的计算结论。"])
    else:
        status = PARTIAL if rejected or result.status == PARTIAL else SUCCESS
        answer = "；".join(str(finding["conclusion"]) for finding in findings)
    return ValidatedResult(status, answer, tuple(findings), tuple(evidence_items), tuple(limitations))


def _validate_finding(
    finding: ComputedFinding, expected_hash: str, tables: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    evidence = finding.evidence
    source = evidence.source
    table_name = source.get("table")
    if source.get("file_hash") != expected_hash or not table_name or table_name not in tables:
        return None, "结论的源文件或数据表证据无效，已拒绝展示。"
    table = tables[table_name]
    table_fields = {column.name for column in table.columns}
    if not evidence.fields:
        return None, "结论缺少参与字段证据，已拒绝展示。"
    unknown_fields = (set(evidence.fields) | set(evidence.grouping)) - table_fields
    if unknown_fields:
        return None, "结论引用了不属于源表字段的证据，已拒绝展示：" + "、".join(sorted(unknown_fields))
    if not str(evidence.calculation).strip():
        return None, "数值结论缺少 calculation（计算表达式）证据，已拒绝展示。"
    if finding.value is None:
        return None, "结论缺少 output value，已拒绝展示。"
    if finding.metric_value is not None and not _is_finite_number(finding.metric_value):
        return None, "数值结论包含无效 output value，已拒绝展示。"
    if not _is_finite_number(finding.confidence):
        return None, "结论置信度无效，已拒绝展示。"
    if not evidence.row_indices:
        return None, "结论缺少源数据行证据，已拒绝展示。"
    if any(
        isinstance(row_index, bool)
        or not isinstance(row_index, Integral)
        or row_index < 0
        or row_index >= table.row_count
        for row_index in evidence.row_indices
    ):
        return None, "结论引用的源数据行不存在，已拒绝展示。"
    if finding.context.get("metric_kind") == "ratio":
        metric_fields = finding.context.get("metric_fields")
        if not isinstance(metric_fields, dict) or not {"numerator", "denominator"} <= set(metric_fields):
            return None, "派生比率结论缺少分子或分母字段证据，已拒绝展示。"
        numerator = metric_fields["numerator"]
        denominator = metric_fields["denominator"]
        if numerator not in table_fields or denominator not in table_fields or not {numerator, denominator} <= set(evidence.fields):
            return None, "派生比率公式的分子/分母字段不属于实际证据字段，已拒绝展示。"
        formula = str(finding.context.get("formula", "")).strip()
        if not formula:
            return None, "派生比率结论缺少公式证据，已拒绝展示。"
        if formula != f"sum({numerator}) / sum({denominator})":
            return None, "派生比率公式未对应真实分子/分母字段，已拒绝展示。"
    return (
        {
            "source": _serialize(source),
            "fields": list(evidence.fields),
            "filters": list(evidence.filters),
            "grouping": list(evidence.grouping),
            "calculation": evidence.calculation,
            "output_value": _serialize(_output_value(finding, evidence)),
            "metric_value": _serialize(finding.metric_value),
            "confidence": finding.confidence,
            "row_indices": _serialize(list(evidence.row_indices)),
            "formula": finding.context.get("formula"),
        },
        None,
    )


def _is_finite_number(value: Any) -> bool:
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _output_value(finding: ComputedFinding, evidence: FindingEvidence) -> Any:
    if finding.kind == "ranking" and evidence.grouping and finding.metric_value is not None:
        return {evidence.grouping[0]: finding.value, "aggregate": finding.metric_value}
    return finding.value


def _serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return _serialize(value.item())
    return value
