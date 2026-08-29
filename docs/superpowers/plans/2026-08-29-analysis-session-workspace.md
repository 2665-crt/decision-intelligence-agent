# Analysis Session Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the single-run analysis page as a persistent multi-session analysis workspace.

**Architecture:** Persist source files as datasets and persist each independent analysis task as a session referencing one dataset. The FastAPI API exposes dataset and session lifecycle endpoints while retaining the deterministic analysis engine. The React client renders fixed three-pane workspace regions and only loads detailed artifacts for the active session.

**Tech Stack:** FastAPI, Python JSON persistence, React, TypeScript, Vite, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-29-analysis-studio-rebuild-design.md` and the user-provided workspace restructuring requirements.

## Global Constraints

- Reuse existing deterministic analysis engine; do not execute user-supplied code.
- Store datasets separately from analysis sessions.
- P0 and P1 are in scope; background execution and a standalone dataset center remain P2.
- Work only in `codex/universal-analysis-agent-mvp` linked worktree.

---

### Task 1: Dataset and Session persistence API

**Files:**
- Modify: `backend/studio_api/store.py`
- Modify: `backend/studio_api/app.py`
- Modify: `backend/studio_api/engine.py`
- Test: `backend/tests/test_analysis_workflow.py`

- [ ] Write failing integration tests for one uploaded dataset creating two independent sessions, listing persisted sessions, renaming, copying, deleting, and independently analyzing one session.
- [ ] Run the tests and confirm the old job-only API lacks these routes.
- [ ] Add dataset directories, session directories, session metadata and lifecycle endpoints.
- [ ] Make the analyzer read the linked dataset source and write generated artifacts beneath its own session.
- [ ] Run backend tests and confirm all old analysis functionality still passes.

### Task 2: Fixed multi-session workspace UI

**Files:**
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/tests/App.test.tsx`

- [ ] Write failing component tests for the workspace shell, new-session entry point, and result-area tabs.
- [ ] Run the test and confirm the single-page interface does not expose them.
- [ ] Replace the vertical result page with session history, conversation, and modular result panes.
- [ ] Add client-side active-session tabs, session search, rename/copy/delete controls, resizable panes, persisted layout and fullscreen result area.
- [ ] Run frontend tests and a production build.

### Task 3: End-to-end verification and delivery

**Files:**
- Modify: `README.md`

- [ ] Update the local start instructions and describe the Dataset → Session → artifacts workflow.
- [ ] Run backend tests, frontend tests and production build.
- [ ] Start local API and web app; verify health, workspace delivery and primary API flow.
- [ ] Commit all tracked implementation files on the isolated branch.
