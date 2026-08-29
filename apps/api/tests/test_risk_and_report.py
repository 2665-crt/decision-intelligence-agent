from uuid import uuid4

from universal_agent.services.decision_service import EvidenceItem, build_decision_report


def test_high_risk_domain_requires_review_and_evidence() -> None:
    report = build_decision_report(
        evidence=[EvidenceItem(level="A", artifact_id=uuid4(), summary="逾期率为 18%")],
        domain="construction safety",
    )

    assert report.risks[0].human_review_required is True
    assert report.risks[0].evidence[0].level == "A"
