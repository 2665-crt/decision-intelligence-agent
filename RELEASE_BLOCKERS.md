# GitHub Release Gate

## Release Decision

READY WITH BLOCKERS FIXED

## Verified Summary

此前阻止发布的五项问题均已修复，并以新增回归测试和隔离环境验证覆盖。当前版本可完成数据上传、受控分析、生成报告、模型会话回答和前端代理联通；回答层保留 `VERIFIED / UNVERIFIED` 证据标识机制。

## Resolved Blockers

### BLOCKER-001: 发布内容与验证内容不一致

状态：已修复。

修复：功能、测试、文档和发布依赖已提交为 `b7c1739` 与 `5e25265`；最终门禁文档会随本次复核提交。运行产物、覆盖率、Pytest 临时目录和 Vite 缓存均已忽略。

验证：在全新临时目录克隆 `5e25265` 后，Python 依赖检查、126 个后端测试、26 个前端测试和前端生产构建均通过。

### BLOCKER-002: 商品销量排名错误使用地区维度

状态：已修复。

修复：数据画像把常见的标签列（含 `商品`）识别为高置信度维度；计划器继续以问题语义筛选维度，避免在“商品排名”请求中回退至未请求的 `地区`。

验证：新增中文商品排名回归用例；真实本地 API 上传 `商品,销量,销售额,地区` 后，返回最高商品 `B`、销量 `25`，且生成的 Markdown 报告为“商品 中的 B 对应 销量 汇总值为 25”。

### BLOCKER-003: 模型服务返回畸形 JSON 时抛出原始异常

状态：已修复。

修复：OpenAI 兼容适配器捕获 JSON 和文本解码异常，统一转换为用户可恢复的 `ProviderError`；会话层可以保存可理解的失败消息，而不是暴露 `JSONDecodeError`。

验证：新增畸形 JSON 响应回归用例，通过。

### BLOCKER-004: README 与前端默认 API 端口不一致

状态：已修复。

修复：前端默认代理改为 `http://127.0.0.1:8001`，与 README 后端启动命令一致；README 说明通过 `VITE_API_URL` 覆盖端口。

验证：在隔离端口上启动后端和前端，页面返回 200，`/api/health` 经 Vite 代理返回 `ok`。

### BLOCKER-005: 文档泄露本机绝对路径

状态：已修复。

修复：四份设计/计划文档已改为仓库相对示例或变量占位符。

验证：对 README、docs、deploy、apps 和 backend 搜索 Windows 绝对路径，无匹配项。

## Regression Evidence

- 后端：`126 passed`；使用项目内 `.pytest-tmp`，规避 Windows 系统临时目录权限造成的假失败。
- 前端：`26 passed`；`vite build` 成功。
- 依赖：隔离克隆中的 `pip check` 成功；`requirements-dev.txt` 明确声明 Pytest 和 FastAPI 测试客户端所需的 `httpx2`。
- 模型回答：模拟模型回答含 `[VERIFIED]`；系统提示明确要求受控证据为 `VERIFIED`，无法证明的解释、建议和假设为 `UNVERIFIED`，且不得补造具体数值。
- 真实 API：上传 CSV、创建会话、发送“按销量对商品进行排名”问题、生成 Markdown/HTML/DOCX 报告均成功。

## Known Release Notes

- 真实第三方模型调用需要发布者自行配置有效 API Key；本次不读取或输出任何密钥。畸形响应的恢复路径已由自动化测试覆盖。
- 未添加开源 License，因为许可类型属于仓库所有者的法律选择；这不影响应用运行，但公开开源前应由所有者确定。
- 组织级 Git 历史密钥扫描和生产级集中日志属于发布后的运维治理项，不是本次功能发布的阻断项。
