"""Made-up Overture Maps answers for the Overture source's tests.

Overture's real files are half a gigabyte each, so the tests read small files
written here in Overture's layout instead: a STAC catalog naming a release, a
collection per feature type listing its files' boxes, an item per file, and
GeoParquet files whose ``bbox`` column carries row-group statistics.

The recorded corpus answers a byte range by its own key, ``<url> bytes=a-b``.
The ranges are the ones ``infrastructure/remote_parquet.py`` asks for: each
file's last 8 bytes, its footer, and each of its row groups. They are found by
running that reader over the files here, so they are the reader's own.

    python utk_curio/backend/tests/test_discovery/overture_fixture.py

writes the catalog, the ranges and their entries in ``fixtures/index.json``;
with ``--parquet`` it writes the GeoParquet files first. A test checks that
both are current. The features are made up. They are not Overture data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROOT = FIXTURES / "overture"
INDEX = FIXTURES / "index.json"

STAC = "https://stac.overturemaps.org"
DATA_HOST = "overturemaps-us-west-2.s3.us-west-2.amazonaws.com"
#: A release that never existed, so no one takes these for Overture's.
RELEASE = "2000-01-01.0"

#: The box the tests ask for, [west, south, east, north]: about Brás, São Paulo.
TEST_BOX = [-46.63, -23.56, -46.6, -23.53]

#: Rows per row group in the files written here.
ROWS_PER_GROUP = 4


def _square(cx: float, cy: float, half: float = 0.0002):
    from shapely.geometry import Polygon

    return Polygon([(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half),
                    (cx - half, cy + half), (cx - half, cy - half)])


def _line(x0: float, y0: float, x1: float, y1: float):
    from shapely.geometry import LineString

    return LineString([(x0, y0), (x1, y1)])


#: Where each file's features are. Buildings, file 0: its first row group
#: inside the box, its second half inside and half to the east, its third
#: far to the south-east. File 1 is in Germany.
BUILDINGS = {
    "part-00000": [
        (-46.62, -23.55), (-46.615, -23.545), (-46.61, -23.54), (-46.605, -23.535),
        (-46.6025, -23.5325), (-46.601, -23.531), (-46.59, -23.531), (-46.585, -23.532),
        (-46.55, -23.45), (-46.54, -23.44), (-46.53, -23.43), (-46.52, -23.42),
    ],
    "part-00001": [(10.0, 50.0), (10.01, 50.01), (10.02, 50.02), (10.03, 50.03)],
}

#: Road segments, one file of one row group: two roads and a railway in the box.
SEGMENTS = {
    "part-00000": [
        ("road", (-46.625, -23.555, -46.62, -23.55)),
        ("road", (-46.61, -23.54, -46.605, -23.535)),
        ("rail", (-46.615, -23.545, -46.61, -23.54)),
    ],
}


def _file_url(theme: str, kind: str, name: str) -> str:
    return f"https://{DATA_HOST}/release/{RELEASE}/theme={theme}/type={kind}/{name}-synthetic.zstd.parquet"


def _geo(types: list[str]) -> bytes:
    return json.dumps({
        "version": "1.1.0",
        "primary_column": "geometry",
        "columns": {"geometry": {
            "encoding": "WKB",
            "geometry_types": types,
            "covering": {"bbox": {
                "xmin": ["bbox", "xmin"], "ymin": ["bbox", "ymin"],
                "xmax": ["bbox", "xmax"], "ymax": ["bbox", "ymax"],
            }},
        }},
    }).encode("utf-8")


def _bbox_struct(geoms):
    import pyarrow as pa

    bounds = [g.bounds for g in geoms]
    return pa.StructArray.from_arrays(
        [pa.array([b[i] for b in bounds], pa.float32()) for i in range(4)],
        names=["xmin", "ymin", "xmax", "ymax"],
    )


def _sources(ids: list[str]):
    import pyarrow as pa

    kind = pa.list_(pa.struct([("dataset", pa.string()), ("record_id", pa.string())]))
    return pa.array([[{"dataset": "Made up", "record_id": i}] for i in ids], kind)


def write_parquet() -> None:
    """Write the GeoParquet files. Run only to change them: the ranges and
    the index follow from the files committed."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    folder = ROOT / "files"
    folder.mkdir(parents=True, exist_ok=True)
    for name, centres in BUILDINGS.items():
        geoms = [_square(x, y) for x, y in centres]
        ids = [f"{name}-b{i:02d}" for i in range(len(geoms))]
        table = pa.table({
            "id": ids,
            "names": pa.array(
                [{"primary": f"Building {i}"} if i % 3 else None for i in range(len(geoms))],
                pa.struct([("primary", pa.string())]),
            ),
            "sources": _sources(ids),
            "height": pa.array([None if i % 4 == 3 else 3.0 + i for i in range(len(geoms))], pa.float64()),
            "subtype": ["residential" if i % 2 else "commercial" for i in range(len(geoms))],
            "class": ["house"] * len(geoms),
            "geometry": pa.array([g.wkb for g in geoms], pa.binary()),
            "bbox": _bbox_struct(geoms),
        }).replace_schema_metadata({b"geo": _geo(["Polygon"])})
        pq.write_table(table, folder / f"buildings-{name}.parquet", row_group_size=ROWS_PER_GROUP,
                       compression="zstd")
    for name, rows in SEGMENTS.items():
        geoms = [_line(*coords) for _, coords in rows]
        ids = [f"{name}-s{i:02d}" for i in range(len(geoms))]
        table = pa.table({
            "id": ids,
            "names": pa.array([{"primary": f"Street {i}"} for i in range(len(geoms))],
                              pa.struct([("primary", pa.string())])),
            "subtype": [subtype for subtype, _ in rows],
            "class": ["residential" if subtype == "road" else "standard_gauge" for subtype, _ in rows],
            "sources": _sources(ids),
            "geometry": pa.array([g.wkb for g in geoms], pa.binary()),
            "bbox": _bbox_struct(geoms),
        }).replace_schema_metadata({b"geo": _geo(["LineString"])})
        pq.write_table(table, folder / f"segments-{name}.parquet", row_group_size=ROWS_PER_GROUP,
                       compression="zstd")


#: Each feature type: (theme, type, license, {file name: local file}).
TYPES = {
    ("buildings", "building"): ("ODbL-1.0", {name: f"buildings-{name}.parquet" for name in BUILDINGS}),
    ("transportation", "segment"): ("ODbL-1.0", {name: f"segments-{name}.parquet" for name in SEGMENTS}),
}


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _file_box(path: Path) -> list[float]:
    import pyarrow.parquet as pq

    bbox = pq.read_table(path, columns=["bbox"]).column("bbox").combine_chunks()
    return [
        float(min(bbox.field("xmin").to_pylist())), float(min(bbox.field("ymin").to_pylist())),
        float(max(bbox.field("xmax").to_pylist())), float(max(bbox.field("ymax").to_pylist())),
    ]


class _LocalFiles:
    """A transport that answers a file's ranges from the file here, and keeps
    each range asked for."""

    def __init__(self, files: dict[str, Path]) -> None:
        self.files = files
        self.asked: list[tuple[str, int, int]] = []

    def download(self, url, sink, *, max_bytes, ceiling=None, headers=None, **_):
        first, last = (int(v) for v in headers["Range"].removeprefix("bytes=").split("-"))
        blob = self.files[url].read_bytes()[first:last + 1]
        self.asked.append((url, first, last))
        sink(blob)


def documents() -> dict[str, tuple[str, bytes, dict]]:
    """Every answer: ``{key: (fixture file, body, index entry)}``."""
    from utk_curio.backend.app.discovery.infrastructure.remote_parquet import RemoteParquet

    out: dict[str, tuple[str, bytes, dict]] = {}

    def add(key: str, name: str, body: bytes, content_type: str, status: int = 200) -> None:
        out[key] = (name, body, {"file": f"overture/{name}", "headers": {"Content-Type": content_type},
                                 "status": status})

    add(f"{STAC}/catalog.json", "catalog.json",
        json.dumps({"type": "Catalog", "id": "Overture Releases", "latest": RELEASE}, indent=1).encode(),
        "application/json")
    for (theme, kind), (license_, files) in TYPES.items():
        paths = {name: ROOT / "files" / local for name, local in files.items()}
        boxes = {name: _file_box(path) for name, path in paths.items()}
        items = []
        for index, name in enumerate(sorted(paths)):
            item_url = f"{STAC}/{RELEASE}/{theme}/{kind}/{index:05d}/{index:05d}.json"
            items.append(item_url)
            item = {
                "type": "Feature", "id": f"{index:05d}", "bbox": boxes[name],
                "assets": {"aws": {"href": _file_url(theme, kind, name), "file:size": paths[name].stat().st_size}},
            }
            add(item_url, f"{theme}-{kind}-{index:05d}.json", json.dumps(item, indent=1).encode(),
                "application/geo+json")
        collection = {
            "type": "Collection", "id": kind, "license": license_,
            "extent": {"spatial": {"bbox": [_union(boxes.values())] + [boxes[n] for n in sorted(paths)]}},
            "links": [{"rel": "item", "href": href} for href in items],
        }
        add(f"{STAC}/{RELEASE}/{theme}/{kind}/collection.json", f"{theme}-{kind}-collection.json",
            json.dumps(collection, indent=1).encode(), "application/json")
        local = _LocalFiles({_file_url(theme, kind, name): path for name, path in paths.items()})
        for name, path in sorted(paths.items()):
            url = _file_url(theme, kind, name)
            remote = RemoteParquet(local, url, path.stat().st_size, max_footer_bytes=1 << 20)
            for g in range(remote.metadata.num_row_groups):
                remote.read_row_group(g)
        blobs = {url: path.read_bytes() for url, path in ((_file_url(theme, kind, n), p) for n, p in paths.items())}
        for url, first, last in local.asked:
            stem = url.rsplit("/", 1)[-1].removesuffix(".zstd.parquet")
            add(f"{url} bytes={first}-{last}", f"ranges/{theme}-{stem}-{first}-{last}.bin",
                blobs[url][first:last + 1], "application/octet-stream", status=206)
    return out


def write() -> None:
    """Write the catalog, the ranges and their index entries."""
    answers = documents()
    for name, body, _ in answers.values():
        target = ROOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    index = {key: entry for key, entry in index.items() if not entry.get("file", "").startswith("overture/")}
    index.update({key: entry for key, (_, _, entry) in answers.items()})
    INDEX.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    if "--parquet" in sys.argv:
        write_parquet()
    write()
