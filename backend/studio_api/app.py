from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .engine import run
from .intake import inspect_file, supported
from .reporting import render
from .store import (
    create_dataset,
    create_job,
    create_session,
    dataset_source,
    delete_session,
    job_dir,
    list_datasets,
    list_sessions,
    load_dataset,
    load_job,
    load_session,
    save_dataset,
    save_job,
    save_session,
    session_dir,
)


app = FastAPI(title="Analysis Studio")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


def session_title(objective: str) -> str:
    clean = objective.strip().replace("分析", "").replace("数据", "").strip("：:，,。 ")
    return f"{clean[:20] or '新建'}分析"


@app.post("/api/datasets", status_code=201)
async def create_dataset_endpoint(file: UploadFile = File(...)) -> dict:
    if not file.filename or not supported(file.filename):
        raise HTTPException(status_code=422, detail="只支持 XLSX、XLS、CSV 和 DOCX 文件。")
    dataset_id, source = create_dataset(file.filename)
    source.write_bytes(await file.read())
    try:
        intake = inspect_file(source)
    except Exception as exc:
        source.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"无法解析文件：{exc}") from exc
    dataset = {"id": dataset_id, "source_name": file.filename, "intake": intake, "created_at": "", "updated_at": ""}
    save_dataset(dataset)
    return load_dataset(dataset_id)


@app.get("/api/datasets")
def datasets() -> list[dict]:
    return list_datasets()


@app.post("/api/sessions", status_code=201)
def create_session_endpoint(payload: dict) -> dict:
    dataset_id = str(payload.get("dataset_id", ""))
    objective = str(payload.get("objective", "")).strip()
    if not dataset_id or not objective:
        raise HTTPException(status_code=422, detail="请选择数据集并填写分析需求。")
    try:
        dataset = load_dataset(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="数据集不存在") from exc
    return create_session(dataset, objective, str(payload.get("title", "")).strip() or session_title(objective))


@app.get("/api/sessions")
def sessions(dataset_id: str | None = None, search: str = "") -> list[dict]:
    return list_sessions(dataset_id, search)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    try:
        return load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="分析任务不存在") from exc


@app.patch("/api/sessions/{session_id}")
def update_session(session_id: str, payload: dict) -> dict:
    try:
        session = load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="分析任务不存在") from exc
    title = str(payload.get("title", "")).strip()
    if not title:
        raise HTTPException(status_code=422, detail="任务名称不能为空。")
    session["title"] = title[:80]
    save_session(session)
    return session


@app.post("/api/sessions/{session_id}/copy", status_code=201)
def copy_session(session_id: str) -> dict:
    try:
        original = load_session(session_id)
        dataset = load_dataset(original["dataset_id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="分析任务不存在") from exc
    copied = create_session(dataset, original["objective"], f"{original['title']} 副本")
    copied["messages"] = []
    save_session(copied)
    return copied


@app.delete("/api/sessions/{session_id}", status_code=204)
def remove_session(session_id: str) -> Response:
    try:
        delete_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="分析任务不存在") from exc
    return Response(status_code=204)


@app.post("/api/sessions/{session_id}/analyze")
def analyse_session(session_id: str) -> dict:
    try:
        session = load_session(session_id)
        source = dataset_source(session["dataset_id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="分析任务或数据集不存在") from exc
    try:
        session["status"] = "analyzing"
        save_session(session)
        result = run(session, session_dir(session_id), source)
        for chart in result["charts"]:
            chart["download_url"] = chart["download_url"].replace("/api/jobs/{job_id}", f"/api/sessions/{session_id}")
        session["status"] = "generating_report"
        save_session(session)
        result["reports"] = render(session, result, session_dir(session_id), route="sessions")
        session.update(result)
        session["messages"].append({"role": "assistant", "content": "分析已完成，结果、图表和报告已保存到右侧工作区。", "created_at": session["updated_at"]})
        save_session(session)
        return session
    except Exception as exc:
        session["status"] = "failed"
        session["error"] = str(exc)
        save_session(session)
        raise HTTPException(status_code=500, detail="分析执行失败，请检查文件格式和数据列。") from exc


@app.get("/api/sessions/{session_id}/files/{artifact_path:path}")
def download_session(session_id: str, artifact_path: str):
    root = session_dir(session_id).resolve()
    target = (root / artifact_path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="工件不存在")
    return FileResponse(target, filename=target.name)


@app.post("/api/jobs", status_code=201)
async def create(objective: str = Form(...), file: UploadFile = File(...)) -> dict:
    if not file.filename or not supported(file.filename):
        raise HTTPException(status_code=422, detail="只支持 XLSX、XLS、CSV 和 DOCX 文件。")
    job_id, source = create_job(file.filename)
    source.write_bytes(await file.read())
    try:
        intake = inspect_file(source)
    except Exception as exc:
        source.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"无法解析文件：{exc}") from exc
    job = {"id": job_id, "objective": objective.strip(), "source_name": file.filename, "status": "ready", "intake": intake}
    save_job(job)
    return job


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        return load_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@app.post("/api/jobs/{job_id}/analyze")
def analyse(job_id: str) -> dict:
    try:
        job = load_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    try:
        result = run(job, job_dir(job_id))
        for chart in result["charts"]:
            chart["download_url"] = chart["download_url"].format(job_id=job_id)
        result["reports"] = render(job, result, job_dir(job_id))
        job.update(result)
        save_job(job)
        return job
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        save_job(job)
        raise HTTPException(status_code=500, detail="分析执行失败，请检查文件格式和数据列。") from exc


@app.get("/api/jobs/{job_id}/files/{artifact_path:path}")
def download(job_id: str, artifact_path: str):
    root = job_dir(job_id).resolve()
    target = (root / artifact_path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="工件不存在")
    return FileResponse(target, filename=target.name)
