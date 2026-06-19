"""Regression test for bundle preview path resolution (review finding B1).

``part['file']`` is stored relative to the dataset dir (``data/parts/...``), and
the bundle manifest lives at ``<id>@1/data/bundle.json``. The preview must resolve
parts against the dataset dir, not the ``data/`` dir, or every part renders as
"Part file is not available on disk."
"""
from __future__ import annotations

import json

from utk_curio.backend.app.datasets.services.preview_service import DatasetPreviewService


def test_bundle_preview_resolves_parts(tmp_path):
    dataset_dir = tmp_path / "computed.node_x@1"
    (dataset_dir / "data" / "parts").mkdir(parents=True)
    (dataset_dir / "data" / "parts" / "00_table.csv").write_text(
        "city,count\nChicago,10\nNYC,20\n", encoding="utf-8"
    )
    bundle_path = dataset_dir / "data" / "bundle.json"
    bundle_path.write_text(
        json.dumps({
            "version": 1,
            "parts": [
                {"index": 0, "label": "t", "kind": "dataframe", "format": "csv",
                 "file": "data/parts/00_table.csv"},
            ],
        }),
        encoding="utf-8",
    )

    preview = DatasetPreviewService()._preview_bundle(bundle_path, 50, 0, {"format": "bundle"})

    assert preview["bundle"] is True
    assert len(preview["parts"]) == 1
    part = preview["parts"][0]
    assert part.get("unsupported") is not True, part.get("message")
    assert part["rows"][0]["city"] == "Chicago"
    assert len(part["rows"]) == 2
