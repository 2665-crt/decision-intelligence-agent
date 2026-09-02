import { FormEvent, PointerEvent, UIEvent, useEffect, useMemo, useRef, useState } from "react";

type Intake = { kind: string; rows?: number; columns?: string[]; missing_cells?: number; paragraph_count?: number };
type Report = { format: string; download_url: string };
type Risk = { title: string; object?: string; level: string; evidence: string[]; reason?: string; mitigation: string };
type Option = { name: string; expected_benefit: string; cost: string; potential_harm: string; next_step: string };
type KeyMetric = { label: string; value: string; detail?: string };
type AnalysisSection = { title: string; items: { text: string }[] };
type DataQuality = { summary: string; limitations: string[] };
type Dataset = { id: string; source_name: string; intake: Intake };
type Message = { role: "user" | "assistant"; content: string; created_at: string };
type FindingEvidence = { source?: { source_name?: string; file_name?: string; table?: string; sheet?: string }; fields?: string[]; filters?: string[]; grouping?: string[]; calculation?: string; output_value?: unknown; confidence?: number; formula?: string; row_indices?: Array<string | number> };
type Finding = { kind: string; conclusion: string; confidence?: number; evidence?: FindingEvidence };
type ChartPoint = { x: string; y: number };
type ChartSpec = { id: string; title: string; type: "line" | "bar" | "stacked-bar" | "donut" | "scatter" | "unavailable"; x_label: string; y_label: string; series: { name: string; points: ChartPoint[] }[]; markers?: { x: string; label: string; kind: string }[]; unavailable_reason?: string | null };
type Session = {
  id: string; dataset_id: string; source_name: string; objective: string; title: string; status: string; intake: Intake; messages: Message[];
  analysis?: { kind: string; numeric_summary?: Record<string, { count: number; missing: number; mean: number; min: number; max: number }> };
  core_conclusion?: string; key_metrics?: KeyMetric[]; sections?: AnalysisSection[]; business_risks?: Risk[]; data_quality?: DataQuality;
  suggestions?: Option[]; forecast?: { model?: string; is_recommended?: boolean; candidate_mae?: number; limitations: string[] } | null;
  charts?: { title: string; download_url: string }[]; chart_specs?: ChartSpec[]; reports?: Report[]; limitations?: string[]; notebook_cells?: { language: string; title: string; code: string }[];
  answer?: string; validation_status?: "SUCCESS" | "PARTIAL" | "INSUFFICIENT_DATA" | string; findings?: Finding[];
};
type SessionPage = { items: Session[]; next_offset: number; has_more: boolean };
type ResultTab = "结果" | "图表" | "数据" | "Notebook" | "报告" | "文件";
const resultTabs: ResultTab[] = ["结果", "图表", "数据", "Notebook", "报告", "文件"];
const PAGE_SIZE = 40;
const DEFAULT_SPLIT_RATIO = 0.5;
const HISTORY_WIDTH = 250;
const DIVIDER_WIDTH = 8;
const MIN_CONVERSATION_WIDTH = 380;
const MIN_RESULT_WIDTH = 460;
const SPLIT_RATIO_KEY = "analysis-studio-conversation-split-ratio";
const RESULT_TAB_KEY = "analysis-studio-active-result-tab";
const RESULT_COLLAPSED_KEY = "analysis-studio-result-collapsed";

function readStoredRatio() {
  const value = Number(localStorage.getItem(SPLIT_RATIO_KEY));
  return Number.isFinite(value) && value > 0 && value < 1 ? value : DEFAULT_SPLIT_RATIO;
}

function readStoredResultTab(): ResultTab {
  const value = localStorage.getItem(RESULT_TAB_KEY);
  return resultTabs.includes(value as ResultTab) ? value as ResultTab : "结果";
}

function clampSplitRatio(value: number, availableWidth: number) {
  if (availableWidth < MIN_CONVERSATION_WIDTH + MIN_RESULT_WIDTH) return Math.min(Math.max(value, 0.42), 0.52);
  const min = MIN_CONVERSATION_WIDTH / availableWidth;
  const max = 1 - MIN_RESULT_WIDTH / availableWidth;
  return Math.min(Math.max(value, min), max);
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const data = isJson && text ? JSON.parse(text) as { detail?: string } : null;
  if (!response.ok) throw new Error(data?.detail ?? `服务请求失败（HTTP ${response.status}）`);
  if (!data) throw new Error("服务返回了无法解析的数据。");
  return data as T;
}

function LegacyApp() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [active, setActive] = useState<Session | null>(null);
  const [openIds, setOpenIds] = useState<string[]>(() => restoreOpenIds());
  const [activeTab, setActiveTab] = useState<ResultTab>("结果");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState({ nextOffset: 0, hasMore: false, loading: false });
  const [showCreate, setShowCreate] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [datasetId, setDatasetId] = useState("");
  const [objective, setObjective] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [fullscreen, setFullscreen] = useState(false);
  const [columns, setColumns] = useState(() => JSON.parse(localStorage.getItem("analysis-studio-columns") ?? "[250,1,1]") as [number, number, number]);
  const historyListRef = useRef<HTMLDivElement>(null);
  const historyScrollTopRef = useRef(0);
  const restoreAttemptedRef = useRef(false);
  const closeCreate = () => { setShowCreate(false); setFile(null); setDatasetId(""); setObjective(""); };

  const loadHistory = async (keyword: string, reset: boolean) => {
    if (!reset && (page.loading || !page.hasMore)) return;
    setPage((current) => ({ ...current, loading: true }));
    try {
      const offset = reset ? 0 : page.nextOffset;
      const next = await request<SessionPage>(`/api/sessions/page?offset=${offset}&limit=${PAGE_SIZE}&search=${encodeURIComponent(keyword)}`);
      setSessions((current) => reset ? next.items : [...current, ...next.items.filter((item) => !current.some((existing) => existing.id === item.id))]);
      setPage({ nextOffset: next.next_offset, hasMore: next.has_more, loading: false });
    } catch {
      if (reset) setSessions([]);
      setPage((current) => ({ ...current, loading: false }));
    }
  };

  useEffect(() => {
    void Promise.all([request<Dataset[]>("/api/datasets"), request<SessionPage>(`/api/sessions/page?offset=0&limit=${PAGE_SIZE}`)])
      .then(([nextDatasets, firstPage]) => { setDatasets(nextDatasets); setSessions(firstPage.items); setPage({ nextOffset: firstPage.next_offset, hasMore: firstPage.has_more, loading: false }); })
      .catch(() => setError("无法连接分析服务，请确认本机 API 已启动。"));
  }, []);
  useEffect(() => { localStorage.setItem("analysis-studio-columns", JSON.stringify(columns)); }, [columns]);
  useEffect(() => { localStorage.setItem("analysis-studio-open-ids", JSON.stringify(openIds)); }, [openIds]);
  useEffect(() => { void loadHistory(search, true); }, [search]);

  const openSessions = openIds.map((id) => sessions.find((session) => session.id === id)).filter((item): item is Session => Boolean(item));
  const applySession = (session: Session) => {
    setActive(session);
    localStorage.setItem("analysis-studio-active-id", session.id);
    setSessions((current) => [session, ...current.filter((item) => item.id !== session.id)]);
    setOpenIds((current) => current.includes(session.id) ? current : [...current, session.id]);
  };
  useEffect(() => {
    if (restoreAttemptedRef.current || sessions.length === 0) return;
    restoreAttemptedRef.current = true;
    const restoredId = localStorage.getItem("analysis-studio-active-id");
    if (!restoredId || !openIds.includes(restoredId) || !sessions.some((session) => session.id === restoredId)) return;
    void request<Session>(`/api/sessions/${restoredId}`).then(applySession).catch(() => {
      setOpenIds((current) => current.filter((id) => id !== restoredId));
      localStorage.removeItem("analysis-studio-active-id");
    });
  }, [sessions, openIds]);
  const selectSession = async (session: Session) => { try { applySession(await request<Session>(`/api/sessions/${session.id}`)); } catch (caught) { setError(caught instanceof Error ? caught.message : "无法读取分析任务"); } };
  const onHistoryScroll = (event: UIEvent<HTMLDivElement>) => {
    historyScrollTopRef.current = event.currentTarget.scrollTop;
    if (event.currentTarget.scrollTop + event.currentTarget.clientHeight >= event.currentTarget.scrollHeight - 80) void loadHistory(search, false);
  };

  const createSession = async (event: FormEvent) => {
    event.preventDefault(); if ((!file && !datasetId) || !objective.trim()) return;
    setBusy(true); setError("");
    try {
      let selectedDatasetId = datasetId;
      if (file) { const form = new FormData(); form.set("file", file); const dataset = await request<Dataset>("/api/datasets", { method: "POST", body: form }); selectedDatasetId = dataset.id; setDatasets((current) => [dataset, ...current]); }
      const session = await request<Session>("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dataset_id: selectedDatasetId, objective: objective.trim() }) });
      applySession(session); setShowCreate(false); setFile(null); setDatasetId(""); setObjective("");
      if (historyScrollTopRef.current < 24) historyListRef.current?.scrollTo({ top: 0 });
    } catch (caught) { setError(caught instanceof Error ? caught.message : "创建任务失败"); } finally { setBusy(false); }
  };
  const analyse = async () => { if (!active) return; applySession({ ...active, status: "analyzing" }); setBusy(true); setError(""); try { applySession(await request<Session>(`/api/sessions/${active.id}/analyze`, { method: "POST" })); } catch (caught) { setError(caught instanceof Error ? caught.message : "分析失败"); } finally { setBusy(false); } };
  const rename = async (session: Session) => { const title = window.prompt("分析任务名称", session.title)?.trim(); if (!title) return; try { applySession(await request<Session>(`/api/sessions/${session.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) })); } catch (caught) { setError(caught instanceof Error ? caught.message : "重命名失败"); } };
  const copy = async (session: Session) => { try { applySession(await request<Session>(`/api/sessions/${session.id}/copy`, { method: "POST" })); } catch (caught) { setError(caught instanceof Error ? caught.message : "复制失败"); } };
  const remove = async (session: Session) => { if (!window.confirm(`删除“${session.title}”及其分析结果？`)) return; try { await request<void>(`/api/sessions/${session.id}`, { method: "DELETE" }); setSessions((current) => current.filter((item) => item.id !== session.id)); setOpenIds((current) => current.filter((id) => id !== session.id)); if (active?.id === session.id) setActive(null); } catch (caught) { setError(caught instanceof Error ? caught.message : "删除失败"); } };
  const resize = (event: PointerEvent<HTMLDivElement>, edge: "left" | "right") => { const start = event.clientX; const starting = [...columns] as [number, number, number]; const onMove = (move: globalThis.PointerEvent) => { const delta = move.clientX - start; setColumns(edge === "left" ? [Math.max(180, starting[0] + delta), Math.max(.35, starting[1] - delta / 500), starting[2]] : [starting[0], Math.max(.35, starting[1] + delta / 500), Math.max(.35, starting[2] - delta / 500)]); }; const onUp = () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); }; window.addEventListener("pointermove", onMove); window.addEventListener("pointerup", onUp); };

  return <main className={`workspace ${fullscreen ? "result-fullscreen" : ""}`} style={{ gridTemplateColumns: `${columns[0]}px minmax(0, ${columns[1]}fr) minmax(0, ${columns[2]}fr)` }}>
    <header className="topbar"><div><span className="brand-mark">◌</span><strong>Analysis Workspace</strong><span className="project-name">通用数据分析 Agent</span></div><div><button className="ghost" onClick={() => setShowCreate(true)}>新建分析</button><span className="status-dot">本机已保存</span></div></header>
    <aside className="history-pane"><div className="history-header"><button className="new-session" onClick={() => setShowCreate(true)}>＋ 新建分析</button><label className="history-search"><span>⌕</span><input aria-label="搜索历史分析" type="search" placeholder="搜索历史分析" value={search} onChange={(event) => setSearch(event.target.value)} /></label><p className="pane-label">历史分析</p></div><section className="history-section"><div className="history-list" data-testid="history-list" ref={historyListRef} onScroll={onHistoryScroll}><div className="session-list">{sessions.length ? sessions.map((session) => <div className={`session-row ${active?.id === session.id ? "selected" : ""}`} key={session.id}><button className="session-open" title={session.objective} onClick={() => void selectSession(session)}><strong>{session.title}</strong><span>{session.source_name}</span><small><Status status={session.status} /></small></button><div className="session-actions"><button aria-label={`重命名 ${session.title}`} onClick={() => void rename(session)}>✎</button><button aria-label={`复制 ${session.title}`} onClick={() => void copy(session)}>⧉</button><button aria-label={`删除 ${session.title}`} onClick={() => void remove(session)}>×</button></div></div>) : <p className="empty-history">还没有分析任务</p>}{page.loading && <p className="history-state">正在加载…</p>}{!page.hasMore && sessions.length > 0 && <p className="history-state">已显示全部历史任务</p>}</div></div></section></aside>
    <div className="splitter left-splitter" onPointerDown={(event) => resize(event, "left")} />
    <section className="conversation-pane"><TaskTabs sessions={openSessions} recentSessions={sessions} activeId={active?.id ?? null} onSelect={(id) => { const session = sessions.find((item) => item.id === id); if (session) void selectSession(session); }} onClose={(id) => { setOpenIds((current) => current.filter((item) => item !== id)); if (active?.id === id) setActive(null); }} onNew={() => setShowCreate(true)} />{active ? <><div className="conversation-heading"><div><p className="pane-label">当前分析任务</p><h1>{active.title}</h1><p>{active.source_name} · <Status status={active.status} /></p></div><button className="ghost" onClick={() => void rename(active)}>重命名</button></div><div className="messages">{active.messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.created_at}-${index}`}><span>{message.role === "user" ? "你" : "Agent"}</span><p>{message.content}</p>{message.role === "assistant" && active.status === "succeeded" && <div className="message-links"><button onClick={() => setActiveTab("图表")}>查看图表</button><button onClick={() => setActiveTab("数据")}>查看数据</button><button onClick={() => setActiveTab("报告")}>查看报告</button></div>}</article>)}</div><div className="conversation-compose"><p>{active.status === "succeeded" ? "本次任务已完成。新需求请新建独立分析任务，避免结果混淆。" : "任务材料已就绪，可以开始独立分析。"}</p>{active.status === "ready" && <button onClick={() => void analyse()} disabled={busy}>{busy ? "正在分析…" : "开始分析"}</button>}</div></> : <EmptyWorkspace onCreate={() => setShowCreate(true)} />}</section>
    <div className="splitter right-splitter" onPointerDown={(event) => resize(event, "right")} />
    <section className="result-pane"><div className="result-header"><div role="tablist" aria-label="分析结果模块">{resultTabs.map((tab) => <button key={tab} role="tab" aria-selected={activeTab === tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>{tab}</button>)}</div><button className="icon-button" aria-label={fullscreen ? "退出全屏" : "全屏结果"} onClick={() => setFullscreen((value) => !value)}>{fullscreen ? "↙" : "⛶"}</button></div><div className="result-panel"><ResultPanel session={active} tab={activeTab} /></div></section>
    <footer className="workspace-footer">{active ? <>文件：{active.source_name}<span>Agent 状态：<Status status={active.status} /></span></> : "选择一个历史分析，或创建新的 Dataset → Session 任务。"}</footer>
    {showCreate && <CreateDialog datasets={datasets} file={file} datasetId={datasetId} objective={objective} busy={busy} onFile={setFile} onDataset={setDatasetId} onObjective={setObjective} onClose={closeCreate} onSubmit={createSession} />}{error && <p className="toast" role="alert">{error}<button onClick={() => setError("")}>×</button></p>}
  </main>;
}

type ConversationMessage = { id: string; role: "user" | "assistant" | "system"; content: string; provider?: string | null; model?: string | null; status: string; error_code?: string | null; artifact_ids: string[]; created_at: string };
type Conversation = Omit<Partial<Session>, "id" | "title" | "status" | "messages"> & { id: string; title: string; selected_provider: string; selected_model: string; file_ids: string[]; status: string; messages: ConversationMessage[]; analysis_state: Record<string, unknown>; artifacts: Array<{ id: string; kind: string; metadata: Record<string, unknown> }> };
type Provider = { id: string; display_name: string; models: Array<{ id: string; display_name: string }> };
type ProviderStatus = { configured: boolean; api_key_masked: string; base_url: string; model: string };

export function App() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<Conversation | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [draft, setDraft] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [datasetId, setDatasetId] = useState("");
  const [objective, setObjective] = useState("");
  const [activeTab, setActiveTab] = useState<ResultTab>(() => readStoredResultTab());
  const [splitRatio, setSplitRatio] = useState(() => readStoredRatio());
  const [resultCollapsed, setResultCollapsed] = useState(() => localStorage.getItem(RESULT_COLLAPSED_KEY) === "true");
  const [mobileWorkspaceView, setMobileWorkspaceView] = useState<"conversation" | "result">("conversation");
  const [isMobileLayout, setIsMobileLayout] = useState(() => window.innerWidth <= 720);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const workspaceRef = useRef<HTMLElement>(null);
  const resizeRef = useRef({ startX: 0, startRatio: DEFAULT_SPLIT_RATIO, nextRatio: DEFAULT_SPLIT_RATIO, frame: 0 as number | 0 });
  const preCollapseRatioRef = useRef(splitRatio);

  useEffect(() => { localStorage.setItem(SPLIT_RATIO_KEY, String(splitRatio)); }, [splitRatio]);
  useEffect(() => { localStorage.setItem(RESULT_TAB_KEY, activeTab); }, [activeTab]);
  useEffect(() => { localStorage.setItem(RESULT_COLLAPSED_KEY, String(resultCollapsed)); }, [resultCollapsed]);
  useEffect(() => {
    const updateMobileLayout = () => setIsMobileLayout(window.innerWidth <= 720);
    window.addEventListener("resize", updateMobileLayout);
    return () => window.removeEventListener("resize", updateMobileLayout);
  }, []);

  const setLiveRatio = (ratio: number) => {
    const node = workspaceRef.current;
    if (!node) return ratio;
    const availableWidth = Math.max(0, node.getBoundingClientRect().width - HISTORY_WIDTH - DIVIDER_WIDTH);
    const boundedRatio = availableWidth ? clampSplitRatio(ratio, availableWidth) : ratio;
    node.style.setProperty("--conversation-width", availableWidth ? `${Math.round(availableWidth * boundedRatio)}px` : "50%");
    node.dataset.splitRatio = String(boundedRatio);
    return boundedRatio;
  };

  useEffect(() => {
    const updateWidth = () => { setLiveRatio(splitRatio); };
    updateWidth();
    window.addEventListener("resize", updateWidth);
    return () => window.removeEventListener("resize", updateWidth);
  }, [splitRatio]);

  const startResize = (event: PointerEvent<HTMLButtonElement>) => {
    const node = workspaceRef.current;
    if (!node) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const availableWidth = Math.max(0, node.getBoundingClientRect().width - HISTORY_WIDTH - DIVIDER_WIDTH);
    const startRatio = availableWidth ? clampSplitRatio(splitRatio, availableWidth) : splitRatio;
    resizeRef.current = { startX: event.clientX, startRatio, nextRatio: startRatio, frame: 0 };
    const move = (moveEvent: globalThis.PointerEvent) => {
      if (!availableWidth) return;
      const nextRatio = clampSplitRatio(startRatio + (moveEvent.clientX - resizeRef.current.startX) / availableWidth, availableWidth);
      resizeRef.current.nextRatio = nextRatio;
      if (resizeRef.current.frame) cancelAnimationFrame(resizeRef.current.frame);
      resizeRef.current.frame = requestAnimationFrame(() => { setLiveRatio(nextRatio); });
    };
    const end = () => {
      if (resizeRef.current.frame) cancelAnimationFrame(resizeRef.current.frame);
      const nextRatio = setLiveRatio(resizeRef.current.nextRatio);
      setSplitRatio(nextRatio);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end, { once: true });
  };

  const resetResize = () => {
    setLiveRatio(DEFAULT_SPLIT_RATIO);
    setSplitRatio(DEFAULT_SPLIT_RATIO);
  };

  const collapseResult = () => {
    preCollapseRatioRef.current = splitRatio;
    setResultCollapsed(true);
  };

  const expandResult = () => {
    setResultCollapsed(false);
    setSplitRatio(preCollapseRatioRef.current);
  };

  const loadConversation = async (id: string) => {
    const detail = await request<Conversation>(`/api/conversations/${id}`);
    setActive(detail);
    setConversations((current) => [detail, ...current.filter((item) => item.id !== detail.id)]);
    localStorage.setItem("analysis-studio-active-conversation", id);
    return detail;
  };
  const load = async () => {
    try {
      const [nextDatasets, nextConversations, nextProviders] = await Promise.all([
        request<Dataset[]>("/api/datasets"), request<Conversation[]>("/api/conversations"), request<Provider[]>("/api/providers"),
      ]);
      setDatasets(nextDatasets); setConversations(nextConversations); setProviders(nextProviders);
      const stored = localStorage.getItem("analysis-studio-active-conversation");
      const candidate = nextConversations.find((item) => item.id === stored) ?? nextConversations[0];
      if (candidate) await loadConversation(candidate.id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "无法连接分析服务，请确认本机 API 已启动。"); }
  };
  useEffect(() => { void load(); }, []);

  const updateModel = async (provider: string, model: string) => {
    if (!active) return;
    try {
      setBusy(true);
      const updated = await request<Conversation>(`/api/conversations/${active.id}/model`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider, model }) });
      setActive(updated); setConversations((items) => [updated, ...items.filter((item) => item.id !== updated.id)]);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "切换模型失败"); } finally { setBusy(false); }
  };
  const changeProvider = async (provider: string) => {
    try {
      const models = await request<Array<{ id: string; display_name: string }>>(`/api/models?provider=${encodeURIComponent(provider)}`);
      if (models[0]) await updateModel(provider, models[0].id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "无法读取模型列表"); }
  };
  const send = async (event: FormEvent) => {
    event.preventDefault(); if (!active || !draft.trim()) return;
    const content = draft.trim(); setDraft(""); setBusy(true);
    try { await request(`/api/conversations/${active.id}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) }); await loadConversation(active.id); }
    catch (caught) { setDraft(content); setError(caught instanceof Error ? caught.message : "发送失败"); } finally { setBusy(false); }
  };
  const create = async (event: FormEvent) => {
    event.preventDefault(); if ((!file && !datasetId) || !objective.trim()) return;
    setBusy(true);
    try {
      let selected = datasetId;
      if (file) { const form = new FormData(); form.set("file", file); const dataset = await request<Dataset>("/api/datasets", { method: "POST", body: form }); selected = dataset.id; setDatasets((items) => [dataset, ...items]); }
      const conversation = await request<Conversation>("/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: objective.trim().slice(0, 20), file_ids: [selected] }) });
      setShowCreate(false); setFile(null); setDatasetId(""); setObjective(""); await loadConversation(conversation.id);
      setDraft("分析" + (conversation.title || "当前数据"));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "创建会话失败"); } finally { setBusy(false); }
  };
  const remove = async (conversation: Conversation) => {
    if (!window.confirm(`删除“${conversation.title}”及其会话专属工件？`)) return;
    try { await request<void>(`/api/conversations/${conversation.id}`, { method: "DELETE" }); setConversations((items) => items.filter((item) => item.id !== conversation.id)); if (active?.id === conversation.id) setActive(null); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "删除失败"); }
  };
  const clear = async () => {
    if (!window.confirm("确认清空全部历史？会删除会话、消息、分析状态和会话专属工件；数据集保留。")) return;
    try { await request<void>("/api/conversations?confirm=true", { method: "DELETE" }); setConversations([]); setActive(null); localStorage.removeItem("analysis-studio-active-conversation"); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "清空历史失败"); }
  };
  const regenerate = async (messageId: string) => {
    if (!active) return;
    try { setBusy(true); await request(`/api/messages/${messageId}/regenerate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: active.selected_provider, model: active.selected_model }) }); await loadConversation(active.id); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "重新生成失败"); } finally { setBusy(false); }
  };
  const currentProvider = providers.find((item) => item.id === active?.selected_provider);
  const resultSession = active ? { ...active, source_name: active.source_name ?? "当前会话文件", intake: active.intake ?? { kind: "spreadsheet" }, status: active.answer || active.validation_status ? "succeeded" : active.status } as Session : null;

  return <main ref={workspaceRef} className={`workspace conversation-workspace conversation-result-split mobile-show-${mobileWorkspaceView}${resultCollapsed ? " result-workspace-collapsed" : ""}`} data-testid="conversation-result-split" data-split-ratio={splitRatio} style={{ gridTemplateColumns: resultCollapsed ? "250px minmax(0, 1fr) 44px" : "250px minmax(0, var(--conversation-width, 1fr)) 8px minmax(0, 1fr)" }}>
    <header className="topbar"><div><span className="brand-mark">◌</span><strong>Analysis Workspace</strong><span className="project-name">多模型数据分析 Agent</span></div><div><button className="ghost" onClick={() => setShowSettings(true)}>设置</button><button className="ghost" onClick={() => setShowCreate(true)}>新建分析</button></div></header>
    {isMobileLayout && <div className="mobile-workspace-toggle" aria-label="移动端工作区视图" role="group"><button type="button" className={mobileWorkspaceView === "conversation" ? "active" : ""} aria-pressed={mobileWorkspaceView === "conversation"} onClick={() => setMobileWorkspaceView("conversation")}>对话视图</button><button type="button" className={mobileWorkspaceView === "result" ? "active" : ""} aria-pressed={mobileWorkspaceView === "result"} onClick={() => setMobileWorkspaceView("result")}>结果视图</button></div>}
    <aside className="history-pane"><div className="history-header"><button className="new-session" onClick={() => setShowCreate(true)}>＋ 新建分析</button><button className="history-clear" aria-label="清空全部历史" onClick={() => void clear()}>清空全部历史</button><label className="history-search"><span>⌕</span><input aria-label="搜索历史分析" type="search" placeholder="搜索历史分析" /></label><p className="pane-label">Conversation History</p></div><section className="history-section"><div className="history-list" data-testid="history-list"><div className="session-list">{conversations.length ? conversations.map((item) => <div className={`session-row ${active?.id === item.id ? "selected" : ""}`} key={item.id}><button className="session-open" onClick={() => void loadConversation(item.id)}><strong>{item.title}</strong><span>{item.selected_model}</span></button><div className="session-actions"><button aria-label={`删除 ${item.title}`} onClick={() => void remove(item)}>×</button></div></div>) : <p className="empty-history">还没有分析会话</p>}</div></div></section></aside>
    <section className="conversation-pane">{active ? <><div className="conversation-heading"><div><p className="pane-label">当前 Conversation</p><h1>{active.title}</h1><p>{active.file_ids.length ? `已绑定 ${active.file_ids.length} 个文件` : "尚未绑定文件"}</p></div><div className="model-selector"><label>Provider<select aria-label="模型 Provider" value={active.selected_provider} disabled={busy} onChange={(event) => void changeProvider(event.target.value)}>{providers.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label><label>模型<select aria-label="模型" value={active.selected_model} disabled={busy} onChange={(event) => void updateModel(active.selected_provider, event.target.value)}>{(currentProvider?.models ?? []).map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label></div></div><div className="messages">{active.messages.map((message) => <article className={`message ${message.role}`} key={message.id}><span>{message.role === "user" ? "你" : message.model ?? "Agent"}</span><p>{message.content}</p>{message.role === "assistant" && <button className="message-regenerate" disabled={busy} onClick={() => void regenerate(message.id)}>重新生成</button>}</article>)}</div><form className="conversation-compose" onSubmit={send}><textarea aria-label="继续分析" rows={2} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="继续追问、限定时间，或修改图表…" /><button disabled={busy || !draft.trim()}>{busy ? "正在处理…" : "发送"}</button></form></> : <EmptyWorkspace onCreate={() => setShowCreate(true)} />}</section>
    {!resultCollapsed && <button type="button" className="workspace-divider" aria-label="调整对话与结果宽度" onPointerDown={startResize} onDoubleClick={resetResize} />}
    <section className="result-pane">{resultCollapsed && <button type="button" className="result-expand-rail" aria-label="展开结果工作区" onClick={expandResult}>‹</button>}<div className="result-header"><button type="button" className="result-collapse" aria-label="折叠结果工作区" onClick={collapseResult}>›</button><div role="tablist" aria-label="分析结果模块">{resultTabs.map((tab) => <button key={tab} role="tab" aria-selected={activeTab === tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>{tab}</button>)}</div></div><div className="result-panel"><ResultPanel session={resultSession} tab={activeTab} /></div></section>
    <footer className="workspace-footer">{active ? `${active.selected_provider} / ${active.selected_model} · 会话与分析结果已本机持久化` : "新建 Conversation 后上传或绑定数据集。"}</footer>
    {showCreate && <ConversationCreateDialog datasets={datasets} file={file} datasetId={datasetId} objective={objective} busy={busy} onFile={setFile} onDataset={setDatasetId} onObjective={setObjective} onClose={() => { setShowCreate(false); setFile(null); setDatasetId(""); setObjective(""); }} onSubmit={create} />}
    {showSettings && <SettingsDialog providers={providers} onClose={() => setShowSettings(false)} onError={setError} onSaved={load} />}{error && <p className="toast" role="alert">{error}<button onClick={() => setError("")}>×</button></p>}
  </main>;
}

function ConversationCreateDialog({ datasets, file, datasetId, objective, busy, onFile, onDataset, onObjective, onClose, onSubmit }: { datasets: Dataset[]; file: File | null; datasetId: string; objective: string; busy: boolean; onFile: (file: File | null) => void; onDataset: (id: string) => void; onObjective: (objective: string) => void; onClose: () => void; onSubmit: (event: FormEvent) => void }) { return <div className="dialog-backdrop"><form className="create-dialog" onSubmit={onSubmit}><div><p className="pane-label">New Conversation</p><h2>新建分析</h2><p>上传新数据或复用已有数据集，然后在同一会话中持续追问。</p></div><label>上传数据集<input aria-label="上传数据集" type="file" accept=".xlsx,.xls,.csv,.tsv,.json,.docx" onChange={(event) => onFile(event.target.files?.[0] ?? null)} /></label>{file && <p className="selected-file">将创建数据集：{file.name}</p>}<label>或选择已有数据集<select aria-label="选择已有数据集" value={datasetId} disabled={Boolean(file)} onChange={(event) => onDataset(event.target.value)}><option value="">请选择</option>{datasets.map((item) => <option key={item.id} value={item.id}>{datasetLabel(item)}</option>)}</select></label><label>分析需求<textarea aria-label="分析需求" rows={4} value={objective} onChange={(event) => onObjective(event.target.value)} /></label><div className="dialog-actions"><button type="button" className="ghost" onClick={onClose}>取消</button><button type="submit" disabled={busy || (!file && !datasetId) || !objective.trim()}>创建任务</button></div></form></div>; }

function SettingsDialog({ providers, onClose, onError, onSaved }: { providers: Provider[]; onClose: () => void; onError: (value: string) => void; onSaved: () => Promise<void> }) {
  const [provider, setProvider] = useState("openai"); const [apiKey, setApiKey] = useState(""); const [baseUrl, setBaseUrl] = useState(""); const [model, setModel] = useState(""); const [statuses, setStatuses] = useState<Record<string, ProviderStatus>>({}); const [notice, setNotice] = useState("");
  const loadStatuses = async () => { try { const next = await request<Record<string, ProviderStatus>>("/api/settings/providers"); setStatuses(next); const selected = next[provider]; if (selected) { setBaseUrl(selected.base_url); setModel(selected.model); } } catch (caught) { onError(caught instanceof Error ? caught.message : "无法读取模型设置"); } };
  useEffect(() => { void loadStatuses(); }, []);
  const chooseProvider = (next: string) => { setProvider(next); setApiKey(""); setBaseUrl(statuses[next]?.base_url ?? ""); setModel(statuses[next]?.model ?? ""); setNotice(""); };
  const save = async (event: FormEvent) => { event.preventDefault(); try { const payload = { base_url: baseUrl, model, ...(apiKey ? { api_key: apiKey } : {}) }; await request(`/api/settings/providers/${provider}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); setApiKey(""); setNotice("设置已保存到本机 providers.env，Key 不会回显。"); await loadStatuses(); await onSaved(); } catch (caught) { onError(caught instanceof Error ? caught.message : "保存设置失败"); } };
  const testConnection = async () => { try { const result = await request<{ message: string }>("/api/providers/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider, model }) }); setNotice(result.message); } catch (caught) { setNotice(caught instanceof Error ? caught.message : "连接测试失败"); } };
  const selected = statuses[provider];
  const selectedProvider = providers.find((item) => item.id === provider);
  return <div className="dialog-backdrop"><form className="create-dialog" onSubmit={save}><div><p className="pane-label">Model / API</p><h2>模型设置</h2><p>Key 仅保存到本机 providers.env，保存后不会回显。</p></div><label>Provider<select value={provider} onChange={(event) => chooseProvider(event.target.value)}>{providers.filter((item) => item.id !== "simulated").map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label><p className="settings-status">{selected?.configured ? `已配置：${selected.api_key_masked}` : "尚未配置 Key"}</p><label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="留空则保留已保存的 Key" /></label><label>Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} /></label>{provider === "openai-compatible" ? <label>默认模型<input aria-label="默认模型" value={model} onChange={(event) => setModel(event.target.value)} placeholder="填写兼容服务的模型 ID" /></label> : <label>默认模型<select aria-label="默认模型" value={model} onChange={(event) => setModel(event.target.value)}>{(selectedProvider?.models ?? []).map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>}{notice && <p className="settings-status">{notice}</p>}<div className="dialog-actions"><button type="button" className="ghost" onClick={onClose}>取消</button><button type="button" className="ghost" onClick={() => void testConnection()}>测试已保存配置</button><button type="submit">保存</button></div></form></div>;
}

function restoreOpenIds(): string[] { try { const stored = JSON.parse(localStorage.getItem("analysis-studio-open-ids") ?? "[]"); return Array.isArray(stored) && stored.every((id) => typeof id === "string") ? stored : []; } catch { return []; } }
function datasetLabel(dataset: Dataset) { const rows = dataset.intake.rows; const columns = dataset.intake.columns?.length; const shape = rows !== undefined && columns !== undefined ? `${rows} 行 × ${columns} 列` : "待识别"; return `${dataset.source_name} · ${shape} · ID ${dataset.id.slice(0, 8)}`; }
function CreateDialog({ datasets, file, datasetId, objective, busy, onFile, onDataset, onObjective, onClose, onSubmit }: { datasets: Dataset[]; file: File | null; datasetId: string; objective: string; busy: boolean; onFile: (file: File | null) => void; onDataset: (id: string) => void; onObjective: (objective: string) => void; onClose: () => void; onSubmit: (event: FormEvent) => void }) { return <div className="dialog-backdrop" role="presentation"><form className="create-dialog" onSubmit={onSubmit}><div><p className="pane-label">新建 Analysis Session</p><h2>从数据集创建独立分析</h2><p>上传新文件，或复用已有数据集；每项分析都有独立对话和结果。</p></div><label>上传数据集<input aria-label="上传数据集" type="file" accept=".xlsx,.xls,.csv,.tsv,.json,.docx" onChange={(event) => onFile(event.target.files?.[0] ?? null)} /></label>{file && <p className="selected-file">将创建数据集：{file.name}</p>}<label>或选择已有数据集<select aria-label="选择已有数据集" value={datasetId} disabled={Boolean(file)} onChange={(event) => onDataset(event.target.value)}><option value="">请选择</option>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{datasetLabel(dataset)}</option>)}</select></label><label>分析需求<textarea aria-label="分析需求" rows={4} value={objective} onChange={(event) => onObjective(event.target.value)} placeholder="例如：分析近 12 个月趋势并预测风险" /></label><div className="dialog-actions"><button type="button" className="ghost" onClick={onClose}>取消</button><button type="submit" disabled={busy || (!file && !datasetId) || !objective.trim()}>{busy ? "创建中…" : "创建任务"}</button></div></form></div>; }
type TaskTabSession = { id: string; title: string; objective: string; status?: string };
export function TaskTabs({ sessions, recentSessions = sessions, activeId, onSelect, onClose, onNew }: { sessions: TaskTabSession[]; recentSessions?: TaskTabSession[]; activeId: string | null; onSelect: (id: string) => void; onClose: (id: string) => void; onNew: () => void }) { const [showAll, setShowAll] = useState(false); return <div className="task-tabs-wrap"><div className="session-tabs" role="tablist" aria-label="已打开的分析任务" onWheel={(event) => { event.currentTarget.scrollLeft += event.deltaY; }}>{sessions.map((session) => <div className={`task-tab ${activeId === session.id ? "active" : ""}`} style={{ minWidth: 120, maxWidth: 220 }} key={session.id}><button role="tab" aria-selected={activeId === session.id} aria-current={activeId === session.id ? "page" : undefined} aria-label={`${session.title}：${session.objective}`} title={session.objective} onClick={() => onSelect(session.id)}><span className="tab-title" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{session.title || session.objective}</span><Status status={session.status ?? "ready"} /></button><button className="close-tab" aria-label={`关闭 ${session.title}`} onClick={() => onClose(session.id)}>×</button></div>)}<button className="new-tab" aria-label="新建分析标签" onClick={onNew}>＋</button></div><button className="all-tasks" aria-label="全部任务" onClick={() => setShowAll((value) => !value)}>全部任务</button>{showAll && <div className="all-tasks-menu" role="menu">{recentSessions.map((session) => <button key={session.id} onClick={() => { onSelect(session.id); setShowAll(false); }}>{session.title}</button>)}</div>}</div>; }
function EmptyWorkspace({ onCreate }: { onCreate: () => void }) { return <div className="empty-workspace"><p className="pane-label">Analysis Workspace</p><h1>选择或新建一个分析任务</h1><p>一个数据集可对应任意多个独立 Session：趋势、异常、预测和报告各自保存，不会混在一起。</p><button onClick={onCreate}>新建分析</button></div>; }
function Status({ status }: { status: string }) { const labels: Record<string, string> = { ready: "等待分析", analyzing: "分析中", generating_report: "生成报告", succeeded: "已完成", failed: "执行失败" }; return <span className={`status ${status}`}>{status === "succeeded" ? "✓" : status === "failed" ? "!" : "●"} {labels[status] ?? status}</span>; }

export function ResultPanel({ session, tab }: { session: Session | null; tab: ResultTab }) {
  if (!session) return <div className="result-empty"><h2>分析结果工作区</h2><p>结果、图表、数据、Notebook、报告和生成文件会集中显示在这里。</p></div>;
  if (session.status !== "succeeded") return <div className="result-empty"><h2>{session.title}</h2><p>{session.status === "failed" ? "分析执行失败，请检查材料后新建或重试任务。" : "等待任务完成后显示模块化分析结果。"}</p></div>;
  if (tab === "结果") return session.validation_status ? <VerifiedResult session={session} /> : <LegacyResult session={session} />;
  if (tab === "图表") return <ChartPanel specs={session.chart_specs ?? []} artifacts={session.charts ?? []} />;
  if (tab === "数据") return <div className="result-content"><h2>数据与质量</h2><p>{session.intake.kind === "spreadsheet" ? `${session.intake.rows} 行 · ${session.intake.columns?.length} 列 · 缺失 ${session.intake.missing_cells ?? 0} 个` : `${session.intake.paragraph_count} 段文档陈述`}</p>{session.analysis?.numeric_summary && <div className="table-wrapper"><table><thead><tr><th>字段</th><th>均值</th><th>最小值</th><th>最大值</th><th>缺失</th></tr></thead><tbody>{Object.entries(session.analysis.numeric_summary).map(([name, value]) => <tr key={name}><td>{name}</td><td>{value.mean}</td><td>{value.min}</td><td>{value.max}</td><td>{value.missing}</td></tr>)}</tbody></table></div>}</div>;
  if (tab === "Notebook") return <div className="result-content"><h2>Notebook</h2>{session.notebook_cells?.map((cell) => <article className="notebook-cell" key={cell.title}><strong>{cell.title}</strong><pre className="code-scroll"><code>{cell.code}</code></pre></article>)}</div>;
  if (tab === "报告") return <div className="result-content"><h2>分析报告</h2>{session.reports?.map((report) => <a className="report-link" key={report.format} href={report.download_url}>{report.format.toUpperCase()} 报告</a>)}</div>;
  const files = [
    ...(session.charts ?? []).map((chart) => ({ id: `chart-${chart.title}`, label: chart.title, downloadUrl: chart.download_url })),
    ...(session.reports ?? []).map((report) => ({ id: `report-${report.format}`, label: `${report.format.toUpperCase()} 报告`, downloadUrl: report.download_url })),
  ];
  return <div className="result-content"><h2>生成文件</h2>{files.map((file) => <a className="report-link" key={file.id} href={file.downloadUrl}>{file.label}</a>)}</div>;
}

function ChartPanel({ specs, artifacts }: { specs: ChartSpec[]; artifacts: { title: string; download_url: string }[] }) { return <div className="result-content chart-panel"><h2>图表</h2>{specs.length ? specs.map((spec) => <ChartCard key={spec.id} spec={spec} />) : artifacts.length ? artifacts.map((chart) => <article className="artifact-card" key={chart.title}><strong>{chart.title}</strong><a href={chart.download_url} target="_blank">在新窗口查看图表</a></article>) : <p>当前分析没有可生成的图表。</p>}</div>; }
function ChartCard({ spec }: { spec: ChartSpec }) {
  if (spec.type === "unavailable") return <article className="chart-card chart-unavailable"><h3>{spec.title}</h3><p>{spec.unavailable_reason}</p></article>;
  const points = spec.series.flatMap((series) => series.points);
  const max = Math.max(...points.map((point) => point.y), 1); const min = Math.min(...points.map((point) => point.y), 0); const range = max - min || 1;
  const width = 620; const height = 260; const padding = 42; const count = Math.max(...spec.series.map((series) => series.points.length), 1);
  const position = (point: ChartPoint, index: number) => ({ x: padding + (index * (width - padding * 2)) / Math.max(count - 1, 1), y: height - padding - ((point.y - min) / range) * (height - padding * 2) });
  return <article className="chart-card"><div className="chart-card-heading"><h3>{spec.title}</h3><span>{spec.type === "bar" ? "柱状图" : "趋势图"}</span></div><svg role="img" aria-label={spec.title} viewBox={`0 0 ${width} ${height}`}><title>{spec.title}</title><line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} className="chart-axis" /><line x1={padding} y1={padding} x2={padding} y2={height - padding} className="chart-axis" />{spec.series.map((series, seriesIndex) => <g key={series.name}>{spec.type === "bar" ? series.points.map((point, index) => { const pos = position(point, index); return <rect key={point.x} className={`chart-bar series-${seriesIndex}`} x={pos.x - 14} y={pos.y} width="28" height={height - padding - pos.y}><title>{`${series.name} ${point.x}: ${point.y}`}</title></rect>; }) : <><polyline className={`chart-line series-${seriesIndex}`} points={series.points.map((point, index) => { const pos = position(point, index); return `${pos.x},${pos.y}`; }).join(" ")} />{series.points.map((point, index) => { const pos = position(point, index); return <circle key={point.x} className={`chart-point series-${seriesIndex}`} cx={pos.x} cy={pos.y} r="4"><title>{`${series.name} ${point.x}: ${point.y}`}</title></circle>; })}</>}</g>)}{(spec.markers ?? []).map((marker) => { const index = spec.series[0]?.points.findIndex((point) => point.x === marker.x) ?? -1; if (index < 0) return null; const point = spec.series[0].points[index]; const pos = position(point, index); return <g className="chart-marker" key={`${marker.x}-${marker.label}`}><line x1={pos.x} y1={padding} x2={pos.x} y2={height - padding} /><text x={pos.x + 5} y={padding + 12}>{marker.label}</text></g>; })}</svg><div className="chart-meta"><span>{spec.x_label}</span><strong>{spec.y_label}</strong></div><div className="chart-legend">{spec.series.map((series) => <span key={series.name}>{series.name}</span>)}</div>{(spec.markers ?? []).map((marker) => <p className="chart-note" key={`${marker.label}-${marker.x}`}>{marker.label}：{marker.x}</p>)}</article>;
}

function VerifiedResult({ session }: { session: Session }) { const status = session.validation_status ?? "INSUFFICIENT_DATA"; const findings = (session.findings ?? []).filter((finding) => Boolean(finding.evidence?.calculation && finding.evidence.fields?.length)); const statusLabel: Record<string, string> = { SUCCESS: "已验证完成", PARTIAL: "部分完成", INSUFFICIENT_DATA: "数据不足" }; const limitations = session.limitations ?? []; return <div className="result-content verified-result"><h2>直接回答</h2><div className="direct-answer-card"><p className="direct-answer-content core-conclusion">{session.answer || "后端没有返回可验证的直接回答。"}</p></div><p className={`validation-status ${status.toLowerCase()}`}><strong>结果状态：{status}</strong><span>{statusLabel[status] ?? status}</span></p>{findings.length > 0 && <><h3>已验证发现</h3><div className="verified-findings">{findings.map((finding, index) => <article className="finding-card" key={`${finding.kind}-${index}`}><div><strong>{finding.conclusion}</strong><span>{finding.kind}</span></div><Evidence evidence={finding.evidence!} sourceName={session.source_name} /></article>)}</div></>}{(status === "INSUFFICIENT_DATA" || status === "PARTIAL" || limitations.length > 0) && <section className="limitations"><h3>{status === "INSUFFICIENT_DATA" ? "数据不足" : "限制与未完成项"}</h3><ul>{limitations.length ? limitations.map((item, index) => <li key={index}>{item}</li>) : <li>后端未提供进一步原因。</li>}</ul></section>}</div>; }
function Evidence({ evidence, sourceName }: { evidence: FindingEvidence; sourceName: string }) { const source = evidence.source ?? {}; const file = source.file_name ?? source.source_name ?? sourceName; const table = source.sheet ?? source.table; const rows = evidence.row_indices ?? []; return <details className="finding-evidence"><summary>查看数据证据</summary><div className="evidence-body"><ul><li>来源：{file}{table ? ` · 工作表：${table}` : ""}</li>{evidence.fields?.length ? <li>字段：{evidence.fields.join("、")}</li> : null}{evidence.filters?.length ? <li>筛选：{evidence.filters.join("；")}</li> : null}{evidence.grouping?.length ? <li>分组：{evidence.grouping.join("、")}</li> : null}{evidence.calculation ? <li>计算：{evidence.calculation}</li> : null}{evidence.formula ? <li>派生公式：{evidence.formula}</li> : null}{evidence.confidence !== undefined ? <li>置信度：{evidence.confidence}</li> : null}</ul>{rows.length > 0 && <details className="evidence-detail"><summary>查看来源行（{rows.length}）</summary><pre className="evidence-scroll">来源行：{rows.join("、")}</pre></details>}{evidence.output_value !== undefined && <details className="evidence-detail"><summary>查看输出值</summary><pre className="evidence-scroll">输出值：{displayValue(evidence.output_value)}</pre></details>}</div></details>; }
function displayValue(value: unknown): string { if (typeof value === "number") return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(value); if (typeof value === "string") return value; if (Array.isArray(value)) return value.map(displayValue).join("、"); if (value && typeof value === "object") return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}：${displayValue(item)}`).join("\n"); return String(value); }
function LegacyResult({ session }: { session: Session }) { return <div className="result-content"><h2>核心结论</h2><div className="direct-answer-card"><p className="direct-answer-content core-conclusion">{session.core_conclusion}</p></div><h3>关键数据</h3><div className="kpi-grid">{session.key_metrics?.map((metric) => <Kpi key={metric.label} label={metric.label} value={metric.value} detail={metric.detail} />)}</div><h3>详细分析</h3>{session.sections?.map((section) => <section className="analysis-section" key={section.title}><h4>{section.title}</h4><ul>{section.items.map((item, index) => <li key={index}>{item.text}</li>)}</ul></section>)}{Boolean(session.business_risks?.length) && <><h3>业务风险</h3>{session.business_risks?.map((risk) => <article className="risk-card" key={risk.title}><div><span className={`risk-level ${risk.level}`}>{risk.level}</span><strong>{risk.title}</strong></div><p>{risk.evidence.join(" ")}</p><small>风险原因：{risk.reason ?? "当前数据未提供可验证的业务原因。"}</small></article>)}</>}<h3>建议</h3>{session.suggestions?.map((option) => <article className="option-card" key={option.name}><strong>{option.name}</strong><p>{option.expected_benefit}</p><small>下一步：{option.next_step}</small></article>)}<details className="data-quality"><summary>数据质量与分析限制</summary><p>{session.data_quality?.summary}</p><ul>{[...(session.data_quality?.limitations ?? []), ...(session.limitations ?? [])].map((item, index) => <li key={index}>{item}</li>)}</ul></details></div>; }
function Kpi({ label, value, detail }: { label: string; value: string; detail?: string }) { return <div className="kpi"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>; }
