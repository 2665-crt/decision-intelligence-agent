from uuid import UUID

from sqlalchemy.orm import Session

from universal_agent.storage.models import AnalysisTask, Revision, Selection, UploadedFile, as_uuid


def create_task(session: Session) -> AnalysisTask:
    task = AnalysisTask()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def create_revision(session: Session, task_id: UUID, kind: str) -> Revision | None:
    task = session.get(AnalysisTask, str(task_id))
    if task is None:
        return None
    revision = Revision(task_id=str(task_id), kind=kind)
    session.add(revision)
    session.commit()
    session.refresh(revision)
    return revision


def get_revision(session: Session, revision_id: UUID) -> Revision | None:
    return session.get(Revision, str(revision_id))


def get_selection(session: Session, selection_id: UUID) -> Selection | None:
    return session.get(Selection, str(selection_id))


def get_selection_files(session: Session, revision_id: UUID) -> list[UploadedFile]:
    revision = get_revision(session, revision_id)
    if revision is None:
        return []
    selection_id = revision.snapshot.get("selection_id")
    if not selection_id:
        return []
    selection = session.get(Selection, selection_id)
    if selection is None:
        return []
    return session.query(UploadedFile).filter(UploadedFile.id.in_(selection.file_ids)).all()


def create_plan_revision(session: Session, selection: Selection, objective: str, operations: list[str]) -> Revision:
    revision = Revision(task_id=selection.task_id, kind="plan", snapshot={"selection_id": selection.id, "objective": objective, "operations": operations})
    session.add(revision)
    session.commit()
    session.refresh(revision)
    return revision


def create_run_revision(session: Session, plan: Revision) -> Revision:
    revision = Revision(task_id=plan.task_id, kind="run", confirmed=True, snapshot={**plan.snapshot, "parent_revision_id": plan.id})
    session.add(revision); session.commit(); session.refresh(revision)
    return revision


def confirm_revision(session: Session, revision_id: UUID) -> Revision | None:
    revision = get_revision(session, revision_id)
    if revision is None:
        return None
    revision.confirmed = True
    session.commit()
    session.refresh(revision)
    return revision


def task_id(task: AnalysisTask) -> UUID:
    return as_uuid(task.id)


def revision_id(revision: Revision) -> UUID:
    return as_uuid(revision.id)
