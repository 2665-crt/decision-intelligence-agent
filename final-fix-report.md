# 最终定点修复报告

## 修复范围

1. 复合指标请求把静态财务别名和通用数值字段放入同一候选跨度，统一按出现位置、最长匹配和包含边界去重。问题明确写出“营业收入目标”时，不再截断为“营业收入”；静态别名与同名字段跨度相同时仍保留静态财务语义。
2. 比率异常关联的 `reason_comment`、`reason_driver`、`reason_unavailable` 增加关联指标类型元数据。机器字段 `metric_value` 保留原始比率值，所有用户可见 KPI 值和 detail 统一显示百分比，例如 `90.00%`。

## TDD 证据

- 修复前定向用例：2 项按预期失败，分别实际选成“营业收入”和显示原始值 `0.9`。
- 修复后定向用例：2 passed。
- 相邻覆盖：复合分析相关 28 passed；通用验收 17 passed。

## 全量验证

- 后端：`.venv\Scripts\python.exe -m pytest backend/tests -q` → 98 passed。
- 前端：`pnpm --dir apps/web test --run` → 11 passed。
- 前端生产构建：`pnpm --dir apps/web build` → 成功，34 modules transformed。
- 差异检查：`git diff --check` 无空白错误；仅有 Git 的 LF/CRLF 工作区提示。

## 边界与顾虑

- 本次仅修改指标请求匹配、比率原因展示及对应回归测试，没有扩展分析功能。
- 工作区已有未跟踪运行产物和文档均未删除、未暂存。
