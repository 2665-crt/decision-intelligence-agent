# Resizable Conversation Result Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Conversation 与 Result Workspace 变为持久化、可拖拽、可折叠且在移动端可切换的工作区。

**Architecture:** 保持历史栏、Conversation Pane 和 Result Workspace 的现有数据流。`App` 仅新增本地布局状态和 Pointer Events；CSS 变量在拖动时由 `requestAnimationFrame` 更新，React/localStorage 只在交互结束时提交。Result Workspace 始终挂载，折叠与移动端切换只改变布局与可见性。

**Tech Stack:** React 19、TypeScript、原生 Pointer Events、CSS Grid、localStorage、Vitest、Testing Library。

**Spec:** `docs/superpowers/specs/2026-09-01-resizable-conversation-result-workspace-design.md`

## Global Constraints

- 不修改后端、Provider、模型、会话数据或 ResultPanel 的分析内容。
- 桌面默认 split ratio 为 `0.5`；Conversation 最小宽度 `380px`，Result 最小宽度 `460px`，拖拽条宽度 `8px`，折叠轨道宽度 `44px`。
- 拖动中不写 localStorage，不发 API 请求，不卸载 Result Workspace。
- 拖拽使用 Pointer Events 和 `requestAnimationFrame`；不增加第三方 split-pane 依赖。
- 移动端阈值为 `720px`，以“对话 / 结果”按钮切换，两个面板保持挂载。
- 当前工作树已有用户改动；不得提交、重置、覆盖或清理无关文件。

---

### Task 1: 布局状态与持久化工具

**Files:**
- Modify: `apps/web/src/App.tsx:1-150`
- Test: `apps/web/tests/conversation.test.tsx`

**Interfaces:**
- Produces: `DEFAULT_SPLIT_RATIO`, `MIN_CONVERSATION_WIDTH`, `MIN_RESULT_WIDTH`, `readStoredRatio`, `clampSplitRatio` 与布局 localStorage key。
- Consumes: 浏览器 `localStorage`、`window.innerWidth`。

- [ ] **Step 1: 写入失败测试，覆盖无效缓存回退与有效缓存恢复**

```tsx
test("restores a valid saved workspace layout and ignores invalid values", async () => {
  localStorage.setItem("analysis-studio-conversation-split-ratio", "0.68");
  localStorage.setItem("analysis-studio-result-collapsed", "true");
  localStorage.setItem("analysis-studio-active-result-tab", "图表");
  render(<App />);
  expect(await screen.findByLabelText("展开结果工作区")).toBeInTheDocument();

  cleanup();
  localStorage.setItem("analysis-studio-conversation-split-ratio", "not-a-number");
  render(<App />);
  expect(screen.getByTestId("conversation-result-split")).toHaveAttribute("data-split-ratio", "0.5");
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pnpm test --run tests/conversation.test.tsx`

Expected: FAIL，缺少 `展开结果工作区` 和 `conversation-result-split`。

- [ ] **Step 3: 在 `App.tsx` 添加确定性布局状态与工具函数**

```tsx
const DEFAULT_SPLIT_RATIO = 0.5;
const MIN_CONVERSATION_WIDTH = 380;
const MIN_RESULT_WIDTH = 460;
const SPLIT_RATIO_KEY = "analysis-studio-conversation-split-ratio";
const RESULT_COLLAPSED_KEY = "analysis-studio-result-collapsed";
const RESULT_TAB_KEY = "analysis-studio-active-result-tab";

function splitBounds(availableWidth: number) {
  if (availableWidth >= MIN_CONVERSATION_WIDTH + MIN_RESULT_WIDTH) {
    return {
      min: MIN_CONVERSATION_WIDTH / availableWidth,
      max: 1 - MIN_RESULT_WIDTH / availableWidth,
    };
  }
  return { min: 0.42, max: 0.52 };
}

function clampSplitRatio(value: number, availableWidth: number) {
  const { min, max } = splitBounds(Math.max(availableWidth, 1));
  return Math.min(Math.max(value, min), max);
}

function readStoredRatio() {
  const value = Number(localStorage.getItem(SPLIT_RATIO_KEY));
  return Number.isFinite(value) && value > 0 && value < 1 ? value : DEFAULT_SPLIT_RATIO;
}
```

初始化 `splitRatio`、`resultCollapsed`、`activeTab`，并在状态改变的 effect 中写入三个 key。`activeTab` 读取值必须属于 `resultTabs`，否则回退“结果”。在可用宽度小于 `840px` 但仍处于桌面/平板模式时，采用 `0.42–0.52` 的自适应比例范围；`720px` 及以下进入移动端视图。因此宽窗口严格遵守 380px / 460px 最小值，窄窗口不会因两个固定最小值相加超过可用空间而失去可用性。

- [ ] **Step 4: 运行测试并确认通过**

Run: `pnpm test --run tests/conversation.test.tsx`

Expected: PASS，既有对话、模型切换和设置测试仍通过。

### Task 2: 桌面端 Pointer 拖拽、边界与双击复位

**Files:**
- Modify: `apps/web/src/App.tsx:140-245`
- Modify: `apps/web/src/styles.css:1-110`
- Test: `apps/web/tests/conversation.test.tsx`

**Interfaces:**
- Consumes: Task 1 的 `splitRatio`、边界常量和 key。
- Produces: `data-testid="conversation-result-split"` 容器、`aria-label="调整对话与结果宽度"` 的 divider，以及 `onPointerDown` / `onDoubleClick`。

- [ ] **Step 1: 写入失败测试，覆盖拖拽夹紧与双击复位**

```tsx
test("resizes the conversation result split within limits and resets on double click", async () => {
  render(<App />);
  const divider = await screen.findByLabelText("调整对话与结果宽度");
  fireEvent.pointerDown(divider, { pointerId: 1, clientX: 800 });
  fireEvent.pointerMove(window, { pointerId: 1, clientX: 99999 });
  fireEvent.pointerUp(window, { pointerId: 1, clientX: 99999 });
  expect(screen.getByTestId("conversation-result-split").getAttribute("data-split-ratio")).not.toBe("1");
  fireEvent.doubleClick(divider);
  expect(screen.getByTestId("conversation-result-split")).toHaveAttribute("data-split-ratio", "0.5");
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pnpm test --run tests/conversation.test.tsx`

Expected: FAIL，缺少 divider 与 CSS 变量。

- [ ] **Step 3: 实现 requestAnimationFrame 驱动的 Pointer 拖拽**

```tsx
const workspaceRef = useRef<HTMLElement>(null);
const dragRef = useRef<{ startX: number; startRatio: number; frame: number | null }>({ startX: 0, startRatio: 0, frame: null });

const setLiveRatio = (ratio: number) => {
  const node = workspaceRef.current;
  if (!node) return ratio;
  const available = node.getBoundingClientRect().width - HISTORY_WIDTH - DIVIDER_WIDTH;
  const boundedRatio = clampSplitRatio(ratio, available);
  node.style.setProperty("--conversation-width", `${Math.round(available * boundedRatio)}px`);
  node.dataset.splitRatio = String(boundedRatio);
  return boundedRatio;
};

const startResize = (event: React.PointerEvent<HTMLButtonElement>) => {
  if (resultCollapsed) return;
  event.currentTarget.setPointerCapture(event.pointerId);
  dragRef.current = { startX: event.clientX, startRatio: splitRatio, frame: null };
  const move = (moveEvent: PointerEvent) => {
    const node = workspaceRef.current;
    if (!node) return;
    const available = node.getBoundingClientRect().width - 250 - 8;
    const ratio = clampSplitRatio(dragRef.current.startRatio + (moveEvent.clientX - dragRef.current.startX) / available, available);
    if (dragRef.current.frame) cancelAnimationFrame(dragRef.current.frame);
    dragRef.current.frame = requestAnimationFrame(() => setLiveRatio(ratio));
  };
  const end = () => {
    const ratio = Number(workspaceRef.current?.dataset.splitRatio) || splitRatio;
    setSplitRatio(ratio);
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", end, { once: true });
};
```

展开时使用 CSS Grid 列 `250px minmax(0, var(--conversation-width)) 8px minmax(0, 1fr)`；`--conversation-width` 是上面 `setLiveRatio` 计算出的像素值，不能在 CSS 中进行 ratio 与 `fr` 的乘法。初始化、`ResizeObserver` 回调和每次状态比例变更都调用 `setLiveRatio(splitRatio)`，窗口变化后用同一 ratio 重新换算像素宽度。实际可用宽度由 JS 夹紧，CSS 负责独立滚动。divider 使用 button，双击将像素变量和状态都恢复为 `0.5`。

- [ ] **Step 4: 添加 divider 视觉和滚动隔离样式**

```css
.conversation-result-split { --conversation-width: 50%; }
.workspace-divider { width: 8px; cursor: col-resize; touch-action: none; background: linear-gradient(90deg, transparent 3px, #c8d6df 3px 5px, transparent 5px); }
.workspace-divider:hover, .workspace-divider:focus-visible { background: linear-gradient(90deg, transparent 2px, #178371 2px 6px, transparent 6px); outline: 0; }
```

Conversation 和 Result 均保留 `min-width: 0`、`overflow: hidden`，内部 `messages` 与 `result-panel` 保持独立滚动。

- [ ] **Step 5: 运行交互测试并确认通过**

Run: `pnpm test --run tests/conversation.test.tsx`

Expected: PASS，拖拽不会把任一内容面板推到 0 宽，双击恢复默认比例。

### Task 3: Result 折叠、展开与结果状态保留

**Files:**
- Modify: `apps/web/src/App.tsx:220-245`
- Modify: `apps/web/src/styles.css:80-145`
- Test: `apps/web/tests/conversation.test.tsx`

**Interfaces:**
- Consumes: Task 1 的 `resultCollapsed`、`activeTab`、`preCollapseRatio`。
- Produces: `aria-label="折叠结果工作区"` 和 `aria-label="展开结果工作区"` 控件；Result 轨道样式类 `result-workspace-collapsed`。

- [ ] **Step 1: 写入失败测试，覆盖折叠、展开和 Tab 保留**

```tsx
test("collapses result workspace without losing the selected result tab", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name: "图表" }));
  fireEvent.click(screen.getByLabelText("折叠结果工作区"));
  expect(screen.getByLabelText("展开结果工作区")).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("展开结果工作区"));
  expect(screen.getByRole("tab", { name: "图表" })).toHaveAttribute("aria-selected", "true");
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pnpm test --run tests/conversation.test.tsx`

Expected: FAIL，缺少折叠和展开控件。

- [ ] **Step 3: 保持 ResultPanel 挂载并实现折叠轨道**

```tsx
const collapseResult = () => {
  setPreCollapseRatio(splitRatio);
  setResultCollapsed(true);
};
const expandResult = () => {
  setResultCollapsed(false);
  setSplitRatio(preCollapseRatio);
};
```

将 `<section className="result-pane">` 始终渲染。展开网格列为 `250px minmax(0, var(--conversation-width)) 8px minmax(0, 1fr)`，并把 `conversation-pane`、divider、`result-pane` 分别置于第 2、3、4 列；折叠网格列切换为 `250px minmax(0, 1fr) 44px`，把 `result-pane` 移至第 3 列。折叠时添加 `.result-workspace-collapsed`，隐藏其 header 与 panel 的可视内容但不条件渲染删除；在轨道内渲染展开 button。展开状态将折叠 button 放在 divider 顶部。结果 Tab 点击继续调用 `setActiveTab`，不触发 `load`、`loadConversation` 或任何 API 请求。

- [ ] **Step 4: 写入折叠布局样式**

```css
.conversation-workspace.result-workspace-collapsed { grid-template-columns: 250px minmax(0, 1fr) 44px; }
.result-workspace-collapsed .result-pane { grid-column: 3; }
.result-workspace-collapsed .result-header,
.result-workspace-collapsed .result-panel { visibility: hidden; pointer-events: none; }
.result-expand-rail { position: sticky; top: 10px; display: grid; place-items: center; }
```

折叠时 Conversation 网格列占用剩余宽度，Result 轨道保留可点击展开按钮；不使用 `display: none` 隐藏整个 ResultPanel。

- [ ] **Step 5: 运行测试并确认通过**

Run: `pnpm test --run tests/conversation.test.tsx`

Expected: PASS，折叠/展开保持图表 Tab，且已有结果组件仍在 DOM 中。

### Task 4: 移动端切换和内容自适应

**Files:**
- Modify: `apps/web/src/App.tsx:220-245`
- Modify: `apps/web/src/styles.css:120-160`
- Test: `apps/web/tests/conversation.test.tsx`

**Interfaces:**
- Produces: `mobileWorkspaceView: "conversation" | "result"` 与 `aria-label="移动端工作区视图"`。
- Consumes: 现有 `ResultPanel`、`.table-wrapper`、`.code-scroll` 与 SVG 图表 CSS。

- [ ] **Step 1: 写入失败测试，覆盖移动端视图切换但不卸载结果 Tab**

```tsx
test("switches mobile workspace views without resetting the active result tab", async () => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 640 });
  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name: "图表" }));
  fireEvent.click(screen.getByRole("button", { name: "结果视图" }));
  expect(screen.getByRole("tab", { name: "图表" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("button", { name: "对话视图" })).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pnpm test --run tests/conversation.test.tsx`

Expected: FAIL，缺少移动端视图按钮。

- [ ] **Step 3: 实现移动端布局控制**

在 topbar 下方渲染仅移动端显示的分段按钮。`mobileWorkspaceView` 只设置 `.mobile-show-conversation` 或 `.mobile-show-result` 类；两个面板继续渲染。`resize` 事件跨越 720px 时重算是否显示控制按钮，但不覆盖桌面 `splitRatio` 与折叠状态。

- [ ] **Step 4: 追加移动端与内容容器样式**

```css
@media (max-width: 720px) {
  .workspace { grid-template-columns: minmax(0, 1fr); }
  .workspace-divider, .history-pane { display: none; }
  .mobile-workspace-toggle { display: flex; }
  .mobile-show-conversation .result-pane,
  .mobile-show-result .conversation-pane { display: none; }
}
```

保留 `.table-wrapper { overflow: auto; }`、`.code-scroll { overflow: auto; }` 与 `.chart-card svg { width: 100%; height: auto; }`；报告使用现有 `max-width` 居中规则。

- [ ] **Step 5: 运行移动端测试并确认通过**

Run: `pnpm test --run tests/conversation.test.tsx`

Expected: PASS，切换视图后图表 Tab 仍为选中状态，ResultPanel 没有被卸载。

### Task 5: 端到端交互验证与构建

**Files:**
- Modify: `apps/web/tests/conversation.test.tsx`
- Verify: `apps/web/src/App.tsx`, `apps/web/src/styles.css`

**Interfaces:**
- Consumes: Tasks 1-4 的布局状态、控件和样式。
- Produces: 可复现的测试输出与浏览器验收记录。

- [ ] **Step 1: 运行完整前端测试套件**

Run: `pnpm test --run`

Expected: 全部 Vitest 用例通过，包括既有模型切换、历史会话和新增工作区交互。

- [ ] **Step 2: 运行生产构建**

Run: `pnpm build`

Expected: `tsc -b && vite build` 退出码为 0。

- [ ] **Step 3: 运行浏览器手工验收**

在 `http://127.0.0.1:5187/` 验证：拖拽实时更新；两端最小宽度；双击 50 / 50；折叠/展开保持图表 Tab；刷新恢复布局；移动端切换；图表随 Result 宽度变化；表格横向滚动；Notebook 横向滚动正常。

- [ ] **Step 4: 检查本次路径的空白与格式问题**

Run: `git diff --check -- apps/web/src/App.tsx apps/web/src/styles.css apps/web/tests/conversation.test.tsx`

Expected: 无空白错误。不要提交，因为工作树含用户已有未提交改动。
