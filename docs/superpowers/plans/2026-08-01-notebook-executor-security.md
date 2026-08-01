# Notebook Executor, Dependencies, and Network Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute selected notebook cells reproducibly in short-lived containers with dependency replay, automatic package preparation, task-scoped networking, immutable revisions, and artifact generation.

**Architecture:** A privileged executor controller accepts signed run manifests but never executes user code itself. It creates locked dependency layers and unprivileged user-code containers with read-only inputs, revision-specific outputs, resource limits, and an optional egress proxy allowlist.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, Docker SDK, networkx, pip-tools, pip-audit, Squid or Envoy egress proxy, pytest, Matplotlib, Plotly, Kaleido, python-docx, ReportLab.

## Global Constraints

- The controller alone may access Docker Socket.
- User-code containers must run non-root, drop all capabilities, use read-only root filesystems, and have no Docker Socket.
- Install missing packages automatically; users never run installation steps.
- Code repair attempts are limited to two; dependency preparation is not a repair attempt.
- Default network is none; allowlisted runs use only an egress proxy network.

---

### Task 1: Define Signed Executor Contracts

**Files:**
- Create: `services/executor/src/executor/contracts.py`
- Create: `services/executor/src/executor/auth.py`
- Create: `services/executor/src/executor/main.py`
- Create: `services/executor/tests/test_contracts.py`

**Interfaces:**
- Consumes: `RunExecutionRequest(run_id, task_id, selection_manifest, notebook_snapshot, target_cell_ids, network_policy)`.
- Produces: `POST /runs`, `POST /runs/{run_id}/stop`, `GET /runs/{run_id}`.

- [ ] **Step 1: Write failing signature and traversal tests**

```python
def test_rejects_tampered_manifest(client, signed_request):
    signed_request["body"]["selection_manifest"]["files"][0]["path"] = "../../host"
    response = client.post("/runs", json=signed_request["body"], headers=signed_request["headers"])
    assert response.status_code == 401
```

Also reject absolute host paths, duplicate IDs, unknown target cells, and signatures older than five minutes.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest services/executor/tests/test_contracts.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement contracts and HMAC verification**

Canonicalize JSON before signing. Resolve input references only through the controller's object-store adapter. Never accept a client-supplied host path.

- [ ] **Step 4: Run tests**

Run: `python -m pytest services/executor/tests/test_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/executor/src/executor services/executor/tests/test_contracts.py
git commit -m "feat: add signed executor contracts"
```

### Task 2: Build Cell Dependency Replay

**Files:**
- Create: `services/executor/src/executor/notebook.py`
- Create: `services/executor/src/executor/planner.py`
- Create: `services/executor/tests/test_replay_plan.py`

**Interfaces:**
- Produces: `build_replay_plan(cells: list[CellSnapshot], targets: list[UUID]) -> list[CellSnapshot]`.

- [ ] **Step 1: Write failing dependency tests**

```python
def test_target_cell_replays_transitive_dependencies():
    cells = [cell("read"), cell("aggregate", depends=["read"]), cell("chart", depends=["aggregate"])]
    assert [c.name for c in build_replay_plan(cells, [cells[2].cell_id])] == ["read", "aggregate", "chart"]
```

Add cycle, missing dependency, stable order, and disabled-cell tests.

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest services/executor/tests/test_replay_plan.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement deterministic topological planning**

Use an explicit DAG and stable original-order tie breaking. Reject cycles before any container starts.

- [ ] **Step 4: Run tests**

Run: `python -m pytest services/executor/tests/test_replay_plan.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/executor/src/executor/notebook.py services/executor/src/executor/planner.py services/executor/tests/test_replay_plan.py
git commit -m "feat: plan reproducible notebook cell replay"
```

### Task 3: Launch Hardened Ephemeral Containers

**Files:**
- Create: `services/executor/src/executor/runtime.py`
- Create: `services/executor/src/executor/resources.py`
- Create: `deploy/images/Dockerfile.analysis-runtime`
- Create: `services/executor/tests/test_runtime_security.py`

**Interfaces:**
- Produces: `ContainerRuntime.run(plan, mounts, dependency_layer, network_policy, limits) -> RunResult`.

- [ ] **Step 1: Write failing security probes**

Probe `/var/run/docker.sock`, host environment names, `/host`, raw sockets, process fork limits, writes outside `/outputs`, and outbound HTTPS under offline mode.

- [ ] **Step 2: Run probes against the unhardened fixture**

Run: `python -m pytest services/executor/tests/test_runtime_security.py -q`

Expected: FAIL because hardened runtime is absent.

- [ ] **Step 3: Implement hardened launch options**

Use non-root UID, `cap_drop=["ALL"]`, `security_opt=["no-new-privileges"]`, read-only root filesystem, `tmpfs /tmp`, read-only `/inputs`, writable `/outputs`, CPU/memory/PID/time/output limits, and `network_mode="none"` by default.

- [ ] **Step 4: Run security probes**

Run: `python -m pytest services/executor/tests/test_runtime_security.py -q`

Expected: PASS; every forbidden access returns a controlled error.

- [ ] **Step 5: Commit**

```powershell
git add services/executor/src/executor/runtime.py services/executor/src/executor/resources.py deploy/images/Dockerfile.analysis-runtime services/executor/tests/test_runtime_security.py
git commit -m "feat: run notebooks in hardened containers"
```

### Task 4: Automatically Prepare Missing Dependencies

**Files:**
- Create: `services/executor/src/executor/imports.py`
- Create: `services/executor/src/executor/dependencies.py`
- Create: `services/executor/src/executor/dependency_builder.py`
- Create: `deploy/images/Dockerfile.dependency-builder`
- Create: `services/executor/tests/test_dependencies.py`

**Interfaces:**
- Produces: `scan_imports(code: str) -> set[str]`.
- Produces: `prepare_dependencies(imports, python_version, platform) -> DependencyLock`.

- [ ] **Step 1: Write failing automatic-install tests**

```python
def test_missing_matplotlib_is_prepared_without_user_action(builder, empty_runtime):
    lock = builder.prepare_dependencies({"matplotlib.pyplot"}, "3.12", "linux-x86_64")
    assert "matplotlib==" in lock.requirements_text
    assert lock.hashes
    assert builder.run_import_probe(lock, "import matplotlib.pyplot as plt") == 0
```

Also test standard-library exclusion, import-to-distribution mapping, cache reuse, incompatible native package failure, hash mismatch rejection, and equivalent-library fallback event.

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest services/executor/tests/test_dependencies.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement builder isolation**

The builder may access only configured package indexes. Resolve exact versions, require hashes, run `pip-audit`, build a read-only wheel layer, and emit `dependency_preparing`/`dependency_ready` events. Do not mount user files or secrets into the builder.

- [ ] **Step 4: Run dependency tests**

Run: `python -m pytest services/executor/tests/test_dependencies.py -q`

Expected: PASS, including cold and cached matplotlib paths.

- [ ] **Step 5: Commit**

```powershell
git add services/executor/src/executor/imports.py services/executor/src/executor/dependencies.py services/executor/src/executor/dependency_builder.py deploy/images/Dockerfile.dependency-builder services/executor/tests/test_dependencies.py
git commit -m "feat: prepare notebook dependencies automatically"
```

### Task 5: Enforce Task-Scoped Network Allowlists

**Files:**
- Create: `services/executor/src/executor/network.py`
- Create: `deploy/egress/squid.conf.template`
- Create: `services/executor/tests/test_network_policy.py`

**Interfaces:**
- Produces: `NetworkPolicy(mode: Literal["offline", "allowlist"], domains: list[str], ports: list[int])`.
- Produces: `EgressProxy.create_run_policy(run_id, policy) -> ProxyLease`.

- [ ] **Step 1: Write failing egress tests**

Assert offline runs cannot resolve or connect externally. In allowlist mode, permit one test HTTPS domain while blocking another, localhost, RFC1918, link-local, cloud metadata, raw IPs, wildcard domains, and redirects to an unlisted domain.

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest services/executor/tests/test_network_policy.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement per-run proxy leases**

Create a run-specific proxy configuration, route the user container only through that proxy, validate DNS resolution against private ranges before connection, and destroy the lease when the run finishes. Redact authorization headers and query secrets from logs.

- [ ] **Step 4: Run egress tests**

Run: `python -m pytest services/executor/tests/test_network_policy.py -q`

Expected: PASS with audit entries containing domain, method, status, response bytes, and purpose.

- [ ] **Step 5: Commit**

```powershell
git add services/executor/src/executor/network.py deploy/egress services/executor/tests/test_network_policy.py
git commit -m "feat: add task-scoped egress allowlists"
```

### Task 6: Persist Revisions, Artifacts, Stop, and Cleanup

**Files:**
- Create: `services/executor/src/executor/artifacts.py`
- Create: `services/executor/src/executor/revisions.py`
- Create: `services/executor/src/executor/cleanup.py`
- Create: `services/executor/tests/test_revisions.py`
- Create: `services/executor/tests/test_artifacts.py`

**Interfaces:**
- Produces: `finalize_revision(run_result) -> RevisionManifest`.
- Produces: PNG, SVG, Plotly HTML, table, Markdown, DOCX, PDF artifact manifests.

- [ ] **Step 1: Write failing revision tests**

Test that failed/stopped runs preserve logs, do not replace the successful revision, cannot publish partial failures, and re-signing an expired artifact does not rerun code.

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest services/executor/tests/test_revisions.py services/executor/tests/test_artifacts.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement atomic artifact finalization**

Write into a staging directory, validate MIME/signature/size, compute hashes, then atomically move into `revisions/{revision_id}`. Mark success only after every required artifact is finalized. Stop must terminate the container and preserve collected logs.

- [ ] **Step 4: Run executor suite**

Run: `python -m pytest services/executor/tests -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/executor/src/executor/artifacts.py services/executor/src/executor/revisions.py services/executor/src/executor/cleanup.py services/executor/tests
git commit -m "feat: preserve revisioned analysis artifacts"
```
