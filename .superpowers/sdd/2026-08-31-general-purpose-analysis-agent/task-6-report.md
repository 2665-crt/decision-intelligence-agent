# Task 6 验收报告：通用验收数据集与对抗性审查

## 结论

通过。新增 `backend/tests/test_generic_acceptance.py`，使用测试内存数据覆盖十类业务/数据领域和全部对抗性检查。每个领域用例均经过真实的 `profile -> build_plan -> execute_plan -> validate_result` 链路；多 Sheet、多文件用例在此基础上继续检查关系候选、置信度和文件 hash。

未发现需要修改产品代码的缺陷。低库存风险和无时间字段预测均保守返回 `INSUFFICIENT_DATA`，没有生成虚假 finding、evidence 或数字。

## 十领域验收矩阵

| # | 领域 | 问题与数据 | 计划/校验状态 | 核心计算或拒绝原因 | Evidence 断言 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 电商 | 产品销售额排名 | `READY -> SUCCESS` | `groupby(product_name).sum(sales_amount)`；A=150 | hash、table、fields、rows、output/metric value 完整 | 通过 |
| 2 | 交通 | 路段拥堵指标比较 | `READY -> SUCCESS` | `groupby(road_segment).mean(congestion_index)`；east=0.85 | 计算式和参与行可回溯 | 通过 |
| 3 | 成绩 | 科目成绩均值差异 | `READY -> SUCCESS` | `groupby(subject).mean(score_value)`；math=90 | 分组、数值和参与行一致 | 通过 |
| 4 | 服务器日志 | `error_rate` 异常时段 | `READY -> SUCCESS` | `iqr_outliers(error_rate, k=1.5)`；第 4 行=0.95 | 时间上下文、异常行和数值一致 | 通过 |
| 5 | 库存 | 识别低库存风险 | `INSUFFICIENT_DATA` | 当前问题不对应允许的排名、趋势、异常、比较、相关或预测算子 | findings/evidence 均为空，回答说明能力不足 | 通过 |
| 6 | 财务 | 非标准字段 `net_result_x` 下降趋势 | `READY -> SUCCESS` | `groupby(period_key).sum(net_result_x).sort_index()`；120 降至 80 | 未依赖“营业收入/营业利润”等固定字段 | 通过 |
| 7 | 无时间预测 | 预测 `measure_x` | `INSUFFICIENT_DATA` | 缺少可信时间字段 | findings/evidence 均为空，限制明确指出时间字段 | 通过 |
| 8 | 非标准字段 | `dt/col1/value_x` 排名 | `READY -> SUCCESS` | Profile 判定 time/dimension/metric；`groupby(col1).sum(value_x)`；alpha=25 | 语义置信度均不低于 0.70，数值可回溯 | 通过 |
| 9 | 多 Sheet | customers/orders/activity | `READY -> SUCCESS` | orders 内 `groupby(region).sum(load_value)`；仅 customers-orders 高置信关系可自动使用 | 中低置信关系全部要求确认，未进入计划字段或计算 | 通过 |
| 10 | 多文件 | customers.csv + orders.csv | `READY -> SUCCESS` | orders 内 `groupby(region).sum(order_value)` | 两次 profile/relationship 输出一致；两文件 SHA-256 和关系两端 hash 完整 | 通过 |

## 对抗性审查

| 检查 | 验证方式 | 结果 |
| --- | --- | --- |
| 未知/低置信字段不得计算 | 单行 `mystery_label/mystery_value=999999` 均低于 0.70；计划字段为空，回答不含 999999 | 通过 |
| `sales_amount` 不得响应“销量” | 问题请求销量时仅选择产品维度，不选择 `sales_amount`，最终 `INSUFFICIENT_DATA` | 通过 |
| 非数值/NaN 不污染证据 | `bad` 和空值行从排名参与行排除；A=27 的 evidence rows 仅为 0、2、4、5 | 通过 |
| 不安全关联不得自动使用 | `account_id` 与 `group_id` 不产生候选；相同 `paid_amount` 只产生需确认候选 | 通过 |
| 数值 finding 缺 calculation/value 必须拒绝 | 参数化构造缺 calculation、缺 output value 两种 finding；均被 validator 拒绝 | 通过 |
| 输出数字必须可回溯 | 校验回答严格由 validated findings 拼接；finding value/metric_value 与 evidence output/metric value 完全一致 | 通过 |

## 验证结果

| 命令 | 结果 |
| --- | --- |
| `python -m pytest backend/tests/test_generic_acceptance.py -q` | 17 passed |
| `python -m pytest backend/tests -q` | 70 passed |
| `pnpm test --run`（`apps/web`） | 11 passed |
| `pnpm --dir apps/web build` | 成功，Vite 生产构建完成 |
| `python -m compileall -q backend` | 成功 |
| `git diff --check` | 通过 |

## 已确认限制

- 当前基础执行白名单没有“低库存风险”专用算子；系统保守拒绝，不把最低值排名包装成已识别风险。
- 预测虽可被计划识别，但执行白名单尚无 forecast 执行器；本次无时间字段用例在计划阶段即因缺可信时间字段而拒绝。
- 多 Sheet/多文件验收覆盖 Profile 与关系发现安全策略；当前通用执行链仍为单表受控计算，不自动执行跨表 join。
