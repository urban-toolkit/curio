#!/usr/bin/env python3
"""Generate the SAGE-IDOT example's committed datasets.

Example 31 ports the Cities in Motion workshop team's analyses of three SAGE
cameras at IDOT rail crossings, each on the day the team studied, a UTC date.
Their data stays in the ``idot`` bucket on data.urbantk.org, read in place
where the deployment mounts the bucket and once cached elsewhere. What lands
in the committed Data Catalog is small:

    datasets/data.sage.idot-<camera>-records-<month>@1/   the month's JSON Lines file (records)
    datasets/data.sage.idot-<camera>-snapshots-<day>@1/   the day's snapshots (snapshots)
    datasets/data.cities-in-motion.idot-cameras@1/        the team's control points and zones
    datasets/data.cities-in-motion.idot-yolo26n@1/        Keira's YOLO26n boxes on the snapshots

The first six are added from ``discovery/source.sage.idot-crossings@1``
through the Discovery Catalog's own add path, as ``build_example_storage.py``
adds the storage examples' datasets: each is an index of its files, from the
bucket's listing, with what the add reads of each snapshot (its size in
pixels), and none of the files' bytes. A day's snapshots are its month's row
narrowed to the day by their names, in nanoseconds since 1970.

The team's files come from its repository at one commit, through GitHub's
API: each camera's control points from Joao's scripts, which map snapshot
pixels to UTM zone 16N (EPSG:26916), its four zones from Zahra's JSON files,
in snapshot pixels, with their names in words, and Keira's CSV of YOLO26n's
boxes, as committed. Each camera's image size is its snapshots' size, which
the add read.

Every date the datasets record is pinned, so a rebuild writes the same files
while the bucket holds the same ones. Needs network access to data.urbantk.org
and api.github.com. Run from the repository root:

    PYTHONPATH=$PWD python scripts/build_example_idot.py
"""

from __future__ import annotations

import ast
import csv
import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "discovery" / "source.sage.idot-crossings@1"
CATALOG = REPO / "datasets"

#: Every date the committed datasets record, the day they were built.
PINNED_ISO = "2026-11-17T00:00:00Z"

#: What every description ends with: the data are the authors', used with
#: their permission, and carry no license.
PERMISSION = "Used with the permission of its authors."

#: The team's repository and the commit its files are read at.
TEAM_REPO = "isalva2/cities-in-motion-video"
TEAM_COMMIT = "cf66012d663f2a1e5a286a3723673ef7142287ab"
TEAM = "Cities in Motion workshop team (isalva2/cities-in-motion-video)"

#: Each camera: the UTC day the team studied, the script holding its control
#: points, and the JSON file holding its zones.
CAMERAS = {
    "W042": ("2025-08-09", "joao_scripts/reprojection_w042.py", "zahra/W042_bounding_boxes.json"),
    "W065": ("2025-08-17", "joao_scripts/animated_map_w065.py", "zahra/W065_bounding_boxes.json"),
    "W06E": ("2025-12-02", "joao_scripts/animated_map_w06E.py", "zahra/W06E_bounding_boxes.json"),
}
YOLO26N = "keira/yolo26n_detections.csv"

#: A zone file's direction words, misspelled as they are, in words.
DIRECTIONS = {
    "westhbound": "Westbound", "westthbound": "Westbound", "easthbound": "Eastbound",
    "northbound": "Northbound", "southbound": "Southbound",
}

CAMERAS_ID = "data.cities-in-motion.idot-cameras"
YOLO26N_ID = "data.cities-in-motion.idot-yolo26n"


def records_id(camera: str, day: str) -> str:
    return f"data.sage.idot-{camera.lower()}-records-{day[:7]}"


def snapshots_id(camera: str, day: str) -> str:
    return f"data.sage.idot-{camera.lower()}-snapshots-{day}"


def _month_row(resource: str, camera: str, day: str) -> str:
    """The listing's row of *camera*'s month of *day* in *resource*."""
    return f"{resource}@crossing={camera};month={day[:7]}-01T00:00:00"


def _day_in_ns(day: str) -> dict:
    """The names of a UTC day's snapshots, in nanoseconds since 1970: a range
    the add narrows the month's row to."""
    start = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=timezone.utc)
    first = int(start.timestamp()) * 10**9
    return {"min": first, "max": first + 86_400 * 10**9 - 1}


# ── The team's files ────────────────────────────────────────────────────────


def team_file(path: str) -> bytes:
    """A file of the team's repository at ``TEAM_COMMIT``, through GitHub's API."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{TEAM_REPO}/contents/{path}?ref={TEAM_COMMIT}",
        headers={"Accept": "application/vnd.github.raw+json", "User-Agent": "curio-example-builder"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _points(script: str, name: str) -> list[list[float]]:
    """The points a script assigns to *name* as ``np.float32([...])``, its
    numbers as the script writes them."""
    found = re.search(rf"^{name}\s*=\s*np\.float32\((\[.*?\])\)", script, re.MULTILINE | re.DOTALL)
    if found is None:
        raise SystemExit(f"no {name} in the script")
    text = re.sub(r"#[^\n]*", "", found.group(1))
    return [[float(value) for value in point] for point in ast.literal_eval(text)]


def zone_name(key: str) -> str:
    """A zone file's key in words: ``westhbound_before_crossing`` is
    ``Westbound, before the crossing``."""
    direction, side = key.split("_")[0], "before" if "_before_" in key else "after"
    return f"{DIRECTIONS[direction]}, {side} the crossing"


def camera_rows(camera: str, day: str, script_path: str, zones_path: str, size: tuple[int, int]) -> list[dict]:
    """One row per control point, then one per zone vertex, of *camera*."""
    script = team_file(script_path).decode("utf-8")
    image, world = _points(script, "IMAGE_POINTS"), _points(script, "WORLD_POINTS")
    if len(image) != len(world) or len(image) < 4:
        raise SystemExit(f"{script_path}: {len(image)} image points and {len(world)} ground points")
    base = {"camera": camera, "day": day, "image_width": size[0], "image_height": size[1]}
    rows = [
        {**base, "kind": "control point", "zone": "", "point": n, "x_px": x, "y_px": y,
         "easting_m": e, "northing_m": north}
        for n, ((x, y), (e, north)) in enumerate(zip(image, world), start=1)
    ]
    zones = json.loads(team_file(zones_path))
    for key, vertices in zones.items():
        rows += [
            {**base, "kind": "zone", "zone": zone_name(key), "point": n, "x_px": float(x), "y_px": float(y),
             "easting_m": "", "northing_m": ""}
            for n, (x, y) in enumerate(vertices, start=1)
        ]
    return rows


CAMERA_COLUMNS = ("camera", "day", "image_width", "image_height", "kind", "zone", "point", "x_px", "y_px",
                  "easting_m", "northing_m")


def _number(value):
    """A number as the CSV writes it: an integer without its ``.0``."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def write_team_datasets(sizes: dict[str, tuple[int, int]]) -> list[str]:
    rows = []
    for camera, (day, script_path, zones_path) in CAMERAS.items():
        rows += camera_rows(camera, day, script_path, zones_path, sizes[camera])
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CAMERA_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: _number(value) for key, value in row.items()} for row in rows)
    points = sum(row["kind"] == "control point" for row in rows)
    vertices = len(rows) - points
    cameras = _team_dataset(
        CAMERAS_ID, "IDOT cameras: control points and zones", "cameras.csv", buffer.getvalue().encode("utf-8"),
        len(rows),
        "The three SAGE cameras at IDOT rail crossings as the Cities in Motion workshop team set them up, one "
        f"row per point: {points} control points, each a pixel of the camera's snapshots (x_px, y_px) and "
        "where it lies on the ground in UTM zone 16N, EPSG:26916 (easting_m, northing_m), from Joao's scripts "
        f"({', '.join(script for _day, script, _zones in CAMERAS.values())}), and the {vertices} vertices of "
        "each camera's four zones in pixels, a lane before or after the crossing, from Zahra's files "
        f"({', '.join(zones for _day, _script, zones in CAMERAS.values())}), their keys written in words. "
        "image_width and image_height are the size of the camera's snapshots, and day is the UTC day the team "
        f"studied. Read from {TEAM_REPO} at commit {TEAM_COMMIT[:12]}. {PERMISSION}",
        ["cities in motion", "rail crossings", "control points", "zones"],
    )
    boxes = team_file(YOLO26N)
    count = sum(1 for _ in csv.DictReader(io.StringIO(boxes.decode("utf-8"))))
    yolo26n = _team_dataset(
        YOLO26N_ID, "IDOT snapshots: YOLO26n boxes", "yolo26n_detections.csv", boxes, count,
        f"Keira's run of Ultralytics' YOLO26n, at a confidence of 0.25 or more, on the snapshots of the three "
        f"team days: {count:,} boxes, one row each, with the snapshot's name in nanoseconds (timestamps_ns), the "
        "class, the confidence, the box in pixels (x_min, y_min, x_max, y_max) and the team day (dataset). A "
        "snapshot YOLO26n found nothing in has no row. As committed in "
        f"{YOLO26N} of {TEAM_REPO} at commit {TEAM_COMMIT[:12]}. {PERMISSION}",
        ["cities in motion", "rail crossings", "object detection", "yolo26n"],
    )
    return [cameras, yolo26n]


def _team_dataset(dataset_id, name, file_name, data: bytes, rows: int, description: str, tags) -> str:
    target = CATALOG / f"{dataset_id}@1"
    if target.exists():
        shutil.rmtree(target)
    (target / "data").mkdir(parents=True)
    (target / "data" / file_name).write_bytes(data)
    manifest = {
        "id": dataset_id,
        "name": name,
        "version": "1.0.0",
        "format": "csv",
        "description": description,
        "publisher": TEAM,
        "license": "",
        "tags": tags,
        "dataFile": f"data/{file_name}",
        "compatibility": {"major": 1},
        "sourceLabel": TEAM,
        "createdAt": PINNED_ISO,
        "updatedAt": PINNED_ISO,
        "rowCount": rows,
        "featureCount": None,
        "schema": None,
    }
    _write_manifest(target, manifest)
    return target.name


# ── The bucket's datasets ───────────────────────────────────────────────────


def _install(placed: list[Path]):
    """The add's seam into the Data Catalog: each dataset lands in a store of
    its own, in the temporary state folder, and its folder is kept."""
    from utk_curio.backend.app.datasets.install.installer import install_imported_path

    def install_path(path, filename, fmt, **kwargs):
        result = install_imported_path(
            "1", path, filename, fmt,
            title=kwargs.get("title"),
            discovery_source=kwargs.get("discovery_source"),
            description=kwargs.get("description"),
            collection=kwargs.get("collection"),
        )
        placed.append(result.dest)
        return {"id": result.manifest.id}

    return install_path


def _commit(built: Path, dataset_id: str, name: str, description: str, tags: list[str]) -> Path:
    """Move one added dataset into ``datasets/`` under its committed id."""
    import pandas as pd

    raw = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    frame = pd.read_parquet(built / raw["dataFile"])
    collection = dict(raw["collection"], indexedAt=PINNED_ISO)
    manifest = {
        "id": dataset_id,
        "name": name,
        "version": "1.0.0",
        "format": raw["format"],
        "description": description,
        "publisher": "SAGE",
        "license": "",
        "tags": tags,
        "dataFile": raw["dataFile"],
        "compatibility": {"major": 1},
        "sourceLabel": raw["discoverySource"]["sourceName"],
        "createdAt": PINNED_ISO,
        "updatedAt": PINNED_ISO,
        "rowCount": len(frame),
        "featureCount": None,
        "schema": None,
        "discoverySource": dict(raw["discoverySource"], fetchedAt=PINNED_ISO),
        "collection": collection,
    }
    target = CATALOG / f"{dataset_id}@1"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(built / "data", target / "data")
    _write_manifest(target, manifest)
    return target


def _write_manifest(target: Path, manifest: dict) -> None:
    from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest

    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # The catalog reads it as it reads every committed dataset.
    load_dataset_manifest(target)


def _month_words(day: str) -> str:
    return date.fromisoformat(day).strftime("%B %Y")


def add_bucket_datasets() -> tuple[list[str], dict[str, tuple[int, int]]]:
    """Each camera's month of records and day of snapshots, added and committed;
    with each camera's snapshot size."""
    import pandas as pd

    from utk_curio.backend.app.datasets.repositories import index as index_repo
    from utk_curio.backend.app.discovery.application.storage_acquire import StorageAcquire
    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.app.discovery.infrastructure.transport import HttpDiscoveryTransport
    from utk_curio.backend.app.discovery.providers import build_storage

    # The build writes files to commit, with no database to index them in.
    index_repo.safe_upsert_from_dir = lambda *_args, **_kwargs: None

    manifest = load_source_manifest(SOURCE)
    provider = build_storage(manifest, HttpDiscoveryTransport())
    placed: list[Path] = []
    acquire = StorageAcquire(
        user_key="1",
        storage_for=lambda _m: provider,
        install_path=_install(placed),
        import_layers=None,
        find_held=lambda *_a: None,
    )
    written, sizes = [], {}
    for camera, (day, _script, _zones) in CAMERAS.items():
        acquire.acquire(manifest, _month_row("records", camera, day))
        built = placed.pop()
        row = pd.read_parquet(built / "data" / "index.parquet").iloc[0]
        records = _commit(
            built, records_id(camera, day), f"SAGE-IDOT {camera} records, {_month_words(day)}",
            f"The detection records of SAGE's {camera} camera at an IDOT rail crossing for {_month_words(day)}, "
            f"its month's JSON Lines file of {int(row['bytes']):,} bytes: a line per image, about every 3 "
            "seconds, the JSON text of what YOLOv5n, YOLOv8n and YOLOv10n detected in it, and a line per "
            "snapshot uploaded. The file stays in the idot bucket on data.urbantk.org, read in place where the "
            "deployment mounts the bucket and once cached elsewhere; node code opens it from its row's path. "
            f"{PERMISSION}",
            ["sage", "rail crossings", "illinois", "object detection"],
        )
        acquire.acquire(manifest, _month_row("snapshots", camera, day), filters={"ns": _day_in_ns(day)})
        built = placed.pop()
        index = pd.read_parquet(built / "data" / "index.parquet")
        shapes = set(zip(index["width"], index["height"]))
        if len(shapes) != 1 or index["probe_error"].notna().any():
            raise SystemExit(f"{camera}'s snapshots of {day}: sizes {shapes}, "
                             f"{int(index['probe_error'].notna().sum())} unread")
        ((width, height),) = shapes
        sizes[camera] = (int(width), int(height))
        snapshots = _commit(
            built, snapshots_id(camera, day), f"SAGE-IDOT {camera} snapshots, {day}",
            f"The {len(index):,} snapshots SAGE's {camera} camera took of its IDOT rail crossing on {day} (UTC), "
            f"one every 5 minutes at {width} by {height} pixels, each named by when it was taken in nanoseconds "
            "since 1970 (ns), with that time in UTC (taken_at). They stay in the idot bucket on data.urbantk.org, "
            "read in place where the deployment mounts the bucket and once cached elsewhere. "
            f"{PERMISSION}",
            ["sage", "rail crossings", "illinois", "images"],
        )
        written += [records.name, snapshots.name]
        print(f"{camera} {day}: {row['relpath']} ({int(row['bytes']):,} bytes), "
              f"{len(index)} snapshots of {width}x{height}, {index['taken_at'].min()} to {index['taken_at'].max()}")
    return written, sizes


def main() -> int:
    os.chdir(REPO)
    state = tempfile.mkdtemp(prefix="curio-example-idot-")
    os.environ["CURIO_STATE_DIR"] = state
    try:
        bucket, sizes = add_bucket_datasets()
        team = write_team_datasets(sizes)
    finally:
        shutil.rmtree(state, ignore_errors=True)
    for name in bucket + team:
        folder = CATALOG / name
        total = sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
        print(f"wrote datasets/{name}: {total:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
