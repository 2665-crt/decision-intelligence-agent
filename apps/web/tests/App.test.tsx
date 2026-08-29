import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { App } from "../src/App";

test("requires a file and goal before creating an analysis job", () => {
  render(<App />);

  expect(screen.getByRole("button", { name: "创建分析任务" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("分析目标"), { target: { value: "分析营收趋势" } });
  expect(screen.getByRole("button", { name: "创建分析任务" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("上传数据或文档"), { target: { files: [new File(["a"], "sample.xlsx")] } });
  expect(screen.getByRole("button", { name: "创建分析任务" })).toBeEnabled();
});
