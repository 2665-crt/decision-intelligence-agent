# Core API and File Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the workbench API, durable metadata, file parsing, manual selection snapshots, and safe uploaded-file deletion.

**Architecture:** FastAPI exposes task/file/selection endpoints. PostgreSQL stores identities and immutable snapshots, Redis/RQ performs parsing, and a filesystem object store keeps originals and historical snapshots behind opaque IDs.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis 7, RQ, pandas, openpyxl, python-docx, pytest.

## Global Constraints

- Use the exact file limits and lifecycle rules from the master plan.
- Never return server filesystem paths to clients or Dify.
- File deletion must preserve historical revision reproducibility.
- Every database mutation must be scoped by `user_id` and `task_id`.

---

### Task 1: Scaffold API, Configuration, and Database

**Files:**
- Create: `pyproject.toml`
- Create: `apps/api/src/workbench/main.py`
- Create: `apps/api/src/workbench/settings.py`
- Create: `apps/api/src/workbench/db.py`
- Create: `apps/api/tests/test_health.py`
- Create: `deploy/docker-compose.yml`
- Create: `deploy/env.example`

**Interfaces:**
- Produces: `create_app() -> FastAPI`, `get_session() -> AsyncIterator[AsyncSession]`, `/health -> {"status":"ready"}`.

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient
from workbench.main import create_app

def test_health_is_ready():
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
```

- [ ] **Step 2: Run the failing test**

Run: `python -m pytest apps/api/tests/test_health.py -q`

Expected: FAIL because `workbench.main` does not exist.

- [ ] **Step 3: Implement the minimal app and typed settings**

```python
from fastapi import FastAPI

def create_app() -> FastAPI:
    app = FastAPI(title="Data Analysis Workbench")
    app.get("/health")(lambda: {"status": "ready"})
    return app
```

Add PostgreSQL, Redis, object-store root, 50 MB, 200 MB, and 5-file settings. Compose must start `postgres`, `redis`, `api`, and `worker` with health checks.

- [ ] **Step 4: Run test and container configuration validation**

Run: `python -m pytest apps/api/tests/test_health.py -q`

Expected: PASS.

Run: `docker compose -f deploy/docker-compose.yml config`

Expected: exit 0 with all four services resolved.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml apps/api deploy
git commit -m "feat: scaffold workbench API"
```

### Task 2: Define Core Entities and Migrations

**Files:**
- Create: `apps/api/src/workbench/models.py`
- Create: `apps/api/src/workbench/contracts.py`
- Create: `apps/api/alembic.ini`
- Create: `apps/api/alembic/env.py`
- Create: `apps/api/alembic/versions/0001_core_entities.py`
- Create: `apps/api/tests/test_models.py`

**Interfaces:**
- Produces: `AnalysisTask`, `UploadedFile`, `FileSelection`, `Notebook`, `Cell`, `Run`, `Revision`, `Artifact`, `ConversationTurn`, `TaskEvent`, `HistorySnapshot` SQLAlchemy models.
- Produces: UUID primary keys named exactly `task_id`, `file_id`, `selection_id`, `notebook_id`, `cell_id`, `run_id`, `revision_id`, `artifact_id`.

- [ ] **Step 1: Write failing model invariant tests**

```python
def test_selection_file_ids_are_immutable(session, task, uploaded_files):
    selection = FileSelection(task_id=task.task_id, file_ids=[f.file_id for f in uploaded_files])
    session.add(selection)
    session.commit()
    original = tuple(selection.file_ids)
    selection.file_ids.append(uuid4())
    with pytest.raises(ValueError, match="selection is immutable"):
        session.commit()
    assert tuple(session.get(FileSelection, selection.selection_id).file_ids) == original
```

Also test that a failed revision cannot change `AnalysisTask.current_success_revision_id`.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest apps/api/tests/test_models.py -q`

Expected: FAIL because models are absent.

- [ ] **Step 3: Implement models and migration**

Use `UUID(as_uuid=True)`, UTC timestamps, explicit foreign keys, JSONB only for bounded manifests, and a `before_update` guard for immutable selections. Store current success only on `AnalysisTask`; never infer it from latest revision.

- [ ] **Step 4: Run migration and model tests**

Run: `python -m alembic -c apps/api/alembic.ini upgrade head`

Expected: migration applies once and is idempotent on a second status check.

Run: `python -m pytest apps/api/tests/test_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/workbench/models.py apps/api/src/workbench/contracts.py apps/api/alembic apps/api/tests/test_models.py
git commit -m "feat: add immutable analysis entities"
```

### Task 3: Implement Object Storage and Streaming Upload Limits

**Files:**
- Create: `apps/api/src/workbench/storage.py`
- Create: `apps/api/src/workbench/files/service.py`
- Create: `apps/api/src/workbench/files/routes.py`
- Create: `apps/api/tests/files/test_upload.py`

**Interfaces:**
- Produces: `FileStorage.save_stream(task_id, file_id, stream) -> StoredObject`.
- Produces: `POST /tasks/{task_id}/files -> UploadedFileResponse`.

- [ ] **Step 1: Write failing boundary tests**

```python
def test_sixth_file_is_rejected_without_losing_first_five(client, task_id, csv_bytes):
    ids = [upload(client, task_id, f"{i}.csv", csv_bytes)["file_id"] for i in range(5)]
    response = client.post(f"/tasks/{task_id}/files", files={"file": ("6.csv", csv_bytes)})
    assert response.status_code == 409
    assert [f["file_id"] for f in client.get(f"/tasks/{task_id}/files").json()] == ids
```

Add tests for 50 MB per file, 200 MB total, extension/MIME allowlist, SHA-256, and partial-file cleanup.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest apps/api/tests/files/test_upload.py -q`

Expected: FAIL because routes and storage do not exist.

- [ ] **Step 3: Implement streaming upload**

Read fixed-size chunks, update SHA-256 and byte counters before writing, reject immediately on limit breach, and atomically rename a completed temporary object. Do not load complete files into RAM.

- [ ] **Step 4: Run upload tests**

Run: `python -m pytest apps/api/tests/files/test_upload.py -q`

Expected: PASS with no temporary files remaining after rejected uploads.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/workbench/storage.py apps/api/src/workbench/files apps/api/tests/files/test_upload.py
git commit -m "feat: add bounded streaming file uploads"
```

### Task 4: Parse CSV, XLSX, and DOCX in Durable Jobs

**Files:**
- Create: `apps/api/src/workbench/files/parsers.py`
- Create: `apps/api/src/workbench/jobs.py`
- Create: `apps/api/src/workbench/worker.py`
- Create: `apps/api/tests/files/test_parsers.py`
- Create: `apps/api/tests/fixtures/`

**Interfaces:**
- Produces: `parse_uploaded_file(file_id: UUID) -> ParseManifest`.
- `ParseManifest` contains `mode`, `rows`, `columns`, `sheets`, `headings`, `paragraphs`, `tables`, `images`, `warnings`, and bounded samples.

- [ ] **Step 1: Add real fixture tests**

Create minimal UTF-8/GB18030 CSV, multi-sheet XLSX with hidden sheet/formula/merged cell, and DOCX with headings/table/image. Assert exact manifest counts and that original SHA-256 is unchanged.

- [ ] **Step 2: Run parser tests to verify failure**

Run: `python -m pytest apps/api/tests/files/test_parsers.py -q`

Expected: FAIL because parsers do not exist.

- [ ] **Step 3: Implement bounded parsers and RQ job**

CSV must use chunked reads. XLSX must use read-only workbook inspection without skipping hidden sheets. DOCX must count paragraphs, headings, tables, and inline shapes. Enqueue parsing immediately after upload and persist progress/error states.

- [ ] **Step 4: Run parser and worker tests**

Run: `python -m pytest apps/api/tests/files/test_parsers.py -q`

Expected: PASS with manifests matching fixture truth.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/workbench/files/parsers.py apps/api/src/workbench/jobs.py apps/api/src/workbench/worker.py apps/api/tests/files
git commit -m "feat: parse supported analysis files"
```

### Task 5: Implement Manual Selection and File Deletion

**Files:**
- Create: `apps/api/src/workbench/selections/routes.py`
- Create: `apps/api/src/workbench/selections/service.py`
- Modify: `apps/api/src/workbench/files/routes.py`
- Modify: `apps/api/src/workbench/files/service.py`
- Create: `apps/api/tests/files/test_delete.py`
- Create: `apps/api/tests/selections/test_selection.py`

**Interfaces:**
- Produces: `POST /tasks/{task_id}/selections`.
- Produces: `DELETE /tasks/{task_id}/files/{file_id}`.
- Produces: `remove_file(user_id, task_id, file_id) -> FileRemovalResult`.

- [ ] **Step 1: Write failing deletion tests**

```python
def test_delete_wrong_file_preserves_other_files_and_requirement(client, task_with_requirement, three_files):
    response = client.delete(f"/tasks/{task_with_requirement.task_id}/files/{three_files[1].file_id}")
    assert response.status_code == 204
    task = client.get(f"/tasks/{task_with_requirement.task_id}").json()
    assert task["requirement"] == task_with_requirement.requirement
    assert {f["file_id"] for f in task["files"]} == {str(three_files[0].file_id), str(three_files[2].file_id)}
```

Also test canceling an in-flight upload, deleting during parsing, creating a new selection when a selected file is removed, returning to waiting-selection when none remain, and retaining a historical object referenced by a revision.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest apps/api/tests/files/test_delete.py apps/api/tests/selections/test_selection.py -q`

Expected: FAIL because deletion and selection routes do not exist.

- [ ] **Step 3: Implement deletion transaction**

Lock task and file rows. Cancel queued jobs. Remove temporary/current objects only when no revision references them. Otherwise mark `removed_from_current_at` and retain the immutable object until retention expiry. Never mutate an existing selection; create a new selection snapshot.

- [ ] **Step 4: Run lifecycle tests**

Run: `python -m pytest apps/api/tests/files/test_delete.py apps/api/tests/selections/test_selection.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/workbench/files apps/api/src/workbench/selections apps/api/tests/files/test_delete.py apps/api/tests/selections
git commit -m "feat: add manual selection and file removal"
```

### Task 6: Expose Task Event Stream and Contract Snapshot

**Files:**
- Create: `apps/api/src/workbench/events.py`
- Create: `apps/api/src/workbench/events/routes.py`
- Create: `contracts/events.schema.json`
- Create: `apps/api/tests/test_events.py`

**Interfaces:**
- Produces: `GET /tasks/{task_id}/events` as Server-Sent Events.
- Produces: monotonically ordered `event_id`, `task_id`, `type`, `payload`, `created_at`.

- [ ] **Step 1: Write failing replay test**

Assert a reconnect with `Last-Event-ID` receives only later events and cannot read another user's task.

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest apps/api/tests/test_events.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement persisted events and SSE**

Persist events before publishing them. Heartbeat every 15 seconds. Apply user/task authorization before opening the stream.

- [ ] **Step 4: Verify API suite and OpenAPI**

Run: `python -m pytest apps/api/tests -q`

Expected: PASS.

Run: `python -c "from workbench.main import create_app; assert '/tasks/{task_id}/files/{file_id}' in create_app().openapi()['paths']"`

Expected: exit 0.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/workbench/events.py apps/api/src/workbench/events contracts/events.schema.json apps/api/tests/test_events.py
git commit -m "feat: stream durable task events"
```

### Task 7: Persist and Restore Complete Task History

**Files:**
- Create: `apps/api/src/workbench/history/routes.py`
- Create: `apps/api/src/workbench/history/service.py`
- Create: `apps/api/src/workbench/history/contracts.py`
- Create: `apps/api/tests/history/test_restore.py`
- Create: `apps/api/tests/history/test_continue.py`

**Interfaces:**
- Produces: `GET /history/tasks`.
- Produces: `GET /history/tasks/{task_id}/snapshots/{snapshot_id}`.
- Produces: `POST /history/snapshots/{snapshot_id}/continue`.
- Produces: `restore_snapshot(user_id, snapshot_id) -> CompleteTaskSnapshot`.
- Produces: `continue_from_snapshot(user_id, snapshot_id) -> WorkingRevision`.

- [ ] **Step 1: Write failing exact-restore tests**

```python
def test_history_snapshot_restores_exact_task_without_regeneration(client, completed_task, spy_dify, spy_executor):
    snapshot = client.get(
        f"/history/tasks/{completed_task.task_id}/snapshots/{completed_task.snapshot_id}"
    ).json()
    assert snapshot["conversation"] == completed_task.expected_conversation
    assert snapshot["file_events"] == completed_task.expected_file_events
    assert snapshot["selection_id"] == str(completed_task.selection_id)
    assert snapshot["notebook"] == completed_task.expected_notebook
    assert snapshot["artifacts"] == completed_task.expected_artifacts
    spy_dify.assert_not_called()
    spy_executor.assert_not_called()
```

Also close and recreate the API client before restoration to prove persistence. Assert user A cannot read user B history and deleted-current files remain available through historical read-only references.

- [ ] **Step 2: Run restore tests to verify failure**

Run: `python -m pytest apps/api/tests/history/test_restore.py -q`

Expected: FAIL because history routes and snapshot assembly do not exist.

- [ ] **Step 3: Implement immutable snapshot assembly**

Persist conversation turns and task events as they occur. On every successful or failed revision finalization, create a `HistorySnapshot` containing ordered IDs and hashes for conversation cursor, file events, selection, notebook, run, revision, and artifacts. Restore by joining those exact IDs; never select “latest” child objects while viewing an older snapshot.

- [ ] **Step 4: Write and implement continue-from-history tests**

```python
def test_continue_from_history_creates_child_revision(client, snapshot):
    response = client.post(f"/history/snapshots/{snapshot.snapshot_id}/continue")
    assert response.status_code == 201
    working = response.json()
    assert working["parent_revision_id"] == str(snapshot.revision_id)
    assert working["revision_id"] != str(snapshot.revision_id)
```

Implement a transaction that copies editable conversation/notebook state into a new working revision while retaining immutable references to existing artifacts until the first new run.

- [ ] **Step 5: Run history suite**

Run: `python -m pytest apps/api/tests/history -q`

Expected: PASS; restore performs zero Dify/executor calls and continue preserves the original snapshot.

- [ ] **Step 6: Commit**

```powershell
git add apps/api/src/workbench/history apps/api/tests/history apps/api/src/workbench/models.py apps/api/alembic
git commit -m "feat: restore complete analysis history"
```
