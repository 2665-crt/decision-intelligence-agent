from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TaskResponse(BaseModel):
    id: UUID
    created_at: datetime


class CreateRevisionRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=32)


class RevisionResponse(BaseModel):
    id: UUID
    task_id: UUID
    kind: str
    created_at: datetime


class UploadedFileResponse(BaseModel):
    id: UUID
    name: str
    parse_status: str
    summary: dict[str, Any]


class CreateSelectionRequest(BaseModel):
    file_ids: list[UUID] = Field(min_length=1, max_length=5)


class SelectionResponse(BaseModel):
    id: UUID
    task_id: UUID
    file_ids: list[UUID]
