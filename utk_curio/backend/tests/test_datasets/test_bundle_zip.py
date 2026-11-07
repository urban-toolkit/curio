"""A bundle exports as one zip, and a zip Curio exported imports back as a bundle (#1335).

The Data Catalog's Export of a bundle gives ``<title>.zip``: a file per part,
named after the part's label, a table as CSV, a GeoDataFrame as GeoJSON and a
raster as GeoTIFF, and ``bundle.json``, which records the container and each
part's index, key, label and kind, and its file or its value. A node's output
of several parts exports the same way, saved and live, a live one only for a
caller who may read it, as a single live file. A layer group exports as the
dict of its layers by name that ``curio_load_data`` gives for it.

Importing such a zip gives a bundle of the same parts, labels and container. A
zip whose ``bundle.json`` does not describe what it holds is refused, saying
what is wrong.

The zip's writer is ``sandbox/util/bundle_zip.py``, read inside each test.
"""
from __future__ import annotations

import base64
import io
import json
import stat
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from utk_curio import shipped
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    save_project_with_output,
    store_sandbox_artifact,
)

CHICAGO = "data.curio.chicago-loop-layers"
CHICAGO_BUNDLE = shipped.path(f"datasets/{CHICAGO}@1/data/bundle.json")
CHICAGO_LABELS = [
    "Census tracts with CDC/ATSDR's Social Vulnerability Index 2020",
    "CTA 'L' rail lines (City of Chicago)",
    "Trees (OpenStreetMap)",
    "CTA 'L' rail stations (City of Chicago)",
]
CHICAGO_FILES = [
    "Census_tracts_with_CDC_ATSDR_s_Social_Vulnerability_Index_2020.geojson",
    "CTA_L_rail_lines_City_of_Chicago.geojson",
    "Trees_OpenStreetMap.geojson",
    "CTA_L_rail_stations_City_of_Chicago.geojson",
]
#: The features of each of Chicago Loop Layers' parts.
CHICAGO_ROWS = [42, 37, 12441, 29]

TREES = pd.DataFrame({"tree": ["oak", "elm"], "height": [10, 12]})
#: What a node of several outputs that hands on a table, a geo table and a
#: number exports as, its parts labelled by kind and place.
SEVERAL_FILES = ["Table_part_1.csv", "Geo_table_part_2.geojson", "bundle.json"]
SEVERAL_PARTS = [
    {"index": 0, "label": "Table · part 1", "kind": "dataframe", "file": "Table_part_1.csv"},
    {"index": 1, "label": "Geo table · part 2", "kind": "geodataframe", "file": "Geo_table_part_2.geojson"},
    {"index": 2, "label": "Number · part 3", "kind": "int", "value": 3},
]


def _stations():
    import geopandas as gpd
    from shapely.geometry import Point

    return gpd.GeoDataFrame(
        {"name": ["Clark/Lake", "Grand"]},
        geometry=[Point(447000, 4637000), Point(447500, 4637800)], crs="EPSG:32616",
    )


def _download(client, token, dataset_id, **params):
    return client.get(f"/api/datasets/{dataset_id}/download", headers=auth_headers(token), query_string=params)


def _zip(resp) -> tuple[list[str], dict]:
    """The members of the zip *resp* downloaded, in order, and its bundle.json."""
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.mimetype == "application/zip", resp.mimetype
    with zipfile.ZipFile(io.BytesIO(resp.data)) as archive:
        return archive.namelist(), json.loads(archive.read("bundle.json"))


def _member(resp, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(resp.data)) as archive:
        return archive.read(name)


def _features(resp, name: str) -> int:
    return len(json.loads(_member(resp, name))["features"])


def _live(node_id: str, art_id: str) -> str:
    entry = {"node_id": node_id, "filename": art_id, "data_type": "outputs"}
    return base64.b64encode(json.dumps([entry]).encode()).decode()


# -- export ------------------------------------------------------------------

def test_chicago_loop_layers_exports_as_a_zip_of_its_four_layers_named_by_their_labels(client, user_and_token):
    _, token = user_and_token
    resp = _download(client, token, CHICAGO)

    names, spec = _zip(resp)
    assert "Chicago Loop Layers.zip" in resp.headers["Content-Disposition"]
    assert names == [*CHICAGO_FILES, "bundle.json"]
    assert spec == {
        "version": 1,
        "container": "tuple",
        "parts": [
            {"index": index, "label": label, "kind": "geodataframe", "file": file}
            for index, (label, file) in enumerate(zip(CHICAGO_LABELS, CHICAGO_FILES))
        ],
    }
    assert [_features(resp, file) for file in CHICAGO_FILES] == CHICAGO_ROWS
    # The same bundle is the same file, byte for byte.
    assert _download(client, token, CHICAGO).data == resp.data


def test_a_computed_bundle_with_a_number_exports_saved_and_live(client, user_and_token):
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    _, token = user_and_token
    project_id = create_project(client, token, name="Several outputs")
    saved = store_sandbox_artifact((TREES, _stations(), 3), node_id="several")
    save_project_with_output(client, token, project_id, saved, node_id="several")
    live = save_to_duckdb((TREES, _stations(), 3), node_id="live", session_id=token)

    exports = [
        _download(client, token, computed_dataset_id("several", project_id), dataflowId=project_id),
        _download(client, token, computed_dataset_id("live", project_id), dataflowId=project_id,
                  liveOutputs=_live("live", live)),
    ]
    for resp in exports:
        names, spec = _zip(resp)
        assert names == SEVERAL_FILES
        assert spec == {"version": 1, "container": "tuple", "parts": SEVERAL_PARTS}
        assert _member(resp, "Table_part_1.csv").decode("utf-8") == "tree,height\noak,10\nelm,12\n"
        assert _features(resp, "Geo_table_part_2.geojson") == 2
        assert resp.headers["Content-Disposition"].rstrip('"').endswith(".zip")


def test_a_live_bundle_exports_for_a_caller_who_may_read_it_and_no_other(client, user_and_token):
    """As a single live file (#1150): one the caller may not read is not
    found, and nothing of it is sent."""
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    _, token = user_and_token
    project_id = create_project(client, token, name="Whose outputs")
    mine = save_to_duckdb((TREES, _stations(), 3), node_id="mine", session_id=token)
    theirs = save_to_duckdb(
        (pd.DataFrame({"zone": ["Bob's own zone"]}), 7), node_id="theirs", session_id="bob-token-789",
    )

    names, _spec = _zip(_download(client, token, computed_dataset_id("mine", project_id),
                                  dataflowId=project_id, liveOutputs=_live("mine", mine)))
    assert names == SEVERAL_FILES
    refused = _download(client, token, computed_dataset_id("theirs", project_id),
                        dataflowId=project_id, liveOutputs=_live("theirs", theirs))
    assert refused.status_code == 404, refused.get_data(as_text=True)
    assert "Bob's own zone" not in refused.get_data(as_text=True)


def test_a_saved_load_of_the_chicago_bundle_exports_under_its_labels(client, user_and_token):
    """A Data Loading node that loads the whole bundle hands on its layers,
    each with its label, and its saved output exports under those labels."""
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.sandbox.util.catalog_helpers import read_dataset

    _, token = user_and_token
    project_id = create_project(client, token, name="Chicago layers")
    loaded = store_sandbox_artifact(read_dataset(str(CHICAGO_BUNDLE), "bundle"), node_id="loader")
    save_project_with_output(client, token, project_id, loaded, node_id="loader")

    resp = _download(client, token, computed_dataset_id("loader", project_id), dataflowId=project_id)
    names, spec = _zip(resp)
    assert names == [*CHICAGO_FILES, "bundle.json"]
    assert [part["label"] for part in spec["parts"]] == CHICAGO_LABELS
    assert [_features(resp, file) for file in CHICAGO_FILES] == CHICAGO_ROWS


def _import(client, token, body: bytes, filename: str):
    return client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(body), filename)},
        content_type="multipart/form-data",
    )


def test_a_layer_group_exports_as_a_zip_of_its_layers_by_name(client, user_and_token, tmp_path):
    import geopandas as gpd
    import pyogrio
    from shapely.geometry import Point

    _, token = user_and_token
    gpkg = tmp_path / "chicago.gpkg"
    gpd.GeoDataFrame(
        {"name": ["alpha", "beta"]}, geometry=[Point(-87.62, 41.88), Point(-87.63, 41.89)], crs="EPSG:4326",
    ).to_file(gpkg, layer="stops", driver="GPKG")
    pyogrio.write_dataframe(
        pd.DataFrame({"code": ["a", "b"], "label": ["Alpha", "Beta"]}), gpkg, layer="lookup", driver="GPKG", append=True,
    )
    imported = _import(client, token, gpkg.read_bytes(), "chicago.gpkg")
    assert imported.status_code == 201, imported.get_data(as_text=True)

    resp = _download(client, token, imported.get_json()["groupId"])
    names, spec = _zip(resp)
    assert names == ["lookup.csv", "stops.geojson", "bundle.json"]
    assert spec == {
        "version": 1,
        "container": "dict",
        "parts": [
            {"index": 0, "key": "lookup", "label": "lookup", "kind": "dataframe", "file": "lookup.csv"},
            {"index": 1, "key": "stops", "label": "stops", "kind": "geodataframe", "file": "stops.geojson"},
        ],
    }
    assert _member(resp, "lookup.csv").decode("utf-8") == "code,label\na,Alpha\nb,Beta\n"
    assert _features(resp, "stops.geojson") == 2


# -- import ------------------------------------------------------------------

def test_an_exported_bundle_imports_back_with_its_parts_labels_and_container(client, user_and_token):
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.sandbox.util.catalog_helpers import read_dataset

    _, token = user_and_token
    project_id = create_project(client, token, name="Round trip")
    art = store_sandbox_artifact({"trees": TREES, "stations": _stations(), "count": 3}, node_id="parts")
    save_project_with_output(client, token, project_id, art, node_id="parts")
    exported = _download(client, token, computed_dataset_id("parts", project_id), dataflowId=project_id)
    names, spec = _zip(exported)

    imported = _import(client, token, exported.data, "Round trip.zip")
    assert imported.status_code == 201, imported.get_data(as_text=True)
    item = imported.get_json()
    assert item["format"] == "bundle"
    assert item["title"] == "Round Trip"
    stored = json.loads(Path(item["path"]).read_text(encoding="utf-8"))
    assert stored.get("container") == "dict"
    assert [(part["index"], part["key"], part["label"], part["kind"]) for part in stored["parts"]] == [
        (0, "trees", "trees", "dataframe"), (1, "stations", "stations", "geodataframe"), (2, "count", "count", "int"),
    ]
    loaded = read_dataset(item["path"], "bundle")
    assert list(loaded) == ["trees", "stations", "count"]
    pd.testing.assert_frame_equal(loaded["trees"], TREES)
    assert loaded["stations"].crs.to_epsg() == 32616 and list(loaded["stations"]["name"]) == ["Clark/Lake", "Grand"]
    assert loaded["count"] == 3
    # And it exports again as the zip it was imported from.
    again = _download(client, token, item["id"])
    assert _zip(again) == (names, spec)
    assert "Round Trip.zip" in again.headers["Content-Disposition"]


def test_a_zip_of_a_raster_part_imports_as_a_geotiff_part(client, user_and_token, tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from utk_curio.sandbox.util.bundle_zip import parts_of, write_zip

    _, token = user_and_token
    tif = tmp_path / "heights.tif"
    with rasterio.open(
        tif, "w", driver="GTiff", width=4, height=3, count=1, dtype="float32",
        crs="EPSG:32616", transform=from_origin(440000, 4640000, 30, 30),
    ) as raster:
        raster.write(np.arange(12, dtype="float32").reshape(3, 4), 1)
    with rasterio.open(tif) as raster:
        write_zip(str(tmp_path / "heights.zip"), *parts_of((raster, "a note")))

    imported = _import(client, token, (tmp_path / "heights.zip").read_bytes(), "heights.zip")
    assert imported.status_code == 201, imported.get_data(as_text=True)
    stored = json.loads(Path(imported.get_json()["path"]).read_text(encoding="utf-8"))
    assert [(part["kind"], part["format"]) for part in stored["parts"]] == [("raster", "geotiff"), ("str", "json")]
    from utk_curio.sandbox.util.catalog_helpers import read_dataset

    heights, note = read_dataset(imported.get_json()["path"], "bundle")
    try:
        assert heights.crs.to_epsg() == 32616
        np.testing.assert_array_equal(heights.read(1), np.arange(12, dtype="float32").reshape(3, 4))
    finally:
        heights.close()
    assert note == "a note"


CSV = "tree\noak\n"


def _bundle_json(*parts, container="tuple", version=1) -> str:
    return json.dumps({"version": version, "container": container, "parts": list(parts)})


def _part(file="trees.csv", kind="dataframe", index=0, **more) -> dict:
    return {"index": index, "label": "Trees", "kind": kind, "file": file, **more}


def _zip_of(members: dict[str, str], *, links=()) -> bytes:
    """A zip holding *members*, and a symbolic link by each name in *links*."""
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return sink.getvalue()


REFUSED = {
    "a member that climbs out": (
        {"bundle.json": _bundle_json(_part()), "trees.csv": CSV, "../evil.csv": CSV}, (), "contains '..'",
    ),
    "a link": ({"bundle.json": _bundle_json(_part())}, ("trees.csv",), "'trees.csv' is a symbolic link"),
    "a part in a folder": (
        {"bundle.json": _bundle_json(_part("parts/trees.csv")), "parts/trees.csv": CSV}, (),
        "bundle.json lists 'parts/trees.csv', which is not a file at the top of the zip",
    ),
    "a file bundle.json does not list": (
        {"bundle.json": _bundle_json(_part()), "trees.csv": CSV, "extra.csv": CSV}, (),
        "it holds 'extra.csv', which bundle.json does not list",
    ),
    "a listed file it does not hold": (
        {"bundle.json": _bundle_json(_part(), _part("more.csv", index=1)), "trees.csv": CSV}, (),
        "bundle.json lists 'more.csv', which the zip does not hold",
    ),
    "a bundle.json that is not JSON": ({"bundle.json": "{parts", "trees.csv": CSV}, (), "its bundle.json is not JSON"),
    "a file that is not its kind's": (
        {"bundle.json": _bundle_json(_part("trees.txt")), "trees.txt": CSV}, (),
        "the part 'Trees' is a dataframe, whose file ends in .csv, and its file is 'trees.txt'",
    ),
    "a container a bundle cannot be": (
        {"bundle.json": _bundle_json(_part(), container="set"), "trees.csv": CSV}, (),
        "records the container 'set'",
    ),
    "a value of a kind that is a file": (
        {"bundle.json": _bundle_json({"index": 0, "label": "Trees", "kind": "dataframe", "value": 1})}, (),
        "the part 'Trees' is a dataframe, which is a file of the zip, not a value",
    ),
    "a zip of another version": (
        {"bundle.json": _bundle_json(_part(), version=2), "trees.csv": CSV}, (), "is a version 2 bundle",
    ),
}


@pytest.mark.parametrize("members, links, reason", list(REFUSED.values()), ids=list(REFUSED))
def test_a_zip_whose_bundle_json_does_not_describe_it_is_refused(client, user_and_token, members, links, reason):
    _, token = user_and_token
    resp = _import(client, token, _zip_of(members, links=links), "layers.zip")
    assert resp.status_code == 400, resp.get_data(as_text=True)
    error = resp.get_json()["error"]
    assert error.startswith("layers.zip cannot be imported as a bundle: "), error
    assert reason in error, error
    items = client.get("/api/datasets/catalog", headers=auth_headers(token)).get_json()["items"]
    assert not [item for item in items if item.get("format") == "bundle" and item.get("origin") == "imported"]


def test_a_bundle_zip_over_the_archive_caps_is_refused(client, user_and_token, monkeypatch):
    from utk_curio.backend.app.discovery.application import archives

    _, token = user_and_token
    monkeypatch.setattr(archives, "MAX_UNPACKED_BYTES", 64)
    body = _zip_of({"bundle.json": _bundle_json(_part()), "trees.csv": "tree\n" + "oak\n" * 40})

    resp = _import(client, token, body, "layers.zip")
    assert resp.status_code == 400, resp.get_data(as_text=True)
    error = resp.get_json()["error"]
    assert error.startswith("layers.zip cannot be imported as a bundle: "), error
    assert "more than 64 bytes" in error, error
