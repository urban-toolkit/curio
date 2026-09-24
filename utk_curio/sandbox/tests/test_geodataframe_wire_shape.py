"""The wire shape of a GeoDataFrame, pinned.

Sibling of ``test_dataframe_wire_shape.py``, and for the same reason:
``parseOutput`` is the only thing that decides what a ``geodataframe`` payload
looks like to the browser, nothing asserted it, and the parts nobody asserted
are exactly the parts that were broken.

Three separate crashes lived here, all of them silent or misattributed:

* a second geometry column (``gdf['centroid'] = gdf.centroid``) raised
  ``TypeError: Object of type Point is not JSON serializable`` -- an ordinary
  teaching operation that could not be sent to a chart at all;
* a GeoDataFrame with no active geometry raised ``AttributeError`` from
  ``.geometry.name``, in several different places, one of which swallowed it
  and returned ``None``;
* the active geometry column's *name* never reached the browser, so a frame
  whose geometry was called ``geom`` was indistinguishable from one with no
  geometry at all.

The payload carries three keys beyond the GeoJSON: ``crs``, ``geometry_name``
and ``schema``. ``geometry_name`` is the contract that lets the Vega-Lite node
draw a map without the user hand-writing a converter, so it is pinned here
rather than inferred downstream.
"""
import geopandas as gpd
import pandas as pd
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
)

from utk_curio.sandbox.util.parsers import parseOutput


def _square(x=0.0, y=0.0, size=1.0):
    """A unit square. Ring winding matters downstream (d3-geo wants clockwise
    exteriors) but not to this file -- here it just needs to be valid."""
    return Polygon(
        [(x, y), (x, y + size), (x + size, y + size), (x + size, y), (x, y)]
    )


def _frame(crs="EPSG:4326"):
    return gpd.GeoDataFrame(
        {"zip": ["60601", "60602"], "pop": [2746, 8804]},
        geometry=[_square(), _square(2.0, 2.0)],
        crs=crs,
    )


# --- D3, D17: the baseline payload -------------------------------------------

def test_a_geodataframe_is_a_feature_collection_with_geometry():
    out = parseOutput(_frame())

    assert out["dataType"] == "geodataframe"
    data = out["data"]
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2

    feature = data["features"][0]
    # Full geometry per feature. The browser used to drop this on the floor.
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["geometry"]["coordinates"][0][0] == [0.0, 0.0]
    # geopandas excludes the active geometry column from `properties`, which is
    # why a geometry column can keep its own name without ever colliding.
    assert feature["properties"] == {"zip": "60601", "pop": 2746}


def test_the_crs_urn_is_reinjected():
    data = parseOutput(_frame())["data"]

    assert data["crs"]["properties"]["name"] == "urn:ogc:def:crs:EPSG::4326"


def test_a_projected_crs_reports_its_own_code():
    data = parseOutput(_frame().to_crs(3395))["data"]

    assert data["crs"]["properties"]["name"] == "urn:ogc:def:crs:EPSG::3395"


# --- D20: no CRS -------------------------------------------------------------

def test_no_crs_emits_no_crs_key():
    # The browser falls back to a coordinate-magnitude heuristic in this case,
    # so the *absence* of the key is the signal and must stay absent.
    data = parseOutput(_frame(crs=None))["data"]

    assert "crs" not in data


# --- D3, D6, D7, D8: geometry_name -------------------------------------------

def test_the_active_geometry_column_is_named():
    data = parseOutput(_frame())["data"]

    assert data["geometry_name"] == "geometry"


def test_a_renamed_geometry_column_reports_its_real_name():
    # D6. Without this the browser cannot tell which column it is looking at,
    # and 'geometry' is only a convention.
    gdf = _frame().rename_geometry("geom")

    data = parseOutput(gdf)["data"]

    assert data["geometry_name"] == "geom"


def test_a_string_column_called_geometry_is_left_alone():
    # D7. The active column is `geom`; a *string* column happens to be called
    # `geometry`. Neither may shadow the other.
    gdf = _frame().rename_geometry("geom")
    gdf["geometry"] = gdf["zip"]

    data = parseOutput(gdf)["data"]

    assert data["geometry_name"] == "geom"
    assert data["features"][0]["properties"]["geometry"] == "60601"
    assert data["features"][0]["geometry"]["type"] == "Polygon"


def test_a_geodataframe_with_no_active_geometry_is_tabular():
    # D8. `.geometry` raises here, which used to take down parseOutput entirely.
    #
    # Such a frame is reported as a plain `dataframe`, not an empty
    # `geodataframe`. That is not a dodge: it cannot be written as GeoParquet
    # either (the 'geo' metadata comes out with no `primary_column` and reading
    # it back raises), so storage has to treat it as a table regardless. Saying
    # the same thing in the payload keeps the value from changing shape as it
    # moves between the two.
    gdf = gpd.GeoDataFrame(pd.DataFrame({"zip": ["60601"], "pop": [2746]}))

    out = parseOutput(gdf)

    assert out["dataType"] == "dataframe"
    assert out["data"] == {"zip": ["60601"], "pop": [2746]}
    assert out["schema"]["pop"].startswith("int")


# --- D4, D5, D11: secondary geometry columns ---------------------------------

def test_a_centroid_column_serializes_as_geojson():
    # D4 -- the headline crash. `TypeError: Object of type Point is not JSON
    # serializable` for what is a one-line geopandas idiom.
    gdf = _frame()
    gdf["centroid"] = gdf.geometry.centroid

    data = parseOutput(gdf)["data"]

    centroid = data["features"][0]["properties"]["centroid"]
    assert centroid["type"] == "Point"
    assert centroid["coordinates"] == [0.5, 0.5]
    # Lists, not tuples. shapely hands back tuples; the in-process dict is what
    # the parquet encoder and these tests both read, so the conversion has to
    # happen here rather than at `json.dumps` time.
    assert isinstance(centroid["coordinates"], list)


def test_three_geometry_columns_all_serialize():
    # D5.
    gdf = _frame()
    gdf["centroid"] = gdf.geometry.centroid
    gdf["bbox"] = gdf.geometry.envelope

    data = parseOutput(gdf)["data"]
    props = data["features"][0]["properties"]

    assert props["centroid"]["type"] == "Point"
    assert props["bbox"]["type"] == "Polygon"
    assert data["geometry_name"] == "geometry"


def test_nulls_in_a_secondary_geometry_column_are_null():
    # D11.
    gdf = _frame()
    gdf["centroid"] = [Point(0.5, 0.5), None]

    features = parseOutput(gdf)["data"]["features"]

    assert features[0]["properties"]["centroid"]["type"] == "Point"
    assert features[1]["properties"]["centroid"] is None


# --- D9, D10: missing active geometry ----------------------------------------

def test_some_rows_missing_geometry():
    # D9.
    gdf = gpd.GeoDataFrame(
        {"zip": ["60601", "60602"]}, geometry=[_square(), None], crs="EPSG:4326"
    )

    features = parseOutput(gdf)["data"]["features"]

    assert features[0]["geometry"]["type"] == "Polygon"
    assert features[1]["geometry"] is None


def test_an_all_null_geometry_column():
    # D10. Still a GeoDataFrame, still has an active column name.
    gdf = gpd.GeoDataFrame(
        {"zip": ["60601", "60602"]}, geometry=[None, None], crs="EPSG:4326"
    )

    data = parseOutput(gdf)["data"]

    assert data["geometry_name"] == "geometry"
    assert [f["geometry"] for f in data["features"]] == [None, None]


# --- D12-D15: exotic geometry ------------------------------------------------

def test_multipolygon():
    gdf = gpd.GeoDataFrame(
        {"zip": ["60601"]},
        geometry=[MultiPolygon([_square(), _square(3.0, 3.0)])],
        crs="EPSG:4326",
    )

    assert parseOutput(gdf)["data"]["features"][0]["geometry"]["type"] == "MultiPolygon"


def test_geometry_collection():
    gdf = gpd.GeoDataFrame(
        {"zip": ["60601"]},
        geometry=[GeometryCollection([_square(), Point(9.0, 9.0)])],
        crs="EPSG:4326",
    )

    geom = parseOutput(gdf)["data"]["features"][0]["geometry"]

    assert geom["type"] == "GeometryCollection"
    assert [g["type"] for g in geom["geometries"]] == ["Polygon", "Point"]


def test_mixed_geometry_types_in_one_column():
    gdf = gpd.GeoDataFrame(
        {"zip": ["a", "b", "c"]},
        geometry=[_square(), Point(1.0, 1.0), LineString([(0, 0), (1, 1)])],
        crs="EPSG:4326",
    )

    types = [f["geometry"]["type"] for f in parseOutput(gdf)["data"]["features"]]

    assert types == ["Polygon", "Point", "LineString"]


def test_z_coordinates_survive():
    gdf = gpd.GeoDataFrame(
        {"zip": ["60601"]}, geometry=[Point(1.0, 2.0, 3.0)], crs="EPSG:4326"
    )

    coords = parseOutput(gdf)["data"]["features"][0]["geometry"]["coordinates"]

    assert coords == [1.0, 2.0, 3.0]


# --- D16: empty --------------------------------------------------------------

def test_an_empty_geodataframe_is_an_empty_feature_collection():
    gdf = _frame().iloc[0:0]

    data = parseOutput(gdf)["data"]

    assert data["type"] == "FeatureCollection"
    assert data["features"] == []
    assert data["geometry_name"] == "geometry"


# --- schema ------------------------------------------------------------------

# pandas 3 reports a string column's dtype as 'str'; pandas 2 said 'object'.
# Anything classifying columns by dtype string has to accept both, so the
# tolerance is stated here once rather than hidden in each assertion.
STRING_DTYPES = {"str", "object"}


def test_schema_is_emitted_for_a_geodataframe():
    schema = parseOutput(_frame())["schema"]

    assert schema["zip"] in STRING_DTYPES
    assert schema["pop"].startswith("int")
    assert schema["geometry"] == "geometry"


def test_schema_is_emitted_for_a_plain_dataframe_too():
    # The default-spec chooser reads this for bar/line/scatter as much as for
    # maps, so it must not be a geo-only key.
    df = pd.DataFrame({"pop": [1, 2], "name": ["a", "b"]})

    out = parseOutput(df)

    assert out["dataType"] == "dataframe"
    assert out["schema"]["name"] in STRING_DTYPES
    assert out["schema"]["pop"].startswith("int")


def test_schema_names_a_secondary_geometry_column_as_geometry():
    gdf = _frame()
    gdf["centroid"] = gdf.geometry.centroid

    schema = parseOutput(gdf)["schema"]

    assert schema["centroid"] == "geometry"
