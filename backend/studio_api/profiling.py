from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
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
    return TableProfile(
        name=str(name),
        row_count=int(len(normalized)),
        column_count=int(len(normalized.columns)),
        missing_cells=int(normalized.isna().sum().sum()),
        duplicate_rows=int(normalized.duplicated().sum()),
        columns=[_profile_column(str(column), normalized[column]) for column in normalized.columns],
    )


def _profile_column(name: str, series: pd.Series) -> ColumnProfile:
    non_null = series.dropna()
    total = len(series)
    non_null_ratio = round(len(non_null) / total, 4) if total else 0.0
    unique_ratio = round(non_null.nunique(dropna=True) / len(non_null), 4) if len(non_null) else 0.0
    parsed_type, numeric = _parsed_type(non_null)
    role, confidence = _semantic_role(name, non_null, parsed_type, numeric, unique_ratio)
    samples = [_json_value(value) for value in non_null.head(5).tolist()]
    numeric_summary = None
    if numeric is not None and len(numeric):
        numeric_summary = {
            "count": int(len(numeric)),
            "min": round(float(numeric.min()), 6),
            "max": round(float(numeric.max()), 6),
            "mean": round(float(numeric.mean()), 6),
        }
    return ColumnProfile(
        name=name,
        parsed_type=parsed_type,
        non_null_ratio=non_null_ratio,
        null_ratio=round(1 - non_null_ratio, 4),
        unique_ratio=unique_ratio,
        samples=samples,
        numeric_summary=numeric_summary,
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


def _semantic_role(name: str, values: pd.Series, parsed_type: str, numeric: pd.Series | None, unique_ratio: float) -> tuple[str, float]:
    label = name.casefold()
    identifier_label = any(token in label for token in ("id", "code", "key", "编号", "编码", "序号"))
    if parsed_type == "empty":
        return "uncertain", 0.0
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
    if unique_ratio <= 0.8 and len(strings) >= 2:
        return "dimension", 0.8
    if median_length >= 30:
        return "text", 0.8
    return "uncertain", 0.5


def _json_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value
