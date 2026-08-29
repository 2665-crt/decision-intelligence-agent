from hashlib import sha256
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from universal_agent.services.file_parser import parse_file
from universal_agent.storage.models import AnalysisTask, Selection, UploadedFile


def save_uploaded_file(session: Session, task_id: UUID, upload: UploadFile) -> UploadedFile:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xls", ".docx"}:
        raise ValueError("unsupported file type")
    if session.get(AnalysisTask, str(task_id)) is None:
        raise LookupError("task not found")
    if session.scalar(select(func.count()).select_from(UploadedFile).where(UploadedFile.task_id == str(task_id))) >= 5:
        raise OverflowError("maximum of five files")
    content = upload.file.read()
    target = Path(".data") / str(task_id) / f"{sha256(content).hexdigest()}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    record = UploadedFile(task_id=str(task_id), name=upload.filename or "upload", sha256=sha256(content).hexdigest(), path=str(target), summary=parse_file(target, suffix))
    session.add(record); session.commit(); session.refresh(record)
    return record


def create_selection(session: Session, task_id: UUID, file_ids: list[UUID]) -> Selection:
    found = session.scalars(select(UploadedFile).where(UploadedFile.task_id == str(task_id), UploadedFile.id.in_([str(file_id) for file_id in file_ids]))).all()
    if len(found) != len(file_ids):
        raise ValueError("selected files do not belong to task")
    selection = Selection(task_id=str(task_id), file_ids=[str(file_id) for file_id in file_ids])
    session.add(selection); session.commit(); session.refresh(selection)
    return selection
