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
(g) the store's own database read through an output named after it: a live
    output, a save, a manual install or a publish.
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
    from utk_curio.backend.app.datasets.infrastructure.output_paths import (
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
    from utk_curio.backend.app.datasets.install.installer import (
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
    from utk_curio.backend.app.datasets.install.bundle import install_node_output

    result = install_node_output(
        "1", node_id="node-b", path_ref="../../../../etc/hosts", data_type="dataframe"
    )
    assert result is None


# ── (c) unpublish must not 500 on a legacy ``dirName: null`` ref ─────────────

def test_unpublish_reconciles_spec_with_null_dirname_ref(app, client, user_and_token, monkeypatch, tmp_path):
    from utk_curio.backend.app.datasets.infrastructure import storage
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
    from utk_curio.backend.app.datasets.application.preview import DatasetPreviewService

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
    assert svc._paths._resolve_item_path(item) is None


def test_preview_does_not_leak_file_from_live_outputs(client, user_and_token):
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user, token = user_and_token
    secret = _secret_outside_roots("secret_preview.txt")

    resp = client.get(
        f"/api/datasets/computed.atk/preview"
        f"?liveOutputs={_live_outputs_param('atk', secret.as_posix())}",
        headers=auth_headers(token),
    )
    # A path is no output's name: the request's live output is dropped.
    assert resp.status_code == 404, resp.get_data(as_text=True)
    assert _SECRET not in resp.get_data(as_text=True)

    # Handed to the service past that check, the path is still not read.
    body = DatasetCatalogService(user).preview(
        "computed.atk",
        live_outputs=[{"node_id": "atk", "filename": secret.as_posix(), "data_type": "csv"}],
    )
    assert body.get("rows") == []
    assert body.get("unsupported") is True
    assert _SECRET not in json.dumps(body, default=str)


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


def test_listing_does_not_disclose_out_of_root_path_from_live_outputs(client, user_and_token):
    """The catalog *listing* must not echo an attacker-controlled absolute path.

    Preview/download are gated by ``_resolve_item_path``, but the listing
    enrichment used to copy a ``liveOutputs`` filename verbatim into
    ``item["path"]``/``loaderSnippet`` whenever the file existed on disk —
    a file-existence oracle plus absolute-path disclosure. The enrichment
    must confine the kept path to the allowed read roots (#143 follow-up).
    """
    _, token = user_and_token
    secret = _secret_outside_roots("secret_listing.txt")
    abs_path = secret.as_posix()

    resp = client.get(
        f"/api/datasets/catalog"
        f"?liveOutputs={_live_outputs_param('atk3', abs_path)}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    # The leaked absolute path must appear nowhere in the response body...
    body_text = resp.get_data(as_text=True)
    assert abs_path not in body_text
    assert _SECRET not in body_text
    # ...and the offending item, if surfaced at all, must carry no path.
    item = next(
        (it for it in resp.get_json()["items"] if it["id"] == "computed.atk3"),
        None,
    )
    if item is not None:
        assert item.get("path") is None


def test_detail_does_not_disclose_out_of_root_path_from_live_outputs(client, user_and_token):
    """Same protection on the single-item ``GET /api/datasets/<id>`` route."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user, token = user_and_token
    secret = _secret_outside_roots("secret_detail.txt")
    abs_path = secret.as_posix()

    resp = client.get(
        f"/api/datasets/computed.atk4"
        f"?liveOutputs={_live_outputs_param('atk4', abs_path)}",
        headers=auth_headers(token),
    )
    # A path is no output's name: the request's live output is dropped.
    assert resp.status_code == 404, resp.get_data(as_text=True)
    body_text = resp.get_data(as_text=True)
    assert abs_path not in body_text
    assert _SECRET not in body_text

    # Handed to the service past that check, the item still carries no path.
    item = DatasetCatalogService(user).get_dataset(
        "computed.atk4",
        live_outputs=[{"node_id": "atk4", "filename": abs_path, "data_type": "csv"}],
    )
    assert item.get("path") is None
    item_text = json.dumps(item, default=str)
    assert abs_path not in item_text
    assert _SECRET not in item_text


# ── (g) the store's database through an output named after it ───────────────
#
# The shared data directory also holds the sandbox's store, whose rows name
# the session that made each one. No node run names an output after it, so
# neither a live output, nor a save, nor a manual install, nor a publish may
# reach it. The stand-ins below hold a marker instead of a real database.

_STORE_SECRET = "SESSION-TOKEN-KEPT-IN-THE-STORE"
_STORE_NAMES = ("curio_data.duckdb", "curio_data.duckdb.wal")


def _plant_store_files() -> list[Path]:
    """Stand-ins for the store's database and its write-ahead log, in this
    test's own shared data directory, plus a file no node run made."""
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    files = [shared / name for name in (*_STORE_NAMES, "notes.txt")]
    for file in files:
        file.write_text(_STORE_SECRET, encoding="utf-8")
    return files


def _copies_of_the_secret(planted: list[Path]) -> list[str]:
    """Every file of this test's workspace, other than the stand-ins, that
    holds the marker: a copy the request made."""
    workspace = Path(os.environ["CURIO_LAUNCH_CWD"])
    planted_set = {p.resolve() for p in planted}
    return [
        str(path) for path in workspace.rglob("*")
        if path.is_file() and path.resolve() not in planted_set
        and _STORE_SECRET.encode() in path.read_bytes()
    ]


def test_resolve_shared_output_path_never_answers_the_store_database(app):
    from utk_curio.backend.app.datasets.infrastructure.output_paths import resolve_shared_output_path

    _plant_store_files()
    for name in _STORE_NAMES:
        assert resolve_shared_output_path(name) is None, name


@pytest.mark.parametrize("name", [*_STORE_NAMES, "notes.txt", "absolute path to the store"])
def test_a_live_output_named_after_any_other_file_is_not_served(client, user_and_token, name):
    _, token = user_and_token
    planted = _plant_store_files()
    filename = planted[0].as_posix() if name == "absolute path to the store" else name
    live = _live_outputs_param("crafted", filename)

    listing = client.get(f"/api/datasets/catalog?includeHub=true&liveOutputs={live}",
                         headers=auth_headers(token))
    assert listing.status_code == 200, listing.get_data(as_text=True)
    assert "computed.crafted" not in [item["id"] for item in listing.get_json()["items"]]
    assert filename not in listing.get_data(as_text=True)
    for route in ("preview", "download"):
        resp = client.get(f"/api/datasets/computed.crafted/{route}?liveOutputs={live}",
                          headers=auth_headers(token))
        assert resp.status_code == 404, (route, resp.status_code, resp.get_data(as_text=True)[:200])
        assert _STORE_SECRET not in resp.get_data(as_text=True), route


@pytest.mark.parametrize("name", _STORE_NAMES)
def test_a_saved_output_named_after_the_store_database_is_not_installed(client, user_and_token, name):
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import save_project_with_output

    _, token = user_and_token
    planted = _plant_store_files()
    project_id = create_project(client, token, name="Crafted save")
    save_project_with_output(client, token, project_id, name, node_id="crafted")

    assert _copies_of_the_secret(planted) == []
    resp = client.get(
        f"/api/datasets/{computed_dataset_id('crafted', project_id)}/download?dataflowId={project_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404, resp.get_data(as_text=True)[:200]
    assert _STORE_SECRET not in resp.get_data(as_text=True)


@pytest.mark.parametrize("name", _STORE_NAMES)
def test_a_computed_item_named_after_the_store_database_is_not_installed(client, user_and_token, name):
    _, token = user_and_token
    planted = _plant_store_files()
    project_id = create_project(client, token, name="Crafted install")

    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": "computed.crafted", "sourceItem": {
            "id": "computed.crafted", "origin": "computed",
            "uri": f"curio://outputs/{name}", "producerNodeId": "crafted",
        }}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 404, resp.get_data(as_text=True)[:200]
    assert _copies_of_the_secret(planted) == []


@pytest.mark.parametrize("name", _STORE_NAMES)
def test_a_live_output_named_after_the_store_database_is_not_published(
    client, user_and_token, tmp_path, monkeypatch, name,
):
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(tmp_path / "catalog"))
    _, token = user_and_token
    planted = _plant_store_files()

    resp = client.post(
        "/api/datasets/publish",
        data=json.dumps({
            "datasetId": "computed.crafted",
            "liveOutputs": [{"node_id": "crafted", "filename": name}],
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 404, resp.get_data(as_text=True)[:200]
    assert _copies_of_the_secret(planted) == []
