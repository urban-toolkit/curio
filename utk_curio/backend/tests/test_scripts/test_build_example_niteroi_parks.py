"""The parks of Niterói example 36 loads, each with its area
(``scripts/build_example_niteroi_parks.py``).

The committed ``docs/examples/data/niteroi_parks.geojson`` agrees with itself
and with the extract it was built from: each park is a polygon whose ``area``
is its outline's area in the script's equal-area projection, in square metres,
and names an element of ``niteroi.osm.pbf`` (read with ``_support/osm_pbf.py``,
no pyosmium) whose tags are a park's as autk-db's parks layer reads them.

The script is loaded inside each test: it must load without pyosmium, which
is not one of Curio's dependencies.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from utk_curio.backend.tests._support.osm_pbf import read_pbf

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "build_example_niteroi_parks.py"
PARKS = REPO_ROOT / "docs" / "examples" / "data" / "niteroi_parks.geojson"
EXTRACT = REPO_ROOT / "docs" / "examples" / "data" / "niteroi.osm.pbf"


def _script():
    spec = importlib.util.spec_from_file_location("_scripts_build_example_niteroi_parks", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit as exc:
        raise AssertionError(f"the script must load without pyosmium: {exc}") from None
    return module


def _parks() -> list[dict]:
    return json.loads(PARKS.read_text(encoding="utf-8"))["features"]


def test_a_park_is_what_autk_dbs_parks_layer_takes_by_its_tags():
    script = _script()

    assert script.is_park({"leisure": "park"})
    assert script.is_park({"landuse": "forest", "name": "Mata"})
    assert script.is_park({"natural": "scrub"})
    assert not script.is_park({"leisure": "pitch"})
    assert not script.is_park({"natural": "water"})
    assert not script.is_park({"landuse": "residential"})


def test_each_park_carries_the_area_of_its_outline_in_square_metres():
    from shapely.geometry import shape

    script = _script()
    parks = _parks()

    assert len(parks) > 100
    for park in parks:
        geometry = shape(park["geometry"])
        assert geometry.geom_type in ("Polygon", "MultiPolygon") and geometry.is_valid, park["properties"]
        assert abs(script.equal_area(geometry) - park["properties"]["area"]) <= 1, park["properties"]


def test_each_park_is_a_park_element_of_the_extract_it_was_built_from():
    script = _script()
    extract = read_pbf(EXTRACT)
    elements = {"way": extract.ways, "relation": extract.relations}

    for park in _parks():
        kind, ref = park["properties"]["osm_type"], park["properties"]["osm_id"]
        assert ref in elements[kind], f"{kind} {ref} is not in {EXTRACT.name}"
        assert script.is_park(elements[kind][ref][1]), f"{kind} {ref} is not tagged as a park"


def test_the_parks_are_in_the_order_of_their_elements_once_each():
    keys = [(park["properties"]["osm_type"], park["properties"]["osm_id"]) for park in _parks()]

    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
