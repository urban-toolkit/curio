"""A run that names a layer group's id reads the group's layers.

An OSM ``.pbf`` or a GeoPackage of several layers is imported as a layer group
whose layers are datasets of their own. ``curio_load_data("<group id>")``
loads the whole group as a dict of its layers by name, as the group card's
loader builds it. So every path that resolves the ids a run names resolves a
group's id to its layers: each layer's file, which the sandbox reads (and
stages under isolation), and an entry for the group that names its layers in
the card's order.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from utk_curio.backend.tests.test_datasets.test_execution_path_resolution import (
    _capture_sandbox,
    _exec_code,
)
from utk_curio.backend.tests.test_datasets.test_gpkg_import import _import, _write_gpkg, geo

#: A line of the loader the group card gives: one layer, read by its own id.
_LOADER_LINE = re.compile(r'^layers\[(".*")\] = curio_load_data\(("[^"]+")\)$')


def _imported_group(client, token, tmp_path, monkeypatch):
    """``(group id, [(layer name, layer id), ...])`` of a GeoPackage of four
    layers, imported, the layers named and ordered as its card's loader names
    and orders them."""
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    resp = _import(client, token, _write_gpkg(tmp_path / "chicago.gpkg"))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    group_id = resp.get_json()["groupId"]
    cards = client.get(
        "/api/datasets/catalog?groupOsm=true", headers={"Authorization": f"Bearer {token}"},
    ).get_json()["items"]
    [card] = [c for c in cards if c["id"] == group_id]
    layers = []
    for line in card["loaderSnippet"]["code"].splitlines()[1:]:
        found = _LOADER_LINE.match(line)
        assert found, f"the card's loader has a line of another shape: {line!r}"
        layers.append((json.loads(found.group(1)), json.loads(found.group(2))))
    assert [name for name, _id in layers] == ["lookup", "roads", "stops", "zones"], layers
    return group_id, layers


@geo
def test_a_group_id_resolves_to_its_layers_files_and_names_them_in_order(
    app, client, user_and_token, tmp_path, monkeypatch,
):
    user, token = user_and_token
    group_id, layers = _imported_group(client, token, tmp_path, monkeypatch)

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    with app.app_context():
        service = DatasetCatalogService(user)
        formats: dict = {}
        paths = service.resolve_execution_paths([group_id], formats=formats)
        # The same files when the caller asks for no formats.
        bare = service.resolve_execution_paths([group_id])
        unknown_formats: dict = {}
        unknown = service.resolve_execution_paths(["gpkg.xdeadbeef"], formats=unknown_formats)

    assert formats[group_id] == {"format": "layer-group", "layers": [[name, i] for name, i in layers]}
    assert set(paths) == {i for _name, i in layers}
    assert all(Path(path).is_file() for path in paths.values()), paths
    # Each layer is read as curio_load_data reads it on its own.
    assert {i: formats[i] for _name, i in layers} == {i: {"format": "parquet"} for _name, i in layers}
    assert bare == paths
    # A group the account has no layer of resolves to nothing.
    assert unknown == {} and unknown_formats == {}


@geo
def test_play_sends_the_sandbox_a_groups_layers_and_its_entry(
    client, user_and_token, tmp_path, monkeypatch,
):
    _user, token = user_and_token
    group_id, layers = _imported_group(client, token, tmp_path, monkeypatch)
    captured = _capture_sandbox(monkeypatch)

    resp = _exec_code(client, token, f'    return curio_load_data("{group_id}")\n')
    assert resp.status_code == 200, resp.get_data(as_text=True)

    body = captured["body"]
    assert set(body["dataset_paths"]) == {i for _name, i in layers}
    assert body["dataset_formats"][group_id] == {
        "format": "layer-group", "layers": [[name, i] for name, i in layers],
    }


@geo
def test_a_reopened_dataflow_keys_a_group_loader_by_the_layers_its_run_read(
    app, client, user_and_token, tmp_path, monkeypatch,
):
    """A kept output is found again under the key its run gave it, which
    names the datasets the run read (``node_exec`` keys it with the paths it
    sent). For a node that loads a group those are the group's layers, so a
    reopened dataflow keys the node by them too."""
    user, token = user_and_token
    group_id, layers = _imported_group(client, token, tmp_path, monkeypatch)
    code = f'    return curio_load_data("{group_id}")\n'

    from utk_curio.backend.app.runs import kept, reopen

    with app.app_context():
        reopened = reopen._datasets_by_node({"n": code}, None, user)["n"]
        ran = kept.datasets_read(code, None, user)

    assert set(reopened) == {i for _name, i in layers}
    assert reopened == ran


@geo
def test_solve_runs_a_group_loader_with_the_groups_layers(
    app, client, user_and_token, tmp_path, monkeypatch,
):
    """Solve's runs through a node send the paths and formats a group loader
    needs, from the mapping a session keeps and from a validate-node's own
    resolution. Only the group's entries are sent, so every other dataset is
    read as Solve's runs read it before."""
    user, token = user_and_token
    group_id, layers = _imported_group(client, token, tmp_path, monkeypatch)
    code = f'layers = curio_load_data("{group_id}")\nreturn layers'
    entry = {"format": "layer-group", "layers": [[name, i] for name, i in layers]}
    expected_formats = {group_id: entry, **{i: {"format": "parquet"} for _name, i in layers}}

    from flask import g

    from utk_curio.backend.app.agents.application.turns import grounding

    with app.test_request_context():
        g.user = user
        session_formats: dict = {}
        mapping: dict = {}
        session_paths = grounding._session_dataset_paths(None, user, mapping, [code], session_formats)
        validate_formats: dict = {}
        validate_paths = grounding._exec_dataset_paths(None, code, formats=validate_formats)

    assert set(session_paths) == {i for _name, i in layers}
    assert session_formats == expected_formats
    assert validate_paths == session_paths
    assert validate_formats == expected_formats
