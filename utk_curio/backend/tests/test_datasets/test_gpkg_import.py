"""GeoPackage import (#268).

A ``.gpkg`` is multi-layer, the same shape as the OSM PBF the importer already
handles: GDAL exposes each layer separately, and each has its own geometry type
and its own CRS. So it takes the same route - convert each layer to GeoParquet
on the way in, register one standalone dataset per layer, and tie them together
with a ``group_id`` so the catalog shows one card.

That choice is what keeps this small. Storing a ``.gpkg`` verbatim as a new
first-class format would put a ``gpkg`` branch in every reader, and the loader
snippet has no way to name a layer, so there would be nothing sensible to
generate for a file holding three of them.

Two things differ from the PBF path and both are correctness, not style:

* an OSM layer is always WGS84, so a missing CRS can simply be declared. A
  GeoPackage layer carries whatever it was made with, so a layer that is not
  4326 has to be *reprojected*, not relabelled. Getting that wrong moves the
  data somewhere else on Earth and nothing downstream can tell.
* a GeoPackage may hold attribute-only tables with no geometry at all. Dropping
  them silently loses the user's data.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _geo_available() -> bool:
    try:
        import geopandas  # noqa: F401
        import pyogrio
    except Exception:
        return False
    try:
        return bool(pyogrio.list_drivers().get("GPKG"))
    except Exception:
        return False


geo = pytest.mark.skipif(
    not _geo_available(),
    reason="geopandas/pyogrio with the GDAL GPKG driver is not available",
)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _write_gpkg(path: Path, *, layers: str = "multi") -> Path:
    """Build a GeoPackage fixture in place.

    Synthesised rather than committed: unlike a PBF, a GeoPackage is a few lines
    of geopandas, and a binary in git that only one suite reads is a binary
    nobody can review. ``roads`` is deliberately EPSG:3857 so the reprojection
    is exercised, and ``lookup`` deliberately carries no geometry.
    """
    import geopandas as gpd
    import pandas as pd
    import pyogrio
    from shapely.geometry import LineString, Point, Polygon

    gpd.GeoDataFrame(
        {"name": ["alpha", "beta"]},
        geometry=[Point(-87.62, 41.88), Point(-87.63, 41.89)],
        crs="EPSG:4326",
    ).to_file(path, layer="stops", driver="GPKG")
    if layers == "single":
        return path

    # Web-mercator metres for the same rough area, so a correct reprojection
    # lands back near Chicago and an incorrect one lands in the Atlantic.
    gpd.GeoDataFrame(
        {"road": ["main"]},
        geometry=[LineString([(-9754000, 5142000), (-9755000, 5143000)])],
        crs="EPSG:3857",
    ).to_file(path, layer="roads", driver="GPKG", mode="a")
    gpd.GeoDataFrame(
        {"zone": ["loop"]},
        geometry=[Polygon([(-87.64, 41.87), (-87.61, 41.87), (-87.61, 41.90)])],
        crs="EPSG:4326",
    ).to_file(path, layer="zones", driver="GPKG", mode="a")
    pyogrio.write_dataframe(
        pd.DataFrame({"code": ["a", "b"], "label": ["Alpha", "Beta"]}),
        path,
        layer="lookup",
        driver="GPKG",
        append=True,
    )
    return path


def _import(client, token, path: Path):
    with open(path, "rb") as fh:
        return client.post(
            "/api/datasets/import",
            headers=_auth(token),
            data={"file": (fh, path.name)},
            content_type="multipart/form-data",
        )


@geo
class TestAMultiLayerGeoPackage:
    @pytest.fixture()
    def imported(self, client, user_and_token, tmp_path, monkeypatch):
        _user, token = user_and_token
        monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
        src = _write_gpkg(tmp_path / "chicago.gpkg")
        resp = _import(client, token, src)
        assert resp.status_code == 201, resp.get_data(as_text=True)
        primary = resp.get_json()
        items = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()["items"]
        return primary, items, token

    def test_it_is_accepted_at_all(self, imported):
        primary, _items, _token = imported
        assert primary["id"]

    def test_every_layer_becomes_its_own_dataset(self, imported):
        primary, items, _token = imported
        group_id = primary["groupId"]
        members = [i for i in items if i.get("groupId") == group_id]
        assert {m["layerName"] for m in members} == {"stops", "roads", "zones", "lookup"}

    def test_the_layers_share_one_group(self, imported):
        primary, _items, _token = imported
        assert primary["groupId"].startswith("gpkg.")

    def test_the_response_says_how_many_datasets_it_made(self, imported):
        primary, _items, _token = imported
        assert primary["importedDatasetCount"] == 4

    def test_the_group_shows_as_one_card(self, imported):
        primary, _items, token = imported
        grouped = client_get_grouped(imported)
        card = next(c for c in grouped if c["id"] == primary["groupId"])
        assert card["format"] == "gpkg"
        assert len(card["groupLayerIds"]) == 4

    def test_a_layer_that_was_not_4326_is_reprojected(self, imported):
        _primary, items, _token = imported
        import geopandas as gpd

        roads = next(i for i in items if i.get("layerName") == "roads")
        gdf = gpd.read_parquet(roads["path"])
        assert gdf.crs is not None and gdf.crs.to_epsg() == 4326
        # Chicago, not the Gulf of Guinea. A set_crs instead of a to_crs would
        # leave the mercator metres untouched and fail this.
        minx, miny, maxx, maxy = gdf.total_bounds
        assert -88.5 < minx < -87.0 and 41.0 < miny < 42.5

    def test_an_attribute_only_table_is_kept(self, imported):
        _primary, items, _token = imported
        import pandas as pd

        lookup = next(i for i in items if i.get("layerName") == "lookup")
        df = pd.read_parquet(lookup["path"])
        assert list(df["code"]) == ["a", "b"]


@geo
class TestASingleLayerGeoPackage:
    def test_it_imports_as_an_ordinary_dataset_with_no_group(
        self, client, user_and_token, tmp_path, monkeypatch
    ):
        # One layer is not a group; wrapping it in a card the user has to expand
        # to reach one dataset is worse than not having a card.
        _user, token = user_and_token
        monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
        src = _write_gpkg(tmp_path / "solo.gpkg", layers="single")
        resp = _import(client, token, src)
        assert resp.status_code == 201, resp.get_data(as_text=True)
        item = resp.get_json()
        assert item.get("groupId") is None
        assert item["format"] == "parquet"


@geo
def test_a_gpkg_that_is_not_a_gpkg_is_refused(
    client, user_and_token, tmp_path, monkeypatch
):
    _user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    bogus = tmp_path / "broken.gpkg"
    bogus.write_bytes(b"not a geopackage at all")
    resp = _import(client, token, bogus)
    assert resp.status_code >= 400
    assert "gpkg" in resp.get_data(as_text=True).lower() or "geopackage" in resp.get_data(as_text=True).lower()


def test_import_gpkg_reports_a_clear_error_when_geo_extras_are_missing(
    client, user_and_token, tmp_path, monkeypatch
):
    from utk_curio.backend.app.datasets.install import gpkg as gpkg_mod

    _user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    def _no_geo():
        raise gpkg_mod.GpkgError(
            "Importing GeoPackage files requires the geospatial extras "
            "(geopandas / pyogrio), which aren't available on this server."
        )

    monkeypatch.setattr(gpkg_mod, "_import_geo", _no_geo)
    src = tmp_path / "anything.gpkg"
    src.write_bytes(b"\x00")
    resp = _import(client, token, src)
    assert resp.status_code >= 400
    assert "geospatial extras" in resp.get_data(as_text=True)


def client_get_grouped(imported):
    """The catalog listing with groups folded, as the drawer requests it."""
    _primary, _items, token = imported
    from flask import current_app

    client = current_app.test_client()
    return client.get(
        "/api/datasets/catalog?groupOsm=true", headers=_auth(token)
    ).get_json()["items"]
