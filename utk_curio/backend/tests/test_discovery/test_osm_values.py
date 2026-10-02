"""OpenStreetMap tags that hold a number, written as numbers (``domain/osm_values.py``)."""
from __future__ import annotations

import copy
import json

import pytest

from utk_curio.backend.app.discovery.domain.osm_values import (
    COUNT_KEYS,
    LENGTH_KEYS,
    NUMERIC_KEYS,
    SPEED_KEYS,
    number,
    with_numbers,
)


@pytest.mark.parametrize("raw, expected", [
    ("12", 12), (" 12 ", 12), ("12.5", 12.5), (".5", 0.5), ("5.", 5), ("+3", 3), ("-2", -2),
    ("12 m", 12), ("12m", 12), ("12 M", 12), ("1.2 km", 1200),
    ("40 ft", 12.19), ("1 mi", 1609.34), ("1 nmi", 1852),
    ("10'0\"", 3.05), ("12'", 3.66), ("6\"", 0.15), ("12' 6\"", 3.81),
    ("none", None), ("3;4", None), ("~10", None), ("10-12", None), ("1e3", None),
    ("nan", None), ("inf", None), ("2,5", None), ("12 metres", None), ("12 mph", None), ("", None),
])
def test_a_length_is_in_metres(raw, expected):
    assert number("height", raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("40", 40), ("50 km/h", 50), ("45 mph", 72.42), ("25 mph", 40.23), ("30mph", 48.28), ("45 MPH", 72.42),
    ("10 knots", 18.52),
    ("none", None), ("signals", None), ("walk", None), ("RU:urban", None), ("50 kph", None),
    ("50;30", None), ("12 m", None),
])
def test_a_speed_is_in_kilometres_per_hour(raw, expected):
    assert number("maxspeed", raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("2", 2), ("-1", -1), ("1.5", 1.5), ("2 m", None), ("3;4", None), ("two", None),
])
def test_a_count_takes_no_unit(raw, expected):
    assert number("building:levels", raw) == expected


def test_whole_numbers_are_ints():
    assert isinstance(number("lanes", "2"), int)
    assert isinstance(number("height", "12.0"), int)
    assert isinstance(number("height", "12.25"), float)


def test_a_value_that_is_already_a_number_is_kept():
    assert number("height", 12) == 12
    assert number("height", 12.346) == 12.35
    assert number("height", float("nan")) is None
    assert number("height", float("inf")) is None
    assert number("height", True) is None
    assert number("height", None) is None


def test_only_the_listed_keys_are_numbers():
    assert not (LENGTH_KEYS & SPEED_KEYS or LENGTH_KEYS & COUNT_KEYS or SPEED_KEYS & COUNT_KEYS)
    with pytest.raises(KeyError):
        number("ref", "12")


def _collection(*properties):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": p}
        for p in properties
    ]}


def test_with_numbers_changes_the_listed_keys_alone():
    tags = {
        "height": "12", "maxspeed": "45 mph", "lanes": "2",
        "ref": "12", "addr:housenumber": "12", "maxweight": "3.5", "maxweight:signed": "no",
        "name": "Golf Road", "osm_type": "way", "osm_id": 501, "building_id": 3,
    }
    original = _collection(tags)
    before = copy.deepcopy(original)
    (feature,) = with_numbers(original)["features"]
    assert feature["properties"] == {
        **tags, "height": 12, "maxspeed": 72.42, "lanes": 2,
    }
    assert original == before


def test_no_text_is_left_in_a_listed_key():
    words = ["12", "none", "3;4", "40 ft", "", "signals", "2,5", "1e3", "x"]
    collection = _collection(*({key: word for key in NUMERIC_KEYS} for word in words))
    for feature in with_numbers(collection)["features"]:
        for key in NUMERIC_KEYS:
            assert feature["properties"][key] is None or isinstance(feature["properties"][key], (int, float))
    # And the GeoJSON stays valid JSON: no NaN or Infinity.
    json.dumps(with_numbers(collection), allow_nan=False)


def test_a_feature_without_properties_stays_without():
    collection = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None, "properties": None}]}
    assert with_numbers(collection)["features"][0]["properties"] is None


def test_the_columns_read_as_numbers(tmp_path):
    """GDAL types a GeoJSON property String when any value is text, so a
    column is numeric only when no text is left in it."""
    gpd = pytest.importorskip("geopandas")
    import pandas as pd

    collection = with_numbers(_collection(
        {"height": "12", "maxspeed": "none"},
        {"name": "no height"},
        {"height": "none", "maxspeed": "signals"},
        {"height": "40 ft", "maxspeed": "walk"},
    ))
    path = tmp_path / "layer.geojson"
    path.write_text(json.dumps(collection))
    frame = gpd.read_file(path)
    assert pd.api.types.is_numeric_dtype(frame["height"])
    assert frame["height"].tolist()[0] == 12 and frame["height"].tolist()[3] == 12.19
    assert frame["height"].isna().tolist() == [False, True, True, False]
    assert frame["maxspeed"].isna().all()
