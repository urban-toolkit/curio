from __future__ import annotations

from pathlib import Path

import pandas as pd

from utk_curio.backend.app.datasets.service import DatasetPreviewService
from utk_curio.sandbox.util.parsers import parseOutput
from utk_curio.sandbox.util.tabular_preview import preview_parquet_file, rows_from_parse_output


def test_rows_from_parse_output_dataframe():
    parsed = parseOutput(pd.DataFrame({"zone": ["North", "South"], "pm25": [12.1, 9.8]}))
    rows = rows_from_parse_output(parsed)
    assert rows == [{"zone": "North", "pm25": 12.1}, {"zone": "South", "pm25": 9.8}]


def test_preview_parquet_file_paginates(tmp_path: Path):
    path = tmp_path / "metrics.parquet"
    pd.DataFrame(
        {"id": [1, 2, 3], "label": ["a", "b", "c"]},
    ).to_parquet(path, index=False)

    rows, total, _ = preview_parquet_file(path, row_limit=2, offset=1)
    assert total == 3
    assert rows == [{"id": 2, "label": "b"}, {"id": 3, "label": "c"}]


def test_dataset_preview_service_parquet(tmp_path: Path):
    path = tmp_path / "output.parquet"
    pd.DataFrame({"gid": ["x1"], "name": ["Loop"]}).to_parquet(path, index=False)

    service = DatasetPreviewService()
    payload = service.preview(
        {
            "format": "parquet",
            "path": path.as_posix(),
            "schema": {"fields": []},
        },
        row_limit=10,
        offset=0,
    )

    assert payload.get("unsupported") is not True
    assert payload["rows"][0]["gid"] == "x1"
    assert payload["totalRows"] == 1
