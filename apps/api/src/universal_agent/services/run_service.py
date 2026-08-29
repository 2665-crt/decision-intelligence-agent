from pathlib import Path
from uuid import UUID

from executor.runner import read_excel_and_run
from sqlalchemy.orm import Session

from universal_agent.storage.repository import get_selection_files

def run_confirmed_plan(session: Session, revision_id: UUID) -> dict:
    revision_files = get_selection_files(session, revision_id)
    if len(revision_files) != 1:
        raise ValueError("analysis run requires exactly one selected spreadsheet")
    source = revision_files[0]
    if Path(source.path).suffix.lower() not in {".xlsx", ".xls"}:
        raise ValueError("Word documents provide statements, not numeric analysis frames")
    output = Path(".data") / "runs" / str(revision_id)
    result = read_excel_and_run(Path(source.path), ["profile", "quality_check", "trend"], output)
    return result.as_dict()
