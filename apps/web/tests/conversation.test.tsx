import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../src/App";
import "../src/styles.css";

afterEach(cleanup);
afterEach(() => vi.unstubAllGlobals());
afterEach(() => localStorage.clear());

const conversation = {
  id: "conversation-1", title: "经营趋势", selected_provider: "simulated", selected_model: "analysis-sim", file_ids: [], status: "active",
  messages: [{ id: "m1", role: "user", content: "分析营业收入趋势", status: "completed", artifact_ids: [], created_at: "2026-09-01" }],
  analysis_state: {}, artifacts: [], source_name: "未绑定文件", intake: { kind: "spreadsheet" }, charts: [], reports: [],
};

function json(body: unknown) { return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }); }

test("keeps messages visible while switching models and sends a follow-up", async () => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/datasets") return Promise.resolve(json([]));
    if (path === "/api/conversations") return Promise.resolve(json([conversation]));
    if (path === "/api/providers") return Promise.resolve(json([{ id: "simulated", display_name: "本地模拟", models: [{ id: "analysis-sim", display_name: "本地模拟分析" }] }, { id: "openai", display_name: "OpenAI", models: [{ id: "gpt-5.6-terra", display_name: "GPT-5.6 Terra" }] }]));
    if (path === "/api/settings/providers") return Promise.resolve(json({}));
    if (path === "/api/conversations/conversation-1") return Promise.resolve(json(conversation));
    if (path === "/api/models?provider=openai") return Promise.resolve(json([{ id: "gpt-5.6-terra", display_name: "GPT-5.6 Terra" }]));
    if (path === "/api/conversations/conversation-1/model" && init?.method === "PUT") return Promise.resolve(json({ ...conversation, selected_provider: "openai", selected_model: "gpt-5.6-terra" }));
    if (path === "/api/conversations/conversation-1/messages" && init?.method === "POST") return Promise.resolve(json({ id: "m2", role: "assistant", content: "已完成", status: "completed" }));
    return Promise.resolve(json({}));
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);
  expect(await screen.findByText("分析营业收入趋势")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("模型 Provider"), { target: { value: "openai" } });
  await waitFor(() => expect(screen.getByLabelText("模型")).toHaveValue("gpt-5.6-terra"));
  expect(screen.getByText("分析营业收入趋势")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("继续分析"), { target: { value: "那 2025 年呢？" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/conversations/conversation-1/messages", expect.objectContaining({ method: "POST" })));
});

test("asks for confirmation before clearing conversation history", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/datasets" || path === "/api/conversations") return Promise.resolve(json([]));
    if (path === "/api/providers") return Promise.resolve(json([]));
    if (path === "/api/settings/providers") return Promise.resolve(json({}));
    return Promise.resolve(json({}));
  }));
  vi.stubGlobal("confirm", vi.fn(() => false));

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "清空全部历史" }));

  expect(window.confirm).toHaveBeenCalled();
});

test("regenerates an assistant message without deleting conversation history", async () => {
  const withAssistant = { ...conversation, messages: [...conversation.messages, { id: "m2", role: "assistant" as const, content: "营业收入上升", status: "completed", artifact_ids: [], created_at: "2026-09-01" }] };
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/datasets") return Promise.resolve(json([]));
    if (path === "/api/conversations") return Promise.resolve(json([withAssistant]));
    if (path === "/api/providers") return Promise.resolve(json([{ id: "simulated", display_name: "本地模拟", models: [{ id: "analysis-sim", display_name: "本地模拟分析" }] }]));
    if (path === "/api/conversations/conversation-1") return Promise.resolve(json(withAssistant));
    if (path === "/api/messages/m2/regenerate") return Promise.resolve(json({ id: "m3", role: "assistant", content: "重新生成", status: "completed" }));
    return Promise.resolve(json({}));
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "重新生成" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/messages/m2/regenerate", expect.objectContaining({ method: "POST" })));
  expect(screen.getByText("分析营业收入趋势")).toBeInTheDocument();
});

test("shows only masked provider configuration in settings", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/datasets" || path === "/api/conversations") return Promise.resolve(json([]));
    if (path === "/api/providers") return Promise.resolve(json([{ id: "openai", display_name: "OpenAI", models: [{ id: "gpt-5.6-terra", display_name: "GPT-5.6 Terra" }] }]));
    if (path === "/api/settings/providers") return Promise.resolve(json({ openai: { configured: true, api_key_masked: "sk-a…1234", base_url: "https://api.openai.com/v1", model: "gpt-5.6-terra" } }));
    return Promise.resolve(json({}));
  }));

  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "设置" }));

  expect(await screen.findByText("已配置：sk-a…1234")).toBeInTheDocument();
  expect(screen.queryByText("secret-value")).not.toBeInTheDocument();
});

test("saves a curated model selection to the persistent local provider store", async () => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/datasets" || path === "/api/conversations") return Promise.resolve(json([]));
    if (path === "/api/providers") return Promise.resolve(json([{ id: "openai", display_name: "OpenAI", models: [{ id: "gpt-5.6-terra", display_name: "GPT-5.6 Terra" }, { id: "gpt-5.6-luna", display_name: "GPT-5.6 Luna" }] }, { id: "deepseek", display_name: "DeepSeek", models: [{ id: "deepseek-v4-flash", display_name: "deepseek-v4-flash" }] }]));
    if (path === "/api/settings/providers") return Promise.resolve(json({ openai: { configured: false, api_key_masked: "", base_url: "https://api.openai.com/v1", model: "gpt-5.6-terra" } }));
    if (path === "/api/settings/providers/openai" && init?.method === "PUT") return Promise.resolve(json({ configured: true, api_key_masked: "sk-a…1234", base_url: "https://api.openai.com/v1", model: "gpt-5.6-luna" }));
    return Promise.resolve(json({}));
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "设置" }));
  await screen.findByRole("heading", { name: "模型设置" });
  expect(screen.getByText("Key 仅保存到本机 providers.env，保存后不会回显。")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("默认模型"), { target: { value: "gpt-5.6-luna" } });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));

  await waitFor(() => expect(fetchMock.mock.calls.filter(([path]) => path === "/api/providers")).toHaveLength(2));
});

test("restores the saved result tab and split ratio", async () => {
  localStorage.setItem("analysis-studio-conversation-split-ratio", "0.68");
  localStorage.setItem("analysis-studio-active-result-tab", "图表");
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/datasets" || path === "/api/conversations") return Promise.resolve(json([]));
    if (path === "/api/providers") return Promise.resolve(json([]));
    if (path === "/api/settings/providers") return Promise.resolve(json({}));
    return Promise.resolve(json({}));
  }));

  render(<App />);

  expect(await screen.findByRole("tab", { name: "图表" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByTestId("conversation-result-split")).toHaveAttribute("data-split-ratio", "0.68");
});

test("falls back to the default split ratio when its saved value is invalid", async () => {
  localStorage.setItem("analysis-studio-conversation-split-ratio", "not-a-number");
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/datasets" || path === "/api/conversations") return Promise.resolve(json([]));
    if (path === "/api/providers") return Promise.resolve(json([]));
    if (path === "/api/settings/providers") return Promise.resolve(json({}));
    return Promise.resolve(json({}));
  }));

  render(<App />);

  expect(await screen.findByTestId("conversation-result-split")).toHaveAttribute("data-split-ratio", "0.5");
});

test("constrains a dragged conversation split to the minimum result width", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/datasets" || path === "/api/conversations") return Promise.resolve(json([]));
    if (path === "/api/providers") return Promise.resolve(json([]));
    if (path === "/api/settings/providers") return Promise.resolve(json({}));
    return Promise.resolve(json({}));
  }));
  render(<App />);
  const workspace = await screen.findByTestId("conversation-result-split");
  vi.spyOn(workspace, "getBoundingClientRect").mockReturnValue({ width: 1200 } as DOMRect);
  const divider = screen.getByLabelText("调整对话与结果宽度");

  fireEvent(divider, new MouseEvent("pointerdown", { bubbles: true, clientX: 600 }));
  fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 99999 }));
  fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 99999 }));

  await waitFor(() => expect(Number(workspace.dataset.splitRatio)).toBeCloseTo(1 - 460 / 942, 3));
});

test("resets the conversation split ratio on divider double click", async () => {
  localStorage.setItem("analysis-studio-conversation-split-ratio", "0.68");
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/datasets" || path === "/api/conversations") return Promise.resolve(json([]));
    if (path === "/api/providers") return Promise.resolve(json([]));
    if (path === "/api/settings/providers") return Promise.resolve(json({}));
    return Promise.resolve(json({}));
  }));
  render(<App />);
  const workspace = await screen.findByTestId("conversation-result-split");

  fireEvent.doubleClick(screen.getByLabelText("调整对话与结果宽度"));

  await waitFor(() => expect(workspace).toHaveAttribute("data-split-ratio", "0.5"));
});

test("keeps the result panel and selected tab while the workspace is collapsed", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/datasets" || path === "/api/conversations") return Promise.resolve(json([]));
    if (path === "/api/providers") return Promise.resolve(json([]));
    if (path === "/api/settings/providers") return Promise.resolve(json({}));
    return Promise.resolve(json({}));
  }));
  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name: "图表" }));
  const resultPanel = document.querySelector(".result-panel");

  fireEvent.click(screen.getByLabelText("折叠结果工作区"));

  expect(screen.getByLabelText("展开结果工作区")).toBeInTheDocument();
  expect(resultPanel).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("展开结果工作区"));
  expect(screen.getByRole("tab", { name: "图表" })).toHaveAttribute("aria-selected", "true");
});

test("restores a collapsed result workspace from local storage", async () => {
  localStorage.setItem("analysis-studio-result-collapsed", "true");
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/datasets" || path === "/api/conversations") return Promise.resolve(json([]));
    if (path === "/api/providers") return Promise.resolve(json([]));
    if (path === "/api/settings/providers") return Promise.resolve(json({}));
    return Promise.resolve(json({}));
  }));

  render(<App />);

  expect(await screen.findByLabelText("展开结果工作区")).toBeInTheDocument();
});

test("switches mobile workspace views without resetting the selected result tab", async () => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 640 });
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/datasets" || path === "/api/conversations") return Promise.resolve(json([]));
    if (path === "/api/providers") return Promise.resolve(json([]));
    if (path === "/api/settings/providers") return Promise.resolve(json({}));
    return Promise.resolve(json({}));
  }));
  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name: "图表" }));

  fireEvent.click(screen.getByRole("button", { name: "结果视图" }));

  expect(screen.getByLabelText("移动端工作区视图")).toBeInTheDocument();
  expect(screen.getByTestId("conversation-result-split")).toHaveClass("mobile-show-result");
  expect(screen.getByRole("tab", { name: "图表" })).toHaveAttribute("aria-selected", "true");
});
