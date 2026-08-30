from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd


TYPE_KEYWORDS = {
    "trend": ("趋势", "变化", "上升", "下降", "环比", "同比"),
    "anomaly": ("异常", "波动", "拐点"),
    "ranking": ("排名", "最好", "最差", "最高", "最低", "哪些"),
    "risk": ("风险",),
    "forecast": ("预测", "预估", "forecast", "未来", "下一期"),
}
TIME_KEYWORDS = ("date", "time", "month", "period", "日期", "时间", "期间", "月份", "月")
METRIC_KEYWORDS = ("revenue", "sales", "amount", "gmv", "营收", "收入", "销售", "金额")
IDENTIFIER_KEYWORDS = ("id", "编号", "序号")
DIMENSION_KEYWORDS = ("region", "area", "product", "business", "customer", "地区", "区域", "产品", "业务", "客户")


@dataclass(frozen=True)
class QuestionPlan:
    objective: str
    types: tuple[str, ...]
    time_column: str | None
    metric_column: str | None
    dimension_column: str | None
    title: str
    metric_columns: tuple[str, ...] = ()
    period_start: pd.Timestamp | None = None
    period_end: pd.Timestamp | None = None


def session_title(objective: str) -> str:
    text = objective.lower()
    subject = "地区" if any(term in text for term in ("地区", "区域", "region", "area")) else "产品" if any(term in text for term in ("产品", "product")) else "客户" if any(term in text for term in ("客户", "customer")) else "月度" if any(term in text for term in ("月", "month")) else "数据"
    metric = "营收" if any(term in text for term in ("营收", "收入", "revenue")) else "销售" if any(term in text for term in ("销售", "sales")) else "GMV" if "gmv" in text else ""
    purpose = "风险" if "风险" in text else "预测" if any(term in text for term in TYPE_KEYWORDS["forecast"]) else "异常" if any(term in text for term in TYPE_KEYWORDS["anomaly"]) else "趋势" if any(term in text for term in TYPE_KEYWORDS["trend"]) else "分析"
    if subject == "数据" and metric:
        subject = ""
    return f"{subject}{metric}{purpose}"


def plan_question(frame: pd.DataFrame, objective: str) -> QuestionPlan:
    text = objective.lower()
    types = tuple(kind for kind, terms in TYPE_KEYWORDS.items() if any(term in text for term in terms)) or ("overview",)
    columns = [str(column) for column in frame.columns]
    time_column = _match(columns, TIME_KEYWORDS)
    numeric_columns = [str(column) for column in frame.select_dtypes(include="number").columns]
    metric_columns = _requested_metrics(columns, numeric_columns, text)
    if not metric_columns:
        metric_column = _match(numeric_columns, METRIC_KEYWORDS)
        if metric_column is None:
            metric_column = next((column for column in numeric_columns if not any(term in column.lower() for term in IDENTIFIER_KEYWORDS)), numeric_columns[0] if numeric_columns else None)
        metric_columns = (metric_column,) if metric_column else ()
    metric_column = metric_columns[0] if metric_columns else None
    dimension_column = _match(columns, DIMENSION_KEYWORDS) if _requests_dimension(text) else None
    if dimension_column is None and _requests_dimension(text):
        dimension_column = next((column for column in columns if column != time_column and column != metric_column and frame[column].dtype == "object"), None)
    period_start, period_end = _requested_period_range(objective)
    return QuestionPlan(objective, types, time_column, metric_column, dimension_column, session_title(objective), metric_columns, period_start, period_end)


def _match(columns: list[str], keywords: tuple[str, ...]) -> str | None:
    return next((column for column in columns if any(term in column.lower() for term in keywords)), None)


def _requested_metrics(columns: list[str], numeric_columns: list[str], text: str) -> tuple[str, ...]:
    requested: list[tuple[int, str]] = []
    for column in numeric_columns:
        position = text.find(column.lower())
        if position >= 0:
            requested.append((position, column))
    if "毛利率" in text and "营业收入" in columns and "毛利额" in columns:
        requested.append((text.find("毛利率"), "毛利率"))
    return tuple(name for _, name in sorted(requested, key=lambda item: item[0]))


def _requests_dimension(text: str) -> bool:
    return any(term in text for term in DIMENSION_KEYWORDS)


def _requested_period_range(objective: str) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    months = re.findall(r"(\d{4})\s*(?:-|/|年)\s*(\d{1,2})", objective)
    if len(months) < 2:
        return None, None
    parsed = [pd.Timestamp(year=int(year), month=int(month), day=1) for year, month in months[:2]]
    return min(parsed), max(parsed)
