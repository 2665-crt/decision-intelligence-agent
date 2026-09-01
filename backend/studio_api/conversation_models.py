from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_ANALYSIS_STATE: dict[str, Any] = {
    "active_file_ids": [],
    "active_sheet": "",
    "filters": {},
    "date_range": {},
    "metrics": [],
    "dimensions": [],
    "previous_findings": [],
    "previous_calculations": [],
    "previous_charts": [],
    "current_question": "",
    "current_analysis_goal": "",
    "generated_reports": [],
}


def initial_analysis_state(file_ids: list[str] | None = None) -> dict[str, Any]:
    state = deepcopy(DEFAULT_ANALYSIS_STATE)
    state["active_file_ids"] = list(file_ids or [])
    return state


def merge_state(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_ANALYSIS_STATE)
    merged.update(current)
    for key, value in patch.items():
        if key in {"filters", "date_range"} and isinstance(value, dict):
            existing = merged.get(key)
            merged[key] = {**(existing if isinstance(existing, dict) else {}), **value}
        else:
            merged[key] = value
    return merged
