import json
from pathlib import Path
from uuid import uuid4

from universal_agent.services.decision_service import EvidenceItem, Option, build_decision_report


def test_high_risk_domain_requires_review_and_evidence() -> None:
    report = build_decision_report(
        evidence=[EvidenceItem(level="A", artifact_id=uuid4(), summary="逾期率为 18%")],
        domain="construction safety",
    )

    assert report.risks[0].human_review_required is True
    assert report.risks[0].evidence[0].level == "A"
    assert report.risks[0].probability in {"low", "medium", "high"}
    assert report.risks[0].impact in {"low", "medium", "high"}
    assert report.risks[0].severity in {"low", "medium", "high", "critical"}
    assert report.risks[0].controllability in {"low", "medium", "high"}
    assert report.risks[0].uncertainty
    assert report.risks[0].mitigation


def test_report_preserves_all_evidence_levels_and_option_tradeoffs() -> None:
    evidence = [
        EvidenceItem(level="A", artifact_id=None, summary="原始表共 18 行"),
        EvidenceItem(level="B", artifact_id=None, summary="逾期率呈上升趋势"),
        EvidenceItem(level="C", artifact_id=None, summary="未来三期预测区间扩大"),
        EvidenceItem(level="D", artifact_id=None, summary="假设资源供给保持不变"),
    ]
    options = [Option(
        name="小范围试点",
        expected_benefit=0.8,
        implementation_cost=0.3,
        potential_harm=0.2,
        uncertainty=0.25,
        assumptions=["人员可用"],
        validation_metric="逾期率下降 10%",
    )]

    report = build_decision_report(evidence=evidence, domain="general", options=options)

    assert set(report.evidence_by_level) == {"A", "B", "C", "D"}
    assert report.options[0].expected_benefit == 0.8
    assert report.options[0].implementation_cost == 0.3
    assert report.options[0].potential_harm == 0.2
    assert report.options[0].assumptions == ["人员可用"]
    assert report.options[0].validation_metric == "逾期率下降 10%"


def test_report_schema_requires_risk_and_option_tradeoff_fields() -> None:
    schema = json.loads(Path("contracts/report.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["evidence"]["items"]["properties"]["level"]["enum"] == ["A", "B", "C", "D"]
    assert {
        "description", "probability", "impact", "severity", "controllability",
        "evidence", "uncertainty", "mitigation", "human_review_required",
    } <= set(schema["properties"]["risks"]["items"]["required"])
    assert {
        "name", "expected_benefit", "implementation_cost", "potential_harm",
        "uncertainty", "assumptions", "validation_metric", "hard_constraints_met",
    } <= set(schema["properties"]["options"]["items"]["required"])
