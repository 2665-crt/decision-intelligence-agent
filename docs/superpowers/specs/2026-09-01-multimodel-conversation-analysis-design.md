# 多模型持久化数据分析 Conversation 设计

## 1. 目标

将当前“一次创建 Analysis Session、执行一次、完成后要求新建任务”的工作方式升级为可持续追问的 Conversation。用户能在同一会话中继续限定时间范围、替换指标或图表、查看证据、切换模型，并在刷新页面或重启程序后恢复消息、文件、分析状态和工件。

本次不调用真实的模型 API。系统必须完成可配置的 OpenAI、DeepSeek 和 OpenAI-compatible Provider 架构，并以本地模拟 Provider 验证 Provider 切换、错误恢复和持久化行为。用户以后在本机配置自己的 Key 后，能直接使用同一条分析能力链路。

## 2. 已确认的现状与问题

- 后端以每个目录中的 `session.json` 保存 Session；消息嵌在单个 JSON 文档中，缺少可单独查询、标记模型、重试或重生成的 Message 模型。
- `POST /api/sessions/{id}/analyze` 把当前目标交给确定性分析引擎，完成后写入固定提示，并要求用户新建任务；没有后续消息 API。
- 一个 Session 只关联一个 Dataset；当前已有证据、图表、报告与文件下载均以 Session 工件目录为根。
- 前端已有左侧 Session 历史、中央消息展示和右侧结果 Tab，但输入区不是持续对话输入，且没有 Provider/Model 快速切换、设置或失败恢复操作。
- 当前分析引擎、证据、图表和报告生成已经是可运行的确定性能力，不能因为多模型升级被替换或改为让模型自由执行代码。

## 3. 范围与约束

### 3.1 本次实现

- SQLite 持久化 Conversation、Message、AnalysisState、ConversationFile、Artifact 和非敏感 Provider 配置元数据。
- 在首次启动时迁移现有 `session.json`、消息及已存在的工件索引；原始数据、图表和报告文件保持原位置。
- Conversation 支持新建、打开、重命名、单条删除、全部历史删除、发送消息、模型切换、追加/移除文件和重新生成。
- 建立 LLM Gateway、Provider Adapter、Model Registry、Context Manager 及统一异常规范。
- 首批 Provider：OpenAI、DeepSeek、OpenAI-compatible；未配置 Key 时可显示但不能发起真实请求。
- 模型/API 设置写入本机 `.env`，前端仅收到掩码与“已配置/未配置”状态。
- 以模拟 Provider 运行多轮、多模型、失败、刷新、重启和上下文压缩验收。

### 3.2 不在本次实现

- 不提供开发者自己的 Key，不在测试中调用外网或真实 Provider API。
- 不实现 Anthropic、Gemini、Qwen、Ollama 的具体 Adapter；Registry 与 Adapter 接口必须允许后续接入。
- 不改变现有受控分析函数为模型生成代码，也不让模型直接访问文件系统、shell 或网络。
- 不实现多用户登录、云端密钥托管或跨设备同步。

## 4. 架构

```text
React 工作台
  ├─ Conversation History / 文件列表
  ├─ 持续聊天区 + Provider / Model 选择器
  ├─ 结果、图表、数据、报告、文件 Tab
  └─ 设置页（本机 .env 配置）
              ↓
FastAPI Conversation API
              ↓
Conversation Service ── SQLite Repository ── Conversation / Message / State
              ↓
Agent Orchestrator
  ├─ Context Manager
  ├─ 已有确定性分析引擎、图表、报告能力
  └─ LLM Gateway ── Provider Adapter ── OpenAI / DeepSeek / Compatible
```

数据计算、证据、图表和报告始终由已有受控引擎产生。Provider 只承担当前问题的理解、受支持分析动作的选择和基于真实执行结果的回答组织；所有 Provider 使用相同的 Orchestrator 与工具接口。

## 5. 数据模型

### 5.1 Conversation

```json
{
  "id": "uuid",
  "title": "2024-2025 经营趋势分析",
  "selected_provider": "deepseek",
  "selected_model": "deepseek-chat",
  "conversation_summary": "用户正在分析 2024-2025 年经营趋势，已关注营业收入、毛利率和营业利润。",
  "status": "active",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601"
}
```

标题在首条用户问题后由本地规则生成，控制在 10--20 个中文字符附近；标题重复时沿用已有序号规则。切换模型只更新 `selected_provider` 与 `selected_model`，不得删除 Message、AnalysisState、文件或工件。

### 5.2 Message

```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "role": "user | assistant | system",
  "content": "用户问题或可见回答",
  "provider": "deepseek",
  "model": "deepseek-chat",
  "status": "completed | failed | streaming",
  "error_code": null,
  "artifact_ids": ["uuid"],
  "created_at": "ISO-8601"
}
```

用户消息先持久化，再开始分析或调用 Provider。调用失败时新增失败状态的 assistant Message，原始用户消息与旧结果保留；重新生成创建新的 assistant Message，绝不改写或重排原消息。

### 5.3 AnalysisState

每个 Conversation 仅有一个当前结构化状态，更新采用字段级合并而非整块覆盖：

```json
{
  "conversation_id": "uuid",
  "active_file_ids": ["uuid"],
  "active_sheet": "财务汇总",
  "filters": {"region": ["华东"]},
  "date_range": {"start": "2024-01", "end": "2025-12"},
  "metrics": ["营业收入", "毛利率", "营业利润"],
  "dimensions": ["月份"],
  "previous_findings": ["uuid"],
  "previous_calculations": ["uuid"],
  "previous_charts": ["uuid"],
  "current_question": "重点看 2025 年下半年",
  "current_analysis_goal": "经营趋势分析",
  "generated_reports": ["uuid"]
}
```

例如“只看 2025 年”只更新 `date_range`；“把刚才图换成柱状图”复用 `previous_charts` 和计算结果，生成新图表工件并保留旧图。

### 5.4 文件、工件和删除语义

`ConversationFile` 将 Conversation 与可复用 Dataset/File 以一对多关系绑定；任何分析仅读取该 Conversation 的活动文件。`Artifact` 记录文件路径、类型、来源 Message、分析状态快照和创建时间。

单条删除会删除该 Conversation 的数据库记录、消息、状态、会话专属工件及其文件。数据集若仍被其他 Conversation 使用则保留。"清空全部历史"复用相同删除逻辑，要求用户二次确认，避免误删；删除成功后刷新页面不应恢复记录。

## 6. Provider、模型与配置

### 6.1 统一接口

```python
class BaseLLMProvider:
    def chat(self, messages, model, temperature=None, tools=None, stream=False, **kwargs):
        raise NotImplementedError
```

业务层只调用 `llm_gateway.chat(...)`。Gateway 负责 Provider 路由、Base URL、超时、重试、能力检查、流式事件与异常规范化；不得在 Orchestrator 中出现按 Provider 分支的 SDK 调用。

### 6.2 Model Registry

每项模型包含 `provider`、`model_id`、`display_name`、`context_window`、`supports_tools`、`supports_streaming`、`supports_vision` 和 `supports_structured_output`。Provider 切换时模型下拉框只显示该 Provider 的注册模型。模型不支持工具时 Gateway 不传 tools，统一 Agent 仍可使用确定性分析引擎。

### 6.3 密钥与设置页

`.env` 是唯一敏感配置存储：

```dotenv
OPENAI_API_KEY=
OPENAI_BASE_URL=
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
OPENAI_COMPATIBLE_NAME=
OPENAI_COMPATIBLE_API_KEY=
OPENAI_COMPATIBLE_BASE_URL=
OPENAI_COMPATIBLE_MODEL=
```

仓库新增 `.env.example` 并将 `.env` 写入 `.gitignore`。设置页的保存请求由后端写入本机 `.env`；读取接口仅返回 Provider 名称、Base URL、模型选择与掩码状态，永不返回 Key。连接测试使用统一 Gateway，并将认证、限流、超时、连接、模型不存在和通用 Provider 错误映射成可行动提示。

## 7. 多轮上下文与回答流程

每次发送消息按顺序执行：

1. 持久化用户 Message，更新 `current_question`。
2. Context Manager 读取 Conversation Summary、AnalysisState、最近消息以及当前问题相关的数据上下文。
3. Orchestrator 识别可复用的分析结果或受控分析动作，调用现有引擎生成/更新真实证据、表格、图表与报告。
4. 仅把 schema、列信息、样本、必要聚合、已验证计算和图表摘要交给 Provider；不传完整 DataFrame。
5. Provider 或模拟 Provider 生成可见回答，保存带 Provider/Model 标签的 assistant Message 和关联 Artifact。
6. 字段级合并 AnalysisState；Context 超预算时把早期消息归纳进 `conversation_summary`，原始 Message 不删除。

调用失败时第 1 步的用户消息仍在，步骤 3 的已成功工件仍在。UI 显示失败原因、重新生成和切换模型入口。不会伪造模型思维链；只显示“正在读取数据”“正在计算指标”“正在生成图表”等已执行阶段。

## 8. 前端交互

- 顶部或输入框邻近位置放置 Provider / Model 快速选择；历史 assistant Message 显示简短模型标签。
- 中栏消息区独立滚动，输入框固定底部。已完成 Conversation 仍可继续输入，不能再显示“新需求请新建独立分析任务”。
- 左栏是 Conversation History：新建、搜索、打开、重命名、单条删除和清空历史；文件列表显示当前 Conversation 的已绑定文件。
- 右栏继续使用当前结果 Tab，且只显示当前 Conversation 的 Artifact；新增消息时默认保持核心结论与图表可见，不堆叠无关模块。
- 设置入口包含 Provider/API 配置、掩码状态、连接测试和保存提示。

## 9. API

保留现有下载路由，并提供以下 Conversation API：

```text
POST   /api/conversations
GET    /api/conversations
GET    /api/conversations/{id}
PATCH  /api/conversations/{id}
DELETE /api/conversations/{id}
DELETE /api/conversations
POST   /api/conversations/{id}/messages
POST   /api/conversations/{id}/files
DELETE /api/conversations/{id}/files/{file_id}
PUT    /api/conversations/{id}/model
POST   /api/messages/{id}/regenerate
GET    /api/providers
GET    /api/models?provider={provider}
GET    /api/settings/providers
PUT    /api/settings/providers/{provider}
POST   /api/providers/test
```

旧 Session API 在迁移期可保留兼容读取；前端改用 Conversation API。历史迁移必须可重复执行而不产生重复 Conversation。

## 10. 测试与验收

后端 pytest、前端 Vitest 和浏览器端到端验证均必须运行。最低覆盖：

1. 创建 Conversation，发送“分析营业收入趋势”获得持久化回答。
2. 发送“那 2025 年呢”只更新日期范围且能理解指代。
3. 发送“把刚才图换成柱状图”复用上个图表数据并生成新 Artifact。
4. DeepSeek 模拟 Provider 切到 OpenAI 模拟 Provider，历史、文件和状态不丢失。
5. Provider 调用失败后 Conversation、用户消息与旧工件仍可打开。
6. 浏览器刷新与后端重启后恢复 Conversation。
7. 新 Conversation 不读取旧 Conversation 的文件或 AnalysisState。
8. 两个 Conversation 分别绑定不同文件且分析不串线。
9. 超长消息历史触发 Summary，原始 Message 完整保留。
10. 单条删除与清空历史均经确认后持久生效，且不误删仍被使用的数据集。

还需保留现有数据分析、证据、图表、报告、零行数据、窄屏、快速连续发送等回归测试。真实 API 连通性不属于本次验收；连接测试通过模拟 Gateway 契约和明确的错误映射验证。

## 11. 已知限制与后续方向

本地 `.env` 适合单用户自托管；如要多用户或云端发布，应改为部署环境密钥或密钥管理服务，不能共享本机 `.env`。首批未实现流式真实 API 传输，但前后端事件接口和 `streaming` 状态预留；接入真实 Provider 后可在不改变 Conversation 数据结构的前提下补齐。
