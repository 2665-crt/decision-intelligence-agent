# Multi-File Notebook GUI Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local three-pane data-analysis workbench that uploads and manually selects up to five CSV/XLSX/DOCX files, generates editable notebook cells through Dify, runs them in isolated revisioned containers, and publishes charts and reports only after user approval.

**Architecture:** Use a monorepo with a FastAPI workbench API, a React/TypeScript web app, a separate FastAPI executor service, and Dify integration artifacts. PostgreSQL stores task metadata, Redis/RQ runs durable parsing jobs, local object storage keeps immutable file/revision artifacts, and Docker Compose provides local deployment.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis 7, RQ, pandas, openpyxl, python-docx, Docker Engine, React 19, TypeScript, Vite, Monaco Editor, TanStack Query, Zustand, Plotly.js, Vitest, Playwright, pytest.

## Global Constraints

- Accept CSV, XLSX, and DOCX only.
- Accept 1–5 files; reject the sixth without losing the first five.
- Limit each file to 50 MB and each task to 200 MB total.
- Put a visible delete button on every file card; deleting one file must not remove other files or the analysis requirement.
- Never add a file to analysis without explicit user selection.
- Always show execute, generate-only, and cancel choices before code generation.
- Keep notebook execution ephemeral and reproducible; replay required predecessor cells in a fresh container.
- Preserve immutable revisions; failed runs never replace the current successful revision.
- Automatically repair code at most two times.
- Automatically prepare missing dependencies without user installation work.
- Default user-code networking to off; enable only task-scoped HTTPS domain allowlists through an egress proxy.
- Never expose Docker Socket, host paths, host environment variables, or credentials to user-code containers.
- Produce PNG, SVG, Plotly HTML, Markdown, DOCX, and PDF artifacts.
- Publish only the exact user-approved `revision_id`.
- Persist complete task history and restore the exact conversation, file-processing timeline, notebook, logs, and artifacts without regenerating them.
- Continuing from history must create a child revision and preserve the original snapshot.

---

## Repository Structure

```text
apps/
  api/
    src/workbench/
    tests/
    alembic/
  web/
    src/
    tests/
services/
  executor/
    src/executor/
    tests/
integrations/
  dify/
    prompts/
    workflows/
    tests/
contracts/
  events.schema.json
  examples/
deploy/
  docker-compose.yml
  env.example
  images/
tests/
  e2e/
docs/superpowers/
  specs/
  plans/
```

## Cross-System Interfaces

```python
# apps/api/src/workbench/contracts.py
class GenerateNotebookRequest(BaseModel):
    task_id: UUID
    selection_id: UUID
    requirement: str
    execution_mode: Literal["execute", "generate_only", "cancel"]

class RunNotebookRequest(BaseModel):
    notebook_id: UUID
    target_cell_ids: list[UUID]
    code_snapshot: dict[UUID, str]

class RunEvent(BaseModel):
    event_id: UUID
    run_id: UUID
    type: Literal[
        "queued", "dependency_preparing", "cell_started", "cell_output",
        "repair_started", "artifact_created", "failed", "stopped", "completed"
    ]
    payload: dict[str, Any]
```

The API owns public task/file/notebook/revision IDs. Dify consumes structure summaries and returns notebook plans. The executor consumes an immutable selection manifest, notebook snapshot, dependency lock, and network policy; it returns events and artifact manifests.

## Plan Set and Execution Order

1. [Core API and file lifecycle](2026-08-01-core-api-file-lifecycle.md)
2. [Notebook executor, dependencies, and network isolation](2026-08-01-notebook-executor-security.md)
3. [Dify Agent and Workflow integration](2026-08-01-dify-agent-integration.md)
4. [Three-pane frontend and end-to-end acceptance](2026-08-01-three-pane-web-e2e.md)

Each plan must leave the repository in a working, testable state before the next starts.

## Integration Gates

### Gate 1: Core API Ready

- [ ] Upload, parse, select, delete, and historical-retention tests pass.
- [ ] OpenAPI contains task, file, selection, notebook, run, revision, and artifact endpoints.
- [ ] File identity uses SHA-256 and selection snapshots are immutable.
- [ ] Closing and reopening the browser preserves a searchable history of complete task snapshots.

### Gate 2: Executor Ready

- [ ] Cell dependency replay produces the same result as run-all.
- [ ] Missing dependencies are prepared automatically.
- [ ] Default-offline and task-domain-allowlist tests pass.
- [ ] Docker Socket and host access attempts fail inside user-code containers.

### Gate 3: Dify Ready

- [ ] Dify generates only against selected file summaries.
- [ ] All three execution modes are enforced.
- [ ] Refine, rebuild, and two-attempt automatic repair routes pass contract tests.

### Gate 4: Product Ready

- [ ] The three-pane UI passes component, accessibility, and Playwright tests.
- [ ] All 27 acceptance criteria from the design spec pass with real files.
- [ ] A failed revision leaves the prior successful revision and artifacts intact.
- [ ] Opening a history snapshot performs no Dify call and no executor run; continuing creates a child revision.

## Final Verification

- [ ] Run Python tests: `python -m pytest apps/api/tests services/executor/tests integrations/dify/tests -q`.
- [ ] Run web tests: `pnpm --dir apps/web test -- --run`.
- [ ] Run type checks: `pnpm --dir apps/web typecheck`.
- [ ] Run complete local stack: `docker compose -f deploy/docker-compose.yml up -d --build`.
- [ ] Run end-to-end suite: `pnpm --dir apps/web exec playwright test ../../tests/e2e`.
- [ ] Run security probes from the executor plan.
- [ ] Read back generated PNG, SVG, Plotly HTML, Markdown, DOCX, and PDF artifacts.
- [ ] Verify `git status --short` contains only intentional changes.
