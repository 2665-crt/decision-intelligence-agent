from html import escape
from pathlib import Path
from docx import Document
from universal_agent.services.decision_service import DecisionReport

def _markdown(report: DecisionReport) -> str:
    facts = "\n".join(f"- [{item.level}] {item.summary}" for item in report.evidence)
    risks = "\n".join(f"- {item.description}（人工复核：{'是' if item.human_review_required else '否'}）" for item in report.risks)
    suggestions = "\n".join(f"- {item}" for item in report.suggestions)
    return f"# 决策支持报告\n\n## 文件事实\n{facts}\n\n## 风险\n{risks}\n\n## 待验证建议\n{suggestions}\n"

def render_reports(report: DecisionReport, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown = _markdown(report); md_path = output_dir / "report.md"; html_path = output_dir / "report.html"; docx_path = output_dir / "report.docx"
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(f"<!doctype html><meta charset='utf-8'><pre>{escape(markdown)}</pre>", encoding="utf-8")
    document = Document()
    for title, entries in (("文件事实", [item.summary for item in report.evidence]), ("风险", [item.description for item in report.risks]), ("待验证建议", report.suggestions)):
        document.add_heading(title, level=1)
        for entry in entries: document.add_paragraph(entry, style="List Bullet")
    document.save(docx_path)
    return [md_path, html_path, docx_path]
