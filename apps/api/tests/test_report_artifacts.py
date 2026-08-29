from docx import Document

from universal_agent.services.decision_service import EvidenceItem, build_decision_report
from universal_agent.services.report_service import render_reports


def test_report_writes_three_formats_and_separates_suggestions(tmp_path) -> None:
    report = build_decision_report(
        evidence=[EvidenceItem(level="A", artifact_id=None, summary="收入较上一期下降 12%")],
        domain="general",
    )

    artifacts = render_reports(report, tmp_path)

    assert {item.suffix for item in artifacts} == {".md", ".html", ".docx"}
    assert "待验证建议" in (tmp_path / "report.md").read_text(encoding="utf-8")
    headings = [paragraph.text for paragraph in Document(tmp_path / "report.docx").paragraphs]
    assert "文件事实" in headings
    assert "待验证建议" in headings
