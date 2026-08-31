# Composite Chinese Metric Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** 让通用数据分析 Agent 能够稳定回答“多个中文财务指标 + 趋势 + 异常 + 原因 + 数据证据”的复合问题，保持对其他任意结构化数据的通用能力。

**Architecture:** 在现有通用“数据画像 → 规划 → 执行 → 校验 → 展示”流水线中，新增可组合的指标分析计划。规划器以画像中的字段语义、中文字段名和问题意图生成一个主表、多指标、派生比率、趋势和异常的计划；执行器先按时间聚合，再计算趋势、异常和可审计的原因线索；校验器只放行含字段、计算、数值和行级来源的结论。

**Tech Stack:** Python 3.11、pandas、FastAPI、pytest、React、Vitest。

**Spec:** \`docs/superpowers/specs/2026-08-31-composite-chinese-metric-analysis-design.md\`

## 全局约束

- 不按工作簿名称、表名或当前样例的固定数值写规则。
- 字段选择只能来自数据画像的高置信度语义和真实列名；无法匹配时明确说明缺失内容。
- 复合问题可部分完成，但不得用低置信度列完成关键计算。
- 趋势、环比和异常必须在同一时间粒度的聚合值上计算。
- 比率指标必须使用“聚合分子 / 聚合分母”，不能平均明细行百分比。
- “可能原因”只能作为同表、同期的联动证据或备注证据，禁止把相关性说成因果。
- 保持现有单指标、分组、排名、相关性、预测等通用能力和 API 契约兼容。

## 文件结构

- 修改：\`backend/studio_api/planning.py\`
- 修改：\`backend/studio_api/validation.py\`
- 修改：\`backend/studio_api/engine.py\`
- 修改：\`backend/tests/test_analysis_workflow.py\`
- 如确有展示兼容缺口才修改：\`frontend/src/App.jsx\`、\`frontend/src/App.test.jsx\`

## 任务 1：建立复合中文指标规划模型

**文件：**
- 修改：\`backend/studio_api/planning.py\`
- 修改：\`backend/tests/test_analysis_workflow.py\`

- [ ] 先写失败测试：给出包含“期间、营业收入、毛利、营业利润、备注”的合成表画像和复合中文问题，断言规划结果：
  - 选择有月度字段和全部指标的主表；
  - 返回三个指标计划，而不是单一 \`metric\`；
  - \`营业收入\`、\`营业利润\`为直接指标；
  - \`毛利率\`识别为 \`毛利 / 营业收入\` 派生比率；
  - 操作包含 \`trend\`、\`anomaly\`、\`reason_evidence\`。
- [ ] 运行该测试并确认现有单指标 \`AnalysisPlan\` 不能满足断言。
- [ ] 新增只承载复合路径的 \`MetricAnalysisPlan\`、\`CompositeAnalysisPlan\`（或等价清晰数据结构），不删除既有 \`AnalysisPlan\`。
- [ ] 实现中文字段归一化、指标别名匹配和“率”问题的分子/分母匹配。别名来自字段语义与通用中文名称，例如“收入/营收”“毛利”“营业利润/经营利润”，不能出现样例数值或固定月份。
- [ ] 让 \`build_plan\` 在“多指标 + 时间 + 趋势/异常/原因”组合意图下产出复合计划；简单问题继续走原计划。
- [ ] 重跑测试并确认由红转绿。
- [ ] 提交：\`feat: plan composite Chinese metric analysis\`

## 任务 2：按时间粒度执行多指标趋势与异常

**文件：**
- 修改：\`backend/studio_api/planning.py\`
- 修改：\`backend/tests/test_analysis_workflow.py\`

- [ ] 先写失败测试：使用两个年度的月度数据，断言结果对每个直接指标按月聚合，派生毛利率等于每月毛利总额除以收入总额。
- [ ] 在该数据中制造一个收入和营业利润显著变动的月份，断言异常证据包含“月份、当前值、上月值、环比、方法阈值”，而不是原始明细行。
- [ ] 运行测试，确认现有执行器只支持单一字段或行级异常。
- [ ] 实现复合执行分支：
  - 解析并排序时间；
  - 对直接指标按期间求和；
  - 对比率按聚合分子/分母计算；
  - 对所有计划指标计算首末变化、峰值、谷值及相邻期间变化；
  - 以相邻期间变化的 IQR 规则识别异常；样本不足时返回“不足以可靠识别”，不伪造异常。
- [ ] 每项结果保存可展示的计算说明、使用列、时间粒度和原始行引用。
- [ ] 重跑新增和既有后端测试。
- [ ] 提交：\`feat: execute aggregate metric trends and anomalies\`

## 任务 3：生成受证据约束的原因线索并接入校验

**文件：**
- 修改：\`backend/studio_api/planning.py\`
- 修改：\`backend/studio_api/validation.py\`
- 修改：\`backend/studio_api/engine.py\`
- 修改：\`backend/tests/test_analysis_workflow.py\`

- [ ] 先写失败测试：
  - 有“备注”列时，异常月份的原因线索带有同期间备注和来源行；
  - 有费用、销量、单价等同表字段时，线索显示同期联动方向和数值；
  - 没有备注或驱动字段时，答案明确“无法从现有字段确定原因”，不输出猜测。
- [ ] 运行测试，确认当前结果缺少原因证据或可能以泛化语言掩盖缺口。
- [ ] 实现备注列和驱动列的通用识别；驱动输出固定为“同期联动线索”，包括名称、值、对比值、变化和行来源。
- [ ] 扩展验证规则：复合结论必须至少包含数据集、表、列、计算方式、数值和来源行；派生率必须带分子、分母和公式。
- [ ] 在引擎中保留 \`succeeded\`、\`partial\`、\`insufficient_data\` 的真实生命周期状态，并把受验证的复合发现作为用户答案主体。
- [ ] 重跑新增和既有后端测试。
- [ ] 提交：\`feat: validate evidence-backed composite findings\`

## 任务 4：真实工作簿端到端验收与前端适配

**文件：**
- 修改：\`backend/tests/test_analysis_workflow.py\`
- 如需：\`frontend/src/App.jsx\`、\`frontend/src/App.test.jsx\`

- [ ] 写 API 级回归测试：使用由测试创建的等价中文财务工作簿上传、建会话、提问，断言：
  - 最终结论直接回答营业收入、毛利率、营业利润趋势；
  - 每项指标都含数值证据；
  - 异常月份和可能原因线索有来源，不包含固定样例文本；
  - 不再返回“未找到 metric”或无关模块。
- [ ] 先运行并确认其在旧代码失败；完成实现后转绿。
- [ ] 用用户提供的 \`F:\\财务分析样例数据.xlsx\` 调用运行中的本地 API，提交原始问题，保存响应摘要。
- [ ] 检查 UI：主结论优先、证据卡片可追溯、多任务标签不被空模块淹没；若后端结构已兼容则不做无必要 UI 改动。
- [ ] 运行：后端全量 pytest、前端 Vitest、前端生产构建、Python 编译检查。
- [ ] 进行独立对抗性审查：构造缺少分母、缺少时间、低置信度同义列、短样本、无原因字段和多表冲突输入，确认每种情况要么给出可验证答案，要么准确地说明限制。
- [ ] 提交：\`test: cover composite metric analysis acceptance\`

## 最终验收清单

- [ ] 原始用户问题不再返回 \`metric\` 缺失。
- [ ] 结果明确回答营业收入、毛利率、营业利润三个趋势，并有数值与公式证据。
- [ ] 异常检测在月度聚合值上进行，输出异常月份、前后值和环比。
- [ ] 原因表述严格区分“备注证据 / 同期联动线索 / 无法确定”，没有虚构因果。
- [ ] 方案不绑定当前文件，等价结构的任意上传文件均可走通。
- [ ] 既有通用分析和 UI 回归测试通过。
- [ ] 真实样例 API 响应、自动化测试和对抗性审查均通过。


