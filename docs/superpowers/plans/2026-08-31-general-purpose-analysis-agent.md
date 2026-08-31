# 通用可信数据分析 Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 将固定财务模板改为可理解任意结构化文件、执行可复核计算并返回证据链的分析 Agent。

**Architecture:** 新建 profile、plan、executor、validator 四层；API 与 UI 只消费结构化结果。旧财务逻辑保留为通过通用算子执行的回归案例，不再参与默认字段选择。

**Tech Stack:** Python、pandas、numpy、Plotly、FastAPI、React、pytest、Vitest。

**Spec:** `docs/superpowers/specs/2026-08-31-general-purpose-analysis-agent-design.md`

## Global Constraints

- 不得以地区、营收、月份、产品、客户等名称作为默认分析路径。
- 每个数字必须来自 executor 的可复算 finding，携带文件 hash、表、字段和计算说明。
- 字段语义置信度低于 0.70 时不得自动用于关键结论。
- 不足数据时返回 `PARTIAL` 或 `INSUFFICIENT_DATA`，不生成数值结论。
- 仅在 `codex/universal-analysis-agent-mvp` 分支实施，不合并 master。

---

### Task 1: 通用文件读取与 Schema Profile

**Files:**
- Create: `backend/studio_api/profiling.py`
- Modify: `backend/studio_api/intake.py`
- Modify: `backend/tests/test_analysis_workflow.py`

**Produces:** `DatasetProfile`、`TableProfile`、`ColumnProfile`，含 `file_hash`、所有表、字段角色及置信度。

- [ ] **Step 1: 写失败测试**

```python
def test_profile_classifies_nonstandard_order_fields_without_fixed_business_names(tmp_path):
    profile = profile_file(write_csv(tmp_path, ["dt", "col1", "value_x"], [["2026-01-01", "A", 12]]))
    assert profile.tables[0].columns[0].semantic_role == "time"
    assert profile.tables[0].columns[2].semantic_role == "metric"
```

- [ ] **Step 2: 运行 RED**

Run: `python -m pytest backend/tests/test_analysis_workflow.py::test_profile_classifies_nonstandard_order_fields_without_fixed_business_names -q`

- [ ] **Step 3: 实现 profile 类型和解析器**

```python
@dataclass(frozen=True)
class ColumnProfile:
    name: str; physical_type: str; semantic_role: str; confidence: float

def profile_file(path: Path) -> DatasetProfile: ...
```

- [ ] **Step 4: 验证与提交**

Run: `python -m pytest backend/tests -q`

Commit: `feat: profile arbitrary structured datasets`

### Task 2: 问题计划与基础通用算子

**Files:**
- Create: `backend/studio_api/planning.py`
- Create: `backend/studio_api/execution.py`
- Modify: `backend/tests/test_analysis_workflow.py`

**Consumes:** Task 1 的 `DatasetProfile`。
**Produces:** `AnalysisPlan` 和 `ComputedFinding`，支持排名、时间趋势、异常、分组差异、相关性和不足数据状态。

- [ ] **Step 1: 写失败测试**

```python
def test_plan_ranks_the_requested_dimension_and_metric():
    plan = build_plan(order_profile, "哪个产品销售额最高？")
    result = execute_plan(order_frame, plan)
    assert result.findings[0].value == "A"
    assert result.findings[0].evidence.calculation == "groupby(product).sum(amount)"
```

- [ ] **Step 2: 运行 RED**

Run: `python -m pytest backend/tests/test_analysis_workflow.py::test_plan_ranks_the_requested_dimension_and_metric -q`

- [ ] **Step 3: 实现允许算子与不足数据路径**

```python
def build_plan(profile: DatasetProfile, question: str) -> AnalysisPlan: ...
def execute_plan(tables: dict[str, pd.DataFrame], plan: AnalysisPlan) -> ExecutionResult: ...
```

- [ ] **Step 4: 验证与提交**

Run: `python -m pytest backend/tests -q`

Commit: `feat: plan and execute generic analysis questions`

### Task 3: 证据链与结果验证器

**Files:**
- Create: `backend/studio_api/validation.py`
- Modify: `backend/studio_api/engine.py`
- Modify: `backend/tests/test_analysis_workflow.py`

**Produces:** `SUCCESS`、`PARTIAL`、`INSUFFICIENT_DATA` 的结构化结果，所有 finding 包含 source/fields/filter/calculation/value/confidence。

- [ ] **Step 1: 写失败测试**

```python
def test_validator_rejects_a_numeric_finding_without_calculation_evidence():
    assert validate_result(untraceable_result).status == "INSUFFICIENT_DATA"
```

- [ ] **Step 2: 运行 RED**

Run: `python -m pytest backend/tests/test_analysis_workflow.py::test_validator_rejects_a_numeric_finding_without_calculation_evidence -q`

- [ ] **Step 3: 实现证据和验证**

```python
def validate_result(result: ExecutionResult, profile: DatasetProfile) -> ValidatedResult: ...
```

- [ ] **Step 4: 验证与提交**

Run: `python -m pytest backend/tests -q`

Commit: `feat: validate and trace analysis findings`

### Task 4: 多 Sheet、多文件候选关联与可复现保存

**Files:**
- Modify: `backend/studio_api/intake.py`
- Modify: `backend/studio_api/store.py`
- Modify: `backend/studio_api/app.py`
- Modify: `backend/tests/test_analysis_workflow.py`

**Produces:** 绑定 `file_hash` 的 profile snapshot、候选 join 与可重跑的分析 metadata。

- [ ] **Step 1: 写失败测试**

```python
def test_multi_sheet_profile_reports_high_confidence_join_without_auto_joining_ambiguous_keys():
    assert candidate.confidence >= .95
    assert ambiguous_result.status == "PARTIAL"
```

- [ ] **Step 2: 运行 RED**

Run: `python -m pytest backend/tests/test_analysis_workflow.py::test_multi_sheet_profile_reports_high_confidence_join_without_auto_joining_ambiguous_keys -q`

- [ ] **Step 3: 实现快照与关联候选**

```python
def infer_joins(tables: tuple[TableProfile, ...]) -> tuple[JoinCandidate, ...]: ...
```

- [ ] **Step 4: 验证与提交**

Run: `python -m pytest backend/tests -q`

Commit: `feat: preserve dataset versions and join candidates`

### Task 5: 结构化结果页面与证据展开

**Files:**
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`
- Modify: `apps/web/tests/App.test.tsx`

**Consumes:** `ValidatedResult`。
**Produces:** 问题、直接答案、结论、图表、可展开证据和限制；仅渲染有内容的模块。

- [ ] **Step 1: 写失败组件测试**

```tsx
render(<ResultPanel session={traceableSession} tab="结果" />)
expect(screen.getByText("结论依据")).toBeInTheDocument()
expect(screen.getByText("groupby(product).sum(amount)")).toBeInTheDocument()
expect(screen.queryByText("业务风险")).not.toBeInTheDocument()
```

- [ ] **Step 2: 运行 RED**

Run: `pnpm --dir apps/web test -- --run`

- [ ] **Step 3: 实现结构化渲染与状态提示**

```tsx
type Finding = { conclusion: string; evidence: Evidence; confidence: number };
```

- [ ] **Step 4: 验证与提交**

Run: `pnpm --dir apps/web test -- --run && pnpm --dir apps/web build`

Commit: `feat: render traceable generic analysis results`

### Task 6: 十类通用验收与对抗性审查

**Files:**
- Modify: `backend/tests/test_analysis_workflow.py`
- Modify: `apps/web/tests/App.test.tsx`

**Produces:** 电商、交通、成绩、日志、库存、财务、无时间预测、非规范字段、多 Sheet、多文件的端到端断言。

- [ ] **Step 1: 写失败验收用例**

```python
def test_prediction_without_time_returns_insufficient_data():
    assert analyse(non_temporal_frame, "预测未来趋势")["status"] == "INSUFFICIENT_DATA"
```

- [ ] **Step 2: 运行 RED**

Run: `python -m pytest backend/tests/test_analysis_workflow.py -q`

- [ ] **Step 3: 补齐最小实现缺口**

```python
assert all(finding["evidence"]["source"]["file_hash"] for finding in result["findings"])
```

- [ ] **Step 4: 全量验证与提交**

Run: `python -m pytest backend/tests -q && pnpm --dir apps/web test -- --run && pnpm --dir apps/web build`

Commit: `test: accept generic traceable analysis scenarios`
