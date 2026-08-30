# 问题驱动分析结果与多任务标签重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让每个电子表格分析围绕用户问题生成带数字证据的直接答案，并让多任务标签保持可读、可切换。

**Architecture:** 后端将问题语义、字段角色和可复算统计统一为 QuestionPlan，由问题专用分析函数生成稳定结果合同；完整性闸门阻止质量报告伪装成回答。前端仅渲染合同的优先级结构，并为 Session 标签增加短标题、截断、提示、滚动和最近任务选择。

**Tech Stack:** Python 3、FastAPI、pandas、numpy、Plotly、python-docx、React、TypeScript、Vite、Vitest、Testing Library。

**Spec:** docs/superpowers/specs/2026-08-30-question-driven-analysis-and-task-tabs-design.md

## Global Constraints

- 不调用模型生成的代码、shell 或外部数据源；每个结论必须从上传数据可复算。
- 电子表格成功结果必须有 core_conclusion、对象、数值证据；趋势、异常、风险、预测还需满足各自专属字段。
- 预测只使用时间切分与朴素基线对照；条件不满足时返回明确原因，不伪造预测。
- 数据质量默认只在“数据质量与分析限制”折叠区显示，除非影响具体结论。
- 图表型问题有可用数据时至少输出一张与问题匹配的核心图表。
- 自动标题为 4–10 个中文字符左右且不得使用“分析任务N/副本”；重复使用 “ · N”。
- 标签宽度固定在 120px–220px，溢出横向滚动，完整原问题可以通过 Tooltip 读取。

---

### Task 1: 问题意图、字段角色与语义任务命名

**Files:**
- Create: backend/studio_api/questioning.py
- Modify: backend/studio_api/app.py
- Modify: backend/studio_api/store.py
- Test: backend/tests/test_analysis_workflow.py

**Interfaces:**
- Produces QuestionPlan(types, time_column, metric_column, dimension_column, title) and plan_question(frame, objective).
- Produces session_title(objective) and unique_session_title(dataset_id, base_title).
- Consumes list_sessions(dataset_id) without changing persisted objective.

- [ ] **Step 1: Write the failing test**

    def test_semantic_session_titles_are_short_and_duplicates_are_numbered():
        first = client.post("/api/sessions", json={"dataset_id": dataset_id, "objective": "分析不同地区营收情况，检测异常地区并预测未来营收风险"})
        second = client.post("/api/sessions", json={"dataset_id": dataset_id, "objective": "分析不同地区营收情况，检测异常地区并预测未来营收风险"})
        assert first.json()["title"] == "地区营收风险"
        assert second.json()["title"] == "地区营收风险 · 2"

    def test_question_plan_recognises_region_revenue_risk_request():
        plan = plan_question(frame, "检测地区营收异常风险并预测未来风险")
        assert set(plan.types) == {"anomaly", "risk", "forecast"}
        assert (plan.time_column, plan.metric_column, plan.dimension_column) == ("month", "revenue", "region")

- [ ] **Step 2: Run test to verify it fails**

Run: python -m pytest backend/tests/test_analysis_workflow.py -k "semantic_session_titles or question_plan" -v

Expected: FAIL because questioning and semantic duplicate naming do not exist.

- [ ] **Step 3: Write minimal implementation**

    @dataclass(frozen=True)
    class QuestionPlan:
        types: tuple[str, ...]
        time_column: str | None
        metric_column: str | None
        dimension_column: str | None
        title: str

    def plan_question(frame: pd.DataFrame, objective: str) -> QuestionPlan:
        # Match ordered Chinese/English keywords and real column names.
        # Return only analysis types the question explicitly requests.

Use fixed title components and call unique_session_title before creating and copying a session.

- [ ] **Step 4: Run test to verify it passes**

Run: python -m pytest backend/tests/test_analysis_workflow.py -k "semantic_session_titles or question_plan" -v

Expected: PASS.

- [ ] **Step 5: Commit**

    git add backend/studio_api/questioning.py backend/studio_api/app.py backend/studio_api/store.py backend/tests/test_analysis_workflow.py
    git commit -m "feat: classify questions and name sessions semantically"

### Task 2: 问题专用分析、图表和完整性闸门

**Files:**
- Create: backend/studio_api/answering.py
- Modify: backend/studio_api/engine.py
- Test: backend/tests/test_analysis_workflow.py

**Interfaces:**
- Consumes QuestionPlan and pandas.DataFrame.
- Produces build_question_answer(frame, plan, directory) with core_conclusion, key_metrics, sections, business_risks, data_quality, charts, forecast and limitations.
- Produces validate_answer_completeness(answer, plan); an empty list permits a succeeded Session.

- [ ] **Step 1: Write the failing test**

    def test_region_revenue_risk_answers_with_object_numbers_and_chart():
        result = analyse_uploaded("检测地区营收异常风险")
        assert "south" in result["core_conclusion"].lower()
        assert any(char.isdigit() for char in result["core_conclusion"])
        assert result["business_risks"][0]["object"] == "south"
        assert result["business_risks"][0]["level"] == "high"
        assert result["charts"]

    def test_trend_and_anomaly_sections_include_direction_object_and_magnitude():
        result = analyse_uploaded("分析月度营收趋势，找出下降最严重地区和异常月份")
        headings = [section["title"] for section in result["sections"]]
        assert "趋势分析" in headings and "异常对象" in headings
        assert any("下降" in item["text"] and "%" in item["text"] for section in result["sections"] for item in section["items"])

    def test_forecast_returns_interval_or_explains_missing_time_series_conditions():
        result = analyse_uploaded("预测未来营收")
        assert result["forecast"]["prediction_interval_80"] or result["forecast"]["limitations"]

- [ ] **Step 2: Run test to verify it fails**

Run: python -m pytest backend/tests/test_analysis_workflow.py -k "region_revenue_risk or trend_and_anomaly or forecast_returns" -v

Expected: FAIL because the response lacks the new answer contract and question-specific evidence.

- [ ] **Step 3: Write minimal implementation**

    def analyse_spreadsheet(source: Path, objective: str, directory: Path) -> dict:
        frame = read_spreadsheet(source)
        plan = plan_question(frame, objective)
        answer = build_question_answer(frame, plan, directory)
        missing = validate_answer_completeness(answer, plan)
        if missing:
            raise ValueError("；".join(missing))
        return answer

Generate one Plotly artifact per requested visual question. Keep data_quality separate from business_risks; only attach a missing-data limit to the matching object/time conclusion.

- [ ] **Step 4: Run test to verify it passes**

Run: python -m pytest backend/tests/test_analysis_workflow.py -k "region_revenue_risk or trend_and_anomaly or forecast_returns" -v

Expected: PASS.

- [ ] **Step 5: Run all backend tests and commit**

Run: python -m pytest backend/tests -v

Expected: PASS.

    git add backend/studio_api/answering.py backend/studio_api/engine.py backend/tests/test_analysis_workflow.py
    git commit -m "feat: generate evidence-based answers by question type"

### Task 3: 以回答为中心的报告与结果页

**Files:**
- Modify: backend/studio_api/reporting.py
- Modify: apps/web/src/App.tsx
- Modify: apps/web/src/styles.css
- Test: backend/tests/test_analysis_workflow.py
- Test: apps/web/tests/App.test.tsx

**Interfaces:**
- Consumes the Task 2 answer fields.
- Produces report ordering: 核心结论 -> 关键数据 -> 详细分析 -> 业务风险 -> 建议 -> 数据质量与分析限制.
- Produces ResultPanel with a closed details data-quality section.

- [ ] **Step 1: Write the failing test**

    assert markdown.index("## 核心结论") < markdown.index("## 数据质量与分析限制")
    assert "south" in markdown.lower() and "%" in markdown

    render(<ResultPanel session={completedRiskSession} tab="结果" />);
    expect(screen.getByRole("heading", { name: "核心结论" })).toBeInTheDocument();
    expect(screen.getByText("地区营收风险")).toBeInTheDocument();
    expect(screen.getByText("数据质量与分析限制").closest("details")).not.toHaveAttribute("open");
    expect(screen.queryByText("低损害方案")).not.toBeInTheDocument();

- [ ] **Step 2: Run test to verify it fails**

Run: python -m pytest backend/tests/test_analysis_workflow.py -k report -v
Run: pnpm --dir apps/web exec vitest run tests/App.test.tsx

Expected: FAIL because reports and the first result tab retain the legacy fixed template.

- [ ] **Step 3: Write minimal implementation**

Replace fixed evidence/risk/options report sections with answer fields. Render core_conclusion, key_metrics, sections, business_risks, suggestions and a closed details for data_quality/limitations. Remove legacy quality/risk/chart KPI cards and unconditional disclaimer text.

- [ ] **Step 4: Run test to verify it passes**

Run: python -m pytest backend/tests/test_analysis_workflow.py -k report -v
Run: pnpm --dir apps/web exec vitest run tests/App.test.tsx

Expected: PASS.

- [ ] **Step 5: Commit**

    git add backend/studio_api/reporting.py apps/web/src/App.tsx apps/web/src/styles.css apps/web/tests/App.test.tsx
    git commit -m "feat: prioritize direct answers in reports and results"

### Task 4: 可读的多任务标签栏与任务入口

**Files:**
- Modify: apps/web/src/App.tsx
- Modify: apps/web/src/styles.css
- Test: apps/web/tests/App.test.tsx

**Interfaces:**
- Consumes Session.title and Session.objective.
- Produces TaskTabs behaviour with a recent-task menu and wheel-to-horizontal-scroll.

- [ ] **Step 1: Write the failing test**

    expect(screen.getByRole("tab", { name: /地区营收风险.*检测不同地区营收异常风险/ }))
      .toHaveAttribute("title", "检测不同地区营收异常风险，并分析月度趋势和未来风险");
    expect(screen.getByRole("tab", { name: /地区营收风险/ })).toHaveClass("active");
    fireEvent.click(screen.getByRole("button", { name: "全部任务" }));
    fireEvent.click(screen.getByRole("button", { name: "月度营收预测" }));
    expect(selectSession).toHaveBeenCalledWith("forecast-session");

Use DOM assertions for session-tabs min-width, max-width, overflow-x, text-overflow and selected-tab underline instead of screenshot-only checks.

- [ ] **Step 2: Run test to verify it fails**

Run: pnpm --dir apps/web exec vitest run tests/App.test.tsx

Expected: FAIL because tabs expose the complete title, lack a task menu, and lack target styles.

- [ ] **Step 3: Write minimal implementation**

Render semantic title only; set title={session.objective} and accessible label containing short title plus full objective. Add an “全部任务” trigger/list, an onWheel handler translating vertical delta to scrollLeft, fixed-width ellipsis CSS, active underline/background/bold and isolated close button events.

- [ ] **Step 4: Run test and build to verify they pass**

Run: pnpm --dir apps/web exec vitest run tests/App.test.tsx
Run: pnpm --dir apps/web build

Expected: PASS and build exit code 0.

- [ ] **Step 5: Commit**

    git add apps/web/src/App.tsx apps/web/src/styles.css apps/web/tests/App.test.tsx
    git commit -m "feat: make analysis task tabs readable at scale"

### Task 5: 对抗性验收、修正与全量验证

**Files:**
- Modify: backend/tests/test_analysis_workflow.py
- Modify: apps/web/tests/App.test.tsx

**Interfaces:**
- Consumes all contracts from Tasks 1–4.
- Produces named regression tests mapping directly to the 16 original acceptance criteria.

- [ ] **Step 1: Add adversarial regression cases**

    def test_quality_metadata_cannot_become_the_core_answer():
        result = analyse_uploaded("检测地区营收异常风险")
        assert result["core_conclusion"] != result["data_quality"]["summary"]
        assert result["business_risks"][0]["title"] != "数据质量风险"

    def test_missing_month_that_affects_south_is_named_as_a_limited_month():
        result = analyse_uploaded("分析地区营收趋势")
        assert any("south" in item.lower() and "2025-03" in item for item in result["data_quality"]["limitations"])

Add frontend cases for four open tasks, a title longer than 12 Chinese characters, complete-objective Tooltip, ellipsis styles, active focus, a task-menu selection and horizontal scroll event.

- [ ] **Step 2: Run adversarial tests to expose gaps**

Run: python -m pytest backend/tests -v
Run: pnpm --dir apps/web exec vitest run

Expected: every missed condition fails with a named test.

- [ ] **Step 3: Apply only the minimal correction for each failing condition**

Update the responsible analysis, report, UI or style file; do not weaken an assertion to accept legacy generic content.

- [ ] **Step 4: Run fresh full verification**

Run: python -m pytest backend/tests -v
Run: pnpm --dir apps/web exec vitest run
Run: pnpm --dir apps/web build
Run: git diff --check

Expected: all tests pass, the web build exits 0 and the whitespace check has no output.

- [ ] **Step 5: Commit and record acceptance evidence**

    git add backend/tests/test_analysis_workflow.py apps/web/tests/App.test.tsx backend/studio_api apps/web/src
    git commit -m "test: harden question-driven analysis acceptance"

