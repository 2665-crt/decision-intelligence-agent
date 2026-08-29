from collections.abc import Generator
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from universal_agent.domain.contracts import CreateRevisionRequest, CreateSelectionRequest, PlanRequest, PlanResponse, RevisionResponse, SelectionResponse, TaskResponse, UploadedFileResponse
from universal_agent.services.file_service import create_selection, save_uploaded_file
from universal_agent.services.run_service import run_confirmed_plan
from universal_agent.storage.models import SessionLocal, create_schema
from universal_agent.storage.repository import confirm_revision, create_plan_revision, create_revision, create_task, get_revision, get_selection, revision_id, task_id


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


@app.post("/tasks/{task_id}/files", response_model=UploadedFileResponse, status_code=status.HTTP_201_CREATED)
def post_file(task_id: UUID, file: UploadFile, session: Session = Depends(get_session)) -> UploadedFileResponse:
    try:
        uploaded = save_uploaded_file(session, task_id, file)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (OverflowError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return UploadedFileResponse(id=UUID(uploaded.id), name=uploaded.name, parse_status=uploaded.parse_status, summary=uploaded.summary)


@app.post("/tasks/{task_id}/selections", response_model=SelectionResponse, status_code=status.HTTP_201_CREATED)
def post_selection(task_id: UUID, payload: CreateSelectionRequest, session: Session = Depends(get_session)) -> SelectionResponse:
    try:
        selection = create_selection(session, task_id, payload.file_ids)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return SelectionResponse(id=UUID(selection.id), task_id=task_id, file_ids=[UUID(file_id) for file_id in selection.file_ids])


@app.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def post_plan(payload: PlanRequest, session: Session = Depends(get_session)) -> PlanResponse:
    selection = get_selection(session, payload.selection_id)
    if selection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="selection not found")
    operations = ["profile", "quality_check", "trend"]
    revision = create_plan_revision(session, selection, payload.objective, operations)
    return PlanResponse(revision_id=revision_id(revision), objective=payload.objective, operations=operations, confirmed=False)


@app.post("/revisions/{revision_id}/confirm")
def post_confirm(revision_id: UUID, session: Session = Depends(get_session)) -> dict[str, bool]:
    revision = confirm_revision(session, revision_id)
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision not found")
    return {"confirmed": revision.confirmed}


@app.post("/revisions/{revision_id}/runs", status_code=status.HTTP_202_ACCEPTED)
def post_run(revision_id: UUID, session: Session = Depends(get_session)) -> dict[str, object]:
    revision = get_revision(session, revision_id)
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision not found")
    if not revision.confirmed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="plan must be confirmed")
    try:
        result = run_confirmed_plan(session, revision_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    artifacts = [{"revision_id": str(revision_id), "path": item["path"]} for item in [*result["tables"].values(), *result["charts"]]]
    return {"status": "succeeded", "artifacts": artifacts, "evidence": result["evidence"]}
