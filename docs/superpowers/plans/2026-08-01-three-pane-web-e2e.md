# Three-Pane Web Workbench and End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the user-facing three-pane workbench, complete history restore, notebook editing, mixed result presentation, and all real-file end-to-end acceptance tests.

**Architecture:** React renders task state from the FastAPI API and SSE stream. Zustand stores only transient UI state; durable files, conversations, notebook snapshots, runs, history, and revisions remain server-owned. Monaco edits cells, Plotly renders interactive artifacts, and Playwright verifies complete flows.

**Tech Stack:** React 19, TypeScript, Vite, TanStack Query, Zustand, Monaco Editor, Plotly.js, React Aria, Vitest, Testing Library, Playwright.

## Global Constraints

- The three panes are file selection, conversation/results, and notebook.
- File cards have a visible top-right delete button with an accessible name containing the filename.
- History restore must show exact stored content without triggering generation or execution.
- All actions must remain keyboard accessible and expose live status updates to assistive technology.

---

### Task 1: Scaffold Web App, API Client, and Task Shell

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/api/client.ts`
- Create: `apps/web/src/app/TaskShell.tsx`
- Create: `apps/web/src/app/taskStore.ts`
- Create: `apps/web/tests/TaskShell.test.tsx`

**Interfaces:**
- Produces: `api.getTask`, `api.subscribeTaskEvents`, `TaskShell`, `useTaskUiStore`.

- [ ] **Step 1: Write failing shell test**

```tsx
it("renders three resizable panes", async () => {
  render(<TaskShell taskId="task-1" />)
  expect(await screen.findByRole("region", {name: "文件"})).toBeVisible()
  expect(screen.getByRole("region", {name: "对话与结果"})).toBeVisible()
  expect(screen.getByRole("region", {name: "Notebook"})).toBeVisible()
})
```

- [ ] **Step 2: Run failing test**

Run: `pnpm --dir apps/web test -- --run TaskShell`

Expected: FAIL.

- [ ] **Step 3: Implement the shell**

Use CSS grid with persisted pane widths and keyboard-operable separators. Left and right panes may collapse; center never collapses.

- [ ] **Step 4: Run unit and type tests**

Run: `pnpm --dir apps/web test -- --run TaskShell`

Run: `pnpm --dir apps/web typecheck`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/web
git commit -m "feat: scaffold three-pane workbench"
```

### Task 2: Build Upload, Parse Status, Manual Selection, and Delete

**Files:**
- Create: `apps/web/src/files/FilePane.tsx`
- Create: `apps/web/src/files/FileCard.tsx`
- Create: `apps/web/src/files/UploadDropzone.tsx`
- Create: `apps/web/src/files/SelectedFilesSummary.tsx`
- Create: `apps/web/tests/files/FilePane.test.tsx`

**Interfaces:**
- Consumes: upload/list/delete/select endpoints and file events.
- Produces: selected file IDs only after explicit checkbox actions.

- [ ] **Step 1: Write failing delete and limit tests**

```tsx
it("deletes one mistaken file without losing others or the requirement", async () => {
  render(<FilePane taskId="task-1" />)
  await user.click(await screen.findByRole("button", {name: "删除 wrong.xlsx"}))
  expect(api.deleteFile).toHaveBeenCalledWith("task-1", "wrong-id")
  expect(screen.getByText("keep.csv")).toBeVisible()
  expect(taskStore.getState().requirement).toBe("生成月度图表")
})
```

Also test the sixth file, 50 MB/200 MB messages, disabled continue with no selection, deletion while uploading/parsing, and immediate replacement upload.

- [ ] **Step 2: Run failing tests**

Run: `pnpm --dir apps/web test -- --run FilePane`

Expected: FAIL.

- [ ] **Step 3: Implement file components**

Put `❌` visually in the card's top-right button, with `aria-label="删除 {filename}"`. Reflect server events; never optimistically erase historical references. Keep requirement text in task state when deleting.

- [ ] **Step 4: Run file-pane tests**

Run: `pnpm --dir apps/web test -- --run FilePane`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/web/src/files apps/web/tests/files
git commit -m "feat: manage selected analysis files"
```

### Task 3: Implement Conversation and Mandatory Execution Choice

**Files:**
- Create: `apps/web/src/conversation/ConversationPane.tsx`
- Create: `apps/web/src/conversation/ExecutionChoice.tsx`
- Create: `apps/web/src/conversation/RequirementComposer.tsx`
- Create: `apps/web/tests/conversation/ExecutionChoice.test.tsx`

**Interfaces:**
- Produces: `execution_mode: execute | generate_only | cancel` only from user selection.

- [ ] **Step 1: Write failing three-choice test**

Assert all three choices appear for both small and large file fixtures, generation is disabled before selection, generate-only creates no run, and cancel preserves files/requirement.

- [ ] **Step 2: Run failing test**

Run: `pnpm --dir apps/web test -- --run ExecutionChoice`

Expected: FAIL.

- [ ] **Step 3: Implement conversation flow**

Render selected-file chips above the choice. Provide “返回修改文件”. Announce Agent, dependency, repair, and run progress with an `aria-live="polite"` region.

- [ ] **Step 4: Run tests**

Run: `pnpm --dir apps/web test -- --run ExecutionChoice`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/web/src/conversation apps/web/tests/conversation
git commit -m "feat: require notebook execution choice"
```

### Task 4: Implement Notebook Editor and Mixed Outputs

**Files:**
- Create: `apps/web/src/notebook/NotebookPane.tsx`
- Create: `apps/web/src/notebook/CellEditor.tsx`
- Create: `apps/web/src/notebook/NotebookToolbar.tsx`
- Create: `apps/web/src/results/ResultsPane.tsx`
- Create: `apps/web/src/results/ArtifactViewer.tsx`
- Create: `apps/web/tests/notebook/NotebookPane.test.tsx`
- Create: `apps/web/tests/results/ArtifactViewer.test.tsx`

**Interfaces:**
- Consumes: notebook snapshot, run endpoints, SSE events, signed artifact links.
- Produces: code snapshot keyed by `cell_id` and target cell IDs.

- [ ] **Step 1: Write failing notebook tests**

Test edit, run-cell, run-all, stop, restore-generated-version, add, move, collapse, status display, thumbnail output, and “open in results”.

- [ ] **Step 2: Write failing artifact tests**

Test PNG/SVG, Plotly HTML in a sandboxed iframe, tables, logs, Markdown, DOCX/PDF downloads, and revision/source labels.

- [ ] **Step 3: Run failing tests**

Run: `pnpm --dir apps/web test -- --run NotebookPane ArtifactViewer`

Expected: FAIL.

- [ ] **Step 4: Implement components**

Monaco must not execute code locally. Plotly HTML iframe uses `sandbox="allow-scripts"` without same-origin, forms, popups, or top navigation. Signed downloads must be opened only from server-provided artifact metadata.

- [ ] **Step 5: Run tests and commit**

Run: `pnpm --dir apps/web test -- --run NotebookPane ArtifactViewer`

Run: `pnpm --dir apps/web typecheck`

Expected: PASS.

```powershell
git add apps/web/src/notebook apps/web/src/results apps/web/tests/notebook apps/web/tests/results
git commit -m "feat: edit notebooks and inspect artifacts"
```

### Task 5: Implement Complete History List, Restore, and Continue

**Files:**
- Create: `apps/web/src/history/HistoryList.tsx`
- Create: `apps/web/src/history/HistorySnapshotView.tsx`
- Create: `apps/web/src/history/RevisionTimeline.tsx`
- Create: `apps/web/tests/history/HistoryRestore.test.tsx`

**Interfaces:**
- Consumes: history list, exact snapshot, and continue endpoints.
- Produces: read-only restored task view and explicit “从此版本继续” action.

- [ ] **Step 1: Write failing exact-history test**

```tsx
it("restores the matching conversation, file process, notebook and results", async () => {
  render(<HistorySnapshotView taskId="task-1" snapshotId="snapshot-2" />)
  expect(await screen.findByText("第二次对话内容")).toBeVisible()
  expect(screen.getByText("file-2.xlsx 解析完成")).toBeVisible()
  expect(screen.getByDisplayValue("chart_revision_2()", {exact: false})).toBeVisible()
  expect(screen.getByAltText("修订 2 图表")).toBeVisible()
  expect(api.generateNotebook).not.toHaveBeenCalled()
  expect(api.runNotebook).not.toHaveBeenCalled()
})
```

Also simulate app remount to prove browser close/reopen behavior, search history by title/date/status, and verify missing artifacts are marked rather than silently regenerated.

- [ ] **Step 2: Run failing history tests**

Run: `pnpm --dir apps/web test -- --run HistoryRestore`

Expected: FAIL.

- [ ] **Step 3: Implement history UI**

History list shows title, timestamps, status, selected-file summary, and current successful revision. Snapshot view is read-only. “从此版本继续” calls the continue endpoint, then opens the child working revision with restored conversation and notebook already visible.

- [ ] **Step 4: Run tests**

Run: `pnpm --dir apps/web test -- --run HistoryRestore`

Expected: PASS with zero mocked Dify/executor calls during restore.

- [ ] **Step 5: Commit**

```powershell
git add apps/web/src/history apps/web/tests/history
git commit -m "feat: restore complete analysis history"
```

### Task 6: Implement Revision Actions, Reports, and Publish

**Files:**
- Create: `apps/web/src/revisions/RevisionActions.tsx`
- Create: `apps/web/src/revisions/RevisionTimeline.tsx`
- Create: `apps/web/src/reports/ReportPane.tsx`
- Create: `apps/web/tests/revisions/RevisionActions.test.tsx`

**Interfaces:**
- Produces: refine, rebuild, continue-from-history, and publish actions bound to exact revision IDs.

- [ ] **Step 1: Write failing revision tests**

Assert failed revisions do not hide the prior success, partial failures disable publish, refine/rebuild create children, and publish posts the displayed approved revision ID.

- [ ] **Step 2: Run failing tests**

Run: `pnpm --dir apps/web test -- --run RevisionActions`

Expected: FAIL.

- [ ] **Step 3: Implement actions and report pane**

Render Markdown safely, expose DOCX/PDF downloads, and show source files/revision. Require an explicit click on “满意并发布”.

- [ ] **Step 4: Run tests and commit**

Run: `pnpm --dir apps/web test -- --run RevisionActions`

Expected: PASS.

```powershell
git add apps/web/src/revisions apps/web/src/reports apps/web/tests/revisions
git commit -m "feat: revise report and publish analysis"
```

### Task 7: Build Real-File End-to-End Acceptance Suite

**Files:**
- Create: `tests/e2e/fixtures/build_fixtures.py`
- Create: `tests/e2e/file-lifecycle.spec.ts`
- Create: `tests/e2e/notebook-run.spec.ts`
- Create: `tests/e2e/history-restore.spec.ts`
- Create: `tests/e2e/security.spec.ts`
- Create: `tests/e2e/publish.spec.ts`

**Interfaces:**
- Consumes: complete Docker Compose stack.
- Produces: executable proof for all 27 design acceptance criteria.

- [ ] **Step 1: Generate deterministic real fixtures**

Create five valid mixed files, a sixth file, >50 MB sparse CSV, >200 MB batch, corrupt/encrypted/spoofed files, ambiguous encoding CSV, multi-sheet XLSX, and DOCX with table/image.

- [ ] **Step 2: Write failing lifecycle and history tests**

Cover upload limits, visible delete buttons, wrong-file replacement, manual selection, return/change selection, exact history restore after browser context restart, and continue-from-history child revision.

- [ ] **Step 3: Write failing notebook and security tests**

Cover three modes, dependency replay, matplotlib auto-install, two repairs, stop, outputs, offline mode, allowlisted API, private-address blocks, host/Docker access blocks, and data-exfiltration prevention.

- [ ] **Step 4: Write failing report/publish tests**

Cover PNG/SVG/Plotly, Markdown/DOCX/PDF, partial failure, exact revision publish, no publish without click, and expired-link re-signing.

- [ ] **Step 5: Run and iterate until all pass**

Run: `docker compose -f deploy/docker-compose.yml up -d --build`

Run: `pnpm --dir apps/web exec playwright test ../../tests/e2e`

Expected: 27 acceptance mappings pass with no skipped tests.

- [ ] **Step 6: Commit**

```powershell
git add tests/e2e
git commit -m "test: verify multi-file notebook workbench"
```
