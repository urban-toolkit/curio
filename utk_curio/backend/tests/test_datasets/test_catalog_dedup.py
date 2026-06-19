"""Tests for the tech-debt de-duplication / efficiency cleanups (issue #147).

Covers the behavior-preserving refactors:
* #7 — shared ``title_from_filename`` + ``FORMAT_TO_EXTENSION`` /
  ``SANDBOX_DATATYPE_TO_FORMAT`` single-source maps.
* #2 — computed-output install hard-links the shared artifact (no full copy).
* #4 — local repository counts a file's rows once, then serves cached sidecar
  values on subsequent listings.
"""
from __future__ import annotations

import os
from pathlib import Path

from utk_curio.backend.app.datasets.catalog_utils import title_from_filename
from utk_curio.backend.app.datasets.constants import (
    FORMAT_TO_EXTENSION,
    SANDBOX_DATATYPE_TO_FORMAT,
    SUPPORTED_SUFFIXES,
)


# ── #7: shared helpers / maps ───────────────────────────────────────────────

def test_title_from_filename():
    assert title_from_filename("1718_abcd_my_output.parquet") == "1718 Abcd My Output"
    assert title_from_filename("census-blocks.csv") == "Census Blocks"
    # A stem that titles to whitespace falls back to the raw name.
    assert title_from_filename("___") == "___"


def test_format_to_extension_is_inverse_consistent_with_suffixes():
    # Every canonical extension maps back to its format via SUPPORTED_SUFFIXES.
    for fmt, ext in FORMAT_TO_EXTENSION.items():
        assert SUPPORTED_SUFFIXES[ext] == fmt
    # geotiff resolves to the unambiguous .tif (not .tiff).
    assert FORMAT_TO_EXTENSION["geotiff"] == ".tif"
    # bundle has no single-file extension.
    assert "bundle" not in FORMAT_TO_EXTENSION


def test_sandbox_datatype_map_covers_bundle_and_geo():
    assert SANDBOX_DATATYPE_TO_FORMAT["outputs"] == "bundle"
    assert SANDBOX_DATATYPE_TO_FORMAT["geodataframe"] == "parquet"
    assert SANDBOX_DATATYPE_TO_FORMAT["raster"] == "geotiff"


# ── #2: install hard-links the shared artifact instead of copying ───────────

def test_install_node_output_hardlinks_shared_artifact(app):
    from utk_curio.backend.app.datasets.bundle import install_node_output

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    name = "1718000000333_beef0003_output.parquet"
    src = shared / name
    src.write_bytes(b"PARQUET-BYTES")

    result = install_node_output(
        "1", node_id="node-link", path_ref=name, data_type="dataframe"
    )
    assert result is not None

    installed = result.dest / result.manifest.data_file
    assert installed.is_file()
    assert installed.read_bytes() == b"PARQUET-BYTES"
    # Hard-link on the same filesystem → same inode, no full-file copy.
    assert installed.stat().st_ino == src.stat().st_ino


# ── #4: catalog listing reads cached counts from the sidecar (no full scan) ──

def test_listing_reads_counts_from_sidecar_not_full_file(tmp_path, monkeypatch):
    """The catalog item builder used during listing pulls row/feature counts
    from the ``.meta.json`` sidecar; it must never re-scan the full file."""
    import utk_curio.backend.app.datasets.file_meta as file_meta
    from utk_curio.backend.app.datasets.catalog_items import item_from_file

    csv = tmp_path / "blocks.csv"
    csv.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    file_meta.write_file_meta(csv, 99, None)  # sidecar precomputed (import/first-touch time)

    def _boom(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("count_file must not run on the listing path")

    monkeypatch.setattr(file_meta, "count_file", _boom)

    item = item_from_file(csv, source_label="Workspace data")
    assert item is not None
    assert item["rowCount"] == 99  # served from the sidecar, not a fresh count
