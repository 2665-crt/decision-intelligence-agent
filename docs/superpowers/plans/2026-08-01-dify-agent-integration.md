# Dify Agent and Workflow Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the workbench to Dify so DeepSeek generates selected-file notebook cells, follows the three execution modes, repairs failed code twice, and produces grounded reports without owning file storage or code execution.

**Architecture:** The workbench API exposes narrow tools to Dify. Agent handles intent, planning, refine/rebuild, equivalent-library fallback, and repair decisions. Deterministic Workflow tools handle notebook generation submission, execution requests, artifact collection, and publish requests.

**Tech Stack:** Dify self-hosted API, DeepSeek model provider, YAML DSL exports, Python contract tests, FastAPI workbench client.

## Global Constraints

- Dify receives only selected-file structure summaries, bounded samples, and opaque IDs.
- Dify never receives host paths, object-store credentials, Docker Socket, or raw large files.
- Historical snapshot viewing never calls Dify; only “continue from this version” may append new conversation turns.
- The Agent may prepare dependencies through a tool but may not insert arbitrary install commands into user code.

---

### Task 1: Define Dify Tool Contracts and Mock Server

**Files:**
- Create: `integrations/dify/contracts/tool_contracts.yaml`
- Create: `integrations/dify/tests/mock_workbench.py`
- Create: `integrations/dify/tests/test_tool_contracts.py`
- Create: `apps/api/src/workbench/integrations/dify_client.py`

**Interfaces:**
- Consumes: `get_selection_context(selection_id)`, `save_notebook_plan(notebook_plan)`, `run_notebook(run_request)`, `prepare_dependencies(imports)`, `publish_revision(revision_id)`.
- Produces: typed workbench client methods with connect/read/total timeouts.

- [ ] **Step 1: Write failing schema tests**

Assert every tool requires `task_id` and `selection_id` where applicable, rejects host paths, and returns bounded payloads. Assert publish requires exact `revision_id`.

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest integrations/dify/tests/test_tool_contracts.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement contracts and mock server**

The mock server must record calls and support deterministic timeout, malformed-code, dependency-missing, and success scenarios.

- [ ] **Step 4: Run tests**

Run: `python -m pytest integrations/dify/tests/test_tool_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add integrations/dify/contracts integrations/dify/tests apps/api/src/workbench/integrations/dify_client.py
git commit -m "feat: define Dify workbench tools"
```

### Task 2: Author Grounded Agent Prompt and Notebook Schema

**Files:**
- Create: `integrations/dify/prompts/analysis_agent.md`
- Create: `integrations/dify/contracts/notebook_plan.schema.json`
- Create: `integrations/dify/tests/test_prompt_contract.py`

**Interfaces:**
- Produces: `NotebookPlan(cells, dependency_edges, requested_artifacts, requested_domains)` JSON.

- [ ] **Step 1: Write failing prompt assertions**

Assert the prompt requires `FILES["file_id"]`, forbids unselected files and guessed paths, accepts CSV/XLSX/DOCX summaries, separates refine/rebuild, emits no markdown fences around JSON, and asks for reports only when requested.

- [ ] **Step 2: Run failing assertions**

Run: `python -m pytest integrations/dify/tests/test_prompt_contract.py -q`

Expected: FAIL.

- [ ] **Step 3: Write the complete prompt and schema**

Define cell types `load`, `transform`, `visualize`, `report`; explicit dependencies; allowed outputs; import list; external-domain requests; and a rule that dependency installation is a tool call, never notebook code.

- [ ] **Step 4: Run schema examples**

Validate examples for two separate Excel charts, cross-file analysis, DOCX-derived context, Plotly output, and report generation.

Run: `python -m pytest integrations/dify/tests/test_prompt_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add integrations/dify/prompts integrations/dify/contracts/notebook_plan.schema.json integrations/dify/tests/test_prompt_contract.py
git commit -m "feat: define grounded notebook generation prompt"
```

### Task 3: Build Three-Mode Workflow Routing

**Files:**
- Create: `integrations/dify/workflows/notebook_analysis.yml`
- Create: `integrations/dify/tests/test_workflow_modes.py`

**Interfaces:**
- Consumes: `execution_mode` exactly `execute`, `generate_only`, or `cancel`.
- Produces: notebook plan only for the first two; run request only for `execute`.

- [ ] **Step 1: Write failing workflow graph tests**

Parse the YAML and assert all three branches exist, cancel cannot reach generation/execution, generate-only cannot reach execution, and execute reaches both.

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest integrations/dify/tests/test_workflow_modes.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement the workflow DSL**

Include selection-context tool, DeepSeek structured output, schema validator, save-notebook tool, conditional execution tool, and user-visible status outputs.

- [ ] **Step 4: Run workflow tests**

Run: `python -m pytest integrations/dify/tests/test_workflow_modes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add integrations/dify/workflows/notebook_analysis.yml integrations/dify/tests/test_workflow_modes.py
git commit -m "feat: route notebook execution modes"
```

### Task 4: Implement Refine, Rebuild, and Two-Attempt Repair

**Files:**
- Create: `integrations/dify/prompts/repair_code.md`
- Create: `integrations/dify/workflows/revise_notebook.yml`
- Create: `integrations/dify/tests/test_revision_routing.py`
- Create: `integrations/dify/tests/test_repair_limit.py`

**Interfaces:**
- Consumes: `action: refine_visual | rebuild_visual | repair_code`.
- Produces: child notebook/revision with `parent_revision_id`.

- [ ] **Step 1: Write failing routing and retry tests**

Assert refine receives prior code, rebuild does not receive prior visualization code, repair receives exact error logs, and a third automatic repair is impossible.

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest integrations/dify/tests/test_revision_routing.py integrations/dify/tests/test_repair_limit.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement routing and repair counter**

Persist repair count in the workbench run, not model memory. Dependency preparation retries do not increment it; equivalent-library rewrites do.

- [ ] **Step 4: Run tests**

Run: `python -m pytest integrations/dify/tests/test_revision_routing.py integrations/dify/tests/test_repair_limit.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add integrations/dify/prompts/repair_code.md integrations/dify/workflows/revise_notebook.yml integrations/dify/tests
git commit -m "feat: revise and repair generated notebooks"
```

### Task 5: Ground Report Generation and Publish

**Files:**
- Create: `integrations/dify/prompts/analysis_report.md`
- Create: `integrations/dify/workflows/report_and_publish.yml`
- Create: `integrations/dify/tests/test_report_grounding.py`
- Create: `integrations/dify/tests/test_publish_revision.py`

**Interfaces:**
- Consumes: selected file summaries, successful artifact/table manifests, and exact `revision_id`.
- Produces: Markdown report input and publish request.

- [ ] **Step 1: Write failing grounding tests**

Reject report claims containing numbers absent from execution tables. Reject publish when any required artifact failed or when the requested revision is not current user-approved revision.

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest integrations/dify/tests/test_report_grounding.py integrations/dify/tests/test_publish_revision.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement report/publish workflow**

The report prompt must cite artifact/table IDs internally and return structured sections. The workbench converts Markdown to DOCX/PDF. Publish calls only the exact approved revision.

- [ ] **Step 4: Run integration suite**

Run: `python -m pytest integrations/dify/tests -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add integrations/dify/prompts/analysis_report.md integrations/dify/workflows/report_and_publish.yml integrations/dify/tests
git commit -m "feat: generate grounded reports and publish revisions"
```

### Task 6: Verify Historical Restore Bypasses Dify

**Files:**
- Modify: `apps/api/src/workbench/integrations/dify_client.py`
- Create: `integrations/dify/tests/test_history_no_regeneration.py`

**Interfaces:**
- Consumes: history restore and continue events from the core API.
- Produces: no Dify call on restore; a new conversation invocation only after a user sends a new modification from a continued child revision.

- [ ] **Step 1: Write failing no-regeneration test**

Restore a complete snapshot and assert zero model/tool calls. Continue it and assert still zero calls until a new user message is submitted.

- [ ] **Step 2: Run failing test**

Run: `python -m pytest integrations/dify/tests/test_history_no_regeneration.py -q`

Expected: FAIL until history routes bypass the Dify client.

- [ ] **Step 3: Implement explicit history call boundary**

Keep history reads inside the workbench repository layer. Construct a Dify request only from a new user-authored turn on a working revision.

- [ ] **Step 4: Run full Dify suite**

Run: `python -m pytest integrations/dify/tests -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/workbench/integrations/dify_client.py integrations/dify/tests/test_history_no_regeneration.py
git commit -m "fix: restore history without regeneration"
```
