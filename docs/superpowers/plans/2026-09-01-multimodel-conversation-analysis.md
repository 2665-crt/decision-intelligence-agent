# 多模型持久化 Conversation 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将数据分析工作台升级为可持续追问、可切换模型、持久化恢复的多模型 Conversation，同时复用现有受控分析、证据、图表和报告能力。

**Architecture:** 使用 Python 标准库 `sqlite3` 建立 Conversation、Message、AnalysisState、文件绑定和 Artifact 的持久化仓储；旧 JSON Session 在应用启动时幂等导入。Agent Orchestrator 调用现有确定性引擎计算真实结果，通过 LLM Gateway 抽象 OpenAI、DeepSeek、OpenAI-compatible 与本地模拟 Provider；React 工作台消费新的 Conversation API 并保持三栏结果体验。

**Tech Stack:** Python 3.12、FastAPI、sqlite3、pytest、React 19、TypeScript、Vite、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-09-01-multimodel-conversation-analysis-design.md`

## Global Constraints

- API Key 只能写入本机 `.env`，不得写入 SQLite、返回前端或提交 Git；`.env.example` 必须无密钥且 `.env` 必须被忽略。
- 数据分析、证据、图表和报告继续由已有受控引擎产生；Provider 不运行自由代码、shell 或网络工具。
- 切换 Provider/Model 不能清空 Message、AnalysisState、绑定文件或 Artifact。
- 用户消息必须在调用前持久化；失败 assistant Message、旧结果和用户消息必须保留。
- Conversation 文件按会话隔离；不得自动合并多个文件。
- “清空全部历史”需二次确认，只删除会话专属记录与工件，不删除仍在使用的数据集。
- 本次只验证模拟 Provider；真实 API Key 与外网调用不属于验收。
- 不修改当前未提交的无关代码或本地运行产物。

---

## 文件结构

```text
backend/studio_api/
  conversation_models.py       # dataclass 与状态 JSON 规范化
  conversation_store.py        # SQLite schema、迁移、会话/消息/工件仓储
  conversation_service.py      # 发送消息、状态合并、删除、重生成
  context_manager.py           # 历史摘要与数据上下文预算
  llm/
    base.py                    # Provider 协议和标准异常
    registry.py                # Provider/Model capability registry
    gateway.py                 # 路由、能力检查、异常规范化
    simulated.py               # 无外网验收 Provider
    config.py                  # .env 读取、掩码、受控更新
  app.py                       # Conversation / Provider 路由与旧路由兼容
backend/tests/
  test_conversation_store.py
  test_conversation_service.py
  test_llm_gateway.py
  test_conversation_api.py
apps/web/src/
  api.ts                       # Conversation 与 Provider 请求封装
  types.ts                     # 后端契约对应类型
  App.tsx                      # 工作台持续聊天、历史删除、模型切换、设置
  styles.css                   # 固定输入框、历史操作与设置弹窗
apps/web/tests/
  App.test.tsx                 # 现有结果 Tab 回归及交互测试
  conversation.test.tsx        # 多轮、删除、切换、失败 UI 测试
deploy/env.example             # Provider 配置模板
.gitignore                     # 忽略 .env
README.md                      # 本机配置、Provider 和测试说明
```

### Task 1: 建立 SQLite Conversation 模型、仓储与旧 Session 迁移

**Files:**
- Create: `backend/studio_api/conversation_models.py`
- Create: `backend/studio_api/conversation_store.py`
- Create: `backend/tests/test_conversation_store.py`
- Modify: `backend/studio_api/store.py`

**Interfaces:**
- Produces: `ConversationStore.create_conversation()`, `get_conversation()`, `append_message()`, `merge_analysis_state()`, `delete_conversation()`, `clear_conversations()` 和 `migrate_legacy_sessions()`。
- Consumes: 现有 Dataset JSON、Session JSON 与 `session_dir()` 工件目录。

- [ ] **Step 1: 写入失败的仓储和迁移测试**

```python
def test_migration_imports_legacy_session_once(tmp_path):
    legacy = make_legacy_session(tmp_path, session_id="legacy-1")
    store = ConversationStore(tmp_path / "conversations.sqlite3", legacy_root=tmp_path)

    store.migrate_legacy_sessions()
    store.migrate_legacy_sessions()

    conversation = store.get_conversation("legacy-1")
    assert conversation["title"] == legacy["title"]
    assert len(store.list_messages("legacy-1")) == 1

def test_state_merge_changes_only_requested_fields(tmp_path):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create_conversation("趋势分析", "simulated", "analysis-sim")
    store.merge_analysis_state(conversation["id"], {"metrics": ["营业收入"], "date_range": {"start": "2024-01", "end": "2025-12"}})
    state = store.merge_analysis_state(conversation["id"], {"date_range": {"start": "2025-01", "end": "2025-12"}})
    assert state["metrics"] == ["营业收入"]
    assert state["date_range"]["start"] == "2025-01"
```

- [ ] **Step 2: 运行测试，确认模块不存在而失败**

Run: `python -m pytest backend/tests/test_conversation_store.py -q`

Expected: FAIL，提示无法导入 `studio_api.conversation_store`。

- [ ] **Step 3: 定义模型和 SQLite schema**

```python
@dataclass(frozen=True)
class MessageRecord:
    id: str
    conversation_id: str
    role: str
    content: str
    provider: str | None
    model: str | None
    status: str
    artifact_ids: list[str]

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, selected_provider TEXT NOT NULL, selected_model TEXT NOT NULL, conversation_summary TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, legacy_session_id TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, provider TEXT, model TEXT, status TEXT NOT NULL, error_code TEXT, artifact_ids_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS analysis_states (conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE, state_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversation_files (conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, dataset_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, added_at TEXT NOT NULL, PRIMARY KEY(conversation_id, dataset_id));
CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, message_id TEXT REFERENCES messages(id) ON DELETE SET NULL, kind TEXT NOT NULL, relative_path TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS legacy_session_once ON conversations(legacy_session_id);
"""
```

实现 JSON 列的安全编码/解码、事务式创建、按 `updated_at` 倒序的分页列表、字段级 `merge_analysis_state`，以及只在 `legacy_session_id` 不存在时导入旧 JSON。

- [ ] **Step 4: 运行仓储测试并检查迁移幂等性**

Run: `python -m pytest backend/tests/test_conversation_store.py -q`

Expected: PASS；第二次迁移不新增 Conversation 或 Message。

- [ ] **Step 5: 提交本任务**

```bash
git add backend/studio_api/conversation_models.py backend/studio_api/conversation_store.py backend/studio_api/store.py backend/tests/test_conversation_store.py
git commit -m "feat: persist conversations in sqlite"
```

### Task 2: 实现 `.env` 配置、模型注册表和模拟 LLM Gateway

**Files:**
- Create: `backend/studio_api/llm/__init__.py`
- Create: `backend/studio_api/llm/base.py`
- Create: `backend/studio_api/llm/registry.py`
- Create: `backend/studio_api/llm/gateway.py`
- Create: `backend/studio_api/llm/simulated.py`
- Create: `backend/studio_api/llm/config.py`
- Create: `backend/tests/test_llm_gateway.py`
- Modify: `deploy/env.example`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `LLMGateway.chat()`, `list_providers()`, `list_models()`, `ProviderConfigStore.public_status()` 和 `ProviderError` 子类。
- Consumes: Provider、Model、消息与 `.env` 文件路径。

- [ ] **Step 1: 写入失败的配置安全和 Gateway 路由测试**

```python
def test_public_provider_status_masks_key_and_writes_env(tmp_path):
    config = ProviderConfigStore(tmp_path / ".env")
    config.save("deepseek", {"api_key": "secret-value", "base_url": "https://api.deepseek.com"})
    status = config.public_status()["deepseek"]
    assert status["configured"] is True
    assert "secret-value" not in str(status)
    assert "DEEPSEEK_API_KEY=secret-value" in (tmp_path / ".env").read_text(encoding="utf-8")

def test_gateway_uses_simulated_provider_and_rejects_unsupported_tools():
    gateway = LLMGateway({"simulated": SimulatedProvider()})
    response = gateway.chat(provider="simulated", model="analysis-sim", messages=[{"role": "user", "content": "分析收入"}])
    assert response.content.startswith("已基于受控分析结果")
```

- [ ] **Step 2: 运行测试，确认 Gateway 尚不存在而失败**

Run: `python -m pytest backend/tests/test_llm_gateway.py -q`

Expected: FAIL，提示无法导入 `studio_api.llm`。

- [ ] **Step 3: 实现 Provider 契约与注册表**

```python
class BaseLLMProvider(Protocol):
    def chat(self, messages: list[dict[str, str]], model: str, *, tools: list[dict] | None = None, stream: bool = False) -> ProviderResponse:
        raise NotImplementedError

MODEL_REGISTRY = {
    "simulated": {"analysis-sim": ModelCapability("analysis-sim", "本地模拟分析", 8192, True, False, False, True)},
    "openai": {"gpt-5-mini": ModelCapability("gpt-5-mini", "GPT-5 mini", 128000, True, True, False, True)},
    "deepseek": {"deepseek-chat": ModelCapability("deepseek-chat", "DeepSeek Chat", 64000, True, True, False, True)},
    "openai-compatible": {"custom": ModelCapability("custom", "自定义兼容模型", 32768, True, True, False, False)},
}
```

实现 `AuthenticationError`、`RateLimitError`、`TimeoutError`、`ConnectionError`、`ModelNotFoundError` 和 `ProviderError`。Gateway 必须先从 Registry 验证模型和 tools 能力，再调用 Adapter；模拟 Provider 依据输入的 `analysis_result` 生成确定性的可见回答并可注入标准异常。

- [ ] **Step 4: 实现 `.env` 的受控读写和公开状态**

```python
def public_status(self) -> dict[str, dict[str, object]]:
    return {name: {"configured": bool(values.get("api_key")), "api_key_masked": mask(values.get("api_key")), "base_url": values.get("base_url", ""), "models": values.get("models", [])} for name, values in self.load().items()}
```

使用临时文件替换 `.env`，保留未知环境变量，写入前去除换行符；`deploy/env.example` 只包含空值；`.gitignore` 添加 `.env`。

- [ ] **Step 5: 运行 Gateway 测试**

Run: `python -m pytest backend/tests/test_llm_gateway.py -q`

Expected: PASS；密钥未泄漏、未知模型和模拟错误可被区分。

- [ ] **Step 6: 提交本任务**

```bash
git add backend/studio_api/llm backend/tests/test_llm_gateway.py deploy/env.example .gitignore
git commit -m "feat: add provider gateway configuration"
```

### Task 3: 实现 Context Manager 与统一 Conversation Orchestrator

**Files:**
- Create: `backend/studio_api/context_manager.py`
- Create: `backend/studio_api/conversation_service.py`
- Create: `backend/tests/test_conversation_service.py`
- Modify: `backend/studio_api/engine.py`

**Interfaces:**
- Produces: `ConversationService.send_message()`、`regenerate_message()` 与 `ContextManager.build()`。
- Consumes: `ConversationStore`、`LLMGateway`、现有 `run()`、Dataset source 和绑定文件。

- [ ] **Step 1: 写入失败的连续追问、切图、压缩和失败恢复测试**

```python
def test_follow_up_reuses_state_and_preserves_messages(service, conversation_with_csv):
    first = service.send_message(conversation_with_csv, "分析营业收入趋势")
    second = service.send_message(conversation_with_csv, "那 2025 年呢？")
    state = service.get_state(conversation_with_csv)
    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert state["date_range"] == {"start": "2025-01", "end": "2025-12"}
    assert len(service.list_messages(conversation_with_csv)) == 4

def test_provider_failure_keeps_user_message_and_previous_artifact(service, conversation_with_csv):
    service.send_message(conversation_with_csv, "分析营业收入趋势")
    failed = service.send_message(conversation_with_csv, "继续分析", provider="simulated-error")
    assert failed["status"] == "failed"
    assert service.list_artifacts(conversation_with_csv)
```

- [ ] **Step 2: 运行测试，确认 Service 尚不存在而失败**

Run: `python -m pytest backend/tests/test_conversation_service.py -q`

Expected: FAIL，提示无法导入 `ConversationService`。

- [ ] **Step 3: 构建受限数据上下文与摘要预算**

```python
def build(self, conversation: dict, messages: list[dict], state: dict, data_context: dict) -> list[dict]:
    recent = messages[-self.recent_message_limit:]
    return [
        {"role": "system", "content": self.system_prompt},
        {"role": "system", "content": json.dumps({"summary": conversation["conversation_summary"], "analysis_state": state, "data_context": data_context}, ensure_ascii=False)},
        *[{"role": item["role"], "content": item["content"]} for item in recent],
    ]
```

`data_context` 仅含 intake、schema、当前工作表、已验证 findings、图表规格和必要聚合；不得包含 `DataFrame.to_string()`。超预算时从早期 Message 更新 `conversation_summary`，原始 Message 保留。

- [ ] **Step 4: 实现 Orchestrator 并复用现有引擎**

```python
def send_message(self, conversation_id: str, content: str, provider: str | None = None, model: str | None = None) -> dict:
    user = self.store.append_message(conversation_id, role="user", content=content, status="completed")
    try:
        result = self._run_controlled_analysis(conversation_id, content)
        reply = self.gateway.chat(provider=resolved_provider, model=resolved_model, messages=self.context.build(conversation, messages, state, data_context), analysis_result=result)
    except ProviderError as exc:
        return self.store.append_message(conversation_id, role="assistant", content=exc.user_message, provider=resolved_provider, model=resolved_model, status="failed", error_code=exc.code)
    return self._save_success(conversation_id, reply, result)
```

提取“只看 YYYY 年”“换成柱状图”作为受控状态补丁；其他问题调用既有 `engine.run()` 生成结果。每次成功结果创建新 Artifact 并关联 assistant Message，旧 Artifact 不覆盖。

- [ ] **Step 5: 运行 Service 测试**

Run: `python -m pytest backend/tests/test_conversation_service.py -q`

Expected: PASS；连续追问、切图、摘要和 Provider 失败符合契约。

- [ ] **Step 6: 提交本任务**

```bash
git add backend/studio_api/context_manager.py backend/studio_api/conversation_service.py backend/studio_api/engine.py backend/tests/test_conversation_service.py
git commit -m "feat: orchestrate persistent analysis conversations"
```

### Task 4: 提供 Conversation、文件、模型、设置和删除 API

**Files:**
- Modify: `backend/studio_api/app.py`
- Create: `backend/tests/test_conversation_api.py`

**Interfaces:**
- Produces: 设计规格第 9 节的 Conversation、Message、模型、设置和 Provider 测试端点。
- Consumes: Task 1--3 的 Store、Service、Gateway、ProviderConfigStore。

- [ ] **Step 1: 写入失败的 API 契约测试**

```python
def test_model_switch_does_not_clear_history(client, seeded_conversation):
    client.post(f"/api/conversations/{seeded_conversation}/messages", json={"content": "分析趋势"})
    changed = client.put(f"/api/conversations/{seeded_conversation}/model", json={"provider": "openai", "model": "gpt-5-mini"})
    loaded = client.get(f"/api/conversations/{seeded_conversation}").json()
    assert changed.status_code == 200
    assert len(loaded["messages"]) == 2
    assert loaded["selected_model"] == "gpt-5-mini"

def test_clear_history_requires_confirmation_and_preserves_dataset(client, dataset_id):
    assert client.delete("/api/conversations").status_code == 422
    assert client.delete("/api/conversations?confirm=true").status_code == 204
    assert client.get(f"/api/datasets/{dataset_id}").status_code == 200
```

- [ ] **Step 2: 运行 API 测试，确认端点尚不存在而失败**

Run: `python -m pytest backend/tests/test_conversation_api.py -q`

Expected: FAIL，返回 404 或模块导入失败。

- [ ] **Step 3: 接入依赖并注册路由**

```python
@app.post("/api/conversations/{conversation_id}/messages", status_code=201)
def send_conversation_message(conversation_id: str, payload: dict) -> dict:
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=422, detail="请输入分析问题。")
    return conversation_service.send_message(conversation_id, content)

@app.delete("/api/conversations")
def clear_conversation_history(confirm: bool = False) -> Response:
    if not confirm:
        raise HTTPException(status_code=422, detail="请确认清空全部历史。")
    conversation_service.clear_history()
    return Response(status_code=204)
```

应用启动时建立 Store 并执行幂等迁移。端点为不存在的会话/文件返回 404；Provider 失败返回结构化可恢复 Message 而非 500。保留现有 `/api/sessions` 与下载路由以兼容历史界面，新增 Conversation 路由不调用真实 API。

- [ ] **Step 4: 运行 API 测试**

Run: `python -m pytest backend/tests/test_conversation_api.py -q`

Expected: PASS；模型切换保留历史、会话隔离、删除确认和 API Key 掩码均成立。

- [ ] **Step 5: 提交本任务**

```bash
git add backend/studio_api/app.py backend/tests/test_conversation_api.py
git commit -m "feat: expose conversation api"
```

### Task 5: 重构 React 数据契约和 Conversation 工作台

**Files:**
- Create: `apps/web/src/types.ts`
- Create: `apps/web/src/api.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`
- Create: `apps/web/tests/conversation.test.tsx`
- Modify: `apps/web/tests/App.test.tsx`

**Interfaces:**
- Consumes: `/api/conversations`、`/messages`、`/models`、`/providers` 与设置 API。
- Produces: 可打开、发送、切换模型、删除、清空、设置和恢复的三栏 Conversation UI。

- [ ] **Step 1: 写入失败的前端交互测试**

```tsx
test("switches model without clearing displayed messages", async () => {
  server.use(conversationHandlers());
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "DeepSeek Chat" }));
  await userEvent.click(screen.getByRole("option", { name: "GPT-5 mini" }));
  expect(screen.getByText("分析营业收入趋势")).toBeInTheDocument();
  expect(screen.getByText("本地模拟分析")).toBeInTheDocument();
});

test("requires confirmation before clearing history", async () => {
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "清空全部历史" }));
  expect(screen.getByRole("dialog", { name: "确认清空历史" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "确认清空" }));
  expect(await screen.findByText("还没有分析会话")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行前端测试，确认新 UI 尚不存在而失败**

Run: `pnpm --dir apps/web test -- conversation.test.tsx --run`

Expected: FAIL，找不到模型选择器或清空确认对话框。

- [ ] **Step 3: 提取 API 类型并替换 Session 获取逻辑**

```ts
export type Conversation = { id: string; title: string; selected_provider: string; selected_model: string; messages: Message[]; analysis_state: AnalysisState; artifacts: Artifact[] };
export async function sendMessage(id: string, content: string): Promise<MessageResult> {
  return request(`/api/conversations/${id}/messages`, { method: "POST", body: JSON.stringify({ content }) });
}
```

`App` 启动加载历史 Conversation，恢复 `localStorage` 中的打开 ID 和当前 ID；服务端状态始终为真源，刷新后重新读取而不是仅依赖 React state。

- [ ] **Step 4: 实现持续聊天、模型选择和错误恢复 UI**

```tsx
<form className="conversation-compose" onSubmit={sendCurrentMessage}>
  <textarea aria-label="继续分析" value={draft} onChange={(event) => setDraft(event.target.value)} />
  <button disabled={sending || !draft.trim()}>{sending ? "正在处理…" : "发送"}</button>
</form>
```

输入框固定在中栏底部；消息区独立滚动。顶部选择 Provider 后异步刷新模型列表，PUT 成功才更新本地状态。失败 assistant Message 显示“重新生成”和“切换模型”；每条 assistant Message 显示 `display_name` 标签。右栏使用当前 Conversation 的 artifacts 继续渲染结果、图表、数据、报告和文件。

- [ ] **Step 5: 实现历史删除、清空确认与设置页**

```tsx
<button aria-label="清空全部历史" onClick={() => setClearDialogOpen(true)}>清空全部历史</button>
{clearDialogOpen && <ConfirmDialog title="确认清空历史" description="会删除所有会话、消息、分析状态和会话专属工件；可复用数据集保留。" onConfirm={clearHistory} />}
```

单条删除从列表与打开标签移除；清空必须发送 `confirm=true`。设置弹窗展示掩码 Key 与连接状态，保存后不回显 Key；所有失败通过 toast 显示后端可行动提示。

- [ ] **Step 6: 运行前端测试及构建**

Run: `pnpm --dir apps/web test -- --run && pnpm --dir apps/web build`

Expected: PASS；类型检查与生产构建无错误。

- [ ] **Step 7: 提交本任务**

```bash
git add apps/web/src apps/web/tests
git commit -m "feat: add multimodel conversation workspace"
```

### Task 6: 文档、全量回归与真实浏览器验收

**Files:**
- Modify: `README.md`
- Modify: `deploy/env.example`
- Modify: `backend/tests/test_analysis_workflow.py`
- Create: `scripts/acceptance_multimodel_conversation.py`

**Interfaces:**
- Consumes: 完整本机服务、模拟 Provider、示例 CSV/XLSX。
- Produces: 可复现的验收命令与 GitHub 用户配置说明。

- [ ] **Step 1: 写入回归测试，确保旧确定性分析结果仍有证据、图表与报告**

```python
def test_conversation_analysis_keeps_existing_evidence_chart_and_report(client, sales_file):
    conversation = create_conversation_with_file(client, sales_file)
    client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "按地区汇总营业收入并画图"})
    loaded = client.get(f"/api/conversations/{conversation['id']}").json()
    assert loaded["artifacts"]
    assert loaded["messages"][-1]["role"] == "assistant"
    assert loaded["messages"][-1]["artifact_ids"]
```

- [ ] **Step 2: 运行回归测试，确认新增路径在最终接口下通过**

Run: `python -m pytest backend/tests -q`

Expected: PASS；旧分析工作流和新增 Conversation 测试均通过。

- [ ] **Step 3: 补充 README 与环境模板**

```markdown
1. 复制 `deploy/env.example` 为项目根目录 `.env`，或在“设置 → 模型 / API”填写。
2. API Key 只保存于本机 `.env`，不要提交或发送给他人。
3. 未配置 Key 时选择“本地模拟分析”可验证工作台；OpenAI、DeepSeek 和兼容模型需由用户自行配置并测试连接。
```

说明启动命令、SQLite 数据库位置、旧 Session 自动迁移、历史清空语义和真实 API 不在本次验收范围。

- [ ] **Step 4: 启动本机服务并执行浏览器验收脚本**

Run: `python -m uvicorn studio_api.app:app --app-dir backend --host 127.0.0.1 --port 8001`

Run: `pnpm --dir apps/web dev --host 127.0.0.1 --port 5173`

Run: `python scripts/acceptance_multimodel_conversation.py`

Expected: 使用模拟 Provider 验证创建会话、发送三轮追问、切换模型、失败恢复、刷新恢复、重启恢复、会话文件隔离和清空历史；不执行外网请求。

- [ ] **Step 5: 执行最终检查**

Run: `python -m pytest backend/tests -q && pnpm --dir apps/web test -- --run && pnpm --dir apps/web build && git diff --check`

Expected: 全部通过；工作区只包含本次实现和明确保留的用户现有未提交改动。

- [ ] **Step 6: 提交本任务**

```bash
git add README.md deploy/env.example backend/tests/test_analysis_workflow.py scripts/acceptance_multimodel_conversation.py
git commit -m "docs: document multimodel conversation setup"
```
