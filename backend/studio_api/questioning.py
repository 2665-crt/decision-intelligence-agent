from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


TYPE_KEYWORDS = {
    "trend": ("趋势", "变化", "上升", "下降", "环比", "同比"),
    "anomaly": ("异常", "波动", "拐点"),
    "ranking": ("排名", "最好", "最差", "最高", "最低", "哪些"),
    "risk": ("风险",),
    "forecast": ("预测", "预估", "forecast", "未来", "下一期"),
}
TIME_KEYWORDS = ("date", "time", "month", "日期", "时间", "月份", "月")
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
    metric_column = next((column for column in numeric_columns if column.lower() in text), None) or _match(numeric_columns, METRIC_KEYWORDS)
    if metric_column is None:
        metric_column = next((column for column in numeric_columns if not any(term in column.lower() for term in IDENTIFIER_KEYWORDS)), numeric_columns[0] if numeric_columns else None)
    dimension_column = _match(columns, DIMENSION_KEYWORDS)
    if dimension_column is None:
        dimension_column = next((column for column in columns if column != time_column and column != metric_column and frame[column].dtype == "object"), None)
    return QuestionPlan(objective, types, time_column, metric_column, dimension_column, session_title(objective))


def _match(columns: list[str], keywords: tuple[str, ...]) -> str | None:
    return next((column for column in columns if any(term in column.lower() for term in keywords)), None)
