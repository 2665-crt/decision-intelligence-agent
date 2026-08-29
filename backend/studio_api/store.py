import json
import os
from pathlib import Path
from uuid import uuid4


ROOT = Path(os.getenv("ANALYSIS_STUDIO_DATA_DIR", ".analysis-studio-data")).resolve()


def job_dir(job_id: str) -> Path:
    return ROOT / "jobs" / job_id


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
