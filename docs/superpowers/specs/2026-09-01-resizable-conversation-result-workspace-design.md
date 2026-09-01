# Conversation 与 Result 可调整工作区设计

## 目标与范围

将当前 Conversation 与 Result Workspace 的固定双栏改为可拖拽、可折叠的工作区。保留历史栏、对话消息、结果 Tab、图表、表格、Notebook 与报告的既有行为；不修改后端接口、会话数据、模型配置或结果内容。

## 布局结构

桌面端保持三栏：固定 250px 历史栏、Conversation Pane、Result Workspace。后两栏之间插入 8px 的垂直拖拽条。默认 Conversation / Result 比例为 0.5 / 0.5；Conversation 最小宽度为 380px，Result 最小宽度为 460px。可用宽度不足以同时满足两者时，比例按可用空间夹紧，不允许任一内容面板被拖至不可用。

拖拽条使用 `pointerdown`、窗口级 `pointermove` 与 `pointerup`，支持鼠标、触控板和触摸。拖动期间通过 `requestAnimationFrame` 更新工作区 CSS 自定义属性，避免高频 React 重渲染与布局跳跃；`pointerup` 时再提交 React 状态并写入本地存储。拖拽条提供 `col-resize` 光标、可见细线、悬停强调和可访问标签；双击恢复默认比例。

## 状态与持久化

前端维护以下布局状态：

- `splitRatio`：Conversation 在可用双栏宽度中的比例。
- `resultCollapsed`：Result Workspace 是否折叠。
- `activeResultTab`：结果、图表、数据、Notebook、报告或文件。
- `preCollapseRatio`：折叠前比例，用于恢复。

`splitRatio`、`resultCollapsed` 与 `activeResultTab` 使用独立 localStorage key 持久化。读取时校验类型并夹紧比例；无效值回退默认。拖拽过程中不写 localStorage，只在松手、折叠、展开或切换结果 Tab 时写入。

## 折叠与恢复

Result 折叠后不卸载 Result Workspace，而是将其视觉宽度压缩为 44px 的轨道。轨道顶部常驻“展开结果”按钮；Conversation 占用其余空间。折叠前记录当前比例，展开时恢复该比例。折叠仅改变 CSS 布局，ResultPanel 与其 Tab 内容持续挂载，因此不会重新请求 API、清空图表、重置 Notebook 或改变当前 Tab。

展开状态下，折叠控制位于分隔条顶部，带有明确的中文 `aria-label`。进入折叠状态后，恢复入口保留在 Result 轨道顶部，不能被隐藏。

## 响应式与内容适配

桌面端（大于 720px）启用自由拖拽。窄屏与平板收紧拖拽范围；移动端（不超过 720px）切换为“对话 / 结果”视图切换按钮，两个面板仍保持挂载，结果状态与滚动内容不丢失。

现有 SVG 图表采用容器宽度布局，随 Result 宽度自动重排；不创建新的图表实例。数据表继续由可横向滚动容器包裹。Notebook 的代码与输出容器保持 `min-width: 0` 和独立滚动；报告内容继续在最大阅读宽度内居中。

## 修改位置

- `apps/web/src/App.tsx`：布局状态、拖拽 Pointer Events、折叠/展开控件、移动端视图切换与持久化。
- `apps/web/src/styles.css`：工作区网格、分隔条、折叠轨道、响应式规则和内容容器适配。
- `apps/web/tests/conversation.test.tsx`：布局状态恢复、双击复位、折叠恢复与结果 Tab 保留的交互测试。

## 验收

1. 拖动分隔条时两侧实时变化，且最小宽度受限。
2. 双击分隔条恢复 50 / 50。
3. 刷新后恢复上次有效比例、结果折叠状态和当前结果 Tab。
4. 折叠后 Conversation 占满可用宽度，44px 轨道保留展开入口。
5. 展开后恢复折叠前比例和当前结果 Tab，不发生 API 请求或结果卸载。
6. 图表随容器宽度变化；表格与 Notebook 在窄宽度下保持可读和可滚动。
7. 移动端可在对话与结果间切换，二者状态不丢失。
8. 前端自动化测试、生产构建与浏览器实际拖拽流程均通过。
