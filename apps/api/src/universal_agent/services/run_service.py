from dataclasses import asdict
import json
from pathlib import Path
from uuid import UUID

import pandas as pd
from executor.forecasting import ForecastResult, forecast
from executor.runner import read_excel_and_run
from sqlalchemy.orm import Session

from universal_agent.services.decision_service import EvidenceItem, build_decision_report
from universal_agent.services.report_service import render_reports
from universal_agent.storage.repository import get_revision, get_selection_files


def _forecast_payload(result: ForecastResult) -> dict[str, object]:
    return {
        "target_column": result.target_column,
        "time_column": result.time_column,
        "test_start": result.test_start.isoformat(),
        "baseline_model": result.baseline_model,
        "baseline_metrics": asdict(result.baseline_metrics),
        "candidate_metrics": {name: asdict(metrics) for name, metrics in result.candidate_metrics.items()},
        "selected_model": result.selected_model,
        "selected_metrics": asdict(result.selected_metrics),
        "is_recommended": result.is_recommended,
        "backtest_folds": [
            {
                "train_end": fold.train_end.isoformat(),
                "test_time": fold.test_time.isoformat(),
                "actual": fold.actual,
                "predictions": fold.predictions,
            }
            for fold in result.backtest_folds
        ],
        "prediction_interval_80": [asdict(point) for point in result.prediction_interval_80],
        "residual_anomalies": [asdict(item) for item in result.residual_anomalies],
        "limitations": result.limitations,
    }


def _risk_payload(report) -> dict[str, object]:
    risk = report.risks[0]
    return {
        "description": risk.description,
        "probability": risk.probability,
        "impact": risk.impact,
        "severity": risk.severity,
        "controllability": risk.controllability,
        "evidence": [asdict(item) for item in risk.evidence],
        "uncertainty": risk.uncertainty,
        "mitigation": risk.mitigation,
        "human_review_required": risk.human_review_required,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_confirmed_plan(session: Session, revision_id: UUID) -> dict[str, object]:
    revision = get_revision(session, revision_id)
    if revision is None or revision.kind != "run":
        raise ValueError("analysis requires an immutable run revision")
    revision_files = get_selection_files(session, revision_id)
    if len(revision_files) != 1:
        raise ValueError("analysis run requires exactly one selected file in the MVP")
    source = revision_files[0]

    output = Path(".data") / "runs" / str(revision_id)
    if output.exists():
        raise ValueError("run artifact directory already exists")
    output.mkdir(parents=True)
    objective = str(revision.snapshot.get("objective", "")).strip()
    domain = next((name for name in ("medical", "legal", "financial", "chemical", "construction safety") if name in objective.casefold()), "general")
    if Path(source.path).suffix.lower() == ".docx":
        evidence = [EvidenceItem(level="A", artifact_id=None, summary=f"文档陈述：{item['text']}") for item in source.summary.get("text_evidence", [])]
        if not evidence:
            evidence = [EvidenceItem(level="A", artifact_id=None, summary="文档已读取，但未提取到非空段落。")]
        if objective:
            evidence.append(EvidenceItem(level="C", artifact_id=None, summary=f"用户前提：{objective}"))
        report = build_decision_report(evidence=evidence, domain=domain, user_marked_critical="critical" in objective.casefold() or "关键" in objective)
        report_paths = render_reports(report, output)
        decision_path = output / "decision.json"
        manifest_path = output / "run_manifest.json"
        _write_json(decision_path, {"evidence_by_level": {level: [asdict(item) for item in items] for level, items in report.evidence_by_level.items()}, "risk": _risk_payload(report), "options": [asdict(item) for item in report.options]})
        _write_json(manifest_path, {"revision_id": str(revision_id), "parent_revision_id": revision.snapshot.get("parent_revision_id"), "status": "succeeded", "source_file_id": source.id, "source_sha256": source.sha256, "operations": requested_operations})
        return {"tables": {}, "charts": [], "evidence": [asdict(item) for item in evidence], "evidence_by_level": {level: [asdict(item) for item in items] for level, items in report.evidence_by_level.items()}, "forecast": None, "risk": _risk_payload(report), "options": [asdict(item) for item in report.options], "reports": [str(path) for path in report_paths], "decision_artifacts": [str(decision_path), str(manifest_path)]}

    if Path(source.path).suffix.lower() not in {".xlsx", ".xls"}:
        raise ValueError("unsupported analysis file")
    requested_operations = revision.snapshot.get("operations", ["profile", "quality_check", "trend"])
    analysis_operations = [item for item in requested_operations if item != "forecast"]
    result = read_excel_and_run(Path(source.path), analysis_operations, output)
    frame = pd.read_excel(source.path)

    forecast_result = None
    date_columns = [
        name for name in frame.columns
        if any(token in str(name).casefold() for token in ("date", "month", "time", "日期", "时间", "月份"))
    ]
    numeric_columns = frame.select_dtypes(include="number").columns.tolist()
    if "forecast" in requested_operations and date_columns and numeric_columns:
        try:
            forecast_result = forecast(
                frame,
                time_column=date_columns[0],
                target_column=numeric_columns[0],
                horizon=min(3, max(1, len(frame) // 4)),
            )
        except ValueError:
            forecast_result = None

    evidence = [
        EvidenceItem(level=item.level, artifact_id=None, summary=item.summary)
        for item in result.evidence
    ]
    forecast_payload = None
    if forecast_result is not None:
        forecast_payload = _forecast_payload(forecast_result)
        evidence.append(EvidenceItem(
            level="C",
            artifact_id=None,
            summary=(
                f"按时间滚动回测比较朴素基线、ETS 与 ARIMA；选择 {forecast_result.selected_model}，"
                f"MAE={forecast_result.selected_metrics.mae:.3f}，RMSE={forecast_result.selected_metrics.rmse:.3f}。"
            ),
        ))
        if forecast_result.residual_anomalies:
            evidence.append(EvidenceItem(
                level="C",
                artifact_id=None,
                summary=f"回测残差识别出 {len(forecast_result.residual_anomalies)} 个异常时间点。",
            ))
    if objective:
        evidence.append(EvidenceItem(level="C", artifact_id=None, summary=f"用户前提：{objective}"))

    report = build_decision_report(evidence=evidence, domain=domain, user_marked_critical="critical" in objective.casefold() or "关键" in objective)
    report_paths = render_reports(report, output)
    risk_payload = _risk_payload(report)
    option_payload = [asdict(item) for item in report.options]
    decision_payload = {
        "evidence_by_level": {
            level: [asdict(item) for item in items]
            for level, items in report.evidence_by_level.items()
        },
        "risk": risk_payload,
        "options": option_payload,
    }
    forecast_path = output / "forecast.json"
    decision_path = output / "decision.json"
    manifest_path = output / "run_manifest.json"
    if forecast_payload is not None:
        _write_json(forecast_path, forecast_payload)
    _write_json(decision_path, decision_payload)
    _write_json(manifest_path, {
        "revision_id": str(revision_id),
        "parent_revision_id": revision.snapshot.get("parent_revision_id"),
        "status": "succeeded",
        "source_file_id": source.id,
        "source_sha256": source.sha256,
        "operations": requested_operations,
    })

    payload = result.as_dict()
    payload["forecast"] = forecast_payload
    payload["risk"] = risk_payload
    payload["options"] = option_payload
    payload["evidence_by_level"] = decision_payload["evidence_by_level"]
    payload["reports"] = [str(path) for path in report_paths]
    payload["decision_artifacts"] = [
        *([str(forecast_path)] if forecast_payload is not None else []),
        str(decision_path),
        str(manifest_path),
    ]
    return payload
