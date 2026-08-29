from datetime import datetime
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

