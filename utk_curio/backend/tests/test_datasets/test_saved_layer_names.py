"""A saved output reloads with its layers' names and types (#662).

A scenario dragged into another project brings its fixed context as data: the
context's saved output, copied into that project and read there by a Data
Loading node through ``curio_load_data``. An Autark node downstream finds its
layers by name (example 06 reads ``table_osm_roads``) and draws each as its
layer type, so a saved output must reload with both.

* An Autark data node's layers are saved as one JSON document, the wrapper the
  canvas builds (``layersToPoolWrapper``), with ``layerName`` and
  ``layerType`` on each layer.
* A Python node's frames carry theirs in ``metadata``. A tuple of frames is
  saved as a bundle, one parquet file per frame; a single frame as one parquet
  file. The metadata travels in each file's ``.decode.json`` sidecar.

Outputs are written by the real sandbox writers and read back by the real
``curio_load_data`` reader.
"""
from __future__ import annotations

import json

from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.bundle import install_node_output
from utk_curio.backend.tests.test_datasets.computed_test_helpers import store_sandbox_artifact

USER = "1"
DATAFLOW = "df-layer-names"


def _install(path_ref: str, data_type: str):
    return install_node_output(
        USER,
        node_id="layers",
        path_ref=path_ref,
        data_type=data_type,
        node_name="Layers",
        dataflow_id=DATAFLOW,
        node_type="curio.builtin/computation-analysis",
    )


def _reload(result):
    """What ``curio_load_data`` hands a Data Loading node for the dataset."""
    from utk_curio.sandbox.util.catalog_helpers import read_dataset

    dest = dataset_dir(USER, result.manifest.dir_name)
    return read_dataset(str(dest / result.manifest.data_file), result.manifest.format)


def _frame(name: str, layer_type: str, x: float):
    import geopandas as gpd
    from shapely.geometry import box

    frame = gpd.GeoDataFrame({"height": [10.0 + x]}, geometry=[box(x, 0, x + 1, 1)], crs="EPSG:4326")
    frame.metadata = {"name": name, "layerType": layer_type}
    return frame


def _feature_collection(x: float) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"height": 10.0 + x},
            "geometry": {"type": "Point", "coordinates": [x, 0.0]},
        }],
    }


def test_an_autark_data_nodes_layers_reload_with_their_names(app):
    """The wrapper an Autark data node hands on, saved and reloaded."""
    wrapper = {
        "dataType": "outputs",
        "data": [
            {"dataType": "geodataframe", "data": _feature_collection(0), "layerName": "table_osm_roads", "layerType": "roads"},
            {"dataType": "geodataframe", "data": _feature_collection(1), "layerName": "table_osm_buildings", "layerType": "buildings"},
        ],
    }
    result = _install(store_sandbox_artifact(wrapper), "dict")

    assert result.manifest.format == "json"
    reloaded = _reload(result)
    assert [(layer["layerName"], layer["layerType"]) for layer in reloaded["data"]] == [
        ("table_osm_roads", "roads"),
        ("table_osm_buildings", "buildings"),
    ]


def test_a_tuple_of_frames_reloads_with_each_frames_name_and_layer_type(app):
    roads, buildings = _frame("roads", "roads", 0), _frame("buildings", "buildings", 2)
    result = _install(store_sandbox_artifact((roads, buildings)), "outputs")

    assert result.manifest.format == "bundle"
    reloaded = _reload(result)
    assert [getattr(frame, "metadata", None) for frame in reloaded] == [
        {"name": "roads", "layerType": "roads"},
        {"name": "buildings", "layerType": "buildings"},
    ]
    assert list(reloaded[1]["height"]) == [12.0]


def test_a_bundle_lists_each_parts_layer(app):
    """The bundle's own record names each part's layer, so a reader that
    lists the parts (the catalog's preview) can say which is which."""
    roads, buildings = _frame("roads", "roads", 0), _frame("buildings", "buildings", 2)
    result = _install(store_sandbox_artifact((roads, buildings)), "outputs")

    dest = dataset_dir(USER, result.manifest.dir_name)
    spec = json.loads((dest / result.manifest.data_file).read_text(encoding="utf-8"))
    assert [(part["label"], part.get("layerName"), part.get("layerType")) for part in spec["parts"]] == [
        ("roads", "roads", "roads"),
        ("buildings", "buildings", "buildings"),
    ]


def test_a_single_frame_reloads_with_its_name_and_layer_type(app):
    from utk_curio.sandbox.util.parsers import save_dataset_parquet

    filename = save_dataset_parquet(_frame("parcels", "surface", 0), "geodataframe")
    result = _install(filename, "geodataframe")

    assert result.manifest.format == "parquet"
    assert _reload(result).metadata == {"name": "parcels", "layerType": "surface"}


def test_a_discovery_layer_type_is_kept_beside_the_frames_own_name(app):
    """A Discovery download names its layer type when it is loaded; that
    joins the name the frame was saved with instead of replacing it."""
    from utk_curio.sandbox.util.catalog_helpers import read_dataset
    from utk_curio.sandbox.util.parsers import save_dataset_parquet

    filename = save_dataset_parquet(_frame("parcels", "surface", 0), "geodataframe")
    result = _install(filename, "geodataframe")
    dest = dataset_dir(USER, result.manifest.dir_name)

    frame = read_dataset(str(dest / result.manifest.data_file), "parquet", layer_type="buildings")
    assert frame.metadata == {"name": "parcels", "layerType": "buildings"}
