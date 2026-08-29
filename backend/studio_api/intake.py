from pathlib import Path

import pandas as pd
from docx import Document


SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".csv"}
DOCUMENT_EXTENSIONS = {".docx"}


def supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in SPREADSHEET_EXTENSIONS | DOCUMENT_EXTENSIONS


def inspect_file(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix in SPREADSHEET_EXTENSIONS:
        frame = read_spreadsheet(path)
        return {
            "kind": "spreadsheet",
            "rows": int(len(frame)),
            "columns": [str(column) for column in frame.columns],
            "missing_cells": int(frame.isna().sum().sum()),
        }
    document = Document(path)
    statements = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    return {
        "kind": "document",
        "paragraph_count": len(statements),
        "text_preview": statements[:5],
    }


def read_spreadsheet(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)
