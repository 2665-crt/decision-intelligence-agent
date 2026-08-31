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


@dataclass(frozen=True)
class MetricAnalysisPlan:
    name: str
    kind: str
    fields: dict[str, str]
    field_confidences: dict[str, float]
    formula: str | None
    missing_fields: tuple[str, ...]


@dataclass(frozen=True)
class CompositeAnalysisPlan:
    question: str
    status: str
    file_hash: str
    table: str | None
    time_field: str | None
    time_confidence: float | None
    operations: tuple[str, ...]
    metrics: tuple[MetricAnalysisPlan, ...]
    reason_fields: tuple[str, ...]
    driver_fields: tuple[str, ...]
    limitations: tuple[str, ...]
    period_start: str | None = None
    period_end: str | None = None


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
        (("产品",), ("product", "item", "sku", "产品", "商品")),
        (("地区", "区域"), ("region", "area", "地区", "区域")),
        (("客户",), ("customer", "client", "客户")),
        (("类别", "分类"), ("category", "type", "类别", "分类")),
        (("班级", "组别"), ("class", "cohort", "group", "班级", "组别")),
    ),
    "metric": (
        (("销售额",), ("sales_amount", "salesamount", "gmv", "销售额", "销售金额")),
        (("销量",), ("sales_quantity", "salesquantity", "quantity", "volume", "qty", "销量", "销售量")),
        (("利润",), ("profit", "margin", "利润")),
        (("成本",), ("cost", "成本")),
        (("营收", "收入"), ("revenue", "income", "营收", "收入")),
        (("成绩", "分数"), ("score", "grade", "成绩", "分数")),
        (("错误率",), ("error_rate", "errorrate", "错误率")),
        (("库存",), ("inventory", "stock", "库存")),
    ),
    "time": (
        (("日期",), ("date", "day", "dt", "日期")),
        (("时间",), ("time", "timestamp", "datetime", "时间")),
        (("月份", "月度"), ("month", "period", "月份", "月度")),
    ),
}

_COMPOSITE_METRICS = {
    "revenue": {
        "name": "营业收入",
        "kind": "direct",
        "aliases": ("营业收入", "主营业务收入", "营收", "收入", "revenue", "income"),
    },
    "gross_margin": {
        "name": "毛利率",
        "kind": "ratio",
        "aliases": ("毛利率", "gross margin", "gross_margin", "margin rate"),
        "numerator_aliases": ("毛利", "毛利额", "gross profit"),
        "denominator_aliases": ("营业收入", "主营业务收入", "营收", "收入", "revenue", "income"),
    },
    "operating_profit": {
        "name": "营业利润",
        "kind": "direct",
        "aliases": ("营业利润", "经营利润", "operating profit", "operating_profit"),
    },
}

_COMPOSITE_TIME_MARKERS = ("期间", "日期", "时间", "月份", "月度", "date", "time", "month", "period")
_REASON_EVIDENCE_MARKERS = ("原因", "理由", "备注", "说明", "证据", "reason", "evidence", "note", "comment")
_REASON_FIELD_ALIASES = ("备注", "说明", "原因", "note", "comment", "reason", "description")
_DRIVER_FIELD_ALIASES = ("费用", "成本", "支出", "销量", "数量", "单价", "价格", "expense", "cost", "quantity", "volume", "price")
_RATE_OR_GROWTH_MARKERS = ("率", "占比", "比例", "百分比", "增长", "同比", "环比", "rate", "margin", "ratio", "growth", "percent", "yoy", "mom")


def build_plan(profile: DatasetProfile, question: str) -> AnalysisPlan | CompositeAnalysisPlan:
    composite_request = _composite_metric_requests(profile, question)
    composite_operations = _composite_operations(question)
    if len(composite_request) > 1 and _has_time_intent(question) and composite_operations:
        return _build_composite_plan(profile, question, composite_request, composite_operations)

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


def _build_composite_plan(
    profile: DatasetProfile,
    question: str,
    requested_metrics: tuple[str, ...],
    operations: tuple[str, ...],
) -> CompositeAnalysisPlan:
    table, time_column, metrics = _select_composite_table(profile.tables, requested_metrics, question)
    period_start, period_end = _requested_period_range(question)
    reason_fields = _select_reason_fields(table.columns) if table is not None else ()
    driver_fields = _select_driver_fields(table.columns) if table is not None else ()
    limitations: list[str] = []
    requested_range = _period_range_expression(question)
    if requested_range is not None and requested_range[0] > requested_range[1]:
        limitations.append("时间范围起始月份晚于结束月份，已拒绝应用该范围过滤。")
    if time_column is None:
        limitations.append("未找到满足语义置信度 >= 0.70 的时间字段；低置信度字段不会用于关键计算。")
    missing_metrics = [metric.name for metric in metrics if metric.missing_fields]
    if missing_metrics:
        limitations.append("未找到请求指标所需的高置信度字段：" + "、".join(missing_metrics) + "。")
    if "reason_evidence" in operations and not reason_fields:
        limitations.append("未找到满足语义置信度 >= 0.70 的备注/说明/原因证据字段。")
    if table is None or not any(not metric.missing_fields for metric in metrics) or time_column is None:
        status = "INSUFFICIENT_DATA"
    elif missing_metrics:
        status = "PARTIAL"
    else:
        status = "READY"
    return CompositeAnalysisPlan(
        question=question,
        status=status,
        file_hash=profile.file_hash,
        table=table.name if table is not None else None,
        time_field=time_column.name if time_column is not None else None,
        time_confidence=time_column.confidence if time_column is not None else None,
        operations=operations,
        metrics=tuple(metrics),
        reason_fields=reason_fields,
        driver_fields=driver_fields,
        limitations=tuple(limitations),
        period_start=period_start,
        period_end=period_end,
    )


def _select_composite_table(
    tables: list[TableProfile], requested_metrics: tuple[str, ...], question: str
) -> tuple[TableProfile | None, ColumnProfile | None, list[MetricAnalysisPlan]]:
    candidates: list[tuple[int, int, TableProfile, ColumnProfile | None, list[MetricAnalysisPlan]]] = []
    for table in tables:
        time_column = _select_composite_time(table.columns, question)
        metrics = [_build_metric_plan(table.columns, request) for request in requested_metrics]
        complete = sum(not metric.missing_fields for metric in metrics)
        candidates.append((complete, int(time_column is not None), table, time_column, metrics))
    if not candidates:
        return None, None, [_missing_metric_plan(request) for request in requested_metrics]
    _, _, table, time_column, metrics = max(
        candidates,
        key=lambda candidate: (candidate[1], candidate[0], -candidate[2].missing_cells),
    )
    return table, time_column, metrics


def _build_metric_plan(columns: list[ColumnProfile], request: str) -> MetricAnalysisPlan:
    if request.startswith("field:"):
        requested_field = request.removeprefix("field:")
        column = next(
            (
                column
                for column in columns
                if column.name == requested_field
                and column.semantic_role == "metric"
                and column.confidence >= MIN_SEMANTIC_CONFIDENCE
            ),
            None,
        )
        if column is None:
            return _missing_metric_plan(request)
        return MetricAnalysisPlan(
            name=column.name,
            kind="direct",
            fields={"metric": column.name},
            field_confidences={"metric": column.confidence},
            formula=None,
            missing_fields=(),
        )
    definition = _COMPOSITE_METRICS[request]
    if definition["kind"] == "direct":
        column = _match_composite_metric(columns, definition["aliases"])
        if column is None:
            return _missing_metric_plan(request)
        return MetricAnalysisPlan(
            name=definition["name"],
            kind="direct",
            fields={"metric": column.name},
            field_confidences={"metric": column.confidence},
            formula=None,
            missing_fields=(),
        )
    numerator = _match_composite_metric(columns, definition["numerator_aliases"])
    denominator = _match_composite_metric(columns, definition["denominator_aliases"])
    fields: dict[str, str] = {}
    confidences: dict[str, float] = {}
    if numerator is not None:
        fields["numerator"] = numerator.name
        confidences["numerator"] = numerator.confidence
    if denominator is not None:
        fields["denominator"] = denominator.name
        confidences["denominator"] = denominator.confidence
    missing = tuple(role for role in ("numerator", "denominator") if role not in fields)
    formula = None if missing else f"sum({numerator.name}) / sum({denominator.name})"
    return MetricAnalysisPlan(
        name=definition["name"],
        kind="ratio",
        fields=fields,
        field_confidences=confidences,
        formula=formula,
        missing_fields=missing,
    )


def _missing_metric_plan(request: str) -> MetricAnalysisPlan:
    if request.startswith("field:"):
        name = request.removeprefix("field:")
        return MetricAnalysisPlan(
            name=name,
            kind="direct",
            fields={},
            field_confidences={},
            formula=None,
            missing_fields=("metric",),
        )
    definition = _COMPOSITE_METRICS[request]
    fields = ("metric",) if definition["kind"] == "direct" else ("numerator", "denominator")
    return MetricAnalysisPlan(
        name=definition["name"],
        kind=definition["kind"],
        fields={},
        field_confidences={},
        formula=None,
        missing_fields=fields,
    )


def _select_composite_time(columns: list[ColumnProfile], question: str) -> ColumnProfile | None:
    eligible = [
        column
        for column in columns
        if column.semantic_role == "time" and column.confidence >= MIN_SEMANTIC_CONFIDENCE
    ]
    if not eligible:
        return None
    normalized_question = _normalize_field_name(question)
    scored = sorted(
        (
            (100 if _normalize_field_name(column.name) in normalized_question else 0, position, column)
            for position, column in enumerate(eligible)
        ),
        key=lambda item: (item[0], -item[1]),
        reverse=True,
    )
    if len(scored) == 1 or scored[0][0] > scored[1][0]:
        return scored[0][2]
    return None


def _match_composite_metric(columns: list[ColumnProfile], aliases: tuple[str, ...]) -> ColumnProfile | None:
    eligible = [
        column
        for column in columns
        if column.semantic_role == "metric"
        and column.confidence >= MIN_SEMANTIC_CONFIDENCE
        and _is_amount_field(column.name)
    ]
    scored = sorted(
        ((_field_alias_score(column.name, aliases), position, column) for position, column in enumerate(eligible)),
        key=lambda item: (item[0], -item[1]),
        reverse=True,
    )
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][2]


def _is_amount_field(field_name: str) -> bool:
    normalized_field = _normalize_field_name(field_name)
    return not any(_normalize_field_name(marker) in normalized_field for marker in _RATE_OR_GROWTH_MARKERS)


def _select_reason_fields(columns: list[ColumnProfile]) -> tuple[str, ...]:
    return tuple(
        column.name
        for column in columns
        if column.confidence >= MIN_SEMANTIC_CONFIDENCE
        and column.semantic_role in {"dimension", "text"}
        and _field_alias_score(column.name, _REASON_FIELD_ALIASES) > 0
    )


def _select_driver_fields(columns: list[ColumnProfile]) -> tuple[str, ...]:
    return tuple(
        column.name
        for column in columns
        if column.confidence >= MIN_SEMANTIC_CONFIDENCE
        and column.semantic_role == "metric"
        and _field_alias_score(column.name, _DRIVER_FIELD_ALIASES) > 0
    )


def _field_alias_score(field_name: str, aliases: tuple[str, ...]) -> int:
    normalized_field = _normalize_field_name(field_name)
    scores = []
    for alias in aliases:
        normalized_alias = _normalize_field_name(alias)
        if normalized_field == normalized_alias:
            scores.append(100)
        elif normalized_alias and normalized_alias in normalized_field:
            scores.append(50 + len(normalized_alias))
    return max(scores, default=0)


def _normalize_field_name(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def _composite_metric_requests(profile: DatasetProfile, question: str) -> tuple[str, ...]:
    candidates: list[tuple[int, int, int, str]] = []
    for key, definition in _COMPOSITE_METRICS.items():
        candidates.extend(
            (position, length, 0, key)
            for position, length in _phrase_matches(question, definition["aliases"])
        )
    seen_fields: set[str] = set()
    for table in profile.tables:
        for column in table.columns:
            if (
                column.name in seen_fields
                or column.semantic_role != "metric"
                or column.confidence < MIN_SEMANTIC_CONFIDENCE
            ):
                continue
            matches = _phrase_matches(
                question,
                (
                    column.name,
                    re.sub(r"[（(][^）)]*[）)]", "", column.name),
                ),
            )
            if matches:
                candidates.extend(
                    (position, length, 1, f"field:{column.name}")
                    for position, length in matches
                )
                seen_fields.add(column.name)

    requested: list[str] = []
    seen_requests: set[str] = set()
    selected_spans: list[tuple[int, int]] = []
    for position, length, _source_priority, request in sorted(
        candidates, key=lambda item: (item[0], -item[1], item[2])
    ):
        end = position + length
        if request in seen_requests:
            continue
        if any(position >= selected_start and end <= selected_end for selected_start, selected_end in selected_spans):
            continue
        requested.append(request)
        seen_requests.add(request)
        selected_spans.append((position, end))
    return tuple(requested)


def _phrase_matches(question: str, phrases: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    normalized_question = _normalize_field_name(question)
    matches: set[tuple[int, int]] = set()
    for phrase in phrases:
        normalized_phrase = _normalize_field_name(phrase)
        if not normalized_phrase:
            continue
        start = 0
        while (position := normalized_question.find(normalized_phrase, start)) >= 0:
            matches.add((position, len(normalized_phrase)))
            start = position + 1
    return tuple(sorted(matches, key=lambda item: (item[0], -item[1])))


def _requested_period_range(question: str) -> tuple[str | None, str | None]:
    requested_range = _period_range_expression(question)
    if requested_range is None:
        return None, None
    period_start, period_end = requested_range
    if period_start > period_end:
        return None, None
    return period_start, period_end


def _period_range_expression(question: str) -> tuple[str, str] | None:
    match = re.search(
        r"(?<!\d)(\d{4})\s*(?:-|/|年)\s*(\d{1,2})\s*月?\s*(?:到|至)\s*"
        r"(\d{4})\s*(?:-|/|年)\s*(\d{1,2})\s*月?(?!\d)",
        question,
    )
    if match is None:
        return None
    start_year, start_month, end_year, end_month = (int(value) for value in match.groups())
    if not 1 <= start_month <= 12 or not 1 <= end_month <= 12:
        return None
    return f"{start_year:04d}-{start_month:02d}", f"{end_year:04d}-{end_month:02d}"


def _has_time_intent(question: str) -> bool:
    normalized_question = _normalize_field_name(question)
    return (
        any(_normalize_field_name(marker) in normalized_question for marker in _COMPOSITE_TIME_MARKERS)
        or _period_range_expression(question) is not None
    )


def _composite_operations(question: str) -> tuple[str, ...]:
    operations = [
        operation
        for operation, markers in _OPERATION_MARKERS
        if operation in {"trend", "anomaly"} and any(marker in question.casefold() for marker in markers)
    ]
    if any(marker in question.casefold() for marker in _REASON_EVIDENCE_MARKERS):
        operations.append("reason_evidence")
    return tuple(operation for operation in ("trend", "anomaly", "reason_evidence") if operation in operations)


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
    normalized = field_name.casefold()
    parts = [token for token in re.split(r"[^0-9a-z\u4e00-\u9fff]+", normalized) if token]
    return set(parts) | {normalized, "".join(parts)}


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
