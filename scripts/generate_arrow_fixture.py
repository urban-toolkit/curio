"""Generate a small Arrow artifact fixture, both wire formats, for the frontend.

    python scripts/generate_arrow_fixture.py

Written by the real code path: a GeoDataFrame saved through
``parsers.save_to_duckdb`` and read back both ways, so the frontend's adapter
is tested against bytes the sandbox would really send and against the exact
JSON envelope it would otherwise have produced. Pinned by
utk_curio/backend/tests/test_arrow_fixture.py.
"""
import base64
import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = (REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src"
       / "tests" / "fixtures" / "arrow-geodataframe.json")

tmp = tempfile.mkdtemp()
os.environ["CURIO_LAUNCH_CWD"] = tmp
os.environ["CURIO_SHARED_DATA"] = "./.curio/data/"
(Path(tmp) / ".curio" / "data").mkdir(parents=True, exist_ok=True)

import geopandas as gpd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.ipc as ipc  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402

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

table, kind, frame_metadata, encoded = parsers.load_tabular_arrow_from_duckdb(
    art_id, allow_geometry=True
)
sink = pa.BufferOutputStream()
with ipc.new_stream(sink, table.schema) as writer:
    writer.write_table(table)
body = sink.getvalue().to_pybytes()

OUT.write_text(json.dumps({
    "arrow_base64": base64.b64encode(body).decode("ascii"),
    "headers": {
        "X-Curio-Kind": kind,
        "X-Curio-Filename": art_id,
        "X-Curio-Schema": json.dumps(parsers.arrow_frame_schema(table)),
        **({"X-Curio-Encoded-Object-Columns": ",".join(encoded)} if encoded else {}),
        **({"X-Curio-Frame-Metadata": json.dumps(frame_metadata)} if frame_metadata else {}),
    },
    "json_envelope": envelope,
}, indent=2, sort_keys=True) + "\n")
print(f"wrote {OUT} ({len(body)} arrow bytes)")
