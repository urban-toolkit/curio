"""A Data Export node's file: what ``curio_export`` writes, where a run keeps
it, and what ``/output-file`` serves.

``curio_export(data, name)`` writes a table as CSV, a GeoDataFrame as GeoJSON,
a raster as GeoTIFF and anything else as JSON, under a name that ends in its
format's extension, and returns that name, which is the node's output. The file
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
import itertools
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
