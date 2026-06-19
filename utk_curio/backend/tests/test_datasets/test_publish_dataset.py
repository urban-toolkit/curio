"""Regression tests for publish_dataset (review findings B2, B5)."""
from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.datasets import storage as ds_storage
from utk_curio.backend.app.datasets.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.service import DatasetCatalogService


def _bundle_source(tmp_path):
    src = tmp_path / "src" / "computed.x@1"
    (src / "data" / "parts").mkdir(parents=True)
    (src / "data" / "bundle.json").write_text(
        json.dumps({"version": 1, "parts": [{"index": 0, "file": "data/parts/00_array.json"}]}),
        encoding="utf-8",
    )
    (src / "data" / "parts" / "00_array.json").write_text("[1, 2, 3]", encoding="utf-8")
    return src / "data" / "bundle.json"


def test_publish_bundle_copies_parts_subtree(tmp_path, monkeypatch):
    bundle_json = _bundle_source(tmp_path)
    cat_root = tmp_path / "catalog"
    cat_root.mkdir()
    monkeypatch.setattr(ds_storage, "catalog_root", lambda: cat_root)

    svc = DatasetCatalogService(user=None)
    monkeypatch.setattr(svc, "get_dataset", lambda *a, **k: {
        "id": "computed.x", "title": "Bundle", "format": "bundle",
        "path": bundle_json.as_posix(), "origin": "computed", "producerNodeId": "x",
    })

    svc.publish_dataset("computed.x", {})

    pub = cat_root / "computed.x@1"
    assert (pub / "data" / "bundle.json").is_file()
    # B2: the parts subtree must be copied, not just bundle.json.
    assert (pub / "data" / "parts" / "00_array.json").is_file()


def test_publish_rejects_missing_local_file(tmp_path, monkeypatch):
    cat_root = tmp_path / "catalog"
    cat_root.mkdir()
    monkeypatch.setattr(ds_storage, "catalog_root", lambda: cat_root)

    svc = DatasetCatalogService(user=None)
    monkeypatch.setattr(svc, "get_dataset", lambda *a, **k: {
        "id": "computed.y", "title": "Ghost", "format": "csv",
        "path": "curio://datasets/ghost", "origin": "computed", "producerNodeId": "y",
    })

    # B5: no on-disk file → raise rather than write a manifest pointing at nothing.
    with pytest.raises(DatasetCatalogError):
        svc.publish_dataset("computed.y", {})
