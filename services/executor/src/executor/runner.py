from pathlib import Path
import pandas as pd
from executor.analysis import RunResult, run_operations

def read_excel_and_run(input_path: Path, operations: list[str], output_dir: Path) -> RunResult:
    """Read a local, prevalidated spreadsheet without evaluating document macros."""
    frame = pd.read_excel(input_path)
    return run_operations(frame, operations, output_dir)
