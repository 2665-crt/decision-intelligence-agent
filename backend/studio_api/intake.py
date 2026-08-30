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
    return _best_table(pd.ExcelFile(path))


def _best_table(workbook: pd.ExcelFile) -> pd.DataFrame:
    candidates = []
    for sheet_name in workbook.sheet_names:
        raw = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
        for header_row in range(len(raw)):
            header = raw.iloc[header_row]
            columns = [index for index, value in header.items() if isinstance(value, str) and value.strip()]
            if len(columns) < 2:
                continue
            data = raw.iloc[header_row + 1 :, columns].dropna(how="all")
            if data.empty:
                continue
            labels = [str(header[index]).strip() for index in columns]
            score = len(labels) * 10 + min(len(data), 9)
            candidates.append((score, sheet_name, header_row, labels, data))

    _, sheet_name, header_row, labels, data = max(candidates, key=lambda candidate: candidate[0])
    frame = data.copy().infer_objects(copy=False)
    frame.columns = labels
    frame = frame.reset_index(drop=True)
    frame.attrs["source_sheet"] = sheet_name
    frame.attrs["header_row"] = header_row
    return frame
