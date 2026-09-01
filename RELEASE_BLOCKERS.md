# GitHub Release Blockers

## Release Decision

NOT READY

## Critical Summary

隔离克隆的安装、构建和基础服务启动可以完成，但发布版本复现了一个核心语义错误：询问“按销量对商品排名”时，系统返回了按“地区”汇总的结果。另有大模型异常输出未被转换为可恢复错误。并且当前待发布的功能和测试仍未提交，GitHub 克隆得到的不是已验证的工作区版本。

## Blockers

### BLOCKER-001

问题：待发布代码与当前已验证工作区不一致，关键功能、测试和文档仍处于未提交状态。

严重度：Critical

为什么阻止发布：GitHub 使用者只能获得已提交版本；当前通过的 123 个后端测试、26 个前端测试和模型/会话相关实现并不会随当前分支发布。发布内容不可复现。

复现方法：在全新临时目录克隆 `codex/universal-analysis-agent-mvp`，再比较该副本与本工作区的 `git status --short` 和 `git diff --stat`。

证据：工作区有 18 个已修改的跟踪文件及模型、会话、图表和测试等未跟踪文件；隔离克隆状态干净，但内容不含这些变更。

涉及文件：`README.md`、`apps/web/src/App.tsx`、`backend/studio_api/app.py`、`backend/studio_api/llm/*`、`backend/tests/*` 等。

建议修复：仅提交经过本次审计验证且确需发布的源码、测试和文档；重新在提交后的干净克隆中执行完整 Gate。

### BLOCKER-002

问题：商品销量排名请求发生维度错配。

严重度：Critical

为什么阻止发布：这是用户可见的数据分析结论错误。输入四行商品销量数据后，问题为“按销量对商品进行排名，并给出最高商品和数据证据”，期望最高商品为 `B`、销量 `25`；系统却返回“地区中的华北对应销量汇总值为 25”。数值恰好相同不能掩盖分析对象错误。

复现方法：上传列为 `商品,销量,销售额,地区` 的 CSV，提交上述问题并调用 Session 分析接口。

证据：隔离运行时在独立端口和独立数据目录中稳定复现；返回结论为“地区 中的 华北 对应 销量 汇总值为 25”。

涉及文件：`backend/studio_api/planning.py`、`backend/studio_api/execution.py`、相关 API/验收测试。

建议修复：计划器必须同时锁定问题中的指标和分组维度；无高置信度 `商品` 映射时应拒答，不得回退到未请求字段；加入此 CSV 的 API 回归用例。

### BLOCKER-003

问题：OpenAI 兼容模型返回非 JSON 内容时抛出未处理的 `JSONDecodeError`。

严重度：Critical

为什么阻止发布：真实模型服务偶发返回 HTML、网关错误页或截断内容时，会绕过 `ProviderError` 恢复路径，造成请求异常而不是保存可理解的失败消息。

复现方法：用返回 `b'{not-json'` 的响应替身调用 `OpenAICompatibleProvider.chat()`。

证据：实际执行结果为 `JSONDecodeError`；当前代码仅捕获 `HTTPError`、`URLError`、`OSError` 和响应字段错误。

涉及文件：`backend/studio_api/llm/openai_compatible.py`、`backend/studio_api/conversation_service.py`。

建议修复：捕获 JSON 解码和文本解码异常并转换为 `ProviderError`；增加畸形 JSON、空 `choices`、非字符串 content 的端到端恢复测试。

### BLOCKER-004

问题：待提交工作区的 README 本机端口与前端代理端口不一致。

严重度：High

为什么阻止发布：当前 README 指导后端使用 `8001`，而当前 `apps/web/vite.config.ts` 的默认代理为 `8011`。若直接提交当前工作区，陌生开发者按 README 启动后前端会请求错误 API 端口。

复现方法：按当前 README 启动后端至 `8001`，启动当前前端并发送任意 API 请求。

证据：README 第 34 行为 `--port 8001`；当前 Vite 配置默认值为 `http://127.0.0.1:8011`。

涉及文件：`README.md`、`apps/web/vite.config.ts`。

建议修复：统一默认端口，或在 README 明确 `VITE_API_URL` 的配置方法，并在干净克隆中验证。

### BLOCKER-005

问题：跟踪的设计/计划文档包含本机绝对路径。

严重度：High

为什么阻止发布：公开仓库会暴露用户本机路径，且文档中的验收命令不能被他人复现。

复现方法：搜索 `F:\\`。

证据：4 处命中，包括 `docs/superpowers/specs/2026-08-31-composite-chinese-metric-analysis-design.md` 与相关计划文档中的 `F:\财务分析样例数据.xlsx`。

涉及文件：`docs/superpowers/plans/*`、`docs/superpowers/specs/*`。

建议修复：改为仓库内公开样例或变量占位符；确认文档无个人路径后再提交。

## High Priority Before Release

- `.gitignore` 未覆盖 `.coverage`、`.pytest_cache`、`.runtime-*`、运行日志和 Vite 缓存；当前工作区已出现相应未跟踪产物。发布前应补全忽略规则并只暂存允许发布的文件。
- 干净 Python 环境可安装运行依赖并通过 `pip check`，但没有 `pytest`；README 也没有测试命令或开发依赖说明，第三方无法复跑测试。
- 未发现应用层结构化日志配置；模型、上传和分析失败在生产环境中的关联排障信息不足。
- 仓库未跟踪 License。若以开源方式发布，应在发布前补充许可与适用说明。

## Can Be Fixed After Release

- 24,000 行 CSV 上传并完成一次分析耗时约 1.1 秒且未崩溃；该次问题因字段语义不匹配返回 `INSUFFICIENT_DATA`。仍应补充公开、可重复的大数据性能基准和浏览器渲染指标。
- 无法在本机占用的默认 `8001` 端口上完成“干净前端 + 干净后端”同端口 UI 全链路；已在独立端口完成后端流程验证。发布后应把端口设为可配置并在 CI 中覆盖完整 UI 流程。

## Security

- 当前 `.env` 未被 Git 跟踪，且已在 `.gitignore`；当前跟踪文件扫描未发现高置信度真实 Key。
- Git 历史的模式扫描仅命中旧测试文件中的无效 Key 夹具（已在审计输出中脱敏），未确认真实 Key 泄漏。发布前仍建议执行一次组织级密钥扫描并轮换任何曾用于测试的真实凭证。

## Data Accuracy

- 财务趋势样例的 16 个独立数值复核全部通过：收入、成本、毛利、净利润四项各四个月均与 CSV 一致。
- 字段/维度匹配存在 BLOCKER-002 所述错误，因此不能声明通用问数场景可靠。
- 不存在的“平均年龄”字段返回 `INSUFFICIENT_DATA` 且无发现项，未编造数值。

## Installation

- 隔离克隆中 `pip install -r requirements.txt`、`pip check`、`pnpm install --frozen-lockfile` 与前端生产构建成功。
- 后端健康检查返回 200；默认端口被本机既有服务占用时，隔离副本可改用独立端口启动。

## Documentation

- 已提交版本的 README 可说明基础安装、启动和 Docker，但缺少开发测试依赖/命令说明。
- 当前工作区的模型配置文档尚未提交，且端口说明与代码不一致（BLOCKER-004）。

## Runtime Stability

- 两个并发分析 Session 均成功并返回不同结果；服务重启后既有 Session 与结果可恢复。
- 非法扩展名上传返回 422；三种报告文件均可下载。
- 畸形模型 JSON 会触发未处理异常（BLOCKER-003）。

## Multi-task Isolation

- 两个不同数据集的 Session ID、Dataset ID、结果与并发返回均保持独立；未发现已复现的数据串扰。

## UI Blocking Issues

- 隔离前端可加载初始工作区，不是白屏；界面截图已保存到审计附件目录。
- 由于默认代理端口被本机既有服务占用，未将该 UI 结果作为干净端到端 API 成功证据。

## Final Recommendation

先修复并验证 BLOCKER-001 至 BLOCKER-005，尤其是字段维度绑定和模型异常恢复；随后提交发布内容，在全新克隆环境重新跑安装、UI 主流程和 API 回归。完成前不建议公开发布。
