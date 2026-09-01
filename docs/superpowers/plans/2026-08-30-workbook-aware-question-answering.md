# 工作簿感知的多指标问题回答实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对复杂 Excel 财务工作簿直接回答用户点名的多指标分析问题，并用真实样例验证结果。

**Architecture:** 读取层选择真实的表格区域并携带来源元数据；问题层解析多个指标和时间范围；回答层对每个指标构建月度序列、异常证据和图表。前端复用现有结论优先布局，只扩展多指标结果类型。

**Tech Stack:** Python 3、pandas、openpyxl、Plotly、FastAPI、React、Vitest、pytest。

**Spec:** `docs/superpowers/specs/2026-08-30-workbook-aware-question-answering-design.md`

## Global Constraints

- 仅在 `codex/universal-analysis-agent-mvp` 实验分支修改，不合并 master。
- 关键结论必须来自数据，原因只能表述为数据可支持的推断。
- 用户请求趋势、异常、对比或预测时至少生成一张有意义的图表。
- 数据质量保留在默认折叠的次要区域。

---

### Task 1: 工作簿表格区域识别

**Files:**
- Modify: `backend/studio_api/intake.py`
- Modify: `backend/tests/test_analysis_workflow.py`

**Interfaces:**
- Produces: `read_spreadsheet(path) -> pandas.DataFrame`，其 `attrs` 包含 `source_sheet` 与 `header_row`。

- [ ] **Step 1: 写入失败测试**

```python
def test_read_spreadsheet_selects_a_monthly_table_after_cover_rows(tmp_path):
    frame = read_spreadsheet(write_financial_workbook(tmp_path))
    assert frame.attrs["source_sheet"] == "财务汇总"
    assert frame.attrs["header_row"] == 3
    assert {"期间", "营业收入", "毛利率", "营业利润"} <= set(frame.columns)
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_analysis_workflow.py::test_read_spreadsheet_selects_a_monthly_table_after_cover_rows -q`

- [ ] **Step 3: 实现候选工作表与表头评分读取器**

```python
def read_spreadsheet(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return _best_table(pd.ExcelFile(path))
```

- [ ] **Step 4: 运行该测试和后端全量测试**

Run: `python -m pytest backend/tests -q`

### Task 2: 多指标问题规划与证据答案

**Files:**
- Modify: `backend/studio_api/questioning.py`
- Modify: `backend/studio_api/answering.py`
- Modify: `backend/tests/test_analysis_workflow.py`

**Interfaces:**
- Consumes: 任务 1 返回的标准化 DataFrame。
- Produces: `QuestionPlan.metric_columns: tuple[str, ...]` 和结果中的 `key_metrics`、`sections`、`charts`。

- [ ] **Step 1: 写入失败测试**

```python
def test_financial_question_answers_all_requested_metrics_with_monthly_evidence(tmp_path):
    result = analyse_spreadsheet(read_spreadsheet(write_financial_workbook(tmp_path)), REQUEST, tmp_path)
    assert all(name in result["core_conclusion"] for name in ("营业收入", "毛利率", "营业利润"))
    assert "2025-03" in result["core_conclusion"]
    assert result["charts"]
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_analysis_workflow.py::test_financial_question_answers_all_requested_metrics_with_monthly_evidence -q`

- [ ] **Step 3: 实现多指标、日期范围、异常与原因推断**

```python
@dataclass(frozen=True)
class QuestionPlan:
    metric_columns: tuple[str, ...]
    period_start: pd.Timestamp | None
    period_end: pd.Timestamp | None
```

- [ ] **Step 4: 运行新增测试与后端全量测试**

Run: `python -m pytest backend/tests -q`

### Task 3: 页面类型适配与真实文件验收

**Files:**
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/tests/App.test.tsx`

**Interfaces:**
- Consumes: 多指标 `key_metrics` 与 `analysis.plan.metric_columns`。
- Produces: 首屏可读的核心结论、三项关键数据、折叠质量区和现有语义化任务标签。

- [ ] **Step 1: 写入失败组件测试**

```tsx
render(<ResultPanel session={financialSession} tab="结果" />)
expect(screen.getByText("核心结论")).toBeInTheDocument()
expect(screen.getByText("营业收入")).toBeInTheDocument()
expect(screen.queryByText(/缺失.*单元格/)).not.toBeVisible()
```

- [ ] **Step 2: 运行失败测试**

Run: `pnpm --dir apps/web test -- --run`

- [ ] **Step 3: 调整前端类型和结果层级展示**

```tsx
type KeyMetric = { label: string; value: string; detail?: string };
```

- [ ] **Step 4: 构建与真实 API 验收**

Run: `pnpm --dir apps/web build`，再上传测试者提供的财务样例文件并运行指定问题；逐条核对 16 项验收标准。
