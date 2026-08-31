import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App, ResultPanel, TaskTabs } from "../src/App";
import "../src/styles.css";

afterEach(cleanup);

test("requires a dataset and goal before creating an analysis session", () => {
  render(<App />);

  fireEvent.click(screen.getAllByRole("button", { name: "新建分析" })[0]);
  expect(screen.getByRole("button", { name: "创建任务" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("分析需求"), { target: { value: "分析营收趋势" } });
  expect(screen.getByRole("button", { name: "创建任务" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("上传数据集"), { target: { files: [new File(["a"], "sample.xlsx")] } });
  expect(screen.getByRole("button", { name: "创建任务" })).toBeEnabled();
});

test("accepts TSV and JSON datasets in the upload control", () => {
  render(<App />);

  fireEvent.click(screen.getAllByRole("button", { name: "新建分析" })[0]);

  expect(screen.getByLabelText("上传数据集")).toHaveAttribute("accept", ".xlsx,.xls,.csv,.tsv,.json,.docx");
});

test("renders a fixed workspace with session history and modular result tabs", () => {
  render(<App />);

  expect(screen.getAllByRole("button", { name: "新建分析" }).length).toBeGreaterThan(0);
  expect(screen.getAllByRole("searchbox", { name: "搜索历史分析" }).length).toBeGreaterThan(0);
  expect(screen.getByRole("tab", { name: "结果" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "图表" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Notebook" })).toBeInTheDocument();
  expect(screen.getByText("选择或新建一个分析任务")).toBeInTheDocument();
});

test("prioritizes a direct answer and keeps data quality collapsed", () => {
  render(<ResultPanel tab="结果" session={{
    id: "risk-session", dataset_id: "dataset", source_name: "regional.xlsx", objective: "检测地区营收异常风险", title: "地区营收风险", status: "succeeded",
    intake: { kind: "spreadsheet", rows: 36, columns: ["month", "region", "revenue"] }, messages: [],
    core_conclusion: "south 是当前风险最高的对象：2025-01 至 2025-12 从 155 下降至 74，累计下降 52.3%。",
    key_metrics: [{ label: "最高风险对象", value: "south", detail: "累计下降 52.3%" }],
    sections: [{ title: "风险评估", items: [{ text: "south 风险 high。" }] }],
    business_risks: [{ title: "south 持续营收下降", object: "south", level: "high", evidence: ["累计下降 52.3%。"], reason: "收入指标连续下降，当前数据不能归因于单一业务因素。", mitigation: "核对客户和销量。" }],
    suggestions: [{ name: "优先处理 south", expected_benefit: "定位下降来源", cost: "中", potential_harm: "低", next_step: "核对数据" }],
    data_quality: { summary: "36 行、3 列；缺失 0 个单元格。", limitations: [] }, charts: [], reports: [], limitations: [],
  } as never} />);

  expect(screen.getByRole("heading", { name: "核心结论" })).toBeInTheDocument();
  expect(screen.getByText("south 是当前风险最高的对象", { exact: false })).toBeInTheDocument();
  expect(screen.getByText("风险原因：收入指标连续下降，当前数据不能归因于单一业务因素。")).toBeInTheDocument();
  expect(screen.getByText("数据质量与分析限制").closest("details")).not.toHaveAttribute("open");
  expect(screen.queryByText("低损害方案")).not.toBeInTheDocument();
});

test("renders only verified generic findings and their evidence before legacy modules", () => {
  render(<ResultPanel tab="结果" session={{
    id: "product-session", dataset_id: "dataset", source_name: "orders.csv", objective: "哪个产品销售额最高？", title: "产品销售排名", status: "succeeded",
    intake: { kind: "spreadsheet", rows: 3, columns: ["product_name", "sales_amount"] }, messages: [],
    answer: "产品 A 的销售额最高，为 120。", validation_status: "SUCCESS",
    core_conclusion: "旧的固定结论不应显示。",
    findings: [{ kind: "ranking", conclusion: "产品 A 的销售额最高，为 120。", confidence: 0.95, evidence: {
      source: { file_hash: "abc", table: "订单" }, fields: ["product_name", "sales_amount"], filters: [], grouping: ["product_name"], calculation: "groupby(product_name).sum(sales_amount)", output_value: { product_name: "产品 A", sales_amount: 120 }, confidence: 0.95,
    } }],
    charts: [], reports: [], limitations: [],
  } as never} />);

  expect(screen.getByRole("heading", { name: "直接回答" })).toBeInTheDocument();
  expect(screen.getByText("产品 A 的销售额最高，为 120。", { selector: ".core-conclusion" })).toBeInTheDocument();
  expect(screen.getByText("结果状态：SUCCESS")).toBeInTheDocument();
  expect(screen.getByText("字段：product_name、sales_amount")).toBeInTheDocument();
  expect(screen.getByText("计算：groupby(product_name).sum(sales_amount)")).toBeInTheDocument();
  expect(screen.queryByText("旧的固定结论不应显示。")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "业务风险" })).not.toBeInTheDocument();
});

test("shows insufficient data reason without empty analytics modules", () => {
  render(<ResultPanel tab="结果" session={{
    id: "missing-session", dataset_id: "dataset", source_name: "inventory.csv", objective: "预测未来库存", title: "库存预测", status: "succeeded",
    intake: { kind: "spreadsheet", rows: 3, columns: ["sku", "stock"] }, messages: [],
    answer: "无法完成此问题：缺少可用时间字段，不能预测。", validation_status: "INSUFFICIENT_DATA", findings: [], evidence: [], limitations: ["缺少可用时间字段，不能预测。"], charts: [], reports: [],
  } as never} />);

  expect(screen.getByRole("heading", { name: "数据不足" })).toBeInTheDocument();
  expect(screen.getByText("缺少可用时间字段，不能预测。")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "关键数据" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "业务风险" })).not.toBeInTheDocument();
});

test("renders every available verified evidence field", () => {
  render(<ResultPanel tab="结果" session={{
    id: "evidence-session", dataset_id: "dataset", source_name: "fallback.csv", objective: "找出最大值", title: "最大值", status: "succeeded",
    intake: { kind: "spreadsheet" }, messages: [], answer: "已找到最大值。", validation_status: "SUCCESS", limitations: [],
    findings: [{ kind: "ranking", conclusion: "产品 A 为最大值。", evidence: {
      source: { source_name: "orders.csv", sheet: "销售明细" }, fields: ["产品", "金额"], filters: ["状态 = 已支付"], calculation: "max(金额)", output_value: 120, confidence: 0.91,
    } }], charts: [], reports: [],
  } as never} />);

  expect(screen.getByText("来源：orders.csv · 工作表：销售明细")).toBeInTheDocument();
  expect(screen.getByText("字段：产品、金额")).toBeInTheDocument();
  expect(screen.getByText("筛选：状态 = 已支付")).toBeInTheDocument();
  expect(screen.getByText("计算：max(金额)")).toBeInTheDocument();
  expect(screen.getByText("输出值：120")).toBeInTheDocument();
  expect(screen.getByText("置信度：0.91")).toBeInTheDocument();
});

test("omits unavailable optional evidence fields without rendering undefined", () => {
  render(<ResultPanel tab="结果" session={{
    id: "sparse-evidence-session", dataset_id: "dataset", source_name: "inventory.csv", objective: "找出最大库存", title: "库存最大值", status: "succeeded",
    intake: { kind: "spreadsheet" }, messages: [], answer: "SKU-1 库存最高。", validation_status: "SUCCESS", limitations: [],
    findings: [{ kind: "ranking", conclusion: "SKU-1 库存最高。", evidence: {
      source: { table: "库存" }, fields: ["sku", "stock"], calculation: "max(stock)",
    } }], charts: [], reports: [],
  } as never} />);

  expect(screen.getByText("来源：inventory.csv · 工作表：库存")).toBeInTheDocument();
  expect(screen.getByText("字段：sku、stock")).toBeInTheDocument();
  expect(screen.getByText("计算：max(stock)")).toBeInTheDocument();
  expect(screen.queryByText(/^筛选：/)).not.toBeInTheDocument();
  expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
});

test("omits the business risk heading when the analysis has no business risks", () => {
  render(<ResultPanel tab="结果" session={{
    id: "trend-session", dataset_id: "dataset", source_name: "financial.xlsx", objective: "分析财务趋势", title: "财务趋势", status: "succeeded",
    intake: { kind: "spreadsheet", rows: 4, columns: ["期间", "营业收入"] }, messages: [],
    core_conclusion: "营业收入保持上升。", key_metrics: [], sections: [], business_risks: [], suggestions: [],
    data_quality: { summary: "4 行、2 列；缺失 0 个单元格。", limitations: [] }, charts: [], reports: [], limitations: [],
  } as never} />);

  expect(screen.queryByRole("heading", { name: "业务风险" })).not.toBeInTheDocument();
});

test("keeps task tabs readable, scrollable and switchable", () => {
  const selectSession = vi.fn();
  render(<TaskTabs activeId="risk-session" onClose={vi.fn()} onNew={vi.fn()} onSelect={selectSession} sessions={[
    { id: "risk-session", title: "地区营收风险", objective: "检测不同地区营收异常风险，并分析月度趋势和未来风险" },
    { id: "forecast-session", title: "月度营收预测", objective: "分析2025年月度营收趋势并预测未来三个月" },
  ]} />);

  const activeTab = screen.getByRole("tab", { name: "地区营收风险：检测不同地区营收异常风险，并分析月度趋势和未来风险" });
  expect(activeTab).toHaveAttribute("title", "检测不同地区营收异常风险，并分析月度趋势和未来风险");
  expect(activeTab).toHaveAttribute("aria-current", "page");
  expect(screen.getAllByText(/等待分析/)).toHaveLength(2);
  expect(activeTab.closest(".task-tab")).toHaveClass("active");
  const tabList = screen.getByRole("tablist", { name: "已打开的分析任务" });
  fireEvent.wheel(tabList, { deltaY: 120 });
  expect(tabList.scrollLeft).toBe(120);
  fireEvent.click(screen.getByRole("button", { name: "全部任务" }));
  fireEvent.click(screen.getByRole("button", { name: "月度营收预测" }));
  expect(selectSession).toHaveBeenCalledWith("forecast-session");
  expect(getComputedStyle(activeTab.closest(".task-tab")!).minWidth).toBe("120px");
  expect(getComputedStyle(activeTab.closest(".task-tab")!).maxWidth).toBe("220px");
  expect(getComputedStyle(activeTab.querySelector(".tab-title")!).textOverflow).toBe("ellipsis");
});

test("closes a task tab without selecting it", () => {
  const onClose = vi.fn();
  const onSelect = vi.fn();
  render(<TaskTabs activeId="session-1" onClose={onClose} onNew={vi.fn()} onSelect={onSelect} sessions={[
    { id: "session-1", title: "长标题任务", objective: "一个完整的长问题" },
  ]} />);

  fireEvent.click(screen.getByRole("button", { name: "关闭 长标题任务" }));
  expect(onClose).toHaveBeenCalledWith("session-1");
  expect(onSelect).not.toHaveBeenCalled();
});
