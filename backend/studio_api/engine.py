from __future__ import annotations

from pathlib import Path

from docx import Document

from .answering import analyse_spreadsheet
from .intake import read_spreadsheet


HIGH_REVIEW_TERMS = ("医疗", "病", "法律", "合同", "金融", "贷款", "化工", "施工安全", "安全事故")


def run(job: dict, directory: Path, source: Path | None = None) -> dict:
    source = source or next(directory.glob("source.*"))
    if job["intake"]["kind"] == "document":
        result = analyse_document(source, job["objective"])
    else:
        result = analyse_spreadsheet(read_spreadsheet(source), job["objective"], directory)
    result["notebook_cells"] = notebook_cells(job["intake"]["kind"], job["objective"])
    result["status"] = "succeeded"
    return result


def notebook_cells(kind: str, objective: str) -> list[dict]:
    if kind == "document":
        return [{"language": "python", "title": "文档审阅", "code": "from docx import Document\n\ndocument = Document('source.docx')\nstatements = [p.text.strip() for p in document.paragraphs if p.text.strip()]"}]
    return [{"language": "python", "title": "读取与问题分析", "code": f"objective = {objective!r}\n# 根据问题类型选择固定的趋势、异常、排名、风险或预测函数。"}]


def analyse_document(source: Path, objective: str) -> dict:
    document = Document(source)
    statements = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    evidence = [{"level": "document_statement", "summary": f"文档陈述：{statement}"} for statement in statements[:10]]
    conclusion = statements[0] if statements else "文档没有可提取的段落文本，无法回答分析问题。"
    risk = {"title": "文档主张待核验", "object": "文档陈述", "level": "medium", "evidence": ["DOCX 内容为文本陈述，不等同于测量数据或已验证事实。"], "human_review_required": any(term in objective for term in HIGH_REVIEW_TERMS), "mitigation": "将关键主张映射到原始数据、责任人或审计证据后再决策。"}
    return {"analysis": {"kind": "document_review", "statement_count": len(statements)}, "core_conclusion": conclusion, "key_metrics": [{"label": "文档陈述", "value": str(len(statements)), "detail": "条"}], "sections": [{"title": "文档证据", "items": [{"text": item["summary"]} for item in evidence]}], "business_risks": [risk], "data_quality": {"summary": "文档内容不包含可验证测量数据。", "limitations": ["需要原始表格数据才能做统计分析。"]}, "charts": [], "forecast": None, "evidence": evidence or [{"level": "document_statement", "summary": "文档没有可提取的段落文本。"}], "risks": [risk], "suggestions": [], "options": [], "limitations": ["文档审阅不验证文本中的数字或事实；需要提供原始数据才能做统计推断。"]}
