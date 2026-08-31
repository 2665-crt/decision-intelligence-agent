from __future__ import annotations

from pathlib import Path

from docx import Document

from .execution import execute_plan
from .planning import build_plan
from .profiling import profile_file, read_tables
from .validation import validate_result


HIGH_REVIEW_TERMS = ("医疗", "病", "法律", "合同", "金融", "贷款", "化工", "施工安全", "安全事故")


def run(job: dict, directory: Path, source: Path | None = None) -> dict:
    source = source or next(directory.glob("source.*"))
    if job["intake"]["kind"] == "document":
        result = analyse_document(source, job["objective"])
    else:
        result = analyse_structured(source, job["objective"])
    result["notebook_cells"] = notebook_cells(job["intake"]["kind"], job["objective"])
    result["validation_status"] = result.pop("status")
    result["status"] = "succeeded"
    return result


def notebook_cells(kind: str, objective: str) -> list[dict]:
    if kind == "document":
        return [{"language": "python", "title": "文档审阅", "code": "from docx import Document\n\ndocument = Document('source.docx')\nstatements = [p.text.strip() for p in document.paragraphs if p.text.strip()]"}]
    return [{"language": "python", "title": "读取与问题分析", "code": f"objective = {objective!r}\n# 根据数据画像和问题选择允许的受控计算。"}]


def analyse_structured(source: Path, objective: str) -> dict:
    profile = profile_file(source)
    tables = dict(read_tables(source))
    plan = build_plan(profile, objective)
    validated = validate_result(execute_plan(tables, plan), profile)
    result = validated.to_dict()
    result.update(
        {
            "analysis": {
                "kind": "structured_analysis",
                "profile": profile.to_dict(),
                "plan": {
                    "question": plan.question,
                    "status": plan.status,
                    "table": plan.table,
                    "operations": list(plan.operations),
                    "fields": plan.fields,
                    "aggregation": plan.aggregation,
                    "parameters": plan.parameters,
                },
            },
            "core_conclusion": result["answer"],
            "key_metrics": [
                {
                    "label": finding["kind"],
                    "value": str(finding["metric_value"]),
                    "detail": finding["conclusion"],
                }
                for finding in result["findings"]
                if finding["metric_value"] is not None
            ],
            "sections": ([{"title": "分析结论", "items": [{"text": finding["conclusion"]} for finding in result["findings"]]}] if result["findings"] else []),
            "data_quality": {
                "summary": "结论仅使用通过证据校验的受控计算结果。",
                "limitations": result["limitations"],
            },
            "charts": [],
        }
    )
    return result


def analyse_document(source: Path, objective: str) -> dict:
    document = Document(source)
    statements = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    evidence = [{"level": "document_statement", "summary": f"文档陈述：{statement}"} for statement in statements[:10]]
    conclusion = statements[0] if statements else "文档没有可提取的段落文本，无法回答分析问题。"
    risk = {"title": "文档主张待核验", "object": "文档陈述", "level": "medium", "evidence": ["DOCX 内容为文本陈述，不等同于测量数据或已验证事实。"], "human_review_required": any(term in objective for term in HIGH_REVIEW_TERMS), "mitigation": "将关键主张映射到原始数据、责任人或审计证据后再决策。"}
    return {"status": "SUCCESS", "answer": conclusion, "findings": [], "analysis": {"kind": "document_review", "statement_count": len(statements)}, "core_conclusion": conclusion, "key_metrics": [{"label": "文档陈述", "value": str(len(statements)), "detail": "条"}], "sections": [{"title": "文档证据", "items": [{"text": item["summary"]} for item in evidence]}], "business_risks": [risk], "data_quality": {"summary": "文档内容不包含可验证测量数据。", "limitations": ["需要原始表格数据才能做统计分析。"]}, "charts": [], "evidence": evidence or [{"level": "document_statement", "summary": "文档没有可提取的段落文本。"}], "risks": [risk], "suggestions": [], "options": [], "limitations": ["文档审阅不验证文本中的数字或事实；需要提供原始数据才能做统计推断。"]}
