import { FormEvent, useState } from "react";

type Intake = { kind: string; rows?: number; columns?: string[]; missing_cells?: number; paragraph_count?: number; text_preview?: string[] };
type Report = { format: string; download_url: string };
type Risk = { title: string; level: string; evidence: string[]; human_review_required: boolean; mitigation: string };
type Option = { name: string; expected_benefit: string; cost: string; potential_harm: string; next_step: string };
type Job = {
  id: string;
  objective: string;
  source_name: string;
  status: string;
  intake: Intake;
  analysis?: { kind: string; numeric_summary?: Record<string, { count: number; missing: number; mean: number; min: number; max: number }>; quality?: { rows: number; columns: number; duplicate_rows: number; missing_cells: number } };
  evidence?: { level: string; summary: string }[];
  risks?: Risk[];
  options?: Option[];
  forecast?: { model?: string; is_recommended: boolean; baseline_mae?: number; candidate_mae?: number; limitations: string[] } | null;
  charts?: { title: string; download_url: string }[];
  reports?: Report[];
  limitations?: string[];
};

export function App() {
  const [objective, setObjective] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const createJob = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || !objective.trim()) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("objective", objective.trim());
      form.set("file", file);
      const response = await fetch("/api/jobs", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "创建任务失败");
      setJob(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建任务失败");
    } finally {
      setBusy(false);
    }
  };

  const analyse = async () => {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/jobs/${job.id}/analyze`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "分析失败");
      setJob(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分析失败");
    } finally {
      setBusy(false);
    }
  };

  return <main className="shell">
    <header>
      <p className="eyebrow">ANALYSIS STUDIO</p>
      <h1>通用数据分析与决策工作台</h1>
      <p>上传数据或文档，得到可追溯的分析、预测风险、低损害方案和可下载报告。</p>
    </header>

    <section className="card intake-card">
      <div><p className="step">01 / 提交材料</p><h2>开始一项分析</h2></div>
      <form onSubmit={createJob}>
        <label>上传数据或文档
          <input aria-label="上传数据或文档" type="file" accept=".xlsx,.xls,.csv,.docx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        </label>
        {file && <p className="file-chip">{file.name}</p>}
        <label>分析目标
          <textarea aria-label="分析目标" value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="例如：分析营收趋势并预测下一季度风险；给出可先试点的方案" rows={4} />
        </label>
        <button type="submit" disabled={!file || !objective.trim() || busy}>{busy ? "处理中…" : "创建分析任务"}</button>
      </form>
      <p className="hint">支持 XLSX、XLS、CSV、DOCX。涉及医疗、法律、金融、化工或施工安全时，结果会要求人工复核。</p>
    </section>

    {error && <p className="error" role="alert">{error}</p>}

    {job && <section className="card review-card">
      <div><p className="step">02 / 核对输入</p><h2>{job.source_name}</h2><p>目标：{job.objective}</p></div>
      <IntakeView intake={job.intake} />
      {job.status === "ready" && <button onClick={analyse} disabled={busy}>{busy ? "正在执行…" : "开始分析"}</button>}
    </section>}

    {job?.status === "succeeded" && <Results job={job} />}
  </main>;
}

function IntakeView({ intake }: { intake: Intake }) {
  if (intake.kind === "spreadsheet") return <div className="facts"><strong>数据概览</strong><span>{intake.rows} 行 · {intake.columns?.length} 列 · 缺失 {intake.missing_cells ?? 0} 个</span><code>{intake.columns?.join("  |  ")}</code></div>;
  return <div className="facts"><strong>文档概览</strong><span>{intake.paragraph_count} 段可读取文字</span><p>{intake.text_preview?.join(" ")}</p></div>;
}

function Results({ job }: { job: Job }) {
  return <section className="results">
    <div className="result-title"><p className="step">03 / 分析结论</p><h2>可审阅的结果</h2></div>
    <article className="card"><h3>数据事实</h3><ul>{job.evidence?.map((item, index) => <li key={index}><span className="tag">{item.level}</span>{item.summary}</li>)}</ul>
      {job.analysis?.numeric_summary && <table><thead><tr><th>字段</th><th>均值</th><th>最小值</th><th>最大值</th><th>缺失</th></tr></thead><tbody>{Object.entries(job.analysis.numeric_summary).map(([name, value]) => <tr key={name}><td>{name}</td><td>{value.mean}</td><td>{value.min}</td><td>{value.max}</td><td>{value.missing}</td></tr>)}</tbody></table>}
    </article>
    {job.forecast && <article className="card"><h3>预测与不确定性</h3><p>{job.forecast.is_recommended ? `推荐使用 ${job.forecast.model}，候选模型 MAE 为 ${job.forecast.candidate_mae}。` : "没有推荐预测模型：候选模型未能胜过朴素基线。"}</p><ul>{job.forecast.limitations.map((limit, index) => <li key={index}>{limit}</li>)}</ul></article>}
    <article className="card"><h3>风险清单</h3>{job.risks?.map((risk) => <div className="risk" key={risk.title}><div><span className={`level ${risk.level}`}>{risk.level}</span><strong>{risk.title}</strong></div><p>{risk.evidence.join(" ")}</p><p>缓解：{risk.mitigation}</p>{risk.human_review_required && <b>需要人工专业复核</b>}</div>)}</article>
    <article className="card"><h3>方案比较</h3><div className="options">{job.options?.map((option) => <div className="option" key={option.name}><h4>{option.name}</h4><p>{option.expected_benefit}</p><dl><dt>成本</dt><dd>{option.cost}</dd><dt>潜在损害</dt><dd>{option.potential_harm}</dd></dl><p>{option.next_step}</p></div>)}</div></article>
    {job.charts?.length ? <article className="card"><h3>图表</h3>{job.charts.map((chart) => <a key={chart.title} href={chart.download_url} target="_blank">查看 {chart.title}</a>)}</article> : null}
    <article className="card"><h3>报告下载</h3><div className="reports">{job.reports?.map((report) => <a key={report.format} href={report.download_url}>{report.format.toUpperCase()} 报告</a>)}</div><p className="hint">{job.limitations?.join(" ")}</p></article>
  </section>;
}
