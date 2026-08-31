from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .profiling import ColumnProfile, DatasetProfile, TableProfile


AUTO_USE_CONFIDENCE = 0.85


@dataclass(frozen=True)
class RelationshipCandidate:
    left_source: str
    left_file_hash: str
    left_table: str
    left_field: str
    right_source: str
    right_file_hash: str
    right_table: str
    right_field: str
    relation_type: str
    confidence: float
    reason: str
    can_auto_use: bool
    requires_confirmation: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class _TableReference:
    source_name: str
    file_hash: str
    table: TableProfile


def discover_relationships(profiles: list[DatasetProfile]) -> list[RelationshipCandidate]:
    tables = [
        _TableReference(profile.source_name, profile.file_hash, table)
        for profile in profiles
        for table in profile.tables
    ]
    candidates: list[RelationshipCandidate] = []
    for left_index, left in enumerate(tables):
        for right in tables[left_index + 1 :]:
            candidates.extend(_candidates_for_pair(left, right))
    return candidates


def _candidates_for_pair(left: _TableReference, right: _TableReference) -> list[RelationshipCandidate]:
    candidates: list[RelationshipCandidate] = []
    for left_column in left.table.columns:
        for right_column in right.table.columns:
            if _normalize_field(left_column.name) != _normalize_field(right_column.name):
                continue
            candidate = _candidate(left, left_column, right, right_column)
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def _candidate(
    left: _TableReference,
    left_column: ColumnProfile,
    right: _TableReference,
    right_column: ColumnProfile,
) -> RelationshipCandidate | None:
    if not _compatible_columns(left_column, right_column):
        return None
    left_values = set(left_column.distinct_values)
    right_values = set(right_column.distinct_values)
    overlap = left_values & right_values
    if not overlap:
        return None
    minimum_coverage = len(overlap) / min(len(left_values), len(right_values))
    shared_identifier = left_column.semantic_role == right_column.semantic_role == "identifier"
    confidence = _confidence(left_column, right_column, minimum_coverage, shared_identifier)
    can_auto_use = (
        confidence >= AUTO_USE_CONFIDENCE
        and shared_identifier
        and left_column.distinct_values_complete
        and right_column.distinct_values_complete
        and minimum_coverage == 1.0
        and min(left_column.non_null_ratio, right_column.non_null_ratio) >= 0.95
        and min(left_column.unique_ratio, right_column.unique_ratio) >= 0.95
    )
    reason = (
        f"规范化字段名一致；值集合重叠覆盖率 {minimum_coverage:.2f}；"
        f"唯一率 {left_column.unique_ratio:.2f}/{right_column.unique_ratio:.2f}；"
        f"非空率 {left_column.non_null_ratio:.2f}/{right_column.non_null_ratio:.2f}"
    )
    if shared_identifier:
        reason = f"两侧均为显式标识字段；{reason}"
    else:
        reason = f"字段不是两侧显式标识字段；{reason}"
    return RelationshipCandidate(
        left_source=left.source_name,
        left_file_hash=left.file_hash,
        left_table=left.table.name,
        left_field=left_column.name,
        right_source=right.source_name,
        right_file_hash=right.file_hash,
        right_table=right.table.name,
        right_field=right_column.name,
        relation_type="key_match",
        confidence=confidence,
        reason=reason,
        can_auto_use=can_auto_use,
        requires_confirmation=not can_auto_use,
    )


def _compatible_columns(left: ColumnProfile, right: ColumnProfile) -> bool:
    return (
        left.parsed_type == right.parsed_type
        and left.semantic_role != "uncertain"
        and right.semantic_role != "uncertain"
        and bool(left.distinct_values)
        and bool(right.distinct_values)
    )


def _confidence(left: ColumnProfile, right: ColumnProfile, overlap: float, shared_identifier: bool) -> float:
    identifier_score = 0.2 if shared_identifier else 0.0
    name_score = 0.25
    semantic_score = min(left.confidence, right.confidence) * 0.05
    uniqueness_score = min(left.unique_ratio, right.unique_ratio) * 0.2
    completeness_score = min(left.non_null_ratio, right.non_null_ratio) * 0.1
    overlap_score = overlap * 0.2
    return round(name_score + identifier_score + semantic_score + uniqueness_score + completeness_score + overlap_score, 4)


def _normalize_field(name: str) -> str:
    return re.sub(r"[^\\w\\u4e00-\\u9fff]", "", name.casefold())
