"""Tests for the Dataset-node loader snippets (``loader_snippet``).

A "Dataset node" created by dropping a computed dataset onto the canvas is a
``DATA_LOADING`` code node whose code is generated from the catalog item's
loader snippet. For the Dataset node to be a drop-in replacement for the node
that produced the dataset, that generated code must reload the artifact with the
SAME type/schema the producer emitted:

* a computed GeoDataFrame (stored as GeoParquet) must reload as a GeoDataFrame —
  not a plain DataFrame with WKB geometry;
* a multi-output / tuple result (``format: bundle``) must reload as a tuple, so
  the sandbox re-detects the same ``outputs`` envelope.

These tests assert both the generated snippet shape and — by executing the
generated code against real files — that the reconstructed value matches the
original.
"""
from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.datasets.domain.catalog_item import loader_snippet


def _run_loader(snippet: dict):
    """Execute a loader snippet the way the sandbox would and return its result."""
    namespace: dict = {}
    code = "\n".join(snippet["imports"]) + "\n" + snippet["code"]
    exec(code, namespace)  # noqa: S102 — exercising generated loader code on purpose
    return namespace[snippet["returnVariable"]]


# --------------------------------------------------------------------------- #
# Snippet shape (unit)
# --------------------------------------------------------------------------- #

def test_parquet_snippet_prefers_geoparquet_with_fallback():
    snippet = loader_snippet("parquet", "/data/output.parquet")
    assert "import geopandas as gpd" in snippet["imports"]
    assert "import pandas as pd" in snippet["imports"]
    # Geo-aware read first, plain read as fallback.
    assert "gpd.read_parquet(dataset_path)" in snippet["code"]
    assert "pd.read_parquet(dataset_path)" in snippet["code"]
    assert snippet["code"].index("gpd.read_parquet") < snippet["code"].index("pd.read_parquet")
    assert snippet["returnVariable"] == "df"


def test_parquet_snippet_restores_object_columns_from_sidecar():
    snippet = loader_snippet("parquet", "/data/output.parquet")
    # Reads the decode sidecar and re-hydrates the encoded object columns.
    assert ".decode.json" in snippet["code"]
    assert "encoded_object_columns" in snippet["code"]
    assert "import os" in snippet["imports"]
    assert "import json" in snippet["imports"]


def test_bundle_snippet_shape():
    snippet = loader_snippet("bundle", "/data/computed.node_x@1/data/bundle.json")
    assert snippet["returnVariable"] == "bundle"
    assert snippet["pathVariable"] == "bundle_path"
    assert "import geopandas as gpd" in snippet["imports"]
    # Reads the manifest and returns a tuple of parts.
    assert "bundle.json" in snippet["code"]
    assert 'spec.get("parts", [])' in snippet["code"]
    assert "return tuple(items)" in snippet["code"]


@pytest.mark.parametrize(
    "fmt,expected_reader,return_var",
    [
        ("csv", "pd.read_csv(dataset_path)", "df"),
        ("geojson", "gpd.read_file(dataset_path)", "gdf"),
        ("shp", "gpd.read_file(dataset_path)", "gdf"),
        ("json", 'json.loads(_raw.decode("utf-8"))', "data"),
        ("geotiff", "rasterio.open(dataset_path)", "src"),
    ],
)
def test_non_parquet_snippets_unchanged(fmt, expected_reader, return_var):
    """The geo-parquet/bundle work must not regress the other format loaders."""
    snippet = loader_snippet(fmt, "/data/file")
    assert expected_reader in snippet["code"]
    assert snippet["returnVariable"] == return_var


def test_json_snippet_is_zlib_tolerant():
    """format: json covers both plain .json and zlib-compressed .json.zlib
    (computed dict/list outputs), so the loader must read binary and try
    decompressing first — never text-mode ``json.load(f)``."""
    snippet = loader_snippet("json", "/data/computed.node@1/data/out.json.zlib")
    assert "import zlib" in snippet["imports"]
    assert 'open(dataset_path, "rb")' in snippet["code"]
    assert "zlib.decompress(_raw)" in snippet["code"]
    assert "except zlib.error:" in snippet["code"]
    assert "json.load(f)" not in snippet["code"]


# --------------------------------------------------------------------------- #
# Functional reconstruction (data-level e2e of the generated loader)
# --------------------------------------------------------------------------- #

def test_parquet_loader_reloads_geodataframe_as_geodataframe(tmp_path):
    gpd = pytest.importorskip("geopandas")
    shapely = pytest.importorskip("shapely.geometry")

    original = gpd.GeoDataFrame(
        {"name": ["a", "b"]},
        geometry=[shapely.Point(1, 2), shapely.Point(3, 4)],
        crs="EPSG:4326",
    )
    path = tmp_path / "geo_output.parquet"
    original.to_parquet(path)  # GeoParquet — same as save_dataset_parquet for geo

    result = _run_loader(loader_snippet("parquet", str(path)))

    assert isinstance(result, gpd.GeoDataFrame), "geo dataset must reload as a GeoDataFrame"
    assert list(result["name"]) == ["a", "b"]
    assert result.geometry.iloc[0].x == 1
    assert result.crs is not None and result.crs.to_epsg() == 4326  # CRS preserved


def test_parquet_loader_reloads_plain_dataframe(tmp_path):
    pd = pytest.importorskip("pandas")

    path = tmp_path / "table.parquet"
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_parquet(path)

    result = _run_loader(loader_snippet("parquet", str(path)))

    assert isinstance(result, pd.DataFrame)
    assert not result.__class__.__name__ == "GeoDataFrame"
    assert list(result["a"]) == [1, 2]


def test_parquet_loader_restores_object_columns_via_sidecar(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    from utk_curio.sandbox.util import parsers

    # save_dataset_parquet writes the parquet + ``<file>.decode.json`` sidecar here.
    monkeypatch.setattr(parsers, "_shared_data_dir", lambda: tmp_path)
    filename = parsers.save_dataset_parquet(
        pd.DataFrame({"name": ["a", "b"], "payload": [{"x": 1}, ["y", "z"]]}),
        "dataframe",
    )
    assert filename is not None

    result = _run_loader(loader_snippet("parquet", str(tmp_path / filename)))

    # The generated loader decoded the JSON-encoded object column back to objects.
    assert result["payload"].tolist()[0] == {"x": 1}
    assert result["payload"].tolist()[1] == ["y", "z"]


def _write_bundle(tmp_path, parts):
    """Materialize a bundle dir (``data/bundle.json`` + ``data/parts/*``)."""
    dataset_dir = tmp_path / "computed.node_x@1"
    (dataset_dir / "data" / "parts").mkdir(parents=True)
    (dataset_dir / "data" / "bundle.json").write_text(
        json.dumps({"version": 1, "parts": parts}), encoding="utf-8"
    )
    return dataset_dir / "data" / "bundle.json"


def test_bundle_loader_rebuilds_tuple_of_parts(tmp_path):
    pd = pytest.importorskip("pandas")
    gpd = pytest.importorskip("geopandas")
    shapely = pytest.importorskip("shapely.geometry")

    parts_dir = tmp_path / "computed.node_x@1" / "data" / "parts"

    bundle_path = _write_bundle(
        tmp_path,
        parts=[
            {"index": 0, "label": "t", "kind": "dataframe", "format": "parquet",
             "file": "data/parts/00_dataframe.parquet"},
            {"index": 1, "label": "g", "kind": "geodataframe", "format": "parquet",
             "file": "data/parts/01_geodataframe.parquet"},
            {"index": 2, "label": "n", "kind": "int", "format": "json",
             "file": "data/parts/02_int.json"},
            {"index": 3, "label": "o", "kind": "dict", "format": "json",
             "file": "data/parts/03_dict.json"},
        ],
    )
    # Materialize each part exactly as install_computed_bundle_for_node does.
    pd.DataFrame({"a": [1, 2]}).to_parquet(parts_dir / "00_dataframe.parquet")
    gpd.GeoDataFrame(
        {"k": ["v"]}, geometry=[shapely.Point(5, 6)], crs="EPSG:4326"
    ).to_parquet(parts_dir / "01_geodataframe.parquet")
    (parts_dir / "02_int.json").write_text(json.dumps({"value": 5}), encoding="utf-8")
    (parts_dir / "03_dict.json").write_text(json.dumps({"k": "v"}), encoding="utf-8")

    result = _run_loader(loader_snippet("bundle", str(bundle_path)))

    # A tuple so the sandbox re-detects the same `outputs` envelope.
    assert isinstance(result, tuple)
    assert len(result) == 4
    assert isinstance(result[0], pd.DataFrame) and list(result[0]["a"]) == [1, 2]
    assert isinstance(result[1], gpd.GeoDataFrame) and result[1].geometry.iloc[0].x == 5
    assert result[2] == 5 and isinstance(result[2], int)  # scalar unwrapped from {"value": 5}
    assert result[3] == {"k": "v"}  # raw dict preserved


def test_bundle_loader_preserves_part_order(tmp_path):
    pytest.importorskip("pandas")
    parts_dir = tmp_path / "computed.node_x@1" / "data" / "parts"

    # Define parts out of order in the manifest; loader must sort by index.
    bundle_path = _write_bundle(
        tmp_path,
        parts=[
            {"index": 1, "label": "b", "kind": "int", "format": "json",
             "file": "data/parts/01_int.json"},
            {"index": 0, "label": "a", "kind": "int", "format": "json",
             "file": "data/parts/00_int.json"},
        ],
    )
    (parts_dir / "00_int.json").write_text(json.dumps({"value": 100}), encoding="utf-8")
    (parts_dir / "01_int.json").write_text(json.dumps({"value": 200}), encoding="utf-8")

    result = _run_loader(loader_snippet("bundle", str(bundle_path)))
    assert result == (100, 200)


@pytest.mark.parametrize(
    "container,expected",
    [("list", [100, 200]), ("dict", {"roads": 100, "blocks": 200})],
    ids=["list", "dict"],
)
def test_bundle_loader_rebuilds_the_container_bundle_json_records(tmp_path, container, expected):
    """A list or a dict of frames is saved as a bundle too: the loader gives
    back the list, or the dict keyed in index order, not a tuple."""
    parts_dir = tmp_path / "computed.node_x@1" / "data" / "parts"
    bundle_path = _write_bundle(
        tmp_path,
        parts=[
            {"index": 1, "key": "blocks", "label": "blocks", "kind": "int", "format": "json",
             "file": "data/parts/01_int.json"},
            {"index": 0, "key": "roads", "label": "roads", "kind": "int", "format": "json",
             "file": "data/parts/00_int.json"},
        ],
    )
    spec = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle_path.write_text(json.dumps({**spec, "container": container}), encoding="utf-8")
    (parts_dir / "00_int.json").write_text(json.dumps({"value": 100}), encoding="utf-8")
    (parts_dir / "01_int.json").write_text(json.dumps({"value": 200}), encoding="utf-8")

    result = _run_loader(loader_snippet("bundle", str(bundle_path)))

    assert type(result) is type(expected), f"read a {type(result).__name__}"
    assert result == expected
    assert list(result) == list(expected)


# --------------------------------------------------------------------------- #
# Portable id form: curio_load_data, curio_load_collection, curio_data_path
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "fmt,code",
    [
        ("csv", 'df = curio_load_data("imported.xabc123")'),
        ("parquet", 'df = curio_load_data("imported.xabc123")'),
        ("geojson", 'gdf = curio_load_data("imported.xabc123")'),
        ("shp", 'gdf = curio_load_data("imported.xabc123")'),
        ("json", 'data = curio_load_data("imported.xabc123")'),
        # A GeoTIFF's loader names its window, so the node shows the option.
        ("geotiff", 'src = curio_load_data("imported.xabc123", bounds=None)'),
        ("bundle", 'bundle = curio_load_data("imported.xabc123")'),
        ("collection", 'collection = curio_load_collection("imported.xabc123")'),
        ("osm", 'dataset_path = curio_data_path("imported.xabc123")'),
    ],
)
def test_snippet_uses_id_call_when_id_given(fmt, code):
    """With a dataset id the loader is one portable call the sandbox resolves and
    reads by format; the generated code carries no machine-specific path and
    imports nothing. A format nothing reads gets the file's path instead."""
    snippet = loader_snippet(fmt, "C:/Users/someone/.curio/users/3/datasets/x@1/data/f", dataset_id="imported.xabc123")
    assert snippet["code"] == code
    assert "C:/Users" not in snippet["code"]
    assert snippet["imports"] == []


def test_id_call_reads_through_the_sandbox_helpers(tmp_path):
    """The id-form snippet executes against the helpers the sandbox injects,
    and reads the dataset by its format."""
    pd = pytest.importorskip("pandas")
    from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers

    path = tmp_path / "table.parquet"
    pd.DataFrame({"a": [1, 2]}).to_parquet(path)

    snippet = loader_snippet("parquet", None, dataset_id="imported.xabc123")
    namespace: dict = {}
    install_catalog_helpers(
        namespace, data_path={"imported.xabc123": str(path)}.__getitem__,
        formats={"imported.xabc123": {"format": "parquet"}}, collections=None, media_dir=None, models=None,
    )
    exec(snippet["code"], namespace)  # noqa: S102 — exercising generated loader code on purpose
    assert list(namespace[snippet["returnVariable"]]["a"]) == [1, 2]


@pytest.mark.parametrize(
    "bad_id",
    [
        None,
        "",
        'imported."); import os #',  # quote breaks out of the string literal
        "back\\slash",
        "-leading-hyphen",
        "x" * 201,
    ],
)
def test_unsafe_or_missing_id_falls_back_to_literal_path(bad_id):
    """Ids can come from user-editable spec JSON; anything outside the whitelist
    must never be interpolated into generated Python source."""
    snippet = loader_snippet("csv", "/data/file.csv", dataset_id=bad_id)
    assert "curio_" not in snippet["code"]
    assert 'dataset_path = "/data/file.csv"' in snippet["code"]

def test_json_loader_reads_plain_json(tmp_path):
    """The zlib tolerance must not regress user-imported plain .json files."""
    doc = {"name": "café", "values": [1, 2, 3]}
    path = tmp_path / "imported.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    assert _run_loader(loader_snippet("json", str(path))) == doc


def test_json_loader_reads_zlib_compressed_json(tmp_path):
    """Regression: an autk-grammar computed dataset is a zlib-compressed pool
    wrapper (``.json.zlib``) with ``format: json``; the generated loader must
    decompress it and return the same dict the producing node emitted."""
    import zlib

    doc = {
        "dataType": "outputs",
        "data": [{"dataType": "geodataframe", "data": {"type": "FeatureCollection", "features": []}}],
    }
    path = tmp_path / "1786466491428_32e01db8.json.zlib"
    # Persisted exactly as save_to_duckdb's dict branch writes it.
    path.write_bytes(zlib.compress(json.dumps(doc, ensure_ascii=False).encode("utf-8")))

    assert _run_loader(loader_snippet("json", str(path))) == doc


# --------------------------------------------------------------------------- #
# A Discovery download's Autark layer
# --------------------------------------------------------------------------- #

_DISCOVERY_OSM = {"sourceId": "source.osm.openstreetmap@1", "resourceId": "buildings"}


def _catalog_item(**overrides):
    from utk_curio.backend.app.datasets.domain.catalog_item import base_item

    return base_item(**{
        "id": "imported.osm-buildings@1",
        "format": "geojson",
        "path": "/tmp/osm_buildings.geojson",
        "layerName": "buildings",
        "discoverySource": _DISCOVERY_OSM,
        **overrides,
    })


def test_a_discovery_layer_loader_names_its_autark_layer():
    """An Autark node draws the frame as the layer it is: an OpenStreetMap
    Buildings download extrudes. The loader is one ``curio_load_data`` call
    (the frontend's twin writes the same, datasetLoaderSnippets.test.ts); the
    layer travels to the sandbox with the dataset's format."""
    from utk_curio.backend.app.datasets.domain.catalog_item import execution_format

    item = _catalog_item()
    assert item["loaderSnippet"]["code"] == 'gdf = curio_load_data("imported.osm-buildings@1")'
    assert item["loaderSnippet"]["returnVariable"] == "gdf"
    assert execution_format(item) == {"format": "geojson", "layerType": "buildings"}


@pytest.mark.parametrize("overrides", [
    # A GeoPackage layer (or any hand import) may be called "buildings".
    {"discoverySource": None},
    # A Discovery layer that is not one of Autark's.
    {"layerName": "map-features"},
    {"layerName": None},
])
def test_only_a_discovery_download_of_an_autark_layer_is_typed(overrides):
    from utk_curio.backend.app.datasets.domain.catalog_item import execution_format

    assert "layerType" not in execution_format(_catalog_item(**overrides))


def test_curio_load_data_names_the_layer_it_was_sent(tmp_path):
    """The sandbox half: a dataset sent with a layerType loads as a frame naming it."""
    import warnings

    from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers

    path = tmp_path / "osm_buildings.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        "properties": {"building": "yes"},
    }]}), encoding="utf-8")
    namespace: dict = {}
    install_catalog_helpers(
        namespace, data_path={"imported.osm-buildings@1": str(path)}.__getitem__,
        formats={"imported.osm-buildings@1": {"format": "geojson", "layerType": "buildings"}},
        collections=None, media_dir=None, models=None,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gdf = namespace["curio_load_data"]("imported.osm-buildings@1")
    assert gdf.metadata == {"layerType": "buildings"}


def test_the_typed_loader_returns_a_geodataframe_naming_its_layer(tmp_path):
    import warnings

    path = tmp_path / "osm_buildings.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        "properties": {"building": "yes", "height": 12.0},
    }]}), encoding="utf-8")
    snippet = loader_snippet("geojson", str(path), layer_type="buildings")
    # pandas warns on a new attribute; the sandbox runs node code with warnings off.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gdf = _run_loader(snippet)
    assert len(gdf) == 1 and gdf.metadata == {"layerType": "buildings"}
