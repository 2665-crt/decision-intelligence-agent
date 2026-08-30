import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(os.getenv("ANALYSIS_STUDIO_DATA_DIR", ".analysis-studio-data")).resolve()


def job_dir(job_id: str) -> Path:
    return ROOT / "jobs" / job_id


def dataset_dir(dataset_id: str) -> Path:
    return ROOT / "datasets" / dataset_id


def session_dir(session_id: str) -> Path:
    return ROOT / "sessions" / session_id


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(source_name: str) -> tuple[str, Path]:
    job_id = str(uuid4())
    directory = job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=False)
    return job_id, directory / f"source{Path(source_name).suffix.lower()}"


def save_job(job: dict) -> None:
    path = job_dir(job["id"]) / "job.json"
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def load_job(job_id: str) -> dict:
    path = job_dir(job_id) / "job.json"
    if not path.exists():
        raise FileNotFoundError(job_id)
    return json.loads(path.read_text(encoding="utf-8"))


def create_dataset(source_name: str) -> tuple[str, Path]:
    dataset_id = str(uuid4())
    directory = dataset_dir(dataset_id)
    directory.mkdir(parents=True, exist_ok=False)
    return dataset_id, directory / f"source{Path(source_name).suffix.lower()}"


def save_dataset(dataset: dict) -> None:
    directory = dataset_dir(dataset["id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "dataset.json").write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")


def load_dataset(dataset_id: str) -> dict:
    path = dataset_dir(dataset_id) / "dataset.json"
    if not path.exists():
        raise FileNotFoundError(dataset_id)
    return json.loads(path.read_text(encoding="utf-8"))


def list_datasets() -> list[dict]:
    directory = ROOT / "datasets"
    if not directory.exists():
        return []
    datasets = [json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*/dataset.json")]
    return sorted(datasets, key=lambda item: item["updated_at"], reverse=True)


def dataset_source(dataset_id: str) -> Path:
    return next(dataset_dir(dataset_id).glob("source.*"))


def create_session(dataset: dict, objective: str, title: str) -> dict:
    session_id = str(uuid4())
    timestamp = now()
    session = {
        "id": session_id,
        "dataset_id": dataset["id"],
        "source_name": dataset["source_name"],
        "objective": objective,
        "title": title,
        "status": "ready",
        "intake": dataset["intake"],
        "messages": [{"role": "user", "content": objective, "created_at": timestamp}],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    save_session(session)
    return session


def unique_session_title(dataset_id: str, base_title: str) -> str:
    titles = {item["title"] for item in list_sessions(dataset_id)}
    if base_title not in titles:
        return base_title
    number = 2
    while f"{base_title} · {number}" in titles:
        number += 1
    return f"{base_title} · {number}"


def save_session(session: dict) -> None:
    session["updated_at"] = now()
    directory = session_dir(session["id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "session.json").write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def load_session(session_id: str) -> dict:
    path = session_dir(session_id) / "session.json"
    if not path.exists():
        raise FileNotFoundError(session_id)
    return json.loads(path.read_text(encoding="utf-8"))


def list_sessions(dataset_id: str | None = None, search: str = "") -> list[dict]:
    directory = ROOT / "sessions"
    if not directory.exists():
        return []
    sessions = [json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*/session.json")]
    keyword = search.strip().lower()
    if dataset_id:
        sessions = [item for item in sessions if item["dataset_id"] == dataset_id]
    if keyword:
        sessions = [item for item in sessions if keyword in item["title"].lower() or keyword in item["source_name"].lower()]
    return sorted(sessions, key=lambda item: item["updated_at"], reverse=True)


def delete_session(session_id: str) -> None:
    directory = session_dir(session_id)
    if not directory.exists():
        raise FileNotFoundError(session_id)
    shutil.rmtree(directory)
