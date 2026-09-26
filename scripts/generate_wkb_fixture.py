"""Generate the WKB golden fixture from shapely, the encoder that writes it.

    python scripts/generate_wkb_fixture.py

The frontend decodes GeoParquet's WKB geometry into GeoJSON, and this fixture
is how that decoder is tested: real bytes from the library that produces them,
alongside the GeoJSON shapely itself says they mean. It is committed rather
than generated at test time so the frontend suite needs no Python, and it is
pinned by utk_curio/backend/tests/test_wkb_fixture.py, which regenerates and
compares so the two cannot drift apart.

Both byte orders are covered because WKB carries an endianness flag, and a
decoder that ignores it reads little-endian data correctly by luck.
"""
import json
from pathlib import Path

from shapely import wkb as shapely_wkb
from shapely.geometry import (
    GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon,
    Point, Polygon, shape,
)

CASES = {
    "point": Point(1.5, -2.25),
    "point_z": Point(1.0, 2.0, 3.0),
    "linestring": LineString([(0, 0), (1, 1), (2, 0.5)]),
    "polygon": Polygon([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)],
                       [[(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]]),
    "multipoint": MultiPoint([(0, 0), (1, 1)]),
    "multilinestring": MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]]),
    "multipolygon": MultiPolygon([
        Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]),
        Polygon([(2, 2), (3, 2), (3, 3), (2, 2)]),
    ]),
    "geometrycollection": GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 1)])]),
    "empty_point": Point(),
    "empty_polygon": Polygon(),
}

out = {}
for name, geom in CASES.items():
    for order, big_endian in (("little", False), ("big", True)):
        encoded = shapely_wkb.dumps(geom, big_endian=big_endian, hex=True)
        key = name if order == "little" else f"{name}_big_endian"
        out[key] = {
            "wkb_hex": encoded,
            "geojson": json.loads(json.dumps(geom.__geo_interface__)),
        }

path = Path("utk_curio/frontend/urban-workflows/src/tests/fixtures/wkb-geometries.json")
path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
print(f"wrote {len(out)} cases to {path}")
