import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { App } from "../src/App";

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
