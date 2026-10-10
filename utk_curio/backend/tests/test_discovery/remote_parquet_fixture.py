"""Made-up GeoParquet files for an Area on a remote GeoParquet file (#608).

A Direct URL link and a bucket row that point at a GeoParquet file take an
Area, and only the row groups that meet it are read. The tests read small
files written here, served as the recorded corpus serves any file: each byte
range under its own key, ``<url> bytes=a-b``.

- ``blocks.parquet``: GeoParquet 1.1 with a ``bbox`` covering column, five row
  groups. A long ``notes`` column puts its first row groups well before the
  last 64 KiB, which the reader fetches with the footer.
- ``plain.parquet``: GeoParquet with no box column.
- ``projected.parquet``: GeoParquet in EPSG:3857, with a covering column.
- ``table.parquet``: Parquet with no ``geo`` metadata.

The ranges are the ones ``infrastructure/remote_parquet.py`` asks for once it
knows a file's size: the last 8 bytes, the footer, and each row group. A link
is first asked for its size with a one-byte range, answered with
``Content-Range``. The ranges are found by running that reader over the files.

    python utk_curio/backend/tests/test_discovery/remote_parquet_fixture.py

writes the ranges, the bucket's listings and their entries in
``fixtures/index.json``; with ``--parquet`` it writes the GeoParquet files
first. A test checks that both are current. The features are made up.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROOT = FIXTURES / "remote_parquet"
INDEX = FIXTURES / "index.json"

#: Where the Direct URL links point.
PORTAL = "https://portal.test"
#: A public bucket, read by the s3 provider.
BUCKET = "https://bucket.test"

#: The box the tests ask for, [west, south, east, north]: Chicago's Loop.
TEST_BOX = [-87.64, 41.87, -87.62, 41.89]

ROWS_PER_GROUP = 4

#: Characters of ``notes`` per row of ``blocks.parquet``: about 40 KB a row group.
NOTES_CHARS = 10_000

#: Block centres, four to a row group. Group 0 is inside the box; group 1 has
#: two rows inside and two to the east; groups 2 to 4 are far to the south,
#: north and west.
BLOCKS = [
    (-87.635, 41.875), (-87.63, 41.88), (-87.625, 41.885), (-87.632, 41.884),
    (-87.628, 41.872), (-87.622, 41.888), (-87.6, 41.88), (-87.59, 41.88),
    (-87.65, 41.8), (-87.66, 41.79), (-87.67, 41.78), (-87.68, 41.77),
    (-87.7, 41.95), (-87.71, 41.96), (-87.72, 41.97), (-87.73, 41.98),
    (-87.8, 41.88), (-87.81, 41.88), (-87.82, 41.88), (-87.83, 41.88),
]
INSIDE_BLOCKS = [f"b{i:02d}" for i in range(6)]

#: Places with no box column: two inside and two to the east, four far to the
#: south, then one inside and three far to the north.
PLAIN = [
    (-87.635, 41.875), (-87.625, 41.885), (-87.6, 41.88), (-87.59, 41.88),
    (-87.65, 41.8), (-87.66, 41.79), (-87.67, 41.78), (-87.68, 41.77),
    (-87.63, 41.88), (-87.7, 41.95), (-87.71, 41.96), (-87.72, 41.97),
]
INSIDE_PLAIN = ["p00", "p01", "p08"]

#: The same places as the first twelve blocks, in Web Mercator: group 0 inside.
PROJECTED = BLOCKS[:4] + BLOCKS[8:16]
INSIDE_PROJECTED = [f"q{i:02d}" for i in range(4)]

#: Direct URL links: the file name at the portal, and the file here.
LINKS = {
    "blocks.parquet": "blocks.parquet",
    "plain.parquet": "plain.parquet",
    "projected.parquet": "projected.parquet",
    "table.parquet": "table.parquet",
}

#: A link whose server ignores ``Range`` and sends the whole file.
NO_RANGES = "no-ranges.parquet"

#: The bucket's files: the key, and the file here.
BUCKET_FILES = {
    "blocks/loop.parquet": "blocks.parquet",
    "parts/a.parquet": "blocks.parquet",
    "parts/b.parquet": "plain.parquet",
}

#: The listings a scan of the bucket asks for: the whole bucket, then one
#: resource's folder for its add.
LISTINGS = ("", "blocks/", "parts/")


def _square(cx: float, cy: float, half: float = 0.0002):
    from shapely.geometry import Polygon

    return Polygon([(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half),
                    (cx - half, cy + half), (cx - half, cy - half)])


def _geo(*, covering: bool, crs: dict | None = None) -> bytes:
    column: dict = {"encoding": "WKB", "geometry_types": ["Polygon"]}
    if covering:
        column["covering"] = {"bbox": {
            "xmin": ["bbox", "xmin"], "ymin": ["bbox", "ymin"],
            "xmax": ["bbox", "xmax"], "ymax": ["bbox", "ymax"],
        }}
    if crs is not None:
        column["crs"] = crs
    return json.dumps({"version": "1.1.0", "primary_column": "geometry",
                       "columns": {"geometry": column}}).encode("utf-8")


def _bbox_struct(geoms):
    import pyarrow as pa

    bounds = [g.bounds for g in geoms]
    return pa.StructArray.from_arrays(
        [pa.array([b[i] for b in bounds], pa.float64()) for i in range(4)],
        names=["xmin", "ymin", "xmax", "ymax"],
    )


def _notes(block_id: str) -> str:
    """Text that does not compress, the same on every run."""
    out, n = [], 0
    while sum(len(part) for part in out) < NOTES_CHARS:
        out.append(hashlib.sha256(f"{block_id}-{n}".encode()).hexdigest())
        n += 1
    return "".join(out)[:NOTES_CHARS]


#: Statistics only for the box columns and the ids: the notes' would make the
#: footer as long as the file.
_STATISTICS = ["id", "bbox.xmin", "bbox.ymin", "bbox.xmax", "bbox.ymax"]


def write_parquet() -> None:
    """Write the GeoParquet files. Run only to change them: the ranges and
    the index follow from the files committed."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from pyproj import CRS, Transformer
    from shapely.ops import transform

    folder = ROOT / "files"
    folder.mkdir(parents=True, exist_ok=True)
    options = {"row_group_size": ROWS_PER_GROUP, "compression": "none", "use_dictionary": False,
               "write_statistics": _STATISTICS}

    geoms = [_square(x, y) for x, y in BLOCKS]
    ids = [f"b{i:02d}" for i in range(len(geoms))]
    pq.write_table(pa.table({
        "id": ids,
        "name": [f"Block {i}" for i in range(len(geoms))],
        "floors": pa.array([1 + i % 5 for i in range(len(geoms))], pa.int32()),
        "notes": [_notes(i) for i in ids],
        "geometry": pa.array([g.wkb for g in geoms], pa.binary()),
        "bbox": _bbox_struct(geoms),
    }).replace_schema_metadata({b"geo": _geo(covering=True)}), folder / "blocks.parquet", **options)

    geoms = [_square(x, y) for x, y in PLAIN]
    pq.write_table(pa.table({
        "id": [f"p{i:02d}" for i in range(len(geoms))],
        "name": [f"Place {i}" for i in range(len(geoms))],
        "geometry": pa.array([g.wkb for g in geoms], pa.binary()),
    }).replace_schema_metadata({b"geo": _geo(covering=False)}), folder / "plain.parquet",
        **{**options, "write_statistics": ["id"]})

    to_mercator = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
    geoms = [transform(to_mercator, _square(x, y)) for x, y in PROJECTED]
    pq.write_table(pa.table({
        "id": [f"q{i:02d}" for i in range(len(geoms))],
        "geometry": pa.array([g.wkb for g in geoms], pa.binary()),
        "bbox": _bbox_struct(geoms),
    }).replace_schema_metadata({b"geo": _geo(covering=True, crs=CRS.from_epsg(3857).to_json_dict())}),
        folder / "projected.parquet", **options)

    pq.write_table(pa.table({"id": ["t00", "t01", "t02"], "value": [1, 2, 3]}),
                   folder / "table.parquet", compression="none")


class _LocalFiles:
    """A transport that answers a file's ranges from the file here, and keeps
    each range asked for."""

    def __init__(self, path: Path) -> None:
        self.blob = path.read_bytes()
        self.asked: list[tuple[int, int]] = []

    def download(self, url, sink, *, max_bytes, ceiling=None, headers=None, **_):
        first, last = (int(v) for v in headers["Range"].removeprefix("bytes=").split("-"))
        self.asked.append((first, last))
        sink(self.blob[first:last + 1])


def _ranges(path: Path) -> list[tuple[int, int]]:
    """The ranges the reader asks of *path*: the tail, the footer and every row group."""
    from utk_curio.backend.app.discovery.infrastructure.remote_parquet import RemoteParquet

    local = _LocalFiles(path)
    remote = RemoteParquet(local, "file", path.stat().st_size, max_footer_bytes=1 << 20)
    for g in range(remote.metadata.num_row_groups):
        remote.read_row_group(g)
    return local.asked


def _listing(keys: list[tuple[str, int]]) -> str:
    contents = "".join(
        f"<Contents><Key>{key}</Key><Size>{size}</Size><LastModified>2026-01-01T00:00:00.000Z</LastModified>"
        f"<ETag>\"e{i}\"</ETag></Contents>"
        for i, (key, size) in enumerate(keys)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<IsTruncated>false</IsTruncated>{contents}</ListBucketResult>"
    )


def documents() -> dict[str, tuple[str, bytes, dict]]:
    """Every answer: ``{key: (fixture file, body, index entry)}``."""
    from urllib.parse import quote

    out: dict[str, tuple[str, bytes, dict]] = {}

    def add(key: str, name: str, body: bytes, headers: dict, status: int) -> None:
        out[key] = (name, body, {"file": f"remote_parquet/{name}", "headers": headers, "status": status})

    octets = "application/octet-stream"
    for local in sorted(set(LINKS.values()) | set(BUCKET_FILES.values())):
        path = ROOT / "files" / local
        blob, size, stem = path.read_bytes(), path.stat().st_size, local.removesuffix(".parquet")
        urls = [f"{PORTAL}/{name}" for name, file in LINKS.items() if file == local]
        urls += [f"{BUCKET}/{key}" for key, file in BUCKET_FILES.items() if file == local]
        asked = [(0, 0)] + _ranges(path)
        for url in urls:
            for first, last in asked:
                if (first, last) == (0, 0) and url.startswith(BUCKET):
                    # A bucket row's size is in its listing: it is never probed.
                    continue
                add(f"{url} bytes={first}-{last}", f"ranges/{stem}-{first}-{last}.bin", blob[first:last + 1],
                    {"Content-Range": f"bytes {first}-{last}/{size}", "Content-Type": octets}, 206)
    blocks = ROOT / "files" / "blocks.parquet"
    add(f"{PORTAL}/blocks.parquet", "files/blocks.parquet", blocks.read_bytes(), {"Content-Type": octets}, 200)
    add(f"{PORTAL}/{NO_RANGES} bytes=0-0", "files/blocks.parquet", blocks.read_bytes(),
        {"Content-Length": str(blocks.stat().st_size), "Content-Type": octets}, 200)
    sizes = {key: (ROOT / "files" / local).stat().st_size for key, local in BUCKET_FILES.items()}
    for prefix in LISTINGS:
        keys = [(key, size) for key, size in sorted(sizes.items()) if key.startswith(prefix)]
        name = f"listing-{prefix.strip('/') or 'all'}.xml"
        add(f"{BUCKET}/?list-type=2&max-keys=1000&prefix={quote(prefix, safe='')}", name,
            _listing(keys).encode("utf-8"), {"Content-Type": "application/xml"}, 200)
    return out


def write() -> None:
    """Write the ranges, the listings and their index entries."""
    answers = documents()
    for name, body, _ in answers.values():
        target = ROOT / name
        if name.startswith("files/"):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    index = {key: entry for key, entry in index.items() if not entry.get("file", "").startswith("remote_parquet/")}
    index.update({key: entry for key, (_, _, entry) in answers.items()})
    INDEX.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    if "--parquet" in sys.argv:
        write_parquet()
    write()
