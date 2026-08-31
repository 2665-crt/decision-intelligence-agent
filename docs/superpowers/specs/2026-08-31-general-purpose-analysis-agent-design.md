# 通用可信数据分析 Agent 设计

## 目标

将现有依赖财务字段关键词的结果生成器替换为通用结构化数据分析流程。Excel、CSV、JSON、TSV 与多 Sheet 工作簿进入同一套数据理解、问题规划、真实计算、验证和证据构建流程；任何数字结论均可复算并追溯到输入文件版本。

## 非目标

- 不以名称猜测不确定的业务事实。
- 不让语言模型或模板生成未经计算的数值。
- 不在低置信度多文件关联上自动 join。
- 本阶段不改变用户选择“当前实验分支，不合并 master”的约束。

## 架构

### 1. File Parser 与 Dataset Profile

`intake.py` 读取所有支持格式为 `DatasetProfile`：文件 hash、表/数据框列表、每个表的行列数、列 profile、缺失/重复和样例。Excel 不再在上传时丢弃未选 Sheet；CSV、TSV、JSON 统一转换为命名表。

每个 `ColumnProfile` 由字段名、可解析类型、非空率、唯一率、样例、数值分布和与其他字段关系综合得到 `semantic_role`（time、metric、dimension、identifier、text、uncertain）与置信度。字段名只是一个信号；置信度不足时保留 `uncertain`。

### 2. Question Planner

Planner 输入 `DatasetProfile` 与用户问题，输出确定的 `AnalysisPlan`：目标、状态要求、选中的 Sheet、字段、过滤、聚合、计算算子、图表请求和每一步的前置条件。计划只从 profile 中存在的字段引用；找不到必要字段会产生 `INSUFFICIENT_DATA` 计划，而不是回退到默认营收模板。

初始算子集为：排名聚合、时间趋势、异常检测、相关性、分组差异、库存覆盖风险、时间预测。每个算子声明输入角色、输出 schema、可复核计算和最小数据量。预测使用固定随机种子、时间切分与朴素基线。

### 3. Executor、Evidence 与 Validator

Executor 只执行允许的 pandas/numpy 算子，返回 `ComputedFinding`，包含真实值、源表/字段、过滤、分组、公式/方法和行级证据定位。Insight 文本只能由 finding 模板生成，区分事实、推断、假设和建议。

Validator 在展示前验证：计划字段/Sheet 存在、数值来自 executor、筛选与时间范围有效、无 NaN/除零、排名正确、图表数据引用同一 finding。失败时返回 `PARTIAL` 或 `INSUFFICIENT_DATA`，不产生数值结论。

### 4. 多 Sheet 与多文件

Planner 依据字段语义和问题从 profile 中选择相关表。多个表之间先输出候选 join（同名/可兼容类型、键唯一率、匹配率、置信度）；只有高置信候选自动执行，其他候选作为需用户确认的限制。Dataset 与分析 Session 保存 file hash 和 profile snapshot，重跑使用同一版本与相同参数。

### 5. 结果与 UI

结果 contract 扩展为 `analysis_id`、`status`、`source`、`schema`、`plan`、`findings`、`evidence`、`charts`、`limitations`、`run_metadata`。每项 finding 带可信度和可展开的证据链。页面按“问题、直接答案、关键结论、详细分析、图表、数据证据、限制”渲染；只有有数据的模块出现。

## 数据流

`上传文件 -> DatasetProfile -> AnalysisPlan -> Executor -> ComputedFindings -> Validator -> Evidence Builder -> Structured Result -> UI`。

每个步骤保留可序列化快照；同一 `file_hash + plan + seed` 可重放。

## 兼容与迁移

保留 Dataset/Session API、报告和现有财务样例作为回归。旧 `QuestionPlan` 与财务专用回答不再作为默认路径；它们被通用的 profile/plan/算子适配层替换。无法支持的 Word 文档继续明确标识为文本审阅而非测量分析。

## 验收

为以下数据和问题建立可执行测试：电商 Top 产品、交通最拥堵时段、学生成绩差异、日志最高错误率、库存缺货风险、财务利润下降、无时间字段的预测拒答、非规范字段的不确定性、多 Sheet 选择、多文件候选关联。每一项验证状态、结论、数值来源、证据链、图表适用性和不可回答时的限制说明。

## 决策

- 第一阶段交付通用 profile、planner、五个基础算子、validator/evidence contract 与十类验收夹具。
- 多文件自动 join 仅限 confidence >= 0.95，且键唯一率与匹配率均 >= 0.95；其余状态为 `PARTIAL` 并提示确认。
- 字段语义 confidence < 0.70 时不得自动用于关键计算。
