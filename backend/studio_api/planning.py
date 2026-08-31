from __future__ import annotations

from dataclasses import dataclass
import re

from .profiling import ColumnProfile, DatasetProfile, TableProfile


MIN_SEMANTIC_CONFIDENCE = 0.70


@dataclass(frozen=True)
class AnalysisPlan:
    question: str
    status: str
    file_hash: str
    table: str | None
    operations: tuple[str, ...]
    fields: dict[str, str]
    field_confidences: dict[str, float]
    aggregation: str | None
    parameters: dict[str, str | float | int]
    limitations: tuple[str, ...]


_OPERATION_MARKERS = (
    ("forecast", ("预测", "未来", "forecast", "predict")),
    ("correlation", ("相关", "关联", "correlation", "correlate")),
    ("anomaly", ("异常", "离群", "异常值", "anomaly", "outlier")),
    ("ranking", ("最高", "最低", "最好", "最差", "排名", "top", "highest", "lowest", "best", "worst")),
    ("group_comparison", ("比较", "对比", "差异", "compare", "comparison", "difference")),
    ("trend", ("趋势", "走势", "变化", "trend", "over time")),
)

_REQUIRED_ROLES = {
    "ranking": ("dimension", "metric"),
    "trend": ("time", "metric"),
    "anomaly": ("metric",),
    "group_comparison": ("dimension", "metric"),
    "correlation": ("metric", "secondary_metric"),
    "forecast": ("time", "metric"),
}

_QUESTION_CONCEPTS = {
    "dimension": (
        (("产品",), ("product", "item", "sku")),
        (("地区", "区域"), ("region", "area")),
        (("客户",), ("customer", "client")),
        (("类别", "分类"), ("category", "type")),
        (("班级", "组别"), ("class", "cohort", "group")),
    ),
    "metric": (
        (("销售额",), ("sales", "amount", "gmv")),
        (("销量",), ("sales", "quantity", "volume")),
        (("利润",), ("profit", "margin")),
        (("成本",), ("cost",)),
        (("营收", "收入"), ("revenue", "income")),
        (("成绩", "分数"), ("score", "grade")),
        (("错误率",), ("error", "rate")),
        (("库存",), ("inventory", "stock")),
    ),
    "time": (
        (("日期",), ("date", "day", "dt")),
        (("时间",), ("time", "timestamp", "datetime")),
        (("月份", "月度"), ("month", "period")),
    ),
}


def build_plan(profile: DatasetProfile, question: str) -> AnalysisPlan:
    operation = _detect_operation(question)
    if operation is None:
        return AnalysisPlan(
            question=question,
            status="INSUFFICIENT_DATA",
            file_hash=profile.file_hash,
            table=None,
            operations=(),
            fields={},
            field_confidences={},
            aggregation=None,
            parameters={},
            limitations=("问题未明确对应可执行的排名、趋势、异常、分组比较、相关性或预测算子。",),
        )

    table, fields, confidences = _select_table_and_fields(profile.tables, operation, question)
    missing = tuple(role for role in _REQUIRED_ROLES[operation] if role not in fields)
    limitations: list[str] = []
    if missing:
        limitations.append(
            "未找到满足语义置信度 >= 0.70 的必要字段：" + "、".join(missing) + "；低置信度字段不会用于关键计算。"
        )
        if operation == "forecast" and "time" in missing:
            limitations.append("预测需要可信的时间字段，不能在无时间字段的数据上计算。")
        status = "INSUFFICIENT_DATA"
    else:
        status = "READY"

    if operation == "anomaly" and not missing:
        optional = _select_optional_context(table, question)
        for role, column in optional.items():
            fields[role] = column.name
            confidences[role] = column.confidence
        if not optional:
            status = "PARTIAL"
            limitations.append("缺少可定位异常的时间或分组上下文字段；异常值仍可计算，但证据上下文有限。")

    return AnalysisPlan(
        question=question,
        status=status,
        file_hash=profile.file_hash,
        table=table.name if table is not None else None,
        operations=(operation,),
        fields=fields,
        field_confidences=confidences,
        aggregation=_aggregation_for(operation),
        parameters={"direction": _ranking_direction(question)} if operation == "ranking" else {},
        limitations=tuple(limitations),
    )


def _detect_operation(question: str) -> str | None:
    normalized = question.casefold()
    for operation, markers in _OPERATION_MARKERS:
        if any(marker in normalized for marker in markers):
            return operation
    return None


def _select_table_and_fields(
    tables: list[TableProfile], operation: str, question: str
) -> tuple[TableProfile | None, dict[str, str], dict[str, float]]:
    candidates: list[tuple[int, int, TableProfile, dict[str, str], dict[str, float]]] = []
    for table in tables:
        fields, confidences, lexical_score = _select_required_fields(table, operation, question)
        candidates.append((len(fields), lexical_score, table, fields, confidences))
    if not candidates:
        return None, {}, {}
    _, _, table, fields, confidences = max(
        candidates, key=lambda item: (item[0], item[1], -item[2].missing_cells)
    )
    return table, fields, confidences


def _select_required_fields(
    table: TableProfile, operation: str, question: str
) -> tuple[dict[str, str], dict[str, float], int]:
    if operation == "correlation":
        selected = _select_correlation_metrics(table.columns, question)
        if len(selected) == 2:
            first, second = selected
            return (
                {"metric": first.name, "secondary_metric": second.name},
                {"metric": first.confidence, "secondary_metric": second.confidence},
                _field_question_score(first.name, question, "metric")
                + _field_question_score(second.name, question, "metric"),
            )
        return {}, {}, 0
    fields: dict[str, str] = {}
    confidences: dict[str, float] = {}
    lexical_score = 0
    excluded: set[str] = set()
    for requested_role in _REQUIRED_ROLES[operation]:
        semantic_role = "metric" if requested_role == "secondary_metric" else requested_role
        selected, score = _select_column(table.columns, semantic_role, question, excluded)
        if selected is None:
            continue
        fields[requested_role] = selected.name
        confidences[requested_role] = selected.confidence
        lexical_score += score
        excluded.add(selected.name)
    return fields, confidences, lexical_score


def _select_correlation_metrics(columns: list[ColumnProfile], question: str) -> list[ColumnProfile]:
    eligible = [
        column
        for column in columns
        if column.semantic_role == "metric" and column.confidence >= MIN_SEMANTIC_CONFIDENCE
    ]
    normalized_question = question.casefold()
    named = [column for column in eligible if column.name.casefold() in normalized_question]
    if len(named) >= 2:
        return sorted(named, key=lambda column: normalized_question.index(column.name.casefold()))[:2]
    if len(eligible) == 2:
        return eligible
    return []


def _select_optional_context(table: TableProfile | None, question: str) -> dict[str, ColumnProfile]:
    if table is None:
        return {}
    time, _ = _select_column(table.columns, "time", question, set())
    if time is not None:
        return {"time": time}
    dimension, _ = _select_column(table.columns, "dimension", question, set())
    if dimension is not None:
        return {"dimension": dimension}
    return {}


def _select_column(
    columns: list[ColumnProfile], semantic_role: str, question: str, excluded: set[str]
) -> tuple[ColumnProfile | None, int]:
    concept_tokens = _explicit_concept_tokens(question, semantic_role)
    eligible = [
        column
        for column in columns
        if column.name not in excluded
        and column.semantic_role == semantic_role
        and column.confidence >= MIN_SEMANTIC_CONFIDENCE
        and (not concept_tokens or _field_tokens(column.name) & concept_tokens)
    ]
    if not eligible:
        return None, 0
    scored = sorted(
        (
            (_field_question_score(column.name, question, semantic_role), position, column)
            for position, column in enumerate(eligible)
        ),
        key=lambda item: (item[0], -item[1]),
        reverse=True,
    )
    if len(scored) == 1:
        return scored[0][2], scored[0][0]
    if scored[0][0] <= 0 or scored[0][0] == scored[1][0]:
        return None, 0
    return scored[0][2], scored[0][0]


def _field_question_score(field_name: str, question: str, semantic_role: str | None = None) -> int:
    normalized_question = question.casefold()
    normalized_field = field_name.casefold()
    compact_question = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized_question)
    compact_field = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized_field)
    score = 10 if normalized_field in normalized_question or compact_field in compact_question else 0
    field_tokens = {token for token in re.split(r"[^0-9a-z\u4e00-\u9fff]+", normalized_field) if token}
    question_tokens = {token for token in re.split(r"[^0-9a-z\u4e00-\u9fff]+", normalized_question) if token}
    score += 2 * len(field_tokens & question_tokens)
    if semantic_role is not None:
        score += 2 * len(field_tokens & _explicit_concept_tokens(question, semantic_role))
    return score


def _field_tokens(field_name: str) -> set[str]:
    return {token for token in re.split(r"[^0-9a-z\u4e00-\u9fff]+", field_name.casefold()) if token}


def _explicit_concept_tokens(question: str, semantic_role: str) -> set[str]:
    normalized = question.casefold()
    tokens: set[str] = set()
    for markers, aliases in _QUESTION_CONCEPTS.get(semantic_role, ()):
        if any(marker in normalized for marker in markers):
            tokens.update(aliases)
    return tokens


def _aggregation_for(operation: str) -> str | None:
    if operation in {"ranking", "trend", "forecast"}:
        return "sum"
    if operation == "group_comparison":
        return "mean"
    return None


def _ranking_direction(question: str) -> str:
    normalized = question.casefold()
    if any(marker in normalized for marker in ("最低", "最差", "lowest", "worst", "minimum")):
        return "ascending"
    return "descending"
