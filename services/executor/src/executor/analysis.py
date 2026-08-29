"""Deterministic, allow-listed dataframe operations; no generated code or shell."""
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path

import pandas as pd

ALLOWED_OPERATIONS = frozenset({"profile", "quality_check", "group_summary", "trend", "correlation", "anomaly"})

@dataclass(frozen=True)
class TableArtifact:
    name: str
    rows: list[dict]
    path: str

@dataclass(frozen=True)
class ChartArtifact:
    name: str
    path: str

@dataclass(frozen=True)
class EvidenceItem:
    level: str
    summary: str
    artifact_path: str | None = None

@dataclass(frozen=True)
class RunResult:
    tables: dict[str, TableArtifact]
    charts: list[ChartArtifact]
    evidence: list[EvidenceItem]
    logs: list[str]
    def as_dict(self) -> dict:
        return {"tables": {key: asdict(value) for key, value in self.tables.items()}, "charts": [asdict(value) for value in self.charts], "evidence": [asdict(value) for value in self.evidence], "logs": self.logs}
    def __getitem__(self, key: str):
        """Compatibility view for callers that only need artifact payloads."""
        if key == "tables":
            return {name: table.rows for name, table in self.tables.items()}
        if key == "charts":
            return [chart.path for chart in self.charts]
        if key == "evidence":
            return [{"level": item.level, "summary": item.summary} for item in self.evidence]
        raise KeyError(key)

def _write_csv(output_dir: Path, name: str, rows: list[dict]) -> TableArtifact:
    path = output_dir / f"{name}.csv"
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")
    return TableArtifact(name, rows, str(path))

def _write_line_chart(output_dir: Path, frame: pd.DataFrame, x: str, y: str) -> ChartArtifact:
    rows = "\n".join(f"<tr><td>{escape(str(a))}</td><td>{escape(str(b))}</td></tr>" for a, b in zip(frame[x], frame[y], strict=True))
    path = output_dir / "trend.html"
    path.write_text(f"<!doctype html><meta charset='utf-8'><title>趋势图</title><h1>趋势图：{escape(y)}</h1><table><tr><th>{escape(x)}</th><th>{escape(y)}</th></tr>{rows}</table>", encoding="utf-8")
    return ChartArtifact("trend", str(path))

def run_operations(frame: pd.DataFrame, operations: list[str], output_dir: Path) -> RunResult:
    unsupported = set(operations) - ALLOWED_OPERATIONS
    if unsupported:
        raise ValueError(f"unsupported operations: {sorted(unsupported)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    numeric = frame.select_dtypes(include="number").columns.tolist()
    tables: dict[str, TableArtifact] = {}
    charts: list[ChartArtifact] = []
    evidence = [EvidenceItem("A", f"读取 {len(frame)} 行、{len(frame.columns)} 列数据")]
    if "profile" in operations:
        tables["profile"] = _write_csv(output_dir, "profile", [{"column": column, "missing": int(frame[column].isna().sum()), "non_null": int(frame[column].notna().sum())} for column in frame.columns])
    if "quality_check" in operations:
        rows = [{"duplicate_rows": int(frame.duplicated().sum()), "missing_cells": int(frame.isna().sum().sum())}]
        tables["quality"] = _write_csv(output_dir, "quality", rows)
        evidence.append(EvidenceItem("A", f"发现 {rows[0]['duplicate_rows']} 行重复数据和 {rows[0]['missing_cells']} 个缺失单元格", tables["quality"].path))
    if "group_summary" in operations and numeric:
        category = next((column for column in frame.columns if column not in numeric and "date" not in column.casefold() and "time" not in column.casefold()), None)
        if category:
            target = numeric[0]
            rows = frame.groupby(category, dropna=False)[target].sum().reset_index(name=f"{target}_sum").to_dict(orient="records")
            tables["summary_by_region"] = _write_csv(output_dir, "summary_by_region", rows)
            evidence.append(EvidenceItem("B", f"按 {category} 汇总 {target}", tables["summary_by_region"].path))
    if "trend" in operations and numeric and len(frame.columns) >= 2:
        charts.append(_write_line_chart(output_dir, frame, frame.columns[0], numeric[0]))
    if "correlation" in operations and len(numeric) >= 2:
        rows = frame[numeric].corr().round(6).reset_index(names="column").to_dict(orient="records")
        tables["correlation"] = _write_csv(output_dir, "correlation", rows)
    if "anomaly" in operations and numeric:
        target, series = numeric[0], frame[numeric[0]].dropna()
        if len(series) >= 3:
            std = float(series.std(ddof=0)); count = int(((series - float(series.mean())).abs() > 3 * std).sum()) if std else 0
            tables["anomaly"] = _write_csv(output_dir, "anomaly", [{"column": target, "outlier_count": count}])
            evidence.append(EvidenceItem("B", f"按 3σ 规则检测到 {count} 个 {target} 异常值", tables["anomaly"].path))
    return RunResult(tables, charts, evidence, [f"input rows={len(frame)} columns={len(frame.columns)}"])
