# 分析工作台重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每个成功分析 Session 自动提供与结论对应的图表，并将证据、滚动、历史记录和正文布局重构为可用的单界面工作台。

**Architecture:** 后端从已校验 findings 构建纯数据的 `chart_specs`，前端以 SVG 呈现，并保留既有报告/工件路由。前端把工作台根、侧栏、结果面板和结构化长内容分层为独立滚动容器；历史记录通过新的分页接口按需增加。

**Tech Stack:** FastAPI、Python、pandas 执行器、React、TypeScript、CSS Grid/Flex、Vitest、Testing Library。

**Spec:** `docs/superpowers/specs/2026-09-01-analysis-workbench-refactor-design.md`

## Global Constraints

- 图表仅使用已通过后端证据校验的 finding 数值，无法绘制时返回可见原因。
- 保留 `GET /api/sessions` 列表行为；分页使用新端点。
- 普通正文不得横向截断、隐藏或省略；表格、代码与 JSON 使用自己的滚动容器。
- 不新增图表依赖，不修改运行数据、日志或用户未跟踪文件。
- 后端测试使用 `.venv\\Scripts\\python.exe -m pytest backend/tests -q`；前端测试使用 `pnpm --dir apps/web test -- --run`，构建使用 `pnpm --dir apps/web build`。

---

### Task 1: 生成已验证图表规格

**Files:**
- Create: `backend/studio_api/charting.py`
- Modify: `backend/studio_api/engine.py`
- Test: `backend/tests/test_analysis_workflow.py`

**Interfaces:**
- Consumes: `ValidatedResult.to_dict()["findings"]`。
- Produces: `build_chart_specs(findings: list[dict]) -> list[dict]`，每项含 `id`、`title`、`type`、轴名称、`series`、`markers` 和 `unavailable_reason`。

- [ ] **Step 1: 写失败的后端测试**

```python
def test_structured_trend_returns_one_chart_spec_per_requested_metric(tmp_path):
    result = analyse_structured(write_financial_workbook(tmp_path), "分析营业收入、毛利率和营业利润趋势")
    assert [spec["series"][0]["name"] for spec in result["chart_specs"]] == ["营业收入", "毛利率", "营业利润"]
```

- [ ] **Step 2: 运行失败测试**

Run: `.venv\\Scripts\\python.exe -m pytest backend/tests/test_analysis_workflow.py -k chart_spec -q`

Expected: FAIL，因为结果没有 `chart_specs`。

- [ ] **Step 3: 实现最小图表规格构建器**

```python
def build_chart_specs(findings: list[dict]) -> list[dict]:
    return [_trend_spec(finding) for finding in findings if finding["kind"] == "trend"]
```

扩展为分类、占比、相关性和异常；异常 finding 合并为对应趋势规格的 `markers`，没有可绘制 finding 时返回一条原因规格。

- [ ] **Step 4: 在 `analyse_structured` 写入规格**

```python
result.update({"chart_specs": build_chart_specs(result["findings"]), "charts": []})
```

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\\Scripts\\python.exe -m pytest backend/tests/test_analysis_workflow.py -k "chart_spec or composite" -q`

Expected: PASS。

### Task 2: 提供兼容的历史记录分页

**Files:**
- Modify: `backend/studio_api/store.py`
- Modify: `backend/studio_api/app.py`
- Test: `backend/tests/test_analysis_workflow.py`

**Interfaces:**
- Consumes: `offset: int`、`limit: int`、可选 `search: str`。
- Produces: `GET /api/sessions/page` 的 `{items, next_offset, has_more}`；原 `GET /api/sessions` 不变。

- [ ] **Step 1: 写失败 API 测试**

```python
def test_session_page_returns_only_requested_slice(client, dataset_id):
    create_sessions(client, dataset_id, 45)
    page = client.get("/api/sessions/page?offset=0&limit=40").json()
    assert len(page["items"]) == 40
    assert page["next_offset"] == 40 and page["has_more"] is True
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv\\Scripts\\python.exe -m pytest backend/tests/test_analysis_workflow.py -k session_page -q`

Expected: FAIL，路由不存在。

- [ ] **Step 3: 实现 `list_session_page` 与路由**

```python
def list_session_page(offset: int, limit: int, search: str = "") -> dict:
    items = list_sessions(search=search)
    page = items[offset:offset + limit]
    return {"items": page, "next_offset": offset + len(page), "has_more": offset + len(page) < len(items)}
```

路由校验 `offset >= 0`、`1 <= limit <= 100`。

- [ ] **Step 4: 验证后端分页测试通过**

Run: `.venv\\Scripts\\python.exe -m pytest backend/tests/test_analysis_workflow.py -k session_page -q`

Expected: PASS。

### Task 3: 为工作台行为补齐前端失败测试

**Files:**
- Modify: `apps/web/tests/App.test.tsx`
- Modify: `apps/web/src/App.tsx`

**Interfaces:**
- Consumes: `Session.chart_specs` 和分页响应。
- Produces: 图表页多张图卡、默认关闭的证据入口、带 `data-testid="history-list"` 的历史滚动列表。

- [ ] **Step 1: 写失败测试**

```tsx
it("默认收起证据并在图表标签呈现规格", async () => {
  render(<App />);
  await userEvent.click(await screen.findByRole("tab", { name: "图表" }));
  expect(screen.getByText("营业收入月度趋势")).toBeInTheDocument();
  expect(screen.getByText("查看数据证据")).toBeInTheDocument();
  expect(screen.queryByText(/来源行：1、2、3/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: 运行失败测试**

Run: `pnpm --dir apps/web test -- --run`

Expected: FAIL，因为当前组件没有 `chart_specs` 和折叠入口。

- [ ] **Step 3: 扩展 Session 类型和分页加载状态**

```ts
type ChartSpec = { id: string; title: string; type: ChartType; series: ChartSeries[]; markers?: ChartMarker[]; unavailable_reason?: string | null };
const [sessionPage, setSessionPage] = useState({ offset: 0, hasMore: false });
```

加载首批 40 条；历史容器接近底部时请求下一页，搜索变化时重置分页，选择任务时不重置 `scrollTop`。

- [ ] **Step 4: 验证测试通过**

Run: `pnpm --dir apps/web test -- --run`

Expected: PASS。

### Task 4: 渲染图表与可折叠证据

**Files:**
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/tests/App.test.tsx`

**Interfaces:**
- Consumes: `ChartSpec`、`FindingEvidence`。
- Produces: `ChartCard` 和 `Evidence`；所有文本容器设置可收缩与换行规则。

- [ ] **Step 1: 写失败测试**

```tsx
it("为无可视化规格显示明确原因", () => {
  render(<ResultPanel session={noChartSession} tab="图表" />);
  expect(screen.getByText("缺少可用于横轴的时间或分类字段")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行失败测试**

Run: `pnpm --dir apps/web test -- --run`

Expected: FAIL，因为当前图表页面只显示下载链接或空文案。

- [ ] **Step 3: 实现 SVG 图卡与两级证据折叠**

```tsx
function Evidence({ evidence }: Props) {
  return <details className="finding-evidence"><summary>查看数据证据</summary><details><summary>查看来源行（{rows.length}）</summary><pre>{rows.join("、")}</pre></details></details>;
}
```

对 line、bar、stacked-bar、donut、scatter 依据坐标范围绘制 SVG；每张图卡有标题、轴标签、图例、tooltip 文本和异常标记。输出 JSON 与来源行放进限制高度的 `pre`。

- [ ] **Step 4: 添加响应式 CSS**

```css
.direct-answer-content, .result-content p, .finding-card { min-width: 0; max-width: 100%; white-space: normal; overflow-wrap: anywhere; word-break: break-word; }
.table-wrapper, .code-scroll, .evidence-scroll { max-width: 100%; overflow: auto; }
```

移除 `body` 固定最小宽度与正文加粗；不得用正文 `overflow: hidden` 或省略号。

- [ ] **Step 5: 运行前端测试**

Run: `pnpm --dir apps/web test -- --run`

Expected: PASS。

### Task 5: 重构独立滚动与可缩放工作台布局

**Files:**
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/tests/App.test.tsx`

**Interfaces:**
- Consumes: 已有三栏宽度状态与历史列表 ref。
- Produces: 固定侧栏操作区、仅 `.history-list` 滚动的中段，以及独立滚动的结果标签内容。

- [ ] **Step 1: 写失败布局/交互测试**

```tsx
it("历史任务在独立滚动列表中保留位置", async () => {
  render(<App />);
  const list = await screen.findByTestId("history-list");
  Object.defineProperty(list, "scrollTop", { value: 180, writable: true });
  fireEvent.scroll(list);
  await userEvent.click(screen.getByRole("button", { name: /历史任务 30/ }));
  expect(list.scrollTop).toBe(180);
});
```

- [ ] **Step 2: 运行失败测试**

Run: `pnpm --dir apps/web test -- --run`

Expected: FAIL，因为没有独立历史列表和滚动位置恢复。

- [ ] **Step 3: 重组左栏与根布局**

```tsx
<aside className="history-pane"><div className="history-header">…</div><section className="history-section"><div ref={historyListRef} data-testid="history-list" className="history-list">…</div></section></aside>
```

根使用 `height: 100dvh`，所有 Grid/Flex 层设置 `min-width: 0; min-height: 0`；结果面板只纵向滚动；列表设置 `overscroll-behavior: contain` 和细滚动条。

- [ ] **Step 4: 手工/浏览器验收与完整验证**

Run: `pnpm --dir apps/web build; .venv\\Scripts\\python.exe -m pytest backend/tests -q; pnpm --dir apps/web test -- --run`

Expected: 全部退出码为 0。随后启动本机服务并用浏览器检查 900px、1366px、1920px，缩放 80%/100%/125%/150%，拖动两条分栏线，以及长中文、长英文 token、表格和 40+ 条历史记录。
