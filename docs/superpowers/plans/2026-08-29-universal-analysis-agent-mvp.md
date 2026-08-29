# 通用数据分析与决策支持 Agent MVP 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建本地 Web 工作台：用户上传 Excel/Word、确认计划后得到真实数据分析、经回测验证的预测、风险与方案比较、基础图表及 Markdown/HTML/Word 报告。

**Architecture:** 使用 React/Vite 前端和 FastAPI 后端。后端把文件解析、分析操作、预测、风险登记册和报告渲染实现为可测试的确定性服务；Dify 只通过一个适配器生成受 JSON Schema 约束的分析计划。所有结果绑定 SQLite 中不可变的任务修订与本地工件目录；执行器只调用允许的 Python 函数，不运行模型返回的自由代码或 shell。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2、SQLite、pandas、openpyxl、xlrd、python-docx、statsmodels、Plotly、python-docx、pytest；React、TypeScript、Vite、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-08-29-universal-decision-analysis-agent-design.md`

## Global Constraints

- 只接受 XLSX、XLS 与 DOCX；单任务允许 1--5 个文件。
- 用户必须选择文件并确认计划后，才允许创建分析运行。
- 不自动合并两个数据源；跨文件分析必须在计划中列出关联字段并由用户确认。
- 解析和分析结论必须区分文件事实、数据推断、预测结果、用户前提与待验证建议。
- 预测只能对明确的时间列和数值目标列进行；候选模型必须在按时间保留的测试集上优于朴素基线，才能成为推荐模型。
- Agent 只能返回 `AnalysisPlan` JSON；执行器只调用白名单分析函数，禁止自由 Python、shell、运行时安装包和默认外网。
- 高风险领域或用户标为关键的事项必须标记人工复核，不输出可直接执行的专业处置结论。
- 运行、图表和报告必须关联精确 `revision_id`；失败运行不得覆盖最近成功修订。

---

## Repository Structure

```text
apps/
  api/
    src/universal_agent/
      api/
      domain/
      services/
      storage/
      main.py
    tests/
  web/
    src/
    tests/
services/
  executor/
    src/executor/
    tests/
contracts/
  analysis-plan.schema.json
  report.schema.json
deploy/
  docker-compose.yml
  env.example
tests/
  e2e/
```

## Cross-System Interfaces

```python
# apps/api/src/universal_agent/domain/contracts.py
class AnalysisPlan(BaseModel):
    file_ids: list[UUID]
    objective: str
    operations: list[Literal[
        "profile", "quality_check", "group_summary", "trend", "correlation",
        "anomaly", "forecast"
    ]]
    forecast: ForecastRequest | None
    cross_file_join: JoinRequest | None
    assumptions: list[str]
    human_review_required: bool

class ForecastResult(BaseModel):
    target_column: str
    time_column: str
    baseline_metrics: Metrics
    selected_model: Literal["naive", "seasonal_naive", "ets", "arima"]
    selected_metrics: Metrics
    is_recommended: bool
    prediction_interval_80: list[ForecastPoint]
    limitations: list[str]

class EvidenceItem(BaseModel):
    level: Literal["A", "B", "C", "D"]
    artifact_id: UUID | None
    summary: str
```

```typescript
// apps/web/src/api/types.ts
export type TaskStatus = "draft" | "planned" | "running" | "succeeded" | "failed";
export type FileFact = { fileId: string; name: string; parseStatus: string; summary: string };
export type PlanReview = { revisionId: string; plan: AnalysisPlan; selectedFiles: string[] };
```

### Task 1: 搭建可测试的本地应用骨架与不可变修订模型

**Files:**
- Create: `pyproject.toml`
- Create: `apps/api/src/universal_agent/main.py`
- Create: `apps/api/src/universal_agent/domain/contracts.py`
- Create: `apps/api/src/universal_agent/storage/models.py`
- Create: `apps/api/src/universal_agent/storage/repository.py`
- Create: `apps/api/tests/test_health_and_revisions.py`
- Create: `deploy/env.example`

**Interfaces:**
- Produces: `create_task() -> AnalysisTask`、`create_revision(task_id, kind) -> Revision` 与 `GET /health`。
- Consumes: 后续任务的 `task_id`、`revision_id`、`artifact_root`。

- [ ] **Step 1: 写入失败测试，定义健康检查与修订不可变语义**

```python
def test_creating_second_revision_preserves_first_snapshot(client):
    task = client.post("/tasks").json()
    first = client.post(f"/tasks/{task['id']}/revisions", json={"kind": "plan"}).json()
    second = client.post(f"/tasks/{task['id']}/revisions", json={"kind": "run"}).json()

    assert client.get("/health").json() == {"status": "ok"}
    assert first["id"] != second["id"]
    assert client.get(f"/revisions/{first['id']}").json()["kind"] == "plan"
```

- [ ] **Step 2: 运行测试，确认因应用与路由尚不存在而失败**

Run: `python -m pytest apps/api/tests/test_health_and_revisions.py -q`

Expected: FAIL，提示无法导入 `universal_agent.main` 或测试客户端无法连接。

- [ ] **Step 3: 实现最小应用、SQLite 会话和修订模型**

```python
class Revision(Base):
    __tablename__ = "revisions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_tasks.id"), index=True)
    kind: Mapped[str]
    snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: 运行单测与导入检查**

Run: `python -m pytest apps/api/tests/test_health_and_revisions.py -q`

Expected: PASS，且两个修订均可通过只读接口取回。

- [ ] **Step 5: 提交本任务**

```bash
git add pyproject.toml apps/api deploy/env.example
git commit -m "feat: add task revision foundation"
```

### Task 2: 实现 Excel/Word 上传、解析、选择与来源记录

**Files:**
- Create: `apps/api/src/universal_agent/services/file_parser.py`
- Create: `apps/api/src/universal_agent/services/file_service.py`
- Create: `apps/api/src/universal_agent/api/files.py`
- Create: `apps/api/tests/test_file_upload_and_parse.py`
- Create: `apps/api/tests/fixtures/sales.xlsx`
- Create: `apps/api/tests/fixtures/brief.docx`

**Interfaces:**
- Consumes: `task_id`、任务专属 `artifact_root`。
- Produces: `UploadedFile(file_id, sha256, media_type, parse_summary)` 与 `POST /tasks/{task_id}/selections` 返回的不可变 `selection_id`。

- [ ] **Step 1: 写入失败测试，固定真实文件读取与用户选择的行为**

```python
def test_excel_summary_and_explicit_selection(client, sales_xlsx):
    task_id = client.post("/tasks").json()["id"]
    uploaded = client.post(f"/tasks/{task_id}/files", files={"file": sales_xlsx}).json()

    assert uploaded["parse_status"] == "succeeded"
    assert uploaded["summary"]["sheets"][0]["columns"] == ["date", "region", "revenue"]
    selection = client.post(f"/tasks/{task_id}/selections", json={"file_ids": [uploaded["id"]]}).json()
    assert selection["file_ids"] == [uploaded["id"]]

def test_sixth_file_is_rejected_without_removing_first_five(client, five_files, sixth_file):
    task_id = client.post("/tasks").json()["id"]
    for file in five_files:
        assert client.post(f"/tasks/{task_id}/files", files={"file": file}).status_code == 201
    assert client.post(f"/tasks/{task_id}/files", files={"file": sixth_file}).status_code == 422
```

- [ ] **Step 2: 运行测试，确认文件端点尚不存在而失败**

Run: `python -m pytest apps/api/tests/test_file_upload_and_parse.py -q`

Expected: FAIL，状态码为 404。

- [ ] **Step 3: 实现流式落盘、哈希校验和格式解析**

```python
def parse_xlsx(path: Path) -> dict[str, object]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    return {"sheets": [summarize_sheet(workbook[name]) for name in workbook.sheetnames]}

def parse_docx(path: Path) -> dict[str, object]:
    document = Document(path)
    return {
        "paragraph_count": len(document.paragraphs),
        "tables": [summarize_table(table) for table in document.tables],
    }
```

- [ ] **Step 4: 扩展测试，验证 DOCX 来源位置和不自动跨文件合并**

```python
def test_docx_text_is_marked_as_document_statement(client, brief_docx):
    task_id = client.post("/tasks").json()["id"]
    result = client.post(f"/tasks/{task_id}/files", files={"file": brief_docx}).json()
    assert result["summary"]["text_evidence"][0]["level"] == "document_statement"
```

- [ ] **Step 5: 运行所有文件服务测试**

Run: `python -m pytest apps/api/tests/test_file_upload_and_parse.py -q`

Expected: PASS，包含 XLSX、DOCX、数量限制和不可变选择快照。

- [ ] **Step 6: 提交本任务**

```bash
git add apps/api/src/universal_agent apps/api/tests/fixtures apps/api/tests/test_file_upload_and_parse.py
git commit -m "feat: add file parsing and selection snapshots"
```

### Task 3: 定义受约束的 Dify 分析计划适配器与计划确认门

**Files:**
- Create: `contracts/analysis-plan.schema.json`
- Create: `apps/api/src/universal_agent/services/plan_service.py`
- Create: `apps/api/src/universal_agent/services/dify_adapter.py`
- Create: `apps/api/src/universal_agent/api/plans.py`
- Create: `apps/api/tests/test_plan_confirmation.py`

**Interfaces:**
- Consumes: `selection_id`、用户目标和文件解析摘要。
- Produces: `AnalysisPlan`；仅 `POST /revisions/{revision_id}/confirm` 可将状态变为 `planned`。

- [ ] **Step 1: 写入失败测试，要求计划先于执行且禁止自由代码字段**

```python
def test_run_is_rejected_until_plan_is_confirmed(client, selected_task):
    revision = client.post("/plans", json={"selection_id": selected_task.selection_id, "objective": "分析收入趋势"}).json()
    assert client.post(f"/revisions/{revision['id']}/runs").status_code == 409
    client.post(f"/revisions/{revision['id']}/confirm")
    assert client.post(f"/revisions/{revision['id']}/runs").status_code == 202

def test_plan_rejects_python_source_code():
    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate({"objective": "x", "operations": ["profile"], "python": "import os"})
```

- [ ] **Step 2: 运行测试，确认计划模块尚不存在而失败**

Run: `python -m pytest apps/api/tests/test_plan_confirmation.py -q`

Expected: FAIL，提示 `AnalysisPlan` 或 `/plans` 未定义。

- [ ] **Step 3: 实现 Schema 白名单、适配器和确认状态机**

```python
ALLOWED_OPERATIONS = {"profile", "quality_check", "group_summary", "trend", "correlation", "anomaly", "forecast"}

def build_plan(prompt: str, file_summaries: list[dict]) -> AnalysisPlan:
    payload = dify_client.generate_json(prompt, file_summaries)
    plan = AnalysisPlan.model_validate(payload)
    if set(plan.operations) - ALLOWED_OPERATIONS:
        raise PlanValidationError("unsupported operation")
    return plan
```

- [ ] **Step 4: 使用假 Dify 客户端运行合同测试**

Run: `python -m pytest apps/api/tests/test_plan_confirmation.py -q`

Expected: PASS，网络未被测试调用；未确认计划不能创建运行。

- [ ] **Step 5: 提交本任务**

```bash
git add contracts apps/api/src/universal_agent apps/api/tests/test_plan_confirmation.py
git commit -m "feat: add reviewed analysis plans"
```

### Task 4: 实现确定性数据分析、图表和证据工件

**Files:**
- Create: `services/executor/src/executor/analysis.py`
- Create: `services/executor/src/executor/artifacts.py`
- Create: `services/executor/src/executor/runner.py`
- Create: `services/executor/tests/test_analysis_operations.py`
- Create: `apps/api/src/universal_agent/services/run_service.py`
- Create: `apps/api/tests/test_analysis_run.py`

**Interfaces:**
- Consumes: 已确认 `AnalysisPlan`、`selection_id` 和只读文件映射。
- Produces: `RunResult(metrics, tables, charts, evidence, logs)`；每项 `EvidenceItem` 标注 A 或 B 级。

- [ ] **Step 1: 写入失败测试，要求结果来自真实表格并可追溯**

```python
def test_group_summary_writes_table_and_chart(tmp_path, sales_frame):
    result = run_operations(sales_frame, ["profile", "group_summary", "trend"], tmp_path)
    assert result.tables["summary_by_region"].rows[0]["revenue_sum"] == 300
    assert Path(result.charts[0].path).suffix == ".html"
    assert all(item.level in {"A", "B"} for item in result.evidence)

def test_run_binds_all_artifacts_to_revision(client, confirmed_revision):
    run = client.post(f"/revisions/{confirmed_revision}/runs").json()
    assert all(item["revision_id"] == confirmed_revision for item in run["artifacts"])
```

- [ ] **Step 2: 运行测试，确认执行器尚不存在而失败**

Run: `python -m pytest services/executor/tests/test_analysis_operations.py apps/api/tests/test_analysis_run.py -q`

Expected: FAIL，提示 `run_operations` 未定义。

- [ ] **Step 3: 实现白名单分析操作与 Plotly HTML 工件**

```python
def run_operations(frame: pd.DataFrame, operations: list[str], output_dir: Path) -> RunResult:
    if "profile" in operations:
        write_json(output_dir / "profile.json", profile_frame(frame))
    if "group_summary" in operations:
        write_csv(output_dir / "summary_by_region.csv", summarize_by_categorical_column(frame))
    if "trend" in operations:
        figure = plot_trend(frame)
        figure.write_html(output_dir / "trend.html", include_plotlyjs="cdn")
    return collect_artifacts(output_dir)
```

- [ ] **Step 4: 在容器中阻止网络和宿主挂载**

Run: `docker compose -f deploy/docker-compose.yml run --rm executor python -c "import socket; socket.create_connection(('example.com', 443), timeout=1)"`

Expected: FAIL，连接被默认网络策略拒绝；执行器仅挂载当前任务输入只读目录与输出目录。

- [ ] **Step 5: 运行分析与 API 测试**

Run: `python -m pytest services/executor/tests/test_analysis_operations.py apps/api/tests/test_analysis_run.py -q`

Expected: PASS，输出表、图表、日志与 `revision_id` 一致。

- [ ] **Step 6: 提交本任务**

```bash
git add services/executor apps/api/src/universal_agent apps/api/tests/test_analysis_run.py deploy
git commit -m "feat: add controlled analysis execution"
```

### Task 5: 实现经过回测的预测与预测风险

**Files:**
- Create: `services/executor/src/executor/forecasting.py`
- Create: `services/executor/tests/test_forecasting.py`
- Modify: `services/executor/src/executor/runner.py`
- Modify: `apps/api/src/universal_agent/domain/contracts.py`
- Create: `apps/api/tests/test_forecast_api.py`

**Interfaces:**
- Consumes: `ForecastRequest(time_column, target_column, horizon)`。
- Produces: `ForecastResult`，并将 `is_recommended=False` 用于无法通过基线的模型或不适用数据。

- [ ] **Step 1: 写入失败测试，固定时间切分与基线门槛**

```python
def test_forecast_uses_last_observations_as_test_set(monthly_series):
    result = forecast(monthly_series, time_column="month", target_column="revenue", horizon=3)
    assert result.test_start > monthly_series["month"].iloc[-4]
    assert result.baseline_metrics.mae >= 0

def test_forecast_is_not_recommended_when_candidate_loses_to_baseline(noisy_series):
    result = forecast(noisy_series, time_column="month", target_column="value", horizon=2)
    assert result.is_recommended is False
    assert "not better than baseline" in result.limitations
```

- [ ] **Step 2: 运行测试，确认预测器尚不存在而失败**

Run: `python -m pytest services/executor/tests/test_forecasting.py -q`

Expected: FAIL，提示 `forecast` 未定义。

- [ ] **Step 3: 实现朴素基线、ETS、ARIMA 与滚动回测**

```python
def forecast(frame: pd.DataFrame, *, time_column: str, target_column: str, horizon: int) -> ForecastResult:
    series = validate_and_sort_time_series(frame, time_column, target_column)
    train, test = time_holdout(series, horizon)
    baseline = seasonal_naive(train, len(test))
    candidates = [fit_ets(train, len(test)), fit_arima(train, len(test))]
    winner = min([baseline, *candidates], key=lambda item: item.metrics.mae)
    return build_forecast_result(baseline, winner, test, horizon)
```

- [ ] **Step 4: 运行预测测试与 API 测试**

Run: `python -m pytest services/executor/tests/test_forecasting.py apps/api/tests/test_forecast_api.py -q`

Expected: PASS，推荐预测优于基线；失败预测返回限制说明而非虚构数值。

- [ ] **Step 5: 提交本任务**

```bash
git add services/executor apps/api/src/universal_agent apps/api/tests/test_forecast_api.py
git commit -m "feat: add backtested forecasting"
```

### Task 6: 实现证据化风险、方案比较与三种报告格式

**Files:**
- Create: `apps/api/src/universal_agent/services/decision_service.py`
- Create: `apps/api/src/universal_agent/services/report_service.py`
- Create: `contracts/report.schema.json`
- Create: `apps/api/tests/test_risk_and_report.py`
- Create: `apps/api/tests/test_report_artifacts.py`

**Interfaces:**
- Consumes: `RunResult`、`ForecastResult | None`、用户前提与经确认计划。
- Produces: `DecisionReport` 及同一修订绑定的 `.md`、`.html`、`.docx` 文件。

- [ ] **Step 1: 写入失败测试，保证建议不能伪装成文件事实**

```python
def test_risk_item_requires_evidence_and_high_risk_requires_review():
    report = build_decision_report(
        evidence=[EvidenceItem(level="A", artifact_id=uuid4(), summary="逾期率为 18%")],
        domain="construction safety",
    )
    assert report.risks[0].human_review_required is True
    assert report.risks[0].evidence[0].level == "A"

def test_report_separates_evidence_levels_and_writes_three_formats(tmp_path, decision_report):
    artifacts = render_reports(decision_report, tmp_path)
    assert {item.suffix for item in artifacts} == {".md", ".html", ".docx"}
    assert "待验证建议" in (tmp_path / "report.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: 运行测试，确认决策与报告服务尚不存在而失败**

Run: `python -m pytest apps/api/tests/test_risk_and_report.py apps/api/tests/test_report_artifacts.py -q`

Expected: FAIL，提示 `build_decision_report` 或 `render_reports` 未定义。

- [ ] **Step 3: 实现风险登记册、方案权衡与渲染器**

```python
def requires_human_review(domain: str, user_marked_critical: bool) -> bool:
    sensitive = {"medical", "legal", "financial", "chemical", "construction safety"}
    return user_marked_critical or domain.casefold() in sensitive

def rank_options(options: list[Option]) -> list[Option]:
    return sorted(options, key=lambda option: (
        not option.hard_constraints_met,
        option.potential_harm,
        option.implementation_cost,
        -option.expected_benefit,
        option.uncertainty,
    ))
```

- [ ] **Step 4: 运行报告测试并读取生成的 Word 文件**

Run: `python -m pytest apps/api/tests/test_risk_and_report.py apps/api/tests/test_report_artifacts.py -q`

Expected: PASS，三个工件均存在；用 `python-docx` 再次读取 DOCX，确认包含“文件事实”和“待验证建议”标题。

- [ ] **Step 5: 提交本任务**

```bash
git add contracts apps/api/src/universal_agent apps/api/tests
git commit -m "feat: add evidence based reports"
```

### Task 7: 构建最小 Web 工作台与端到端验收

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/src/App.tsx`
- Create: `apps/web/src/features/files/FileSelector.tsx`
- Create: `apps/web/src/features/plans/PlanReview.tsx`
- Create: `apps/web/src/features/results/ResultView.tsx`
- Create: `apps/web/tests/App.test.tsx`
- Create: `tests/e2e/analysis-flow.spec.ts`
- Create: `deploy/docker-compose.yml`

**Interfaces:**
- Consumes: Task/File/Plan/Run/Report REST API。
- Produces: 用户可操作的上传、文件选择、计划确认、运行、结果/风险/报告下载流程。

- [ ] **Step 1: 写入失败前端测试，定义确认计划前禁用运行按钮**

```tsx
it("disables run until the user confirms the generated plan", async () => {
  render(<PlanReview revision={draftRevision} />);
  expect(screen.getByRole("button", { name: "执行分析" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "确认计划" }));
  expect(screen.getByRole("button", { name: "执行分析" })).toBeEnabled();
});
```

- [ ] **Step 2: 运行前端测试，确认组件尚不存在而失败**

Run: `pnpm --dir apps/web test -- --run`

Expected: FAIL，提示测试文件或 `PlanReview` 不存在。

- [ ] **Step 3: 实现三段式最小界面**

```tsx
export function App() {
  return <main>
    <FileSelector />
    <PlanReview />
    <ResultView sections={["分析", "预测", "风险", "方案", "报告"]} />
  </main>;
}
```

- [ ] **Step 4: 编写并运行浏览器端到端测试**

```ts
test("uploads an xlsx, confirms a plan, runs analysis, and downloads a report", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("上传文件").setInputFiles("apps/api/tests/fixtures/sales.xlsx");
  await page.getByRole("button", { name: "生成计划" }).click();
  await page.getByRole("button", { name: "确认计划" }).click();
  await page.getByRole("button", { name: "执行分析" }).click();
  await expect(page.getByText("文件事实")).toBeVisible();
  await expect(page.getByRole("link", { name: "下载 Word 报告" })).toBeVisible();
});
```

Run: `pnpm --dir apps/web exec playwright test ../../tests/e2e/analysis-flow.spec.ts`

Expected: PASS，运行结果页展示证据分层、图表、风险项与报告下载入口。

- [ ] **Step 5: 执行完整验证集**

Run: `python -m pytest apps/api/tests services/executor/tests -q`

Expected: PASS，所有 API、解析、分析、预测和报告测试通过。

Run: `pnpm --dir apps/web test -- --run`

Expected: PASS，前端测试通过。

Run: `pnpm --dir apps/web typecheck`

Expected: PASS，类型检查通过。

Run: `docker compose -f deploy/docker-compose.yml up -d --build`

Expected: 所有服务 healthy，浏览器可访问工作台。

- [ ] **Step 6: 提交本任务**

```bash
git add apps/web tests/e2e deploy
git commit -m "feat: add universal analysis workbench"
```

## Final Verification

- [ ] 用一个 Excel 完成上传、选择、确认、真实统计、图表、报告下载的端到端流程。
- [ ] 用一个含日期和数值列的 Excel 验证：预测结果附带基线指标、候选模型指标和 80% 区间；基线胜出时没有“推荐预测”。
- [ ] 用一个 Word 验证：文本被标为文档陈述，文档中的主张不被展示为数据事实。
- [ ] 检查每个风险项拥有证据与人工复核标志；每个方案包含收益、成本、潜在损害、前提和验证指标。
- [ ] 验证未确认计划时 API 与 UI 都拒绝执行。
- [ ] 验证失败运行不能替换旧成功修订，所有图表和报告都指向正确 `revision_id`。
- [ ] 运行 `git status --short`，确认只有意图内变更。
