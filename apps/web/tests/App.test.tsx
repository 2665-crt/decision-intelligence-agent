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
    business_risks: [{ title: "south 持续营收下降", object: "south", level: "high", evidence: ["累计下降 52.3%。"], mitigation: "核对客户和销量。" }],
    suggestions: [{ name: "优先处理 south", expected_benefit: "定位下降来源", cost: "中", potential_harm: "低", next_step: "核对数据" }],
    data_quality: { summary: "36 行、3 列；缺失 0 个单元格。", limitations: [] }, charts: [], reports: [], limitations: [],
  } as never} />);

  expect(screen.getByRole("heading", { name: "核心结论" })).toBeInTheDocument();
  expect(screen.getByText("south 是当前风险最高的对象", { exact: false })).toBeInTheDocument();
  expect(screen.getByText("数据质量与分析限制").closest("details")).not.toHaveAttribute("open");
  expect(screen.queryByText("低损害方案")).not.toBeInTheDocument();
});

test("keeps task tabs readable, scrollable and switchable", () => {
  const selectSession = vi.fn();
  render(<TaskTabs activeId="risk-session" onClose={vi.fn()} onNew={vi.fn()} onSelect={selectSession} sessions={[
    { id: "risk-session", title: "地区营收风险", objective: "检测不同地区营收异常风险，并分析月度趋势和未来风险" },
    { id: "forecast-session", title: "月度营收预测", objective: "分析2025年月度营收趋势并预测未来三个月" },
  ]} />);

  const activeTab = screen.getByRole("tab", { name: "地区营收风险：检测不同地区营收异常风险，并分析月度趋势和未来风险" });
  expect(activeTab).toHaveAttribute("title", "检测不同地区营收异常风险，并分析月度趋势和未来风险");
  expect(activeTab).toHaveClass("active");
  const tabList = screen.getByRole("tablist", { name: "已打开的分析任务" });
  fireEvent.wheel(tabList, { deltaY: 120 });
  expect(tabList.scrollLeft).toBe(120);
  fireEvent.click(screen.getByRole("button", { name: "全部任务" }));
  fireEvent.click(screen.getByRole("button", { name: "月度营收预测" }));
  expect(selectSession).toHaveBeenCalledWith("forecast-session");
  expect(getComputedStyle(activeTab).minWidth).toBe("120px");
  expect(getComputedStyle(activeTab).maxWidth).toBe("220px");
  expect(getComputedStyle(activeTab.querySelector(".tab-title")!).textOverflow).toBe("ellipsis");
});
