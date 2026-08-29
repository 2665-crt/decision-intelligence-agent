from collections.abc import Generator
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session

from universal_agent.domain.contracts import CreateRevisionRequest, RevisionResponse, TaskResponse
from universal_agent.storage.models import SessionLocal, create_schema
from universal_agent.storage.repository import create_revision, create_task, get_revision, revision_id, task_id


app = FastAPI(title="Universal Analysis Agent")
create_schema()


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def post_task(session: Session = Depends(get_session)) -> TaskResponse:
    task = create_task(session)
    return TaskResponse(id=task_id(task), created_at=task.created_at)


@app.post(
    "/tasks/{task_id}/revisions",
    response_model=RevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_revision(
    task_id: UUID,
    payload: CreateRevisionRequest,
    session: Session = Depends(get_session),
) -> RevisionResponse:
    revision = create_revision(session, task_id, payload.kind)
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return RevisionResponse(
        id=revision_id(revision),
        task_id=task_id,
        kind=revision.kind,
        created_at=revision.created_at,
    )


@app.get("/revisions/{revision_id}", response_model=RevisionResponse)
def read_revision(revision_id: UUID, session: Session = Depends(get_session)) -> RevisionResponse:
    revision = get_revision(session, revision_id)
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision not found")
    return RevisionResponse(
        id=revision_id,
        task_id=UUID(revision.task_id),
        kind=revision.kind,
        created_at=revision.created_at,
    )
