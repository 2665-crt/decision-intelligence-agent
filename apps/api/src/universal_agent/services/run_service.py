from pathlib import Path
from uuid import UUID

import pandas as pd
from executor.forecasting import forecast
from executor.runner import read_excel_and_run
from sqlalchemy.orm import Session

from universal_agent.storage.repository import get_selection_files
from universal_agent.services.decision_service import EvidenceItem, build_decision_report
from universal_agent.services.report_service import render_reports

def run_confirmed_plan(session: Session, revision_id: UUID) -> dict:
    revision_files = get_selection_files(session, revision_id)
    if len(revision_files) != 1:
        raise ValueError("analysis run requires exactly one selected spreadsheet")
    source = revision_files[0]
    if Path(source.path).suffix.lower() not in {".xlsx", ".xls"}:
        raise ValueError("Word documents provide statements, not numeric analysis frames")
    output = Path(".data") / "runs" / str(revision_id)
    result = read_excel_and_run(Path(source.path), ["profile", "quality_check", "trend"], output)
    frame = pd.read_excel(source.path)
    forecast_result = None
    date_columns = [name for name in frame.columns if "date" in name.casefold() or "month" in name.casefold() or "time" in name.casefold()]
    numeric_columns = frame.select_dtypes(include="number").columns.tolist()
    if date_columns and numeric_columns:
        try:
            forecast_result = forecast(frame, time_column=date_columns[0], target_column=numeric_columns[0], horizon=min(3, max(1, len(frame) // 4)))
        except ValueError:
            forecast_result = None
    evidence = [EvidenceItem(level=item["level"], artifact_id=None, summary=item["summary"]) for item in result.as_dict()["evidence"]]
    report = build_decision_report(evidence=evidence, domain="general")
    report_paths = render_reports(report, output)
    payload = result.as_dict()
    payload["forecast"] = None if forecast_result is None else {
        "baseline_metrics": {"mae": forecast_result.baseline_metrics.mae},
        "selected_metrics": {"mae": forecast_result.selected_metrics.mae},
        "is_recommended": forecast_result.is_recommended,
        "limitations": forecast_result.limitations,
    }
    payload["risk"] = {"human_review_required": report.risks[0].human_review_required, "evidence": [item.summary for item in report.risks[0].evidence]}
    payload["reports"] = [str(path) for path in report_paths]
    return payload
