import os
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .engine import run
from .intake import inspect_file, supported
from .context_manager import ContextManager
from .conversation_service import ConversationService
from .conversation_store import ConversationStore
from .llm.config import ProviderConfigStore
from .llm.gateway import LLMGateway
from .llm.registry import get_model, list_models, list_providers
from .questioning import session_title
from .reporting import render
from .store import (
    create_dataset,
    create_job,
    create_session,
    dataset_source,
    delete_session,
    job_dir,
    list_datasets,
    list_session_page,
    list_sessions,
    load_dataset,
    load_job,
    load_session,
    save_dataset,
    save_job,
    save_session,
    session_dir,
    unique_session_title,
    ROOT,
)


app = FastAPI(title="Analysis Studio")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])

ENV_FILE = Path(os.getenv("ANALYSIS_STUDIO_ENV_FILE", ".env")).resolve()
provider_config = ProviderConfigStore(ENV_FILE)
conversation_store = ConversationStore(ROOT / "conversations.sqlite3", legacy_root=ROOT)
conversation_store.migrate_legacy_sessions()


def _conversation_analysis(conversation: dict, objective: str) -> dict:
    if not conversation["file_ids"]:
        return {
            "answer": "当前会话尚未绑定数据文件，请先上传或追加文件后再分析。",
            "findings": [],
            "chart_specs": [],
            "reports": [],
            "analysis": {"kind": "conversation_without_file", "plan": {}},
            "limitations": ["当前会话没有可供受控分析引擎读取的数据文件。"],
        }
    dataset = load_dataset(conversation["file_ids"][0])
    job = {"id": conversation["id"], "source_name": dataset["source_name"], "intake": dataset["intake"], "objective": objective}
    directory = session_dir(conversation["id"])
    directory.mkdir(parents=True, exist_ok=True)
    result = run(job, directory, dataset_source(dataset["id"]))
    for chart in result.get("charts", []):
        chart["download_url"] = chart["download_url"].replace("/api/jobs/{job_id}", f"/api/conversations/{conversation['id']}")
    result["reports"] = render(job, result, directory, route="conversations")
    return result


conversation_service = ConversationService(
    store=conversation_store,
    gateway=LLMGateway(provider_config.build_adapters(), provider_config.configured_models()),
    context_manager=ContextManager(),
    analysis_runner=_conversation_analysis,
    artifact_root=ROOT / "conversation-artifacts",
)


def _conversation_detail(conversation_id: str) -> dict:
    conversation = conversation_store.get_conversation(conversation_id)
    artifacts = conversation_store.list_artifacts(conversation_id)
    detail = conversation | {
        "messages": conversation_store.list_messages(conversation_id),
        "analysis_state": conversation_store.get_analysis_state(conversation_id),
        "artifacts": artifacts,
    }
    latest = next((item for item in reversed(artifacts) if item["kind"] == "analysis_result"), None)
    if latest and isinstance(latest["metadata"].get("result"), dict):
        detail.update(latest["metadata"]["result"])
    return detail


def _refresh_gateway() -> None:
    conversation_service.gateway = LLMGateway(provider_config.build_adapters(), provider_config.configured_models())


def inspect_upload(source: Path) -> dict:
    try:
        intake = inspect_file(source)
    except Exception as exc:
        source.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="无法读取该文件，请确认它是可正常打开的 Excel 或 CSV 文件后重试。") from exc
    if intake.get("kind") == "spreadsheet" and int(intake.get("rows", 0)) == 0:
        source.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="文件没有数据行，请补充数据后重新上传。")
    return intake


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/conversations", status_code=201)
def create_conversation_endpoint(payload: dict) -> dict:
    file_ids = [str(item) for item in payload.get("file_ids", [])]
    for dataset_id in file_ids:
        try:
            load_dataset(dataset_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="数据集不存在") from exc
    provider = str(payload.get("provider") or "simulated")
    model = str(payload.get("model") or "analysis-sim")
    try:
        get_model(provider, model, provider_config.configured_models().get(provider, ""))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Provider 或模型不存在。") from exc
    title = str(payload.get("title") or "新建分析").strip()[:80]
    if not title:
        raise HTTPException(status_code=422, detail="会话名称不能为空。")
    conversation = conversation_store.create_conversation(title, provider, model, file_ids)
    return _conversation_detail(conversation["id"])


@app.get("/api/conversations")
def list_conversations_endpoint(offset: int = 0, limit: int = 100) -> list[dict]:
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="分页参数无效。")
    return conversation_store.list_conversations(offset, limit)


@app.get("/api/conversations/{conversation_id}")
def get_conversation_endpoint(conversation_id: str) -> dict:
    try:
        return _conversation_detail(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析会话不存在。") from exc


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation_endpoint(conversation_id: str, payload: dict) -> dict:
    title = str(payload.get("title", "")).strip()[:80]
    if not title:
        raise HTTPException(status_code=422, detail="会话名称不能为空。")
    try:
        conversation_store.update_title(conversation_id, title)
        return _conversation_detail(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析会话不存在。") from exc


@app.delete("/api/conversations/{conversation_id}", status_code=204)
def delete_conversation_endpoint(conversation_id: str) -> Response:
    if not conversation_store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="分析会话不存在。")
    root = session_dir(conversation_id)
    if root.exists():
        shutil.rmtree(root)
    artifact_root = ROOT / "conversation-artifacts" / conversation_id
    if artifact_root.exists():
        shutil.rmtree(artifact_root)
    return Response(status_code=204)


@app.delete("/api/conversations", status_code=204)
def clear_conversation_history(confirm: bool = False) -> Response:
    if not confirm:
        raise HTTPException(status_code=422, detail="请确认清空全部历史。")
    conversation_ids = [item["id"] for item in conversation_store.list_conversations(limit=1000)]
    conversation_service.clear_history()
    for conversation_id in conversation_ids:
        root = session_dir(conversation_id)
        if root.exists():
            shutil.rmtree(root)
        artifact_root = ROOT / "conversation-artifacts" / conversation_id
        if artifact_root.exists():
            shutil.rmtree(artifact_root)
    return Response(status_code=204)


@app.post("/api/conversations/{conversation_id}/messages", status_code=201)
def send_conversation_message(conversation_id: str, payload: dict) -> dict:
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=422, detail="请输入分析问题。")
    try:
        return conversation_service.send_message(conversation_id, content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析会话不存在。") from exc


@app.post("/api/conversations/{conversation_id}/files")
def add_conversation_file(conversation_id: str, payload: dict) -> dict:
    dataset_id = str(payload.get("dataset_id", ""))
    try:
        load_dataset(dataset_id)
        conversation_store.add_file(conversation_id, dataset_id)
        return _conversation_detail(conversation_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="数据集不存在。") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析会话不存在。") from exc


@app.delete("/api/conversations/{conversation_id}/files/{dataset_id}", status_code=204)
def remove_conversation_file(conversation_id: str, dataset_id: str) -> Response:
    try:
        if not conversation_store.remove_file(conversation_id, dataset_id):
            raise HTTPException(status_code=404, detail="该会话未绑定此数据集。")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析会话不存在。") from exc
    return Response(status_code=204)


@app.get("/api/conversations/{conversation_id}/files/{artifact_path:path}")
def download_conversation_file(conversation_id: str, artifact_path: str):
    root = session_dir(conversation_id).resolve()
    target = (root / artifact_path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="工件不存在")
    return FileResponse(target, filename=target.name)


@app.put("/api/conversations/{conversation_id}/model")
def update_conversation_model(conversation_id: str, payload: dict) -> dict:
    provider = str(payload.get("provider", ""))
    model = str(payload.get("model", ""))
    try:
        get_model(provider, model, provider_config.configured_models().get(provider, ""))
        conversation_store.update_model(conversation_id, provider, model)
        return _conversation_detail(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析会话不存在。") from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Provider 或模型不存在。") from exc


@app.post("/api/messages/{message_id}/regenerate", status_code=201)
def regenerate_message_endpoint(message_id: str, payload: dict | None = None) -> dict:
    payload = payload or {}
    try:
        return conversation_service.regenerate_message(message_id, payload.get("provider"), payload.get("model"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="消息不存在或不可重新生成。") from exc


@app.get("/api/providers")
def providers_endpoint() -> list[dict]:
    return list_providers(provider_config.configured_models())


@app.get("/api/models")
def models_endpoint(provider: str) -> list[dict]:
    return list_models(provider, provider_config.configured_models().get(provider, ""))


@app.get("/api/settings/providers")
def provider_settings_endpoint() -> dict:
    return provider_config.public_status()


@app.put("/api/settings/providers/{provider}")
def save_provider_settings(provider: str, payload: dict) -> dict:
    try:
        provider_config.save(provider, {key: str(value) for key, value in payload.items() if key in {"name", "api_key", "base_url", "model"}})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Provider 不存在。") from exc
    _refresh_gateway()
    return provider_config.public_status().get(provider, {})


@app.post("/api/providers/test")
def test_provider_endpoint(payload: dict) -> dict:
    provider = str(payload.get("provider", ""))
    model = str(payload.get("model", ""))
    try:
        response = conversation_service.gateway.test(provider, model)
        return {"ok": True, "message": response.content}
    except Exception as exc:
        detail = getattr(exc, "user_message", "Provider 连接失败，请检查配置。")
        raise HTTPException(status_code=422, detail=detail) from exc


@app.post("/api/datasets", status_code=201)
async def create_dataset_endpoint(file: UploadFile = File(...)) -> dict:
    if not file.filename or not supported(file.filename):
        raise HTTPException(status_code=422, detail="只支持 XLSX、XLS、CSV 和 DOCX 文件。")
    dataset_id, source = create_dataset(file.filename)
    source.write_bytes(await file.read())
    intake = inspect_upload(source)
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
    base_title = str(payload.get("title", "")).strip() or session_title(objective)
    return create_session(dataset, objective, unique_session_title(base_title))


@app.get("/api/sessions")
def sessions(dataset_id: str | None = None, search: str = "") -> list[dict]:
    return list_sessions(dataset_id, search)


@app.get("/api/sessions/page")
def session_page(offset: int = 0, limit: int = 40, search: str = "") -> dict:
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="分页参数无效。")
    return list_session_page(offset, limit, search)


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
    copied = create_session(dataset, original["objective"], unique_session_title(session_title(original["objective"])))
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
    intake = inspect_upload(source)
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
