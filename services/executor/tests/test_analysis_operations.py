from pathlib import Path

import pandas as pd

from executor.analysis import run_operations


def test_group_summary_writes_table_and_chart(tmp_path: Path) -> None:
    frame = pd.DataFrame({"date": ["2026-01-01", "2026-01-02", "2026-01-03"], "region": ["east", "east", "west"], "revenue": [100, 200, 50]})
    result = run_operations(frame, ["profile", "group_summary", "trend"], tmp_path)

    assert result["tables"]["summary_by_region"][0]["revenue_sum"] == 300
    assert Path(result["charts"][0]).suffix == ".html"
    assert all(item["level"] in {"A", "B"} for item in result["evidence"])
