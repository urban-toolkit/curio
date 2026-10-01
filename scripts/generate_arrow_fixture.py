"""Generate a small Arrow artifact fixture, both wire formats, for the frontend.

    python scripts/generate_arrow_fixture.py

Written by the real code path: a GeoDataFrame saved through
``parsers.save_to_duckdb`` and fetched from the sandbox's own ``/get`` route
both ways, so the frontend's adapter is tested against the bytes and headers
the sandbox really sends and against the exact JSON envelope it would
otherwise have produced. Pinned by utk_curio/backend/tests/test_arrow_fixture.py.
"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Importable from any cwd and any PYTHONPATH: the pinning test spawns this script
# from the repo root, and ``python scripts/generate_arrow_fixture.py`` puts only
# ``scripts/`` on sys.path.
sys.path.insert(0, str(REPO_ROOT))
OUT = (REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src"
       / "tests" / "fixtures" / "arrow-geodataframe.json")

tmp = tempfile.mkdtemp()
os.environ["CURIO_LAUNCH_CWD"] = tmp
os.environ["CURIO_SHARED_DATA"] = "./.curio/data/"
# The route is asked directly, as the sandbox unit suite does (its conftest):
# an inherited shared secret, which the CI container sets, would turn every
# request into a 401. The fixture is about the wire shape, not the auth.
os.environ.pop("CURIO_SANDBOX_TOKEN", None)
(Path(tmp) / ".curio" / "data").mkdir(parents=True, exist_ok=True)

import geopandas as gpd  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402

from utk_curio.sandbox.app import app  # noqa: E402
from utk_curio.sandbox.app.api import ARROW_IPC_MIME  # noqa: E402
from utk_curio.sandbox.util import parsers  # noqa: E402
from utk_curio.sandbox.util.db import init_db  # noqa: E402

init_db()
gdf = gpd.GeoDataFrame(
    {
        "id": [1, 2, 3],
        "name": ["a", "b", "c"],
        "value": [1.5, 2.5, 3.5],
        "geometry": [
            Point(-87.6298, 41.8781),
            LineString([(-87.63, 41.88), (-87.62, 41.89)]),
            Polygon([(-87.65, 41.87), (-87.64, 41.87), (-87.64, 41.88), (-87.65, 41.87)]),
        ],
    },
    crs="EPSG:4326",
)
# A second geometry column, which the shipped examples do
# (`gdf["bbox"] = gdf.geometry.envelope`) and which is WKB in GeoParquet just
# like the active one. Passing it through undecoded is what blanked a chart.
gdf["bbox"] = gdf.geometry.envelope
art_id = parsers.save_to_duckdb(gdf, "fixture-node")

envelope = parsers.parseOutput(parsers.load_from_duckdb(art_id))
envelope["filename"] = art_id

response = app.test_client().get(
    "/get", query_string={"fileName": art_id},
    headers={"Accept": ARROW_IPC_MIME, "X-Curio-Accept-Geometry": "wkb"},
)
assert response.status_code == 200, response.get_data(as_text=True)
body = response.get_data()

OUT.write_text(json.dumps({
    "arrow_base64": base64.b64encode(body).decode("ascii"),
    # Every header the route sends that the adapter reads: the X-Curio set.
    "headers": {
        key: value for key, value in response.headers.items()
        if key.lower().startswith("x-curio-")
    },
    "json_envelope": envelope,
}, indent=2, sort_keys=True) + "\n")
print(f"wrote {OUT} ({len(body)} arrow bytes)")
