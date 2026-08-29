from uuid import UUID

from sqlalchemy.orm import Session

from universal_agent.storage.models import AnalysisTask, Revision, as_uuid


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


def task_id(task: AnalysisTask) -> UUID:
    return as_uuid(task.id)


def revision_id(revision: Revision) -> UUID:
    return as_uuid(revision.id)
