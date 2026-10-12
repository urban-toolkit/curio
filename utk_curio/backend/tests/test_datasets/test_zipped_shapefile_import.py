"""Importing a shapefile (#877).

A shapefile is several files: the ``.shp`` holds the shapes, the ``.dbf`` the
attributes, the ``.shx`` the index, and a ``.prj`` the CRS. Import dataset takes
one file, so a shapefile arrives as a ``.zip`` of its parts and lands as one
GeoParquet dataset, read by the same code the Discovery Catalog uses for a
zipped shapefile (``discovery/application/archives.py``). A ``.shp`` on its own
cannot be read, so it is refused with a message that says how to zip it.

The fixtures are written with geopandas in each test, in web-mercator metres
around Chicago, so a dataset that lands near Chicago in EPSG:4326 proves its
``.prj`` was read.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _write_shapefile(folder: Path) -> Path:
    """``roads.shp`` with its ``.dbf``, ``.shx``, ``.prj`` and ``.cpg``."""
    import geopandas as gpd
    from shapely.geometry import LineString

    folder.mkdir()
    gpd.GeoDataFrame(
        {"name": ["Main St", "Oak Ave"], "lanes": [2, 4]},
        geometry=[
            LineString([(-9754000, 5142000), (-9755000, 5143000)]),
            LineString([(-9756000, 5141000), (-9757000, 5142500)]),
        ],
        crs="EPSG:3857",
    ).to_file(folder / "roads.shp")
    return folder / "roads.shp"


def _zip(dest: Path, shp: Path, *, leave_out: tuple[str, ...] = ()) -> Path:
    """The shapefile's parts in a zip, less the suffixes in *leave_out*."""
    with zipfile.ZipFile(dest, "w") as zf:
        for part in sorted(shp.parent.iterdir()):
            if part.suffix.lower() not in leave_out:
                zf.write(part, part.name)
    return dest


def _import(client, token, path: Path):
    with open(path, "rb") as fh:
        return client.post(
            "/api/datasets/import",
            headers=_auth(token),
            data={"file": (fh, path.name)},
            content_type="multipart/form-data",
        )


def _catalog_ids(client, token) -> set[str]:
    items = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()["items"]
    return {item["id"] for item in items}


class TestAZippedShapefile:
    @pytest.fixture()
    def imported(self, client, user_and_token, tmp_path, monkeypatch):
        _user, token = user_and_token
        monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
        shp = _write_shapefile(tmp_path / "parts")
        resp = _import(client, token, _zip(tmp_path / "roads.zip", shp))
        assert resp.status_code == 201, resp.get_data(as_text=True)
        return resp.get_json()

    def test_it_lands_as_one_geoparquet_dataset(self, imported):
        """#877: one dataset, GeoParquet, named after the zip, with its count."""
        assert imported["format"] == "parquet"
        assert imported.get("groupId") is None
        assert imported["title"] == "roads"
        assert imported["featureCount"] == 2

    def test_it_keeps_the_attributes_of_its_dbf(self, imported):
        """#877: the .dbf's columns and values are in the GeoParquet."""
        import geopandas as gpd

        frame = gpd.read_parquet(imported["path"])
        assert list(frame["name"]) == ["Main St", "Oak Ave"]
        assert list(frame["lanes"]) == [2, 4]

    def test_its_crs_comes_from_its_prj(self, imported):
        """#877: the shapes are reprojected from the .prj's CRS to EPSG:4326,
        so they land in Chicago, not in mercator metres."""
        import geopandas as gpd

        frame = gpd.read_parquet(imported["path"])
        assert frame.crs is not None and frame.crs.to_epsg() == 4326
        minx, miny, maxx, maxy = frame.total_bounds
        assert -88.5 < minx < maxx < -87.0, frame.total_bounds
        assert 41.0 < miny < maxy < 42.5, frame.total_bounds


def test_a_lone_shp_is_refused_with_how_to_zip_it(client, user_and_token, tmp_path, monkeypatch):
    """#877: a .shp without its .dbf and .shx cannot be read. It is refused, the
    message says to zip it with them, and nothing is registered."""
    _user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    shp = _write_shapefile(tmp_path / "parts")
    before = _catalog_ids(client, token)

    resp = _import(client, token, shp)

    assert resp.status_code == 400, resp.get_data(as_text=True)
    message = resp.get_json()["error"]
    for words in ("roads.shp", ".dbf", ".shx", ".zip"):
        assert words in message, message
    assert _catalog_ids(client, token) == before


@pytest.mark.parametrize("missing", [".shx", ".dbf"])
def test_a_zip_missing_a_part_is_refused_as_discovery_refuses_it(
    missing, client, user_and_token, tmp_path, monkeypatch
):
    """#877: a zip whose shapefile lacks its .shx or .dbf is refused in the
    Discovery Catalog's words, and nothing is registered."""
    _user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    shp = _write_shapefile(tmp_path / "parts")
    archive = _zip(tmp_path / "roads.zip", shp, leave_out=(missing,))
    before = _catalog_ids(client, token)

    resp = _import(client, token, archive)

    assert resp.status_code == 400, resp.get_data(as_text=True)
    message = resp.get_json()["error"]
    assert f"'roads.shp' needs its {missing} beside it in the archive" in message, message
    assert _catalog_ids(client, token) == before
