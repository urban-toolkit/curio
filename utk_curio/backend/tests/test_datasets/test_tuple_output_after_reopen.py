"""A tuple output is the tuple again after a reopen under a new sign-in.

Example 09's UTCI node returns ``(utci_list, utci_shape)``, and its zonal node
indexes it (``packages/curio.weather@1``). A Python node's tuple is stored as
one ``outputs`` row naming a row per value, each tagged with the session that
wrote it (``sandbox/util/parsers.save_to_duckdb``). A project save installs
the output as a bundle: ``data/bundle.json`` and a file per value under
``data/parts/`` (``datasets/install/bundle.py``). A reader the session-tagged
store refuses reads the saved output in place, from the file the backend names
for it (``projects/storage.saved_output_file``, handed over as ``savedPath``
or ``saved_paths``): ``/get``, a Python node's inputs in process, the staging
of an isolated node's input (``staging.stage_input``) and ``/raster``. Nothing
is copied into the shared data directory, and nothing reads a copy there.

A copy of a tuple once held the bundle's ``bundle.json`` alone, so after a
reopen under a new sign-in each of them read the bundle's description, a dict,
where the tuple had been. Here an output is written in one session, saved and
loaded through the project routes the canvas calls, and read with another
session's id: what comes back must be what the store gives the session that
wrote it.

A list or a dict of frames is saved as a bundle too (``list_of_ids``,
``dict_of_ids``), so it comes back as that list, or that dict with its keys in
their order, and not as a tuple of its parts.
"""
from __future__ import annotations

import json
import os
import shutil
import textwrap
from pathlib import Path

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)

#: The sign-in that ran the nodes, and the one that reopens the dataflow.
EARLIER, LATER = "earlier-sign-in", "new-sign-in"
UTCI_NODE, ZONES_NODE, PARTS_NODE = "utci-compute", "census-zones", "every-kind"
#: A node that returns its roads and blocks as a list or as a dict.
FRAMES_NODE = "roads-and-blocks"
#: The GeoTIFF the sandbox's raster tests read: 40 x 30 cells in EPSG:32616.
RASTER = Path(__file__).resolve().parents[1] / "test_frontend" / "data" / "autark_raster_utm16n.tif"
#: Where the raster part sits in :func:`_every_kind_of_part`'s tuple.
RASTER_PART = 2


@pytest.fixture(autouse=True)
def _sandbox_routes_take_no_secret(monkeypatch):
    """The sandbox's routes want the shared secret when one is configured, as
    in CI's container; its own suite clears it the same way
    (``sandbox/tests/conftest.py``)."""
    monkeypatch.delenv("CURIO_SANDBOX_TOKEN", raising=False)


def _shared() -> Path:
    return Path(os.environ["CURIO_SHARED_DATA"])


def _sandbox():
    from utk_curio.sandbox.app import app as sandbox_app

    return sandbox_app.test_client()


def _output(node_id: str, art_id: str, data_type: str) -> dict:
    """An output as the canvas sends it with a save."""
    return {
        "node_id": node_id,
        "filename": art_id,
        "data_type": data_type,
        "node_name": "Python Computation",
        "node_type": "curio.builtin/computation-analysis",
    }


def _earlier_sign_in(token) -> str:
    """:data:`EARLIER`, a sign-in of the account *token* signs in to."""
    from utk_curio.backend.app.users.models import UserSession
    from utk_curio.backend.extensions import db

    if UserSession.query.filter_by(token=EARLIER).first() is None:
        user_id = UserSession.query.filter_by(token=token).one().user_id
        db.session.add(UserSession(user_id=user_id, token=EARLIER))
        db.session.commit()
    return EARLIER


def _save(client, token, *outputs) -> str:
    """A dataflow saved with *outputs*: the save installs each one. The
    canvas sends it in the sign-in that ran the nodes, the only one of the
    account that may read what they made."""
    project_id = create_project(client, token, name="Tuple after a reopen")
    saved = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({"outputs": list(outputs)}),
        headers=auth_headers(_earlier_sign_in(token)),
    )
    assert saved.status_code == 200, saved.get_data(as_text=True)
    return project_id


def _files_in_shared_data() -> set:
    """The shared data directory's files, the store's database aside."""
    return {
        path for path in _shared().rglob("*")
        if path.is_file() and not path.name.startswith("curio_data.duckdb")
    }


def _reopen(client, token, project_id: str, *outputs) -> None:
    """Open the dataflow again: the load lists each saved output, and copies
    none of them into the shared data directory."""
    shared_before = _files_in_shared_data()
    loaded = client.get(f"/api/projects/{project_id}", headers=auth_headers(token))
    assert loaded.status_code == 200, loaded.get_data(as_text=True)
    restored = {entry["filename"] for entry in loaded.get_json()["outputs"]}
    assert {entry["filename"] for entry in outputs} <= restored, restored
    assert _files_in_shared_data() == shared_before, (
        "opening the dataflow copied a saved output into the shared data directory"
    )


def _save_and_reopen(client, token, *outputs) -> str:
    project_id = _save(client, token, *outputs)
    _reopen(client, token, project_id, *outputs)
    return project_id


def _saved(user, project_id: str, *art_ids: str) -> dict:
    """``{name: {path, dataType}}``: each saved output's own file, as the
    backend names it to the sandbox for a read on the dataflow."""
    from utk_curio.backend.app.projects import storage

    saved = {}
    for art_id in art_ids:
        held = storage.saved_output_file(str(user.id), project_id, art_id)
        assert held is not None, f"the dataflow names no file for {art_id}"
        saved[art_id] = {"path": str(held.path), "dataType": held.data_type or ""}
    return saved


def _bundle_json(user, project_id: str, node_id: str) -> Path:
    """The ``bundle.json`` of *node_id*'s saved output, in its dataset."""
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    return dataset_dir(str(user.id), f"{computed_dataset_id(node_id, project_id)}@1") / "data" / "bundle.json"


def _write_utci():
    """What example 09's UTCI node returns, written in the earlier sign-in:
    the grid as a list of rows, a cell with no value as NaN, then the grid's
    ``[width, height]``. Returns its id and what the store gives that sign-in."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    utci = ([[31.5, float("nan")], [33.0, 34.5]], [2, 2])
    art_id = save_to_duckdb(utci, node_id=UTCI_NODE, session_id=EARLIER)
    stored = load_from_duckdb(art_id, session_id=EARLIER)
    assert stored == ([[31.5, None], [33.0, 34.5]], [2, 2])
    return art_id, stored


def _raster_facts(dataset) -> tuple:
    import numpy as np

    return (
        (dataset.width, dataset.height),
        dataset.crs.to_epsg(),
        tuple(dataset.transform),
        np.asarray(dataset.read(1), dtype=float),
    )


def _assert_same_raster(dataset, expected) -> None:
    import numpy as np

    facts = _raster_facts(dataset)
    assert facts[:3] == expected[:3]
    assert np.array_equal(facts[3], expected[3], equal_nan=True)


def _close(values) -> None:
    from utk_curio.sandbox.util.rasters import is_dataset

    for value in values if isinstance(values, (list, tuple)) else (values,):
        if is_dataset(value):
            value.close()


def _every_kind_of_part(tmp_path: Path):
    """A tuple with one value of each kind a part is saved as, written in the
    earlier sign-in. Returns its id, what the store gives that sign-in (the
    raster as its facts), and the file the raster was returned from."""
    import geopandas as gpd
    import pandas as pd
    import rasterio
    from shapely.geometry import Point

    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    table = pd.DataFrame({"n": [1, 2], "tags": [{"a": 1}, {"b": [2, 3]}]})
    stations = gpd.GeoDataFrame(
        {"name": ["Brera", "Duomo"]},
        geometry=[Point(9.188, 45.472), Point(9.191, 45.464)],
        crs="EPSG:4326",
    )
    stations.__dict__["metadata"] = {"name": "stations", "layerType": "points"}
    returned = tmp_path / "returned.tif"
    shutil.copyfile(RASTER, returned)
    with rasterio.open(returned) as raster:
        art_id = save_to_duckdb(
            (table, stations, raster, [1, 2, 3], {"unit": "C"}, 42, 3.5, False, "Milan", None),
            node_id=PARTS_NODE,
            session_id=EARLIER,
        )
    stored = load_from_duckdb(art_id, session_id=EARLIER)
    try:
        expected = list(stored)
        expected[RASTER_PART] = _raster_facts(stored[RASTER_PART])
    finally:
        _close(stored)
    return art_id, tuple(expected), returned


# -- example 09's UTCI tuple -------------------------------------------------

def test_load_artifact_gives_the_tuple_after_a_reopen(client, user_and_token):
    from utk_curio.sandbox.util.parsers import load_artifact

    user, token = user_and_token
    art_id, stored = _write_utci()
    project_id = _save_and_reopen(client, token, _output(UTCI_NODE, art_id, "outputs"))

    value = load_artifact(art_id, session_id=LATER, saved_paths=_saved(user, project_id, art_id))

    assert isinstance(value, tuple), f"read a {type(value).__name__}: {value!r}"
    assert value == stored


def test_get_serves_the_tuple_after_a_reopen(client, user_and_token):
    user, token = user_and_token
    art_id, _stored = _write_utci()
    before = _sandbox().get("/get", query_string={"fileName": art_id, "sessionId": EARLIER})
    assert before.status_code == 200, before.get_data(as_text=True)
    project_id = _save_and_reopen(client, token, _output(UTCI_NODE, art_id, "outputs"))

    after = _sandbox().get("/get", query_string={
        "fileName": art_id, "sessionId": LATER,
        "savedPath": _saved(user, project_id, art_id)[art_id]["path"],
    })

    assert after.status_code == 200, after.get_data(as_text=True)
    body = after.get_json()
    assert body["dataType"] == "outputs", body
    assert body == before.get_json()


def test_a_python_node_downstream_indexes_the_tuple(client, user_and_token):
    """Example 09's zonal node reads the grid and its shape out of the tuple,
    beside another saved input, as a node with several input circles gets
    them (in process, as ``/exec`` runs it without isolation)."""
    import pandas as pd

    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    _worker_init()
    user, token = user_and_token
    utci_id, _stored = _write_utci()
    zones_id = save_to_duckdb(
        pd.DataFrame({"zone": ["Brera", "Duomo", "Navigli"]}), node_id=ZONES_NODE, session_id=EARLIER,
    )
    project_id = _save_and_reopen(
        client, token,
        _output(ZONES_NODE, zones_id, "dataframe"),
        _output(UTCI_NODE, utci_id, "outputs"),
    )
    inputs = [{"path": zones_id, "dataType": "dataframe"}, {"path": utci_id, "dataType": "outputs"}]
    code = textwrap.indent(
        "zones = input_0\n"
        "utci_list = input_1[0]\n"
        "utci_shape = input_1[1]\n"
        "empty = sum(value is None for row in utci_list for value in row)\n"
        "return [len(zones), utci_shape, empty]\n",
        "    ",
    )

    result = execute_code(
        code, str(inputs), "curio.builtin/computation-analysis", "outputs",
        session_id=LATER, save_dataset=False, input_slots=[0, 1],
        saved_paths=_saved(user, project_id, zones_id, utci_id),
    )

    assert result["stderr"] == "", result["stderr"]
    assert load_from_duckdb(result["output"]["path"]) == [3, [2, 2], 1]


def test_an_isolated_node_has_the_tuple_staged(client, user_and_token, tmp_path):
    from utk_curio.sandbox.util import staging

    user, token = user_and_token
    art_id, stored = _write_utci()
    project_id = _save_and_reopen(client, token, _output(UTCI_NODE, art_id, "outputs"))
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    spec = staging.stage_input(art_id, scratch, session_id=LATER, saved_paths=_saved(user, project_id, art_id))

    assert (spec.get("kind"), spec.get("container")) == ("sequence", "tuple"), spec
    staged = tuple(
        json.loads((scratch / item["file"]).read_text(encoding="utf-8")) for item in spec["items"]
    )
    assert staged == stored


def test_a_copy_left_in_the_shared_data_directory_is_not_read(client, user_and_token):
    """A server before this one copied each saved output into the shared data
    directory, a tuple sometimes as its ``bundle.json`` alone, under the
    output's name. Nothing reads such a copy now: the tuple comes from its
    dataset, and a read the backend names no file for finds no output."""
    from utk_curio.sandbox.util.parsers import load_artifact

    user, token = user_and_token
    art_id, stored = _write_utci()
    output = _output(UTCI_NODE, art_id, "outputs")
    project_id = _save(client, token, output)
    shutil.copyfile(_bundle_json(user, project_id, UTCI_NODE), _shared() / art_id)
    _reopen(client, token, project_id, output)

    assert load_artifact(art_id, session_id=LATER, saved_paths=_saved(user, project_id, art_id)) == stored
    with pytest.raises(KeyError, match="No artifact with id"):
        load_artifact(art_id, session_id=LATER)


def test_a_part_missing_from_the_saved_dataset_is_a_missing_artifact(client, user_and_token):
    """A tuple short of a part is not the tuple: the read fails with the
    store's own error, as for an output that is nowhere."""
    from utk_curio.sandbox.util.parsers import load_artifact

    user, token = user_and_token
    art_id, _stored = _write_utci()
    project_id = _save_and_reopen(client, token, _output(UTCI_NODE, art_id, "outputs"))
    saved = _saved(user, project_id, art_id)
    parts = sorted(_bundle_json(user, project_id, UTCI_NODE).parent.rglob("01_list.json"))
    assert parts, "the saved dataset holds no second part of the tuple"
    for part in parts:
        part.unlink()

    with pytest.raises(KeyError, match="No artifact with id"):
        load_artifact(art_id, session_id=LATER, saved_paths=saved)


def test_a_part_named_outside_the_saved_dataset_is_not_read(client, user_and_token):
    """The saved file is read with no session check, so a bundle is read only
    from its own dataset's files: a ``bundle.json`` naming a part elsewhere,
    here in the shared data directory, is refused, not followed."""
    from utk_curio.sandbox.util.parsers import load_artifact

    user, token = user_and_token
    art_id, _stored = _write_utci()
    project_id = _save_and_reopen(client, token, _output(UTCI_NODE, art_id, "outputs"))
    saved = _saved(user, project_id, art_id)
    elsewhere = _shared() / "not-this-tuple.json"
    elsewhere.write_text(json.dumps(["not", "this", "tuple"]), encoding="utf-8")
    bundle = _bundle_json(user, project_id, UTCI_NODE)
    spec = json.loads(bundle.read_text(encoding="utf-8"))
    spec["parts"][0]["file"] = os.path.relpath(elsewhere, bundle.parent.parent)
    bundle.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(KeyError, match="No artifact with id"):
        load_artifact(art_id, session_id=LATER, saved_paths=saved)


# -- every kind of part ------------------------------------------------------

def test_every_part_comes_back_as_the_kind_it_was_saved_as(client, user_and_token, tmp_path):
    """Each part as the store gives it: a frame with its object columns
    decoded, a GeoDataFrame with its layer name and type, a raster as a
    rasterio dataset, and JSON values and scalars as they were returned."""
    import pandas as pd
    from geopandas.testing import assert_geodataframe_equal

    from utk_curio.sandbox.util.parsers import load_artifact

    user, token = user_and_token
    art_id, expected, returned = _every_kind_of_part(tmp_path)
    project_id = _save_and_reopen(client, token, _output(PARTS_NODE, art_id, "outputs"))
    # The file the node returned the raster from is a scratch copy: only
    # the saved output still has it.
    returned.unlink()

    value = load_artifact(art_id, session_id=LATER, saved_paths=_saved(user, project_id, art_id))
    assert isinstance(value, tuple), f"read a {type(value).__name__}: {value!r}"
    try:
        assert len(value) == len(expected)
        table, stations, raster, *rest = value
        pd.testing.assert_frame_equal(table, expected[0])
        assert_geodataframe_equal(stations, expected[1])
        assert getattr(stations, "metadata", None) == {"name": "stations", "layerType": "points"}
        _assert_same_raster(raster, expected[RASTER_PART])
        assert rest == list(expected[RASTER_PART + 1:])
        assert [type(item) for item in rest] == [list, dict, int, float, bool, str, type(None)]
    finally:
        _close(value)


def test_the_raster_route_serves_a_raster_part_after_a_reopen(client, user_and_token, tmp_path):
    from rasterio.io import MemoryFile

    user, token = user_and_token
    art_id, expected, returned = _every_kind_of_part(tmp_path)
    project_id = _save_and_reopen(client, token, _output(PARTS_NODE, art_id, "outputs"))
    returned.unlink()

    response = _sandbox().get(
        "/raster", query_string={
            "fileName": art_id, "part": RASTER_PART, "sessionId": LATER,
            "savedPath": _saved(user, project_id, art_id)[art_id]["path"],
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    meta = json.loads(response.headers["X-Curio-Raster"])
    assert (meta["width"], meta["height"], meta["crs"]) == (40, 30, "EPSG:32616")
    with MemoryFile(response.get_data()) as memory, memory.open() as served:
        _assert_same_raster(served, expected[RASTER_PART])


# -- a list or a dict of frames ----------------------------------------------

def _write_frames(container):
    """A node's roads and blocks, written in the earlier sign-in as a list, or
    as a dict whose keys are not in sorted order. The two frames differ in
    kind, columns and rows, so a reader that swaps them is caught. Returns the
    output's id and what the store gives that sign-in."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import LineString

    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    roads = gpd.GeoDataFrame(
        {"name": ["Via Dante", "Corso Como"]},
        geometry=[LineString([(9.186, 45.466), (9.183, 45.469)]), LineString([(9.188, 45.482), (9.190, 45.484)])],
        crs="EPSG:4326",
    )
    roads.__dict__["metadata"] = {"name": "roads", "layerType": "roads"}
    blocks = pd.DataFrame({"block": ["Brera", "Duomo", "Isola"], "population": [120, 340, 90]})
    value = [roads, blocks] if container is list else {"roads": roads, "blocks": blocks}
    art_id = save_to_duckdb(value, node_id=FRAMES_NODE, session_id=EARLIER)
    stored = load_from_duckdb(art_id, session_id=EARLIER)
    assert type(stored) is container
    return art_id, stored


def _assert_same_frames(value, stored) -> None:
    """*value* holds the frames *stored* holds, in the same places: for a dict,
    under the same keys in the same order."""
    import pandas as pd
    from geopandas.testing import assert_geodataframe_equal

    if isinstance(stored, dict):
        assert list(value) == list(stored) == ["roads", "blocks"]
        value, stored = list(value.values()), list(stored.values())
    assert len(value) == len(stored) == 2
    assert_geodataframe_equal(value[0], stored[0])
    assert getattr(value[0], "metadata", None) == {"name": "roads", "layerType": "roads"}
    pd.testing.assert_frame_equal(value[1], stored[1])


def _strip_the_container(bundle: Path) -> None:
    """What a ``bundle.json`` written before bundles recorded their container
    says: the same, with no ``container``."""
    spec = json.loads(bundle.read_text(encoding="utf-8"))
    spec.pop("container", None)
    bundle.write_text(json.dumps(spec), encoding="utf-8")


CONTAINERS = pytest.mark.parametrize("container", [list, dict], ids=["list", "dict"])


@CONTAINERS
def test_load_artifact_gives_the_list_or_the_dict_after_a_reopen(client, user_and_token, container):
    from utk_curio.sandbox.util.parsers import load_artifact

    user, token = user_and_token
    art_id, stored = _write_frames(container)
    project_id = _save_and_reopen(client, token, _output(FRAMES_NODE, art_id, container.__name__))

    value = load_artifact(art_id, session_id=LATER, saved_paths=_saved(user, project_id, art_id))

    assert type(value) is container, f"read a {type(value).__name__}"
    _assert_same_frames(value, stored)


def test_get_serves_the_list_after_a_reopen(client, user_and_token):
    """``/get`` answers what it answered before the reopen."""
    user, token = user_and_token
    art_id, _stored = _write_frames(list)
    before = _sandbox().get("/get", query_string={"fileName": art_id, "sessionId": EARLIER})
    assert before.status_code == 200, before.get_data(as_text=True)
    project_id = _save_and_reopen(client, token, _output(FRAMES_NODE, art_id, "list"))

    after = _sandbox().get("/get", query_string={
        "fileName": art_id, "sessionId": LATER,
        "savedPath": _saved(user, project_id, art_id)[art_id]["path"],
    })

    assert after.status_code == 200, after.get_data(as_text=True)
    body = after.get_json()
    assert body["dataType"] == "list", body["dataType"]
    assert body == before.get_json()


def _answered_under_its_keys(stored: dict) -> dict:
    """What ``/get`` answers for the dict of frames *stored*: a ``dict``
    envelope holding, under each key, the envelope ``/get`` answers for that
    frame alone, which is the one a tuple or a list of frames carries for it."""
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    envelopes = {}
    for key, frame in stored.items():
        alone = save_to_duckdb(frame, node_id=FRAMES_NODE, session_id=EARLIER)
        response = _sandbox().get("/get", query_string={"fileName": alone, "sessionId": EARLIER})
        assert response.status_code == 200, response.get_data(as_text=True)
        envelope = response.get_json()
        assert envelope.pop("filename") == alone
        envelopes[key] = envelope
    return {"dataType": "dict", "data": envelopes}


@pytest.mark.parametrize("reopened", [False, True], ids=["in-the-session-that-wrote-it", "after-a-reopen"])
def test_get_serves_a_dict_of_frames_under_its_keys(client, user_and_token, reopened):
    """``/get`` answers a dict of frames as it answers a tuple or a list of
    them, each frame as the envelope it has alone, under its key: JSON cannot
    carry the frames themselves. The same in the session that wrote the dict
    and after a reopen under a new sign-in."""
    user, token = user_and_token
    art_id, stored = _write_frames(dict)
    expected = _answered_under_its_keys(stored)
    query = {"fileName": art_id, "sessionId": EARLIER}
    if reopened:
        project_id = _save_and_reopen(client, token, _output(FRAMES_NODE, art_id, "dict"))
        query = {
            "fileName": art_id, "sessionId": LATER,
            "savedPath": _saved(user, project_id, art_id)[art_id]["path"],
        }

    response = _sandbox().get("/get", query_string=query)

    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    body = response.get_json()
    assert body["dataType"] == "dict", body["dataType"]
    assert body.pop("filename") == art_id
    assert body == expected


#: What a node downstream does with its input, and what it returns.
USED_AS = {
    list: (
        "frames = input_0\n"
        "frames.append(frames[1].head(1))\n"
        "return [len(frame) for frame in frames]\n",
        [2, 3, 1],
    ),
    dict: (
        'return [list(input_0), len(input_0["roads"]), len(input_0["blocks"])]\n',
        [["roads", "blocks"], 2, 3],
    ),
}


@CONTAINERS
def test_a_python_node_downstream_uses_the_list_or_the_dict(client, user_and_token, container):
    """The node reading the output after the reopen appends to the list, or
    reads the dict by its keys (in process, as ``/exec`` runs it without
    isolation)."""
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    _worker_init()
    user, token = user_and_token
    art_id, _stored = _write_frames(container)
    project_id = _save_and_reopen(client, token, _output(FRAMES_NODE, art_id, container.__name__))
    code, returned = USED_AS[container]

    result = execute_code(
        textwrap.indent(code, "    "), art_id, "curio.builtin/computation-analysis", container.__name__,
        session_id=LATER, save_dataset=False, saved_paths=_saved(user, project_id, art_id),
    )

    assert result["stderr"] == "", result["stderr"]
    assert load_from_duckdb(result["output"]["path"]) == returned


@CONTAINERS
def test_an_isolated_node_gets_the_list_or_the_dict(client, user_and_token, tmp_path, container):
    """Staged for an isolated node and rebuilt as its child rebuilds an input."""
    from utk_curio.sandbox.isolation.child import rebuild_input
    from utk_curio.sandbox.util import staging

    user, token = user_and_token
    art_id, stored = _write_frames(container)
    project_id = _save_and_reopen(client, token, _output(FRAMES_NODE, art_id, container.__name__))
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    spec = staging.stage_input(art_id, scratch, session_id=LATER, saved_paths=_saved(user, project_id, art_id))
    value = rebuild_input(spec, str(scratch))

    assert type(value) is container, f"staged as {spec.get('kind')} {spec.get('container', '')}"
    _assert_same_frames(value, stored)


def test_a_saved_bundle_reads_as_its_dataset_holds_it_now(client, user_and_token):
    """A ``bundle.json`` written before bundles recorded their container has
    none, which reads as a tuple. Each read reads the dataset's own
    ``bundle.json``, so once a save writes it again with its container, the
    list comes back at the next read, with no copy to bring up to date."""
    from utk_curio.sandbox.util.parsers import load_artifact

    user, token = user_and_token
    art_id, stored = _write_frames(list)
    output = _output(FRAMES_NODE, art_id, "list")
    project_id = _save_and_reopen(client, token, output)
    saved = _saved(user, project_id, art_id)
    bundle = _bundle_json(user, project_id, FRAMES_NODE)
    as_installed = bundle.read_text(encoding="utf-8")
    _strip_the_container(bundle)
    assert type(load_artifact(art_id, session_id=LATER, saved_paths=saved)) is tuple
    bundle.write_text(as_installed, encoding="utf-8")

    value = load_artifact(art_id, session_id=LATER, saved_paths=saved)

    assert type(value) is list, f"read a {type(value).__name__}"
    _assert_same_frames(value, stored)


@pytest.mark.parametrize("damage", ["container", "key"], ids=["no-such-container", "a-part-without-its-key"])
def test_a_saved_bundle_that_names_no_container_it_can_be_is_a_missing_artifact(
    client, user_and_token, damage,
):
    """The saved file is read with no session check, so a ``bundle.json``
    that records a container a bundle cannot be, or a dict part without its
    key, reads as missing, as for an output that is nowhere, never as a
    tuple."""
    from utk_curio.sandbox.util.parsers import load_artifact

    user, token = user_and_token
    art_id, _stored = _write_frames(dict)
    project_id = _save_and_reopen(client, token, _output(FRAMES_NODE, art_id, "dict"))
    saved = _saved(user, project_id, art_id)
    bundle = _bundle_json(user, project_id, FRAMES_NODE)
    spec = json.loads(bundle.read_text(encoding="utf-8"))
    if damage == "container":
        spec["container"] = "set"
    else:
        spec["parts"][0].pop("key", None)
    bundle.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(KeyError, match="No artifact with id"):
        load_artifact(art_id, session_id=LATER, saved_paths=saved)
