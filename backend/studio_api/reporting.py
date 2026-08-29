from html import escape
from pathlib import Path

from docx import Document


def render(job: dict, result: dict, directory: Path, route: str = "jobs") -> list[dict]:
    reports = directory / "reports"
    reports.mkdir(exist_ok=True)
    lines = [
        "# 数据分析决策报告",
        f"\n## 分析目标\n{job['objective']}",
        "\n## 数据事实",
        *[f"- {item['summary']}" for item in result['evidence']],
        "\n## 风险",
        *[f"- {item['title']}（{item['level']}）：{'；'.join(item['evidence'])}" for item in result['risks']],
        "\n## 待验证建议",
        *[f"- {item['name']}：{item['next_step']}" for item in result['options']],
        "\n## 限制",
        *[f"- {item}" for item in result['limitations']],
    ]
    if result["forecast"]:
        lines.extend(["\n## 预测", f"- 推荐：{result['forecast'].get('is_recommended')}；模型：{result['forecast'].get('model', '不适用')}。"])
    markdown = "\n".join(lines) + "\n"
    (reports / "report.md").write_text(markdown, encoding="utf-8")
    (reports / "report.html").write_text(f"<html><meta charset='utf-8'><body><pre>{escape(markdown)}</pre></body></html>", encoding="utf-8")
    document = Document()
    document.add_heading("数据分析决策报告", 0)
    for heading, content in (("分析目标", job["objective"]), ("文件事实", "\n".join(item["summary"] for item in result["evidence"])), ("风险", "\n".join(item["title"] for item in result["risks"])), ("待验证建议", "\n".join(item["name"] for item in result["options"]))):
        document.add_heading(heading, level=1)
        document.add_paragraph(content)
    document.save(reports / "report.docx")
    return [
        {"format": "markdown", "download_url": f"/api/{route}/{job['id']}/files/reports/report.md"},
        {"format": "html", "download_url": f"/api/{route}/{job['id']}/files/reports/report.html"},
        {"format": "docx", "download_url": f"/api/{route}/{job['id']}/files/reports/report.docx"},
    ]
