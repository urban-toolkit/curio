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


def _assert_strict_json(payload) -> None:
    """The browser's ``Response.json()`` is a STRICT parser: ``NaN``/``Infinity``
    literals make it throw and the whole preview fails to render. Mirror that by
    re-serializing with ``allow_nan=False`` — it raises if any non-finite float
    survived sanitization."""
    json.dumps(payload, allow_nan=False)


def test_bundle_preview_sanitizes_nan_in_json_part(tmp_path):
    """list/dict artifacts are serialized with ``allow_nan=True``, so a part's
    ``.json`` file can legitimately contain ``NaN`` tokens. The preview must scrub
    them to ``null`` or the strict browser JSON parser rejects the whole response
    ('Unexpected token N ... is not valid JSON') and no part renders."""
    dataset_dir = tmp_path / "computed.node_nan@1"
    (dataset_dir / "data" / "parts").mkdir(parents=True)
    # Write invalid-JSON-with-NaN exactly as ``json.dumps(..., allow_nan=True)`` does.
    (dataset_dir / "data" / "parts" / "00_list.json").write_text(
        "[[NaN, 1.0, NaN], [2.0, NaN, 3.0]]", encoding="utf-8"
    )
    bundle_path = dataset_dir / "data" / "bundle.json"
    bundle_path.write_text(
        json.dumps({
            "version": 1,
            "parts": [
                {"index": 0, "label": "Array · part 1", "kind": "list",
                 "format": "json", "file": "data/parts/00_list.json"},
            ],
        }),
        encoding="utf-8",
    )

    # Go through the public ``preview`` so the service-boundary sanitizer runs.
    preview = DatasetPreviewService().preview(
        {"path": str(bundle_path), "format": "bundle"}, row_limit=6, offset=0
    )

    _assert_strict_json(preview)
    assert preview["bundle"] is True
    part = preview["parts"][0]
    assert part.get("unsupported") is not True, part.get("message")
    # NaN cells became None; finite values are preserved.
    first_row = part["rows"][0]["value"]
    assert first_row == [None, 1.0, None]


def _csv_bundle(tmp_path, n_rows: int):
    """A one-part CSV bundle with ``n_rows`` data rows (city,count)."""
    dataset_dir = tmp_path / "computed.node_pages@1"
    (dataset_dir / "data" / "parts").mkdir(parents=True)
    lines = ["city,count"] + [f"city{i},{i}" for i in range(n_rows)]
    (dataset_dir / "data" / "parts" / "00_table.csv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    bundle_path = dataset_dir / "data" / "bundle.json"
    bundle_path.write_text(
        json.dumps({
            "version": 1,
            "parts": [
                {"index": 0, "label": "Table · part 1", "kind": "dataframe",
                 "format": "csv", "file": "data/parts/00_table.csv"},
            ],
        }),
        encoding="utf-8",
    )
    return bundle_path


def test_bundle_part_pagination_returns_requested_page(tmp_path):
    """``part_index`` paginates a single part at its own offset so a tab can page
    through all of its rows — the overview only ever returns each part's first page."""
    bundle_path = _csv_bundle(tmp_path, n_rows=25)
    svc = DatasetPreviewService()
    item = {"path": str(bundle_path), "format": "bundle"}

    # Overview: one part, first 6 rows, but the FULL totalRows so the tab can size
    # its pagination.
    overview = svc.preview(item, row_limit=6, offset=0)
    assert overview["bundle"] is True
    assert overview["parts"][0]["totalRows"] == 25
    assert len(overview["parts"][0]["rows"]) == 6
    assert overview["parts"][0]["rows"][0]["city"] == "city0"

    # Page 2 of part 0 (offset 6).
    page2 = svc.preview(item, row_limit=6, offset=6, part_index=0)
    assert page2["bundle"] is True and page2["partIndex"] == 0
    assert page2["offset"] == 6
    assert page2["totalRows"] == 25
    assert [r["city"] for r in page2["rows"]] == [f"city{i}" for i in range(6, 12)]

    # Last (partial) page.
    last = svc.preview(item, row_limit=6, offset=24, part_index=0)
    assert [r["city"] for r in last["rows"]] == ["city24"]


def test_bundle_part_pagination_out_of_range(tmp_path):
    bundle_path = _csv_bundle(tmp_path, n_rows=3)
    svc = DatasetPreviewService()
    item = {"path": str(bundle_path), "format": "bundle"}

    missing = svc.preview(item, row_limit=6, offset=0, part_index=5)
    assert missing["unsupported"] is True
    assert missing["partIndex"] == 5
    assert missing["rows"] == []


def test_json_part_load_is_cached_until_file_changes(tmp_path):
    """Paging a JSON part must not re-parse the file each page. The loader is
    memoized by (path, mtime, size) so repeated reads return the same object, and a
    regenerated file (different size/mtime) misses the cache and reloads."""
    from utk_curio.backend.app.datasets.services.preview_service import (
        _load_json_cached,
        _load_json_file,
    )

    _load_json_cached.cache_clear()
    f = tmp_path / "list.json"
    f.write_text("[1, 2, 3]", encoding="utf-8")

    first = _load_json_file(f)
    second = _load_json_file(f)
    assert first is second  # served from cache — not re-parsed
    assert _load_json_cached.cache_info().hits >= 1

    # A regenerated file (different size) invalidates the cache and reloads.
    f.write_text("[1, 2, 3, 4, 5]", encoding="utf-8")
    reloaded = _load_json_file(f)
    assert reloaded == [1, 2, 3, 4, 5]
    assert reloaded is not first
