"""A Data Export node's file: what ``curio_export`` writes, where a run keeps
it, and what ``/output-file`` serves.

``curio_export(data, name)`` writes a table as CSV, a GeoDataFrame as GeoJSON,
a raster as GeoTIFF and anything else as JSON, under a name that ends in its
format's extension, and returns that name, which is the node's output. A tuple,
list or dict that holds a table or a raster, a bundle's parts, is one zip: a
file per part named after its label, and ``bundle.json``. ``part=`` writes one
part, named by its label, its key or its position. No frame is ever written as
its text. The file
goes in the folder of the run (``util/output_files.py``): in process the run
writes there itself, and an isolated child writes into its scratch directory,
from which the parent keeps the one file the output names. ``/output-file``
serves that file by the output's artifact id, to a session that may read the
output, and only from inside the folder of the run that made it. The store's
sweeps take a run's folder with its output.

The modules this exercises are imported inside each test, so a checkout
without them fails each test on its own.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

EXPORT_TYPE = "curio.builtin/data-export@1"
TREES = pd.DataFrame({"tree": ["oak", "elm"], "height": [10, 12]})
TREES_CSV = "tree,height\noak,10\nelm,12\n"

#: A one-band GeoTIFF's mosaic, as a node that returns
#: ``rasterio.open(curio_output_file("mosaic.vrt"))`` holds one.
MOSAIC_VRT = """<VRTDataset rasterXSize="4" rasterYSize="3">
  <SRS>EPSG:32616</SRS>
  <GeoTransform>440000, 30, 0, 4640000, 0, -30</GeoTransform>
  <VRTRasterBand dataType="Float32" band="1">
    <NoDataValue>-1</NoDataValue>
    <SimpleSource>
      <SourceFilename relativeToVRT="1">heights.tif</SourceFilename>
      <SourceBand>1</SourceBand>
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>
"""

DAY_MS = 24 * 3600 * 1000
#: The sweep's time: an hour ahead, so a file made now is older than it unless
#: its own time is set past it (``test_store_sweep.py``).
CUTOFF = int(time.time() * 1000) + 3600 * 1000
OLD = CUTOFF - DAY_MS
NEW = CUTOFF + DAY_MS


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A sandbox store of the test's own, in *tmp_path*."""
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", "./.curio/data/")
    data = tmp_path / ".curio" / "data"
    data.mkdir(parents=True)
    release_connection()
    init_db()
    yield data
    release_connection()


@pytest.fixture()
def client(store):
    from utk_curio.sandbox.app import app

    return app.test_client()


def _geotiff(path: Path) -> Path:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(
        path, "w", driver="GTiff", width=4, height=3, count=1, dtype="float32",
        crs="EPSG:32616", transform=from_origin(440000, 4640000, 30, 30), nodata=-1,
    ) as raster:
        raster.write(np.arange(12, dtype="float32").reshape(3, 4), 1)
    return path


def _exported(tmp_path: Path, data, name) -> Path:
    """The file ``curio_export(data, name)`` writes, in a folder standing in
    for the run's (what ``curio_output_file`` gives)."""
    from utk_curio.sandbox.util.exports import export

    folder = tmp_path / "run"
    folder.mkdir(exist_ok=True)
    return folder / export(data, name, lambda file_name: str(folder / file_name))


# -- what curio_export writes ------------------------------------------------

def test_a_table_is_written_as_csv_and_an_index_of_its_own_is_a_column(tmp_path):
    path = _exported(tmp_path, TREES, "trees")
    assert path.name == "trees.csv"
    assert path.read_text(encoding="utf-8") == TREES_CSV

    path = _exported(tmp_path, TREES.set_index("tree"), "by_tree")
    assert path.read_text(encoding="utf-8") == TREES_CSV


def test_a_geodataframe_is_written_as_geojson_in_its_own_crs(tmp_path):
    import geopandas as gpd
    from shapely.geometry import Point

    stations = gpd.GeoDataFrame(
        {"name": ["Clark/Lake", "Grand"]},
        geometry=[Point(447000, 4637000), Point(447500, 4637800)], crs="EPSG:32616",
    )
    path = _exported(tmp_path, stations, "stations")

    assert path.name == "stations.geojson"
    assert json.loads(path.read_text(encoding="utf-8"))["type"] == "FeatureCollection"
    read = gpd.read_file(path)
    assert read.crs.to_epsg() == 32616
    assert list(read["name"]) == ["Clark/Lake", "Grand"]
    assert [(point.x, point.y) for point in read.geometry] == [(447000, 4637000), (447500, 4637800)]


def test_a_geotiff_is_the_file_itself(tmp_path):
    import rasterio

    source = _geotiff(tmp_path / "heights.tif")
    with rasterio.open(source) as raster:
        path = _exported(tmp_path, raster, "")

    assert path.name == "data_export.tif"
    assert path.read_bytes() == source.read_bytes()


def test_any_other_raster_is_written_out_as_a_geotiff(tmp_path):
    import numpy as np
    import rasterio

    source = _geotiff(tmp_path / "heights.tif")
    (tmp_path / "mosaic.vrt").write_text(MOSAIC_VRT, encoding="utf-8")
    with rasterio.open(tmp_path / "mosaic.vrt") as mosaic:
        assert mosaic.driver == "VRT"
        path = _exported(tmp_path, mosaic, "mosaic")

    assert path.name == "mosaic.tif"
    with rasterio.open(path) as written, rasterio.open(source) as original:
        assert written.driver == "GTiff"
        assert (written.crs, written.transform, written.nodata) == (original.crs, original.transform, -1)
        np.testing.assert_array_equal(written.read(1), original.read(1))


def test_anything_else_is_written_as_json(tmp_path):
    import numpy as np

    summary = {"count": np.int64(3), "mean": np.float64(2.5), "names": ["Árvore", "oak"], "missing": None}
    path = _exported(tmp_path, summary, "summary")
    assert path.name == "summary.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "count": 3, "mean": 2.5, "names": ["Árvore", "oak"], "missing": None,
    }

    assert _exported(tmp_path, [1, 2], None).name == "data_export.json"
    assert json.loads(_exported(tmp_path, 42, "answer").read_text(encoding="utf-8")) == 42


def _data(kind):
    import geopandas as gpd
    from shapely.geometry import Point

    return {
        "table": TREES,
        "geodataframe": gpd.GeoDataFrame({"a": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326"),
        "dict": {"a": 1},
    }[kind]


@pytest.mark.parametrize("name, kind, file_name", [
    ("", "table", "data_export.csv"),
    (None, "dict", "data_export.json"),
    ("trees", "table", "trees.csv"),
    ("trees.csv", "table", "trees.csv"),
    ("trees.CSV", "table", "trees.CSV"),
    ("trees.json", "geodataframe", "trees.json"),
    # Another data format's extension gives way to the format's own.
    ("trees.csv", "geodataframe", "trees.geojson"),
    ("trees.geojson", "table", "trees.csv"),
    ("trees.parquet", "dict", "trees.json"),
    # Any other ending is part of the name.
    ("trees.v2", "table", "trees.v2.csv"),
    # One plain name: no folders, accents, spaces or hidden files.
    ("../../etc/passwd", "table", "etc_passwd.csv"),
    ("Árvores de 2024", "table", "Arvores_de_2024.csv"),
    (".hidden", "table", "hidden.csv"),
])
def test_the_files_name_ends_in_its_formats_extension(name, kind, file_name):
    from utk_curio.sandbox.util.exports import export_name

    assert export_name(name, _data(kind)) == file_name


def test_a_long_name_is_cut_to_what_curio_output_file_takes_keeping_its_extension():
    from utk_curio.sandbox.util.exports import MAX_NAME_CHARS, export_name

    name = export_name("x" * 300 + ".csv", TREES)
    assert len(name) == MAX_NAME_CHARS == 128
    assert name.endswith("x.csv")


# -- several values: one zip -------------------------------------------------

def _stations():
    import geopandas as gpd
    from shapely.geometry import Point

    return gpd.GeoDataFrame(
        {"name": ["Clark/Lake", "Grand"]},
        geometry=[Point(447000, 4637000), Point(447500, 4637800)], crs="EPSG:32616",
    )


def _labelled(frame, label):
    """*frame* as a bundle's part reads: its label in ``metadata["partLabel"]``."""
    frame.__dict__["metadata"] = {**(frame.__dict__.get("metadata") or {}), "partLabel": label}
    return frame


def _zip(path: Path) -> tuple[list[str], dict]:
    """The members of the zip at *path*, in their order, and its bundle.json."""
    import zipfile

    with zipfile.ZipFile(path) as archive:
        return archive.namelist(), json.loads(archive.read("bundle.json"))


def _unzipped(path: Path, folder: Path) -> Path:
    import zipfile

    with zipfile.ZipFile(path) as archive:
        archive.extractall(folder)
    return folder


def test_a_tuple_of_a_table_a_geo_table_a_raster_and_a_number_is_one_zip(tmp_path):
    import geopandas as gpd
    import rasterio
    import zipfile

    source = _geotiff(tmp_path / "heights.tif")
    with rasterio.open(source) as raster:
        path = _exported(tmp_path, (TREES, _stations(), raster, 42), "layers")

    assert path.name == "layers.zip"
    names, spec = _zip(path)
    assert names == ["Table_part_1.csv", "Geo_table_part_2.geojson", "Raster_part_3.tif", "bundle.json"]
    assert spec == {
        "version": 1,
        "container": "tuple",
        "parts": [
            {"index": 0, "label": "Table · part 1", "kind": "dataframe", "file": "Table_part_1.csv"},
            {"index": 1, "label": "Geo table · part 2", "kind": "geodataframe", "file": "Geo_table_part_2.geojson"},
            {"index": 2, "label": "Raster · part 3", "kind": "raster", "file": "Raster_part_3.tif"},
            {"index": 3, "label": "Number · part 4", "kind": "int", "value": 42},
        ],
    }
    out = _unzipped(path, tmp_path / "out")
    assert (out / "Table_part_1.csv").read_text(encoding="utf-8") == TREES_CSV
    stations = gpd.read_file(out / "Geo_table_part_2.geojson")
    assert stations.crs.to_epsg() == 32616 and list(stations["name"]) == ["Clark/Lake", "Grand"]
    assert (out / "Raster_part_3.tif").read_bytes() == source.read_bytes()
    # Every member carries one date, so the same parts make the same file.
    with zipfile.ZipFile(path) as archive:
        assert {info.date_time for info in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    assert sorted(p.name for p in path.parent.iterdir()) == ["layers.zip"]


def test_a_dicts_keys_name_its_parts_and_their_files(tmp_path):
    path = _exported(tmp_path, {"trees": TREES, "stations": _stations(), "count": 2}, "")

    assert path.name == "data_export.zip"
    names, spec = _zip(path)
    assert names == ["trees.csv", "stations.geojson", "bundle.json"]
    assert spec["container"] == "dict"
    assert spec["parts"] == [
        {"index": 0, "key": "trees", "label": "trees", "kind": "dataframe", "file": "trees.csv"},
        {"index": 1, "key": "stations", "label": "stations", "kind": "geodataframe", "file": "stations.geojson"},
        {"index": 2, "key": "count", "label": "count", "kind": "int", "value": 2},
    ]


def test_a_parts_label_is_the_bundles_then_its_key_then_its_frames_name():
    from utk_curio.sandbox.util.bundle_zip import parts_of

    named = _stations()
    named.__dict__["metadata"] = {"name": "table_stations", "layerType": "points"}
    container, parts = parts_of({
        "labelled": _labelled(TREES.copy(), "Trees (OpenStreetMap)"),
        "keyed": named,
    })
    assert container == "dict"
    assert [(part.key, part.label) for part in parts] == [("labelled", "Trees (OpenStreetMap)"), ("keyed", "keyed")]
    container, parts = parts_of((named, 1.5))
    assert container == "tuple"
    assert [(part.key, part.label) for part in parts] == [(None, "table_stations"), (None, "Number · part 2")]


def test_labels_that_clash_or_hold_odd_characters_give_plain_distinct_names(tmp_path):
    labels = [
        "Trees (OpenStreetMap)", "trees: OpenStreetMap", "../../etc/passwd",
        "Árvores de 2024", "???", ".hidden",
    ]
    path = _exported(tmp_path, [_labelled(TREES.copy(), label) for label in labels], "odd")

    names, spec = _zip(path)
    assert names == [
        "Trees_OpenStreetMap.csv", "trees_OpenStreetMap_2.csv", "etc_passwd.csv",
        "Arvores_de_2024.csv", "part_5.csv", "hidden.csv", "bundle.json",
    ]
    assert spec["container"] == "list"
    assert [part["label"] for part in spec["parts"]] == labels
    assert sorted(p.name for p in _unzipped(path, tmp_path / "out").iterdir()) == sorted(names)


def _exported_part(tmp_path: Path, data, part, name="pick") -> Path:
    from utk_curio.sandbox.util.exports import export

    folder = tmp_path / "run"
    folder.mkdir(exist_ok=True)
    return folder / export(data, name, lambda file_name: str(folder / file_name), part)


def test_part_writes_the_one_part_it_names_by_label_key_or_position(tmp_path):
    layers = (_labelled(TREES.copy(), "Trees"), _labelled(_stations(), "Stations"))

    by_label = _exported_part(tmp_path, layers, "Stations")
    assert by_label.name == "pick.geojson"
    assert json.loads(by_label.read_text(encoding="utf-8"))["type"] == "FeatureCollection"
    assert _exported_part(tmp_path, layers, 0).read_text(encoding="utf-8") == TREES_CSV
    # A position as the Part widget gives it, as text.
    assert _exported_part(tmp_path, layers, "1").name == "pick.geojson"
    keyed = {"k": _labelled(TREES.copy(), "Trees"), "count": 3}
    assert _exported_part(tmp_path, keyed, "k").read_text(encoding="utf-8") == TREES_CSV
    assert _exported_part(tmp_path, keyed, "Trees").read_text(encoding="utf-8") == TREES_CSV
    assert json.loads(_exported_part(tmp_path, keyed, "count").read_text(encoding="utf-8")) == 3
    # An empty Part, as the widget is when it is left empty: every part.
    assert _exported_part(tmp_path, layers, "").name == "pick.zip"


def test_part_on_one_value_or_a_part_that_is_not_there_is_refused(tmp_path):
    import re

    with pytest.raises(ValueError, match="part names one part of a tuple, list or dict, and the data is a pandas DataFrame"):
        _exported_part(tmp_path, TREES, "Trees")
    layers = (_labelled(TREES.copy(), "Trees"), _labelled(_stations(), "Stations"))
    for part in ("Roads", 2, "-1"):
        with pytest.raises(ValueError, match=re.escape(
            f"the data has no part {part!r}: its parts are 'Trees' and 'Stations', or 0 to 1 by position"
        )):
            _exported_part(tmp_path, layers, part)


def test_a_frame_inside_a_part_is_refused_and_no_frame_is_ever_written_as_text(tmp_path):
    import re

    from utk_curio.sandbox.util.exports import export

    folder = tmp_path / "run"
    folder.mkdir()

    def output_file(file_name):
        return str(folder / file_name)

    with pytest.raises(ValueError, match=re.escape(
        "the part 'Array · part 2' holds a pandas DataFrame: make each table or raster a part of its own"
    )):
        export((TREES, [TREES, 1]), "nested", output_file)
    # No part is a frame here, and still no frame or data object becomes text.
    with pytest.raises(TypeError, match="the data holds a pandas DataFrame"):
        export([[TREES]], "deeper", output_file)
    with pytest.raises(TypeError, match="the data holds a pandas Series"):
        export({"heights": pd.Series([10, 12])}, "series", output_file)
    assert list(folder.iterdir()) == []


# -- where a run keeps it ------------------------------------------------------

def test_a_run_in_process_writes_the_file_in_its_own_folder_and_the_route_serves_it(client):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util import output_files

    _worker_init()
    result = execute_code(
        "    import pandas as pd\n"
        "    return curio_export(pd.DataFrame({'tree': ['oak', 'elm'], 'height': [10, 12]}), 'trees')\n",
        "", EXPORT_TYPE, "", session_id="alice", save_dataset=False,
    )

    art_id = result["output"]["path"]
    assert art_id and result["output"]["dataType"] == "str", result["stderr"]
    written = output_files.run_output_dir(art_id) / "trees.csv"
    assert written.read_text(encoding="utf-8") == TREES_CSV
    assert output_files.named_file(art_id, "alice") == written.resolve()

    response = client.get("/output-file", query_string={"fileName": art_id, "sessionId": "alice"})
    try:
        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.headers["Content-Disposition"] == "attachment; filename=trees.csv"
        assert response.mimetype == "text/csv"
        assert response.get_data() == written.read_bytes()
    finally:
        response.close()


def test_a_run_that_stores_no_output_leaves_no_folder(store):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util import output_files

    _worker_init()
    result = execute_code(
        "    curio_export([1, 2], 'half')\n    raise ValueError('then it fails')\n",
        "", EXPORT_TYPE, "", session_id="alice", save_dataset=False,
    )

    assert result["output"]["path"] == "", result
    assert "then it fails" in result["stderr"]
    runs = output_files.outputs_root()
    assert not runs.exists() or list(runs.iterdir()) == []


def test_an_isolated_run_hands_its_file_to_the_parent_which_keeps_it_in_the_runs_folder(store, tmp_path):
    from utk_curio.sandbox.isolation import child, protocol
    from utk_curio.sandbox.util import output_files, staging
    from utk_curio.sandbox.util.parsers import _make_id

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = child.run_node({
        "code": "    return curio_export(pd.DataFrame({'tree': ['oak', 'elm'], 'height': [10, 12]}), 'trees')\n",
        "node_type": EXPORT_TYPE, "data_type": "", "scratch_dir": str(scratch),
        "input": {"kind": "none"}, "dataset_paths": {}, "session_imports": [], "limits": {},
    }, lambda: {"pd": pd})

    assert result["ok"], result["stderr"]
    assert result["output"] == {"kind": "str", "value": "trees.csv"}
    assert result["outputFiles"] == ["trees.csv"]

    # As the runner takes it (isolation/runner.execute_isolated).
    manifest = protocol.parse_child_result(json.dumps(result).encode(), scratch_dir=str(scratch))
    art_id = _make_id()
    kept = output_files.keep_named_file(manifest["output"], str(scratch), manifest["outputFiles"], art_id)
    assert kept == output_files.run_output_dir(art_id) / "trees.csv"
    assert not (scratch / "trees.csv").exists()
    assert kept.read_text(encoding="utf-8") == TREES_CSV
    staging.persist_output(manifest["output"], node_id=EXPORT_TYPE, session_id="alice", art_id=art_id)
    assert output_files.named_file(art_id, "alice") == kept.resolve()


def test_an_isolated_run_fed_a_bundle_writes_one_zip_and_the_parent_keeps_only_it(store, tmp_path):
    """The parts reach the child staged from the store, each with its label,
    a table's too, and the parent keeps the zip alone."""
    from utk_curio.sandbox.isolation import child, protocol
    from utk_curio.sandbox.util import output_files, staging
    from utk_curio.sandbox.util.parsers import _make_id, save_to_duckdb

    loaded = save_to_duckdb((_labelled(TREES.copy(), "Trees"), _labelled(_stations(), "CTA stations")))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = child.run_node({
        "code": "    return curio_export(input_0, 'layers', part='')\n",
        # A node's one input that is a tuple is named "file", as the backend
        # names it (node_exec.parse_input_ref): "outputs" is several circles.
        "node_type": EXPORT_TYPE, "data_type": "file", "scratch_dir": str(scratch),
        "input": staging.stage_input(loaded, scratch), "dataset_paths": {}, "session_imports": [], "limits": {},
    }, lambda: {"pd": pd})

    assert result["ok"], result["stderr"]
    assert result["output"] == {"kind": "str", "value": "layers.zip"}
    assert result["outputFiles"] == ["layers.zip"]
    manifest = protocol.parse_child_result(json.dumps(result).encode(), scratch_dir=str(scratch))
    art_id = _make_id()
    kept = output_files.keep_named_file(manifest["output"], str(scratch), manifest["outputFiles"], art_id)
    assert kept == output_files.run_output_dir(art_id) / "layers.zip"
    assert sorted(p.name for p in kept.parent.iterdir()) == ["layers.zip"]
    names, spec = _zip(kept)
    assert names == ["Trees.csv", "CTA_stations.geojson", "bundle.json"]
    assert [(part["label"], part["kind"]) for part in spec["parts"]] == [
        ("Trees", "dataframe"), ("CTA stations", "geodataframe"),
    ]


def test_the_parent_keeps_only_a_plain_file_the_child_was_given_a_name_for(store, tmp_path):
    from utk_curio.sandbox.util import output_files
    from utk_curio.sandbox.util.parsers import _make_id

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    secret = tmp_path / "secret.csv"
    secret.write_text("secret\n", encoding="utf-8")
    (scratch / "unnamed.csv").write_text("a\n", encoding="utf-8")
    os.symlink(secret, scratch / "link.csv")
    (scratch / "twice.csv").write_text("b\n", encoding="utf-8")
    os.link(scratch / "twice.csv", scratch / "twin.csv")
    names = ["link.csv", "twice.csv", "path.csv"]

    # A file curio_output_file never named, a link, a second name of a file,
    # and a path outside the scratch directory: none is kept.
    for value in ("unnamed.csv", "link.csv", "twice.csv", str(secret)):
        art_id = _make_id()
        descriptor = {"kind": "str", "value": value}
        assert output_files.keep_named_file(descriptor, str(scratch), names, art_id) is None, value
        assert not output_files.run_output_dir(art_id).exists(), value
        assert descriptor == {"kind": "str", "value": value}
    assert (scratch / "unnamed.csv").is_file() and (scratch / "link.csv").is_symlink()
    assert secret.read_text(encoding="utf-8") == "secret\n"

    # A path to a named file in the scratch directory: kept, and the output
    # names the kept file.
    (scratch / "path.csv").write_text("c\n", encoding="utf-8")
    art_id = _make_id()
    descriptor = {"kind": "str", "value": str(scratch / "path.csv")}
    kept = output_files.keep_named_file(descriptor, str(scratch), names, art_id)
    assert kept == output_files.run_output_dir(art_id) / "path.csv"
    assert descriptor == {"kind": "str", "value": str(kept)}
    assert kept.read_text(encoding="utf-8") == "c\n"


# -- what /output-file serves --------------------------------------------------

def _stored(value, session_id="alice") -> str:
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    return save_to_duckdb(value, node_id=EXPORT_TYPE, session_id=session_id)


def _wrote(art_id: str, name: str, text: str = TREES_CSV) -> Path:
    from utk_curio.sandbox.util.output_files import run_output_dir

    folder = run_output_dir(art_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def _answer(client, art_id, session_id="alice"):
    """The route's status and, for a refusal, its reason's code."""
    response = client.get("/output-file", query_string={"fileName": art_id, "sessionId": session_id})
    try:
        if response.status_code == 200:
            return 200, response.get_data(as_text=True)
        body = response.get_json(silent=True) or {}
        return response.status_code, body.get("error")
    finally:
        response.close()


def test_the_file_is_served_to_a_session_that_may_read_the_output_and_no_other(client):
    art_id = _stored("trees.csv", "alice")
    _wrote(art_id, "trees.csv")

    assert _answer(client, art_id, "alice") == (200, TREES_CSV)
    assert _answer(client, art_id, "bob") == (404, "not-found")


def test_a_file_outside_the_folder_of_the_run_that_made_the_output_is_refused(client, tmp_path):
    from utk_curio.sandbox.util.output_files import run_output_dir

    secret = tmp_path / "secret.csv"
    secret.write_text("secret\n", encoding="utf-8")
    other = _stored("parks.csv")
    parks = _wrote(other, "parks.csv")

    # A path anywhere else, into another run's folder, or climbing out of its own.
    for value in (str(secret), str(parks), f"../{other}/parks.csv"):
        art_id = _stored(value)
        _wrote(art_id, "trees.csv")
        assert _answer(client, art_id) == (403, "outside"), value

    # A link in its own folder to a file elsewhere.
    linked = _stored("link.csv")
    run_output_dir(linked).mkdir(parents=True)
    os.symlink(secret, run_output_dir(linked) / "link.csv")
    assert _answer(client, linked) == (403, "outside")


def test_an_output_that_names_no_file_or_one_that_is_gone_says_so(client):
    table = _stored(TREES)
    gone = _stored("trees.csv")

    assert _answer(client, table) == (404, "no-file")
    assert _answer(client, gone) == (404, "gone")
    assert _answer(client, "1792169042468_bd44c99d") == (404, "not-found")
    response = client.get("/output-file")
    assert response.status_code == 400
    response.close()


# -- the store's sweeps take a run's folder ---------------------------------------

@contextlib.contextmanager
def _made_at(when):
    """Artifacts minted in this block are dated *when*."""
    from utk_curio.sandbox.util import parsers

    with mock.patch.object(parsers, "_make_id", lambda: f"{when:013d}_{secrets.token_hex(4)}"):
        yield


def test_the_week_sweep_takes_a_runs_folder_with_its_output(store):
    from utk_curio.sandbox.util import output_files, parsers
    from utk_curio.sandbox.util.db import get_connection

    with _made_at(OLD):
        old = _stored("trees.csv")
        returned_again = _stored("heights.tif")
    with _made_at(NEW):
        new = _stored("parks.csv")
    for art_id, name in ((old, "trees.csv"), (returned_again, "heights.tif"), (new, "parks.csv")):
        _wrote(art_id, name)
    # A newer row names a file in an old run's folder: a raster a later run
    # returned again.
    get_connection().execute(
        "INSERT INTO artifacts (id, node_id, kind, value_str) VALUES (?, 'n', 'raster', ?)",
        [f"{NEW:013d}_{secrets.token_hex(4)}", str(output_files.run_output_dir(returned_again) / "heights.tif")],
    )
    # Folders no row was stored for: one past the time, and a run under way.
    abandoned = _wrote(f"{OLD:013d}_{secrets.token_hex(4)}", "half.csv").parent
    running = _wrote(f"{NEW:013d}_{secrets.token_hex(4)}", "half.csv").parent
    os.utime(running, (NEW / 1000, NEW / 1000))

    parsers.forget_made_before(CUTOFF)

    assert not output_files.run_output_dir(old).exists()
    assert not abandoned.exists()
    assert (output_files.run_output_dir(new) / "parks.csv").is_file()
    assert (output_files.run_output_dir(returned_again) / "heights.tif").is_file()
    assert running.is_dir()


def test_forgetting_a_sessions_outputs_takes_their_runs_folders(store):
    from utk_curio.sandbox.util import output_files, parsers

    alice = _stored("trees.csv", "alice")
    bob = _stored("parks.csv", "bob")
    trees = _wrote(alice, "trees.csv")
    _wrote(bob, "parks.csv")

    described = parsers.describe_session_artifacts(["alice"])["alice"]
    assert described["ids"] == [alice]
    assert described["bytes"] >= trees.stat().st_size

    parsers.forget_session_artifacts(["alice"])

    assert not output_files.run_output_dir(alice).exists()
    assert (output_files.run_output_dir(bob) / "parks.csv").is_file()
