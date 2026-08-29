from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .engine import run
from .intake import inspect_file, supported
from .reporting import render
from .store import create_job, job_dir, load_job, save_job


app = FastAPI(title="Analysis Studio")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


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
