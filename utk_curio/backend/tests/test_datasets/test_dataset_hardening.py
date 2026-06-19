"""Regression tests for issue #143 — harden dataset endpoints against
malicious & malformed input.

(a) arbitrary file overwrite via output-ref filename (installer write boundary)
(b) arbitrary file read via output-ref filename (resolve_shared_output_path)
(c) unpublish 500 on a legacy ``dirName: null`` ref
(d) install 500 on a ``sourceItem`` without ``id``
(e) GeoJSON preview 500 on ``"crs": null``
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)


# ── (b) arbitrary file READ via output-ref filename ─────────────────────────

def test_resolve_shared_output_path_rejects_traversal(app):
    from utk_curio.backend.app.datasets.output_paths import (
        _shared_data_dir,
        resolve_shared_output_path,
    )

    shared = _shared_data_dir()
    (shared / "ok.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    # A legitimate flat filename in the shared dir still resolves.
    assert resolve_shared_output_path("ok.csv") == shared / "ok.csv"

    # A real file outside the shared dir must NOT be reachable via traversal.
    secret = Path(os.environ["CURIO_LAUNCH_CWD"]) / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    rel = os.path.relpath(secret, shared)  # e.g. ../../secret.txt
    assert ".." in rel
    assert resolve_shared_output_path(rel) is None
    assert resolve_shared_output_path("../../../../etc/hosts") is None
    assert resolve_shared_output_path("a/b/c") is None


# ── (a) arbitrary file OVERWRITE via output-ref filename ────────────────────

def test_install_computed_file_rejects_traversal_filename(app):
    from utk_curio.backend.app.datasets.installer import (
        InstallerError,
        install_computed_file_for_node,
    )

    with pytest.raises(InstallerError):
        install_computed_file_for_node(
            "1", b"payload", "../../../../evil", "csv", node_id="node-a"
        )
    # The escaping path was never written.
    assert not (Path(os.environ["CURIO_LAUNCH_CWD"]).parent / "evil").exists()


def test_install_node_output_drops_traversal_ref(app):
    """The project-save path resolves the ref via ``resolve_shared_output_path``;
    a traversal ref resolves to nothing and installs nothing (no write)."""
    from utk_curio.backend.app.datasets.bundle import install_node_output

    result = install_node_output(
        "1", node_id="node-b", path_ref="../../../../etc/hosts", data_type="dataframe"
    )
    assert result is None


# ── (c) unpublish must not 500 on a legacy ``dirName: null`` ref ─────────────

def test_unpublish_reconciles_spec_with_null_dirname_ref(app, client, user_and_token, monkeypatch, tmp_path):
    from utk_curio.backend.app.datasets import storage
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user, token = user_and_token
    project_id = create_project(client, token, name="Unpublish null dirName")

    # Pretend the target dataset is published: redirect the committed catalog
    # root to a temp dir holding its folder.
    cat_root = tmp_path / "catalog"
    (cat_root / "computed.target@1").mkdir(parents=True)
    monkeypatch.setattr(storage, "catalog_root", lambda: cat_root)

    svc = DatasetCatalogService(user)
    svc.installed.replace_refs(project_id, [
        {"datasetId": "computed.target", "dirName": "computed.target@1",
         "origin": "computed", "producerNodeId": "n", "publishedToHub": True},
        # Legacy fat ref with a present-but-null dirName — the crash trigger:
        # its ref_id differs from the target, so the dirName split is evaluated.
        {"datasetId": "legacy", "dirName": None, "origin": "imported"},
    ])

    # Must not raise AttributeError (which the route would surface as 500).
    result = svc.unpublish_dataset("computed.target", dataflow_id=project_id)
    assert result["unpublished"] is True

    # Reconciliation ran past the null-dirName ref: the target is now unpublished.
    refs = {r["datasetId"]: r for r in svc.installed.list_refs(project_id)}
    assert refs["computed.target"]["publishedToHub"] is False


# ── (d) install must not 500 on a ``sourceItem`` without ``id`` ─────────────

def test_install_dataset_handles_source_item_without_id(client, user_and_token):
    _, token = user_and_token
    project_id = create_project(client, token, name="Install no id")

    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": "computed.foo", "sourceItem": {"origin": "computed"}}),
        headers=auth_headers(token),
    )
    # Anything but an unhandled 500; the route-supplied id backfills the item.
    assert resp.status_code != 500, resp.get_data(as_text=True)
    assert resp.status_code < 500


# ── (e) GeoJSON preview must not 500 on ``"crs": null`` ─────────────────────

def test_geojson_preview_handles_null_crs(app, tmp_path):
    from utk_curio.backend.app.datasets.services.preview_service import DatasetPreviewService

    geojson = tmp_path / "null_crs.geojson"
    geojson.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "crs": None,  # present-but-null — RFC-7946 valid
            "features": [
                {"type": "Feature", "properties": {"name": "A"},
                 "geometry": {"type": "Point", "coordinates": [0, 0]}},
            ],
        }),
        encoding="utf-8",
    )

    svc = DatasetPreviewService()
    preview = svc._preview_geojson(geojson, 50, 0, {})
    assert preview["schema"]["crs"] is None
    assert preview["rows"][0]["name"] == "A"
