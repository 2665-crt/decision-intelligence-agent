from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    parsed_type: str
    non_null_ratio: float
    null_ratio: float
    unique_ratio: float
    samples: list[Any]
    numeric_summary: dict[str, float | int] | None
    distinct_values: list[str]
    distinct_values_complete: bool
    semantic_role: str
    confidence: float


@dataclass(frozen=True)
class TableProfile:
    name: str
    row_count: int
    column_count: int
    missing_cells: int
    duplicate_rows: int
    columns: list[ColumnProfile]


@dataclass(frozen=True)
class DatasetProfile:
    file_hash: str
    source_name: str
    tables: list[TableProfile]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def profile_file(path: Path) -> DatasetProfile:
    path = Path(path)
    tables = [_profile_table(name, frame) for name, frame in read_tables(path)]
    return DatasetProfile(
        file_hash=sha256(path.read_bytes()).hexdigest(),
        source_name=path.name,
        tables=tables,
    )


def profile_files(paths: list[Path]) -> list[DatasetProfile]:
    return [profile_file(Path(path)) for path in paths]


def read_tables(path: Path) -> list[tuple[str, pd.DataFrame]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [(path.stem, pd.read_csv(path))]
    if suffix == ".tsv":
        return [(path.stem, pd.read_csv(path, sep="\t"))]
    if suffix in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(path)
        return [(sheet_name, _read_sheet(workbook, sheet_name)) for sheet_name in workbook.sheet_names]
    if suffix == ".json":
        return _read_json(path)
    raise ValueError(f"不支持结构化 Profile 的文件类型：{suffix}")


def _read_sheet(workbook: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    raw = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
    candidates: list[tuple[int, pd.DataFrame]] = []
    for header_row in range(min(len(raw), 12)):
        header = raw.iloc[header_row]
        labels = [str(value).strip() for value in header if isinstance(value, str) and value.strip()]
        if not labels or len(labels) != len(set(labels)):
            continue
        selected = [index for index, value in header.items() if isinstance(value, str) and value.strip()]
        data = raw.iloc[header_row + 1 :, selected].dropna(how="all").copy()
        data.columns = labels
        candidates.append((len(labels) * 100 + len(data), data))
    if candidates:
        return max(candidates, key=lambda candidate: candidate[0])[1].reset_index(drop=True)
    return pd.read_excel(workbook, sheet_name=sheet_name)


def _read_json(path: Path) -> list[tuple[str, pd.DataFrame]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return [(path.stem, _frame_from_json_value(payload))]
    if isinstance(payload, dict) and payload and all(isinstance(value, (list, dict)) for value in payload.values()):
        return [(str(name), _frame_from_json_value(value)) for name, value in payload.items()]
    return [(path.stem, _frame_from_json_value(payload))]


def _frame_from_json_value(value: Any) -> pd.DataFrame:
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return pd.json_normalize(value)
        return pd.DataFrame({"value": value})
    if isinstance(value, dict):
        return pd.json_normalize([value])
    return pd.DataFrame({"value": [value]})


def _profile_table(name: str, frame: pd.DataFrame) -> TableProfile:
    normalized = frame.copy()
    normalized.columns = [str(column) for column in normalized.columns]
    stable = normalized.map(_stable_value)
    return TableProfile(
        name=str(name),
        row_count=int(len(normalized)),
        column_count=int(len(normalized.columns)),
        missing_cells=int(normalized.isna().sum().sum()),
        duplicate_rows=int(stable.duplicated().sum()),
        columns=[_profile_column(str(column), normalized[column]) for column in normalized.columns],
    )


def _profile_column(name: str, series: pd.Series) -> ColumnProfile:
    non_null = series[series.map(lambda value: not _is_missing(value))]
    stable_values = non_null.map(_stable_value)
    has_complex_values = any(isinstance(value, (list, dict, set, tuple)) for value in non_null)
    total = len(series)
    non_null_ratio = round(len(non_null) / total, 4) if total else 0.0
    unique_ratio = round(stable_values.nunique(dropna=True) / len(non_null), 4) if len(non_null) else 0.0
    parsed_type, numeric = _parsed_type(stable_values)
    role, confidence = _semantic_role(name, stable_values, parsed_type, numeric, unique_ratio, has_complex_values)
    samples = [_stable_value(value) for value in non_null.head(5).tolist()]
    numeric_summary = None
    if numeric is not None and len(numeric):
        numeric_summary = {
            "count": int(len(numeric)),
            "min": round(float(numeric.min()), 6),
            "max": round(float(numeric.max()), 6),
            "mean": round(float(numeric.mean()), 6),
        }
    distinct_values = sorted({_normalized_join_value(value) for value in stable_values})
    distinct_values_complete = len(distinct_values) <= 1000
    return ColumnProfile(
        name=name,
        parsed_type=parsed_type,
        non_null_ratio=non_null_ratio,
        null_ratio=round(1 - non_null_ratio, 4),
        unique_ratio=unique_ratio,
        samples=samples,
        numeric_summary=numeric_summary,
        distinct_values=distinct_values[:1000],
        distinct_values_complete=distinct_values_complete,
        semantic_role=role,
        confidence=round(confidence, 4),
    )


def _parsed_type(values: pd.Series) -> tuple[str, pd.Series | None]:
    if values.empty:
        return "empty", None
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().mean() >= 0.9:
        return "numeric", numeric.dropna()
    if pd.api.types.is_bool_dtype(values):
        return "boolean", None
    dates = pd.to_datetime(values, format="mixed", errors="coerce")
    if dates.notna().mean() >= 0.9:
        return "datetime", None
    return "string", None


def _semantic_role(name: str, values: pd.Series, parsed_type: str, numeric: pd.Series | None, unique_ratio: float, has_complex_values: bool) -> tuple[str, float]:
    identifier_label = _is_identifier_label(name)
    if parsed_type == "empty":
        return "uncertain", 0.0
    if has_complex_values:
        return "uncertain", 0.5
    if parsed_type == "datetime":
        return "time", 0.9
    if parsed_type == "numeric":
        if identifier_label:
            return "identifier", 0.85
        if numeric is not None and len(numeric) >= 2 and numeric.nunique() >= 2:
            return "metric", 0.8
        return "uncertain", 0.5
    if parsed_type == "boolean":
        return "dimension", 0.75
    strings = values.astype(str).str.strip()
    median_length = float(strings.str.len().median()) if len(strings) else 0.0
    if identifier_label:
        return "identifier", 0.85
    if _is_dimension_label(name) and len(strings) >= 2:
        return "dimension", 0.85
    if unique_ratio <= 0.8 and len(strings) >= 2:
        return "dimension", 0.8
    if median_length >= 30:
        return "text", 0.8
    return "uncertain", 0.5


def _is_identifier_label(name: str) -> bool:
    separated = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    english_tokens = re.findall(r"[a-z0-9]+", separated.casefold())
    return (
        any(token in {"id", "code", "key"} for token in english_tokens)
        or name.strip().endswith(("编号", "编码", "序号"))
    )


def _is_dimension_label(name: str) -> bool:
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", name.casefold())
    return any(
        token in normalized
        for token in (
            "商品",
            "产品",
            "地区",
            "区域",
            "客户",
            "类别",
            "分类",
            "名称",
            "product",
            "item",
            "region",
            "area",
            "customer",
            "category",
            "name",
        )
    )


def _is_missing(value: Any) -> bool:
    if isinstance(value, (list, dict, set, tuple)):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _stable_value(value: Any) -> Any:
    if _is_missing(value):
        return None
    if isinstance(value, (list, dict, set, tuple)):
        return json.dumps(_json_compatible(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return _stable_value(value.item())
    return value


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_compatible(item) for item in value), key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_compatible(value.item())
    return value


def _normalized_join_value(value: Any) -> str:
    return str(value).strip().casefold()
