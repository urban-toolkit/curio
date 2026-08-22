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

from utk_curio.backend.app.datasets.infrastructure.catalog_utils import title_from_filename
from utk_curio.backend.app.datasets.domain.constants import (
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
    from utk_curio.backend.app.datasets.install.bundle import install_node_output

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    name = "1718000000333_beef0003_output.parquet"
    src = shared / name
    src.write_bytes(b"PARQUET-BYTES")

    result = install_node_output(
        "1", node_id="node-link", path_ref=name, data_type="dataframe",
        dataflow_id="flow-link",
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
    import utk_curio.backend.app.datasets.infrastructure.file_meta as file_meta
    from utk_curio.backend.app.datasets.domain.catalog_item import item_from_file

    csv = tmp_path / "blocks.csv"
    csv.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    file_meta.write_file_meta(csv, 99, None)  # sidecar precomputed (import/first-touch time)

    def _boom(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("count_file must not run on the listing path")

    monkeypatch.setattr(file_meta, "count_file", _boom)

    item = item_from_file(csv, source_label="Workspace data")
    assert item is not None
    assert item["rowCount"] == 99  # served from the sidecar, not a fresh count


def test_merge_does_not_resurrect_publishedtohub_after_unpublish():
    """A just-unpublished ref (publishedToHub=False) must not be flipped back to
    True by a lingering hub row during dedup (notable review item)."""
    from utk_curio.backend.app.datasets.domain.dedup import merge_catalog_items

    project_ref = {
        "id": "data.x.thing", "origin": "computed", "installed": True,
        "publishedToHub": False, "producerNodeId": "n1", "dirName": "data.x.thing@1",
    }
    hub_row = {"id": "data.x.thing", "origin": "hub"}

    for a, b in ((project_ref, hub_row), (hub_row, project_ref)):
        merged = merge_catalog_items(a, b)
        assert merged.get("publishedToHub") is False, merged


def test_merge_still_marks_published_when_hub_row_present():
    """Without an explicit unpublish, a hub row still marks the row published."""
    from utk_curio.backend.app.datasets.domain.dedup import merge_catalog_items

    project_ref = {"id": "data.x.thing", "origin": "computed", "installed": True,
                   "producerNodeId": "n1", "dirName": "data.x.thing@1"}
    hub_row = {"id": "data.x.thing", "origin": "hub"}
    assert merge_catalog_items(project_ref, hub_row).get("publishedToHub") is True


def test_distinct_computed_datasets_sharing_a_filename_are_not_collapsed():
    """Distinct saved records (different producer nodes) that happen to share a
    generated data-file basename must EACH stay visible — they are no longer
    collapsed by filename. Mirrors the Autark map output + baseline-compute +
    modified-compute case where all but one used to be silently hidden until the
    siblings were deleted. ``dedupe_items`` only merges rows with the SAME id."""
    from utk_curio.backend.app.datasets.domain.dedup import dedupe_items

    same_name = "1781903321396_c8572ee7.parquet"
    items = [
        {"id": "computed.whatif-baseline-compute", "origin": "computed",
         "producerNodeId": "baseline", "installed": True,
         "dirName": "computed.whatif-baseline-compute@1",
         "path": f"/store/computed.whatif-baseline-compute@1/data/{same_name}"},
        {"id": "computed.whatif-modified-compute", "origin": "computed",
         "producerNodeId": "modified", "installed": True,
         "dirName": "computed.whatif-modified-compute@1",
         "path": f"/store/computed.whatif-modified-compute@1/data/{same_name}"},
        {"id": "computed.whatif-map", "origin": "computed",
         "producerNodeId": "map", "installed": True,
         "dirName": "computed.whatif-map@1",
         "path": f"/store/computed.whatif-map@1/data/{same_name}"},
    ]
    out = dedupe_items(items)
    assert sorted(i["id"] for i in out) == [
        "computed.whatif-baseline-compute",
        "computed.whatif-map",
        "computed.whatif-modified-compute",
    ]


def test_merge_prefers_live_computed_name_over_stale_published():
    """When a published hub copy (stale name) and the live/local computed record
    (current name) share an id, the merged row shows the CURRENT name — so the
    palette and drawer agree instead of showing the stale published name."""
    from utk_curio.backend.app.datasets.domain.dedup import merge_catalog_items

    # Hub-registry copy captured at publish time (richer rank: dirName + path).
    hub = {"id": "computed.nodeX", "origin": "hub", "title": "OLD published name",
           "dirName": "computed.nodeX@1", "path": "/cat/computed.nodeX@1/data/old.parquet",
           "publishedToHub": True, "updatedAt": "2026-06-01T00:00:00Z"}
    # Live re-execution of the same node (current output name).
    live = {"id": "computed.nodeX", "origin": "computed", "title": "NEW current name",
            "producerNodeId": "nodeX", "path": "1782_new.parquet",
            "updatedAt": "2026-06-21T00:00:00Z"}

    for a, b in ((hub, live), (live, hub)):
        merged = merge_catalog_items(a, b)
        assert merged["title"] == "NEW current name", merged
        assert merged["updatedAt"] == "2026-06-21T00:00:00Z"
        assert merged["origin"] == "computed"
        assert merged.get("publishedToHub") is True
        # The merged row must point at the CURRENT (live) file, not the stale
        # hub file — otherwise the file-based collapse keys on the wrong basename.
        assert merged["path"] == "1782_new.parquet"


def test_published_node_merges_by_id_but_distinct_twin_stays_visible():
    """The same dataset's hub registry row and its installed copy (SAME id) still
    merge to one row via dedupe_items. But a DISTINCT second node sharing the same
    data-file basename is its own saved record and must remain visible — it is no
    longer collapsed away. So the set is {merged A, distinct B} = 2 rows."""
    from utk_curio.backend.app.datasets.domain.dedup import dedupe_items

    hub_a = {"id": "computed.a", "origin": "hub", "title": "A", "installed": True,
             "dirName": "computed.a@1", "path": "/cat/computed.a@1/data/STALE.parquet",
             "publishedToHub": True}
    inst_a = {"id": "computed.a", "origin": "computed", "title": "A", "installed": True,
              "producerNodeId": "a", "dirName": "computed.a@1",
              "path": "/user/computed.a@1/data/CURRENT.parquet"}
    inst_b = {"id": "computed.b", "origin": "computed", "title": "A", "installed": True,
              "producerNodeId": "b", "dirName": "computed.b@1",
              "path": "/user/computed.b@1/data/CURRENT.parquet"}

    out = dedupe_items([hub_a, inst_a, inst_b])
    assert sorted(i["id"] for i in out) == ["computed.a", "computed.b"]
    # The merged A row keeps its published badge (hub + installed copy of same id).
    merged_a = next(i for i in out if i["id"] == "computed.a")
    assert merged_a.get("publishedToHub") is True
