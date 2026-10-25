"""A saved output is made once: the store's own file, linked into the Data Catalog.

A node's output is its artifact in the store, ``artifacts/<id>.parquet`` for a
table. A run with Save on used to encode the table a second time, as a file at
the top of the shared data directory that the install linked; an isolated run
copied the child's file there instead, without the ``.decode.json`` that says
which columns hold lists and dicts. Now the install links the store's file and
writes beside it the decode the store keeps in the artifact's row. A saved
table is one file, and its list and dict cells reload as lists and dicts
however the node ran.

Artifacts are written as node runs write them: through the real
``save_to_duckdb`` in process, and as an isolated child leaves its file in its
scratch directory for the parent to move into the store.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from utk_curio.backend.app.datasets.install.bundle import install_node_output
from utk_curio.backend.tests.test_datasets.computed_test_helpers import store_sandbox_artifact
from utk_curio.sandbox.util.catalog_helpers import listed_bundle_parts
from utk_curio.sandbox.util.parsers import load_saved_output

USER = "1"
DATAFLOW = "df-made-once"
NODE = "py-1"

TABLE = pd.DataFrame({
    "n": [1, 2],
    "tags": [["a", "b"], ["c"]],
    "props": [{"k": 1}, {"k": 2}],
})
TABLE_CODE = (
    "    return pd.DataFrame({'n': [1, 2], 'tags': [['a', 'b'], ['c']],"
    " 'props': [{'k': 1}, {'k': 2}]})\n"
)


def _shared() -> Path:
    return Path(os.environ["CURIO_SHARED_DATA"])


def _stored_file(art_id: str) -> Path:
    return _shared() / "artifacts" / f"{art_id}.parquet"


def _install(art_id: str, data_type: str):
    return install_node_output(
        USER,
        node_id=NODE,
        path_ref=art_id,
        data_type=data_type,
        node_name="Python Computation",
        dataflow_id=DATAFLOW,
        node_type="curio.builtin/computation-analysis",
    )


def _stored_by_an_isolated_child(code: str, tmp_path: Path) -> str:
    """The output of *code* as an isolated child leaves it: written in its
    scratch directory, validated by the parent and moved into the store, as
    ``runner._persist_output`` does."""
    import geopandas as gpd

    from utk_curio.sandbox.isolation import child, supervisor
    from utk_curio.sandbox.util import staging

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    request = {
        "code": code,
        "node_type": "curio.builtin/computation-analysis",
        "data_type": "",
        "scratch_dir": str(scratch),
        "input": {"kind": "none"},
        "dataset_paths": {},
        "session_imports": [],
        "limits": {},
    }
    manifest = child.run_node(request, lambda: {"__builtins__": __builtins__, "pd": pd, "gpd": gpd})
    assert manifest["ok"], manifest["stderr"]
    child.write_result(manifest, str(scratch))
    return staging.persist_output(supervisor.read_child_manifest(str(scratch))["output"])


@pytest.fixture(params=["in process", "in an isolated child"])
def stored_table(request, app, tmp_path):
    """The artifact id of TABLE, made as a node run makes it."""
    if request.param == "in process":
        return store_sandbox_artifact(TABLE)
    return _stored_by_an_isolated_child(TABLE_CODE, tmp_path)


def test_a_saved_table_is_the_stores_own_file(stored_table):
    result = _install(stored_table, "dataframe")

    assert result.manifest.data_file == f"data/{stored_table}.parquet"
    assert os.path.samefile(result.dest / result.manifest.data_file, _stored_file(stored_table))


def test_its_list_and_dict_cells_reload_as_lists_and_dicts(stored_table):
    """The decode the store keeps in the row is written beside the saved file."""
    result = _install(stored_table, "dataframe")
    data = result.dest / result.manifest.data_file

    decode = json.loads(data.with_name(data.name + ".decode.json").read_text(encoding="utf-8"))
    assert sorted(decode["encoded_object_columns"]) == ["props", "tags"]
    loaded = load_saved_output(data, stored_table)
    assert loaded["tags"].tolist() == [["a", "b"], ["c"]]
    assert loaded["props"].tolist() == [{"k": 1}, {"k": 2}]


def test_installing_it_again_writes_nothing(stored_table):
    first = _install(stored_table, "dataframe")
    data = first.dest / first.manifest.data_file
    decode = data.with_name(data.name + ".decode.json")
    held = (data.stat().st_ino, decode.stat().st_ino, decode.read_text(encoding="utf-8"))

    again = _install(stored_table, "dataframe")

    assert again.replaced is False
    assert (data.stat().st_ino, decode.stat().st_ino, decode.read_text(encoding="utf-8")) == held


def test_a_geo_table_keeps_its_layer_name(app):
    """A frame's ``metadata`` (its layer's name) is in the row too."""
    import geopandas as gpd
    from shapely.geometry import Point

    frame = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
    frame.metadata = {"name": "parcels"}
    art_id = store_sandbox_artifact(frame)

    result = _install(art_id, "geodataframe")

    loaded = load_saved_output(result.dest / result.manifest.data_file, art_id)
    assert isinstance(loaded, gpd.GeoDataFrame)
    assert getattr(loaded, "metadata", None) == {"name": "parcels"}


def test_a_tuples_tables_are_the_stores_own_files(app):
    parent = store_sandbox_artifact((TABLE, pd.DataFrame({"m": [3]})))

    result = _install(parent, "outputs")

    listed = listed_bundle_parts(result.dest / result.manifest.data_file)
    assert len(listed) == 2
    for entry, file in listed:
        assert os.path.samefile(file, _stored_file(entry["artifactId"])), entry
    first = load_saved_output(result.dest / result.manifest.data_file, parent)[0]
    assert first["tags"].tolist() == [["a", "b"], ["c"]]
