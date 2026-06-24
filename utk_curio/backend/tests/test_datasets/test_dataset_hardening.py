"""Regression tests for issue #143 — harden dataset endpoints against
malicious & malformed input.

(a) arbitrary file overwrite via output-ref filename (installer write boundary)
(b) arbitrary file read via output-ref filename (resolve_shared_output_path)
(c) unpublish 500 on a legacy ``dirName: null`` ref
(d) install 500 on a ``sourceItem`` without ``id``
(e) GeoJSON preview 500 on ``"crs": null``
(f) arbitrary file read via an absolute ``liveOutputs`` filename that bypasses
    ``resolve_shared_output_path`` and reaches the ``_resolve_item_path``
    fallback / preview path directly (#143 follow-up).
"""
from __future__ import annotations

import base64
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


# ── (f) arbitrary file READ via an absolute liveOutputs filename ─────────────
#
# ``resolve_shared_output_path`` rejects path separators, but a ``liveOutputs``
# entry whose ``filename`` is an absolute path (e.g. ``/etc/passwd``) is copied
# verbatim into ``item["path"]`` by ``ComputedDatasetIndexer`` and would, before
# the fix, be returned by the ``_resolve_item_path`` computed fallback (and kept
# by the preview path) — streaming the file's contents back to the client.

_SECRET = "TOP-SECRET-DO-NOT-LEAK"


def _live_outputs_param(node_id: str, abs_filename: str) -> str:
    payload = json.dumps([
        {"node_id": node_id, "filename": abs_filename, "data_type": "csv"}
    ])
    return base64.b64encode(payload.encode()).decode()


def _secret_outside_roots(name: str) -> Path:
    # ``CURIO_LAUNCH_CWD`` itself is outside every allowed read root (shared
    # data, workspace ``data/``, user store, catalog, sample data all sit under
    # subdirectories of it), so a file dropped here is a faithful stand-in for
    # ``/etc/passwd`` without depending on host files.
    secret = Path(os.environ["CURIO_LAUNCH_CWD"]) / name
    secret.write_text(_SECRET, encoding="utf-8")
    return secret


def test_resolve_item_path_rejects_out_of_root_absolute_path(app, user_and_token):
    """The computed fallback must not return a path outside the allowed roots."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user, _ = user_and_token
    secret = _secret_outside_roots("secret_unit.txt")

    svc = DatasetCatalogService(user)
    item = {
        "origin": "computed",
        # URI filename carries a separator → shared resolver returns None,
        # forcing the absolute-path fallback that used to leak the file.
        "uri": f"curio://outputs/{secret.as_posix()}",
        "path": secret.as_posix(),
    }
    assert svc._resolve_item_path(item) is None


def test_preview_does_not_leak_file_from_live_outputs(client, user_and_token):
    _, token = user_and_token
    secret = _secret_outside_roots("secret_preview.txt")

    resp = client.get(
        f"/api/datasets/computed.atk/preview"
        f"?liveOutputs={_live_outputs_param('atk', secret.as_posix())}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body.get("rows") == []
    assert body.get("unsupported") is True
    assert _SECRET not in resp.get_data(as_text=True)


def test_download_does_not_stream_file_from_live_outputs(client, user_and_token):
    _, token = user_and_token
    secret = _secret_outside_roots("secret_download.txt")

    resp = client.get(
        f"/api/datasets/computed.atk2/download"
        f"?liveOutputs={_live_outputs_param('atk2', secret.as_posix())}",
        headers=auth_headers(token),
    )
    # The file must not be streamed; export reports it unavailable instead.
    assert resp.status_code == 404, resp.get_data(as_text=True)
    assert _SECRET not in resp.get_data(as_text=True)
