"""``curio_load_data("<layer group id>")``: a layer group, as a dict of its layers.

An OSM ``.pbf`` or a GeoPackage of several layers is imported as a layer group
whose layers are datasets of their own. The backend sends a run that names the
group's id each layer's path and format, and an entry for the group naming its
layers in order (``{"format": "layer-group", "layers": [[name, id], ...]}``).
The group loads as ``{layer name: frame}``, each layer read as
``curio_load_data`` reads it on its own, in process, through ``/exec`` and in
the isolated child, which reads the staged copies.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

GROUP = "gpkg.x1a2b3c4"
#: The group's layers, in its order: a layer downloaded as an Autark layer, a
#: GeoParquet one and a table with no geometry.
LAYERS = [("points", "imported.xpoints"), ("roads", "imported.xroads"), ("lookup", "imported.xlookup")]
FORMATS = {
    GROUP: {"format": "layer-group", "layers": [[name, dataset_id] for name, dataset_id in LAYERS]},
    "imported.xpoints": {"format": "geojson", "layerType": "points"},
    "imported.xroads": {"format": "parquet"},
    "imported.xlookup": {"format": "parquet"},
}
NODE = "PYTHON_COMPUTATION"


def _layer_files(folder) -> dict:
    """The group's layer files under *folder*, ``{dataset id: path}``."""
    import geopandas as gpd
    from shapely.geometry import LineString

    points = folder / "points.geojson"
    points.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "a"}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
        {"type": "Feature", "properties": {"name": "b"}, "geometry": {"type": "Point", "coordinates": [1, 1]}},
    ]}), encoding="utf-8")
    roads = folder / "roads.parquet"
    gpd.GeoDataFrame({"road": ["main"]}, geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:4326").to_parquet(roads)
    lookup = folder / "lookup.parquet"
    pd.DataFrame({"code": ["a", "b"], "label": ["Alpha", "Beta"]}).to_parquet(lookup)
    return {"imported.xpoints": str(points), "imported.xroads": str(roads), "imported.xlookup": str(lookup)}


def _load(paths):
    """The node's ``curio_load_data``, over *paths* and :data:`FORMATS`."""
    from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers

    def data_path(dataset_id):
        if dataset_id not in paths:
            raise RuntimeError(f"Dataset '{dataset_id}' is not available in this environment")
        return paths[dataset_id]

    namespace: dict = {}
    install_catalog_helpers(
        namespace, data_path=data_path, formats=FORMATS, collections=None, media_dir=None, models=None,
    )
    return namespace["curio_load_data"]


def _assert_the_groups_layers(layers):
    import geopandas as gpd

    assert list(layers) == [name for name, _id in LAYERS]
    assert isinstance(layers["points"], gpd.GeoDataFrame) and list(layers["points"]["name"]) == ["a", "b"]
    assert isinstance(layers["roads"], gpd.GeoDataFrame) and layers["roads"].crs.to_epsg() == 4326
    assert type(layers["lookup"]) is pd.DataFrame and list(layers["lookup"]["code"]) == ["a", "b"]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A throwaway artifact store, as ``test_isolation_staging.py`` makes one."""
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    release_connection()
    init_db()
    yield tmp_path
    release_connection()


def test_a_group_is_a_dict_of_its_layers_each_read_as_on_its_own(tmp_path):
    load = _load(_layer_files(tmp_path))

    layers = load(GROUP)

    _assert_the_groups_layers(layers)
    # Each layer is the value curio_load_data gives for its own id: the
    # downloaded layer keeps its Autark layer.
    assert layers["points"].metadata == {"layerType": "points"}
    for name, dataset_id in LAYERS:
        alone = load(dataset_id)
        assert type(layers[name]) is type(alone) and layers[name].to_json() == alone.to_json(), name


def test_bounds_and_part_are_refused_on_a_group(tmp_path):
    load = _load(_layer_files(tmp_path))

    with pytest.raises(ValueError) as bounds:
        load(GROUP, bounds=(0, 0, 1, 1))
    with pytest.raises(ValueError) as part:
        load(GROUP, part="roads")

    assert str(bounds.value) == (
        f'bounds read a window of a raster, and {GROUP} is a layer group: '
        f'load it without bounds, curio_load_data("{GROUP}").'
    )
    assert str(part.value) == (
        f'part names one file of a dataset of several, and {GROUP} is a layer group: '
        f'load it without part, curio_load_data("{GROUP}"), which gives its layers by name.'
    )


def test_an_in_process_node_hands_on_a_group(workspace):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    _worker_init()
    paths = _layer_files(workspace)

    result = execute_code(
        f'    return curio_load_data("{GROUP}")\n', "", NODE, "",
        save_dataset=False, dataset_paths=paths, dataset_formats=FORMATS,
    )

    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "dict"
    _assert_the_groups_layers(load_from_duckdb(result["output"]["path"]))


def _exec(code, paths, formats):
    from utk_curio.sandbox.app import app
    from utk_curio.sandbox.app.worker import _worker_init

    _worker_init()
    response = app.test_client().post("/exec", json={
        "code": code, "file_path": "", "nodeType": NODE, "dataType": "",
        "session_id": None, "save_dataset": False,
        "dataset_paths": paths, "dataset_formats": formats,
    })
    assert response.status_code == 200
    return response.get_json()


def test_the_exec_route_keeps_a_groups_entry(workspace):
    """``/exec`` reshapes what the backend sends: a group's entry has no path
    of its own, and is kept with its layers."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    data = _exec(
        f'    return ",".join(curio_load_data("{GROUP}"))\n', _layer_files(workspace), FORMATS,
    )

    assert data["stderr"] == "", data["stderr"]
    assert load_from_duckdb(data["output"]["path"]) == "points,roads,lookup"


def test_a_group_of_more_layers_than_a_run_names_datasets_loads_whole(workspace):
    """A run reads at most 32 datasets its code names, and every layer of a
    group among them: a GeoPackage of 40 layers loads all 40."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    paths, layers = {}, []
    for index in range(40):
        path = workspace / f"layer_{index}.csv"
        path.write_text(f"n\n{index}\n", encoding="utf-8")
        paths[f"imported.xlayer{index:02d}"] = str(path)
        layers.append([f"layer {index}", f"imported.xlayer{index:02d}"])
    formats = {
        "gpkg.xbig": {"format": "layer-group", "layers": layers},
        **{dataset_id: {"format": "csv"} for dataset_id in paths},
    }

    data = _exec(
        '    layers = curio_load_data("gpkg.xbig")\n'
        '    return [int(frame["n"].iloc[0]) for frame in layers.values()]\n',
        paths, formats,
    )

    assert data["stderr"] == "", data["stderr"]
    assert load_from_duckdb(data["output"]["path"]) == list(range(40))


def _isolated(code, scratch, paths):
    from utk_curio.sandbox.isolation import child
    from utk_curio.sandbox.util import staging

    return child.run_node({
        "code": code, "node_type": "curio.builtin/computation-analysis", "data_type": "",
        "scratch_dir": str(scratch), "input": {"kind": "none"},
        "dataset_paths": staging.stage_dataset_paths(paths, scratch), "dataset_formats": FORMATS,
        "session_imports": [], "limits": {},
    }, lambda: {"pd": pd})


def test_an_isolated_node_loads_a_group_from_its_staged_layers(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    result = _isolated(
        f'    layers = curio_load_data("{GROUP}")\n'
        '    return ",".join(f"{name}:{type(frame).__name__}" for name, frame in layers.items())\n',
        scratch, _layer_files(tmp_path),
    )

    assert result["ok"], result["stderr"]
    assert result["output"]["value"] == "points:GeoDataFrame,roads:GeoDataFrame,lookup:DataFrame"


def test_an_isolated_node_hands_on_a_group(workspace):
    """The isolated child hands on the dict as the in-process worker stores
    it: each layer an artifact of its own, under its name."""
    from utk_curio.sandbox.isolation import child, supervisor
    from utk_curio.sandbox.util import staging
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    scratch = workspace / "scratch"
    scratch.mkdir()
    result = _isolated(f'    return curio_load_data("{GROUP}")\n', scratch, _layer_files(workspace))
    assert result["ok"], result["stderr"]

    child.write_result(result, scratch)
    manifest = supervisor.read_child_manifest(scratch)
    stored = staging.persist_output(manifest["output"])

    assert manifest["output"]["kind"] == "dict"
    _assert_the_groups_layers(load_from_duckdb(stored))
