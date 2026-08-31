from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
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
    table_names = {table.name for table in profile.tables}
    findings: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []
    limitations = list(result.limitations)
    rejected = 0

    for finding in result.findings:
        evidence, reason = _validate_finding(finding, profile.file_hash, table_names)
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
    finding: ComputedFinding, expected_hash: str, table_names: set[str]
) -> tuple[dict[str, Any] | None, str | None]:
    evidence = finding.evidence
    source = evidence.source
    if source.get("file_hash") != expected_hash or not source.get("table") or source.get("table") not in table_names:
        return None, "结论的源文件或数据表证据无效，已拒绝展示。"
    if not evidence.fields:
        return None, "结论缺少参与字段证据，已拒绝展示。"
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
    if finding.context.get("metric_kind") == "ratio":
        if not {"numerator", "denominator"} <= set(finding.context.get("metric_fields", ())):
            return None, "派生比率结论缺少分子或分母字段证据，已拒绝展示。"
        if not str(finding.context.get("formula", "")).strip():
            return None, "派生比率结论缺少公式证据，已拒绝展示。"
    return (
        {
            "source": _serialize(source),
            "fields": list(evidence.fields),
            "filters": list(evidence.filters),
            "grouping": list(evidence.grouping),
            "calculation": evidence.calculation,
            "output_value": _serialize(finding.value),
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


def _serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if hasattr(value, "item"):
        return _serialize(value.item())
    return value
