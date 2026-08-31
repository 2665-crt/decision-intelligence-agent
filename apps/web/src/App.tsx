import { FormEvent, PointerEvent, useEffect, useMemo, useState } from "react";

type Intake = { kind: string; rows?: number; columns?: string[]; missing_cells?: number; paragraph_count?: number; text_preview?: string[] };
type Report = { format: string; download_url: string };
type Risk = { title: string; object?: string; level: string; evidence: string[]; reason?: string; human_review_required?: boolean; mitigation: string };
type Option = { name: string; expected_benefit: string; cost: string; potential_harm: string; next_step: string };
type KeyMetric = { label: string; value: string; detail?: string };
type AnalysisSection = { title: string; items: { text: string }[] };
type DataQuality = { summary: string; limitations: string[] };
type Dataset = { id: string; source_name: string; intake: Intake };
type Message = { role: "user" | "assistant"; content: string; created_at: string };
type FindingEvidence = {
  source?: { source_name?: string; file_name?: string; table?: string; sheet?: string; file_hash?: string };
  fields?: string[];
  filters?: string[];
  grouping?: string[];
  calculation?: string;
  output_value?: unknown;
  metric_value?: unknown;
  confidence?: number;
  formula?: string;
  row_indices?: Array<string | number>;
};
type Finding = { kind: string; conclusion: string; confidence?: number; evidence?: FindingEvidence };
type Session = {
  id: string; dataset_id: string; source_name: string; objective: string; title: string; status: string; intake: Intake; messages: Message[];
  analysis?: { kind: string; numeric_summary?: Record<string, { count: number; missing: number; mean: number; min: number; max: number }>; quality?: { rows: number; columns: number; duplicate_rows: number; missing_cells: number } };
  core_conclusion?: string; key_metrics?: KeyMetric[]; sections?: AnalysisSection[]; business_risks?: Risk[]; data_quality?: DataQuality;
  evidence?: { level: string; summary: string }[]; risks?: Risk[]; options?: Option[]; suggestions?: Option[]; forecast?: { model?: string; is_recommended?: boolean; candidate_mae?: number; limitations: string[] } | null;
  charts?: { title: string; download_url: string }[]; reports?: Report[]; limitations?: string[]; notebook_cells?: { language: string; title: string; code: string }[];
  answer?: string; validation_status?: "SUCCESS" | "PARTIAL" | "INSUFFICIENT_DATA" | string; findings?: Finding[];
};

type ResultTab = "结果" | "图表" | "数据" | "Notebook" | "报告" | "文件";
const resultTabs: ResultTab[] = ["结果", "图表", "数据", "Notebook", "报告", "文件"];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (response.status === 204) return undefined as T;
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? "操作失败");
  return data as T;
}

export function App() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [active, setActive] = useState<Session | null>(null);
  const [openIds, setOpenIds] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<ResultTab>("结果");
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [datasetId, setDatasetId] = useState("");
  const [objective, setObjective] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fullscreen, setFullscreen] = useState(false);
  const [columns, setColumns] = useState(() => JSON.parse(localStorage.getItem("analysis-studio-columns") ?? "[250, 1, 1]") as [number, number, number]);

  const loadWorkspace = async () => {
    try {
      const [nextDatasets, nextSessions] = await Promise.all([request<Dataset[]>("/api/datasets"), request<Session[]>("/api/sessions")]);
      setDatasets(nextDatasets); setSessions(nextSessions);
    } catch { setError("无法连接分析服务，请确认本机 API 已启动。"); }
  };
  useEffect(() => { void loadWorkspace(); }, []);
  useEffect(() => { localStorage.setItem("analysis-studio-columns", JSON.stringify(columns)); }, [columns]);

  const visibleSessions = useMemo(() => sessions.filter((session) => `${session.title} ${session.source_name}`.toLowerCase().includes(search.toLowerCase())), [search, sessions]);
  const openSessions = openIds.map((id) => sessions.find((session) => session.id === id)).filter((item): item is Session => Boolean(item));
  const applySession = (session: Session) => { setActive(session); setSessions((current) => [session, ...current.filter((item) => item.id !== session.id)]); setOpenIds((current) => current.includes(session.id) ? current : [...current, session.id]); };
  const selectSession = async (session: Session) => { try { applySession(await request<Session>(`/api/sessions/${session.id}`)); } catch (caught) { setError(caught instanceof Error ? caught.message : "无法读取分析任务"); } };

  const createSession = async (event: FormEvent) => {
    event.preventDefault(); if ((!file && !datasetId) || !objective.trim()) return;
    setBusy(true); setError("");
    try {
      let selectedDatasetId = datasetId;
      if (file) { const form = new FormData(); form.set("file", file); const dataset = await request<Dataset>("/api/datasets", { method: "POST", body: form }); selectedDatasetId = dataset.id; setDatasets((current) => [dataset, ...current]); }
      const session = await request<Session>("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dataset_id: selectedDatasetId, objective: objective.trim() }) });
      applySession(session); setShowCreate(false); setFile(null); setDatasetId(""); setObjective("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "创建任务失败"); } finally { setBusy(false); }
  };
  const analyse = async () => { if (!active) return; const pending = { ...active, status: "analyzing" }; applySession(pending); setBusy(true); setError(""); try { applySession(await request<Session>(`/api/sessions/${active.id}/analyze`, { method: "POST" })); } catch (caught) { setError(caught instanceof Error ? caught.message : "分析失败"); } finally { setBusy(false); } };
  const rename = async (session: Session) => { const title = window.prompt("分析任务名称", session.title)?.trim(); if (!title) return; try { applySession(await request<Session>(`/api/sessions/${session.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) })); } catch (caught) { setError(caught instanceof Error ? caught.message : "重命名失败"); } };
  const copy = async (session: Session) => { try { applySession(await request<Session>(`/api/sessions/${session.id}/copy`, { method: "POST" })); } catch (caught) { setError(caught instanceof Error ? caught.message : "复制失败"); } };
  const remove = async (session: Session) => { if (!window.confirm(`删除“${session.title}”及其分析结果？`)) return; try { await request<void>(`/api/sessions/${session.id}`, { method: "DELETE" }); setSessions((current) => current.filter((item) => item.id !== session.id)); setOpenIds((current) => current.filter((id) => id !== session.id)); if (active?.id === session.id) setActive(null); } catch (caught) { setError(caught instanceof Error ? caught.message : "删除失败"); } };
  const resize = (event: PointerEvent<HTMLDivElement>, edge: "left" | "right") => { const start = event.clientX; const starting = [...columns] as [number, number, number]; const onMove = (move: globalThis.PointerEvent) => { const delta = move.clientX - start; setColumns(edge === "left" ? [Math.max(180, starting[0] + delta), Math.max(.55, starting[1] - delta / 500), starting[2]] : [starting[0], Math.max(.55, starting[1] + delta / 500), Math.max(.55, starting[2] - delta / 500)]); }; const onUp = () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); }; window.addEventListener("pointermove", onMove); window.addEventListener("pointerup", onUp); };

  return <main className={`workspace ${fullscreen ? "result-fullscreen" : ""}`} style={{ gridTemplateColumns: `${columns[0]}px minmax(360px, ${columns[1]}fr) minmax(360px, ${columns[2]}fr)` }}>
    <header className="topbar"><div><span className="brand-mark">◌</span><strong>Analysis Workspace</strong><span className="project-name">通用数据分析 Agent</span></div><div><button className="ghost" onClick={() => setShowCreate(true)}>新建分析</button><span className="status-dot">本机已保存</span></div></header>
    <aside className="history-pane"><button className="new-session" onClick={() => setShowCreate(true)}>＋ 新建分析</button><label className="history-search"><span>⌕</span><input aria-label="搜索历史分析" type="search" placeholder="搜索历史分析" value={search} onChange={(event) => setSearch(event.target.value)} /></label><p className="pane-label">历史分析</p><div className="session-list">{visibleSessions.length ? visibleSessions.map((session) => <div className={`session-row ${active?.id === session.id ? "selected" : ""}`} key={session.id}><button className="session-open" onClick={() => void selectSession(session)}><strong>{session.title}</strong><span>{session.source_name}</span><small><Status status={session.status} /></small></button><div className="session-actions"><button aria-label={`重命名 ${session.title}`} onClick={() => void rename(session)}>✎</button><button aria-label={`复制 ${session.title}`} onClick={() => void copy(session)}>⧉</button><button aria-label={`删除 ${session.title}`} onClick={() => void remove(session)}>×</button></div></div>) : <p className="empty-history">还没有分析任务</p>}</div></aside>
    <div className="splitter left-splitter" onPointerDown={(event) => resize(event, "left")} />
    <section className="conversation-pane"><TaskTabs sessions={openSessions} recentSessions={sessions} activeId={active?.id ?? null} onSelect={(id) => { const session = sessions.find((item) => item.id === id); if (session) void selectSession(session); }} onClose={(id) => { setOpenIds((current) => current.filter((item) => item !== id)); if (active?.id === id) setActive(null); }} onNew={() => setShowCreate(true)} />{active ? <><div className="conversation-heading"><div><p className="pane-label">当前分析任务</p><h1>{active.title}</h1><p>{active.source_name} · <Status status={active.status} /></p></div><button className="ghost" onClick={() => void rename(active)}>重命名</button></div><div className="messages">{active.messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.created_at}-${index}`}><span>{message.role === "user" ? "你" : "Agent"}</span><p>{message.content}</p>{message.role === "assistant" && active.status === "succeeded" && <div className="message-links"><button onClick={() => setActiveTab("图表")}>查看图表</button><button onClick={() => setActiveTab("数据")}>查看数据</button><button onClick={() => setActiveTab("报告")}>查看报告</button></div>}</article>)}</div><div className="conversation-compose"><p>{active.status === "succeeded" ? "本次任务已完成。新需求请新建独立分析任务，避免结果混淆。" : "任务材料已就绪，可以开始独立分析。"}</p>{active.status === "ready" && <button onClick={() => void analyse()} disabled={busy}>{busy ? "正在分析…" : "开始分析"}</button>}</div></> : <EmptyWorkspace onCreate={() => setShowCreate(true)} />}</section>
    <div className="splitter right-splitter" onPointerDown={(event) => resize(event, "right")} />
    <section className="result-pane"><div className="result-header"><div role="tablist" aria-label="分析结果模块">{resultTabs.map((tab) => <button key={tab} role="tab" aria-selected={activeTab === tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>{tab}</button>)}</div><button className="icon-button" aria-label={fullscreen ? "退出全屏" : "全屏结果"} onClick={() => setFullscreen((value) => !value)}>{fullscreen ? "↙" : "⛶"}</button></div><ResultPanel session={active} tab={activeTab} /></section>
    <footer className="workspace-footer">{active ? <>文件：{active.source_name}<span>Agent 状态：<Status status={active.status} /></span></> : "选择一个历史分析，或创建新的 Dataset → Session 任务。"}</footer>
    {showCreate && <CreateDialog datasets={datasets} file={file} datasetId={datasetId} objective={objective} busy={busy} onFile={setFile} onDataset={setDatasetId} onObjective={setObjective} onClose={() => setShowCreate(false)} onSubmit={createSession} />}{error && <p className="toast" role="alert">{error}<button onClick={() => setError("")}>×</button></p>}
  </main>;
}

function CreateDialog({ datasets, file, datasetId, objective, busy, onFile, onDataset, onObjective, onClose, onSubmit }: { datasets: Dataset[]; file: File | null; datasetId: string; objective: string; busy: boolean; onFile: (file: File | null) => void; onDataset: (id: string) => void; onObjective: (objective: string) => void; onClose: () => void; onSubmit: (event: FormEvent) => void }) { return <div className="dialog-backdrop" role="presentation"><form className="create-dialog" onSubmit={onSubmit}><div><p className="pane-label">新建 Analysis Session</p><h2>从数据集创建独立分析</h2><p>上传新文件，或复用已有数据集；每项分析都有独立对话和结果。</p></div><label>上传数据集<input aria-label="上传数据集" type="file" accept=".xlsx,.xls,.csv,.tsv,.json,.docx" onChange={(event) => onFile(event.target.files?.[0] ?? null)} /></label>{file && <p className="selected-file">将创建数据集：{file.name}</p>}<label>或选择已有数据集<select aria-label="选择已有数据集" value={datasetId} disabled={Boolean(file)} onChange={(event) => onDataset(event.target.value)}><option value="">请选择</option>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.source_name}</option>)}</select></label><label>分析需求<textarea aria-label="分析需求" rows={4} value={objective} onChange={(event) => onObjective(event.target.value)} placeholder="例如：分析近 12 个月趋势并预测风险" /></label><div className="dialog-actions"><button type="button" className="ghost" onClick={onClose}>取消</button><button type="submit" disabled={busy || (!file && !datasetId) || !objective.trim()}>{busy ? "创建中…" : "创建任务"}</button></div></form></div>; }
type TaskTabSession = { id: string; title: string; objective: string; status?: string };
export function TaskTabs({ sessions, recentSessions = sessions, activeId, onSelect, onClose, onNew }: { sessions: TaskTabSession[]; recentSessions?: TaskTabSession[]; activeId: string | null; onSelect: (id: string) => void; onClose: (id: string) => void; onNew: () => void }) {
  const [showAll, setShowAll] = useState(false);
  return <div className="task-tabs-wrap"><div className="session-tabs" role="tablist" aria-label="已打开的分析任务" onWheel={(event) => { event.currentTarget.scrollLeft += event.deltaY; }}>{sessions.map((session) => <div className={`task-tab ${activeId === session.id ? "active" : ""}`} style={{ minWidth: 120, maxWidth: 220 }} key={session.id}><button role="tab" aria-selected={activeId === session.id} aria-current={activeId === session.id ? "page" : undefined} aria-label={`${session.title}：${session.objective}`} title={session.objective} onClick={() => onSelect(session.id)}><span className="tab-title" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{session.title || session.objective}</span><Status status={session.status ?? "ready"} /></button><button className="close-tab" aria-label={`关闭 ${session.title}`} onClick={() => onClose(session.id)}>×</button></div>)}<button className="new-tab" aria-label="新建分析标签" onClick={onNew}>＋</button></div><button className="all-tasks" aria-label="全部任务" onClick={() => setShowAll((value) => !value)}>全部任务</button>{showAll && <div className="all-tasks-menu" role="menu">{recentSessions.map((session) => <button key={session.id} onClick={() => { onSelect(session.id); setShowAll(false); }}>{session.title}</button>)}</div>}</div>;
}
function EmptyWorkspace({ onCreate }: { onCreate: () => void }) { return <div className="empty-workspace"><p className="pane-label">Analysis Workspace</p><h1>选择或新建一个分析任务</h1><p>一个数据集可对应任意多个独立 Session：趋势、异常、预测和报告各自保存，不会混在一起。</p><button onClick={onCreate}>新建分析</button></div>; }
function Status({ status }: { status: string }) { const labels: Record<string, string> = { ready: "等待分析", analyzing: "分析中", generating_report: "生成报告", succeeded: "已完成", failed: "执行失败" }; return <span className={`status ${status}`}>{status === "succeeded" ? "✓" : status === "failed" ? "!" : "●"} {labels[status] ?? status}</span>; }
export function ResultPanel({ session, tab }: { session: Session | null; tab: ResultTab }) {
  if (!session) return <div className="result-empty"><h2>分析结果工作区</h2><p>结果、图表、数据、Notebook、报告和生成文件会集中显示在这里。</p></div>;
  if (session.status !== "succeeded") return <div className="result-empty"><h2>{session.title}</h2><p>{session.status === "failed" ? "分析执行失败，请检查材料后新建或重试任务。" : "等待任务完成后显示模块化分析结果。"}</p></div>;
  if (tab === "结果") return session.validation_status ? <VerifiedResult session={session} /> : <LegacyResult session={session} />;
  if (tab === "图表") return <div className="result-content"><h2>图表</h2>{session.charts?.length ? session.charts.map((chart) => <article className="artifact-card" key={chart.title}><strong>{chart.title}</strong><a href={chart.download_url} target="_blank">在新窗口查看图表</a></article>) : <p>当前分析没有生成图表。</p>}</div>;
  if (tab === "数据") return <div className="result-content"><h2>数据与质量</h2><p>{session.intake.kind === "spreadsheet" ? `${session.intake.rows} 行 · ${session.intake.columns?.length} 列 · 缺失 ${session.intake.missing_cells ?? 0} 个` : `${session.intake.paragraph_count} 段文档陈述`}</p>{session.analysis?.numeric_summary && <table><thead><tr><th>字段</th><th>均值</th><th>最小值</th><th>最大值</th><th>缺失</th></tr></thead><tbody>{Object.entries(session.analysis.numeric_summary).map(([name, value]) => <tr key={name}><td>{name}</td><td>{value.mean}</td><td>{value.min}</td><td>{value.max}</td><td>{value.missing}</td></tr>)}</tbody></table>}</div>;
  if (tab === "Notebook") return <div className="result-content"><h2>Notebook</h2>{session.notebook_cells?.map((cell) => <article className="notebook-cell" key={cell.title}><strong>{cell.title}</strong><pre><code>{cell.code}</code></pre></article>)}</div>;
  if (tab === "报告") return <div className="result-content"><h2>分析报告</h2>{session.reports?.map((report) => <a className="report-link" key={report.format} href={report.download_url}>{report.format.toUpperCase()} 报告</a>)}</div>;
  return <div className="result-content"><h2>生成文件</h2>{[...(session.charts ?? []), ...(session.reports ?? [])].map((item) => <a className="artifact-card" key={item.download_url} href={item.download_url}>{"title" in item ? item.title : `${item.format.toUpperCase()} 报告`}</a>)}</div>;
}
function VerifiedResult({ session }: { session: Session }) {
  const status = session.validation_status ?? "INSUFFICIENT_DATA";
  const findings = (session.findings ?? []).filter((finding) => Boolean(finding.evidence?.calculation && finding.evidence.fields?.length));
  const statusLabel: Record<string, string> = { SUCCESS: "已验证完成", PARTIAL: "部分完成", INSUFFICIENT_DATA: "数据不足" };
  const limitations = session.limitations ?? [];
  return <div className="result-content verified-result"><h2>直接回答</h2><p className="core-conclusion">{session.answer || "后端没有返回可验证的直接回答。"}</p><p className={`validation-status ${status.toLowerCase()}`}><strong>结果状态：{status}</strong><span>{statusLabel[status] ?? status}</span></p>{findings.length > 0 && <><h3>已验证发现</h3><div className="verified-findings">{findings.map((finding, index) => <article className="finding-card" key={`${finding.kind}-${index}`}><div><strong>{finding.conclusion}</strong><span>{finding.kind}</span></div><Evidence evidence={finding.evidence!} sourceName={session.source_name} /></article>)}</div></>}{(status === "INSUFFICIENT_DATA" || status === "PARTIAL" || limitations.length > 0) && <section className="limitations"><h3>{status === "INSUFFICIENT_DATA" ? "数据不足" : "限制与未完成项"}</h3><ul>{limitations.length ? limitations.map((item, index) => <li key={index}>{item}</li>) : <li>后端未提供进一步原因。</li>}</ul></section>}</div>;
}
function Evidence({ evidence, sourceName }: { evidence: FindingEvidence; sourceName: string }) {
  const source = evidence.source ?? {};
  const file = source.file_name ?? source.source_name ?? sourceName;
  const table = source.sheet ?? source.table;
  return <div className="finding-evidence"><h4>数据证据</h4><ul><li>来源：{file}{table ? ` · 工作表：${table}` : ""}</li>{evidence.fields?.length ? <li>字段：{evidence.fields.join("、")}</li> : null}{evidence.filters?.length ? <li>筛选：{evidence.filters.join("；")}</li> : null}{evidence.grouping?.length ? <li>分组：{evidence.grouping.join("、")}</li> : null}{evidence.calculation ? <li>计算：{evidence.calculation}</li> : null}{evidence.formula ? <li>派生公式：{evidence.formula}</li> : null}{evidence.row_indices?.length ? <li>来源行：{evidence.row_indices.join("、")}</li> : null}{evidence.output_value !== undefined ? <li>输出值：{displayValue(evidence.output_value)}</li> : null}{evidence.confidence !== undefined ? <li>置信度：{evidence.confidence}</li> : null}</ul></div>;
}
function displayValue(value: unknown) { return typeof value === "string" ? value : JSON.stringify(value); }
function LegacyResult({ session }: { session: Session }) { return <div className="result-content"><h2>核心结论</h2><p className="core-conclusion">{session.core_conclusion}</p><h3>关键数据</h3><div className="kpi-grid">{session.key_metrics?.map((metric) => <Kpi key={metric.label} label={metric.label} value={metric.value} detail={metric.detail} />)}</div><h3>详细分析</h3>{session.sections?.map((section) => <section className="analysis-section" key={section.title}><h4>{section.title}</h4><ul>{section.items.map((item, index) => <li key={index}>{item.text}</li>)}</ul></section>)}{Boolean(session.business_risks?.length) && <><h3>业务风险</h3>{session.business_risks?.map((risk) => <article className="risk-card" key={risk.title}><div><span className={`risk-level ${risk.level}`}>{risk.level}</span><strong>{risk.title}</strong></div><p>{risk.evidence.join(" ")}</p><small>风险原因：{risk.reason ?? "当前数据未提供可验证的业务原因。"}</small></article>)}</>}<h3>建议</h3>{session.suggestions?.map((option) => <article className="option-card" key={option.name}><strong>{option.name}</strong><p>{option.expected_benefit}</p><small>下一步：{option.next_step}</small></article>)}<details className="data-quality"><summary>数据质量与分析限制</summary><p>{session.data_quality?.summary}</p><ul>{[...(session.data_quality?.limitations ?? []), ...(session.limitations ?? [])].map((item, index) => <li key={index}>{item}</li>)}</ul></details></div>; }
function Kpi({ label, value, detail }: { label: string; value: string; detail?: string }) { return <div className="kpi"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>; }
