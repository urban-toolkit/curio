#!/usr/bin/env python3
"""Generate the SideSeeing walk's two committed datasets, from its bucket.

One whole walk of the SideSeeing street captures, the West Loop walk of
2026-10-26 that began at 16:03:17.016 in Chicago, lands in the committed Data
Catalog as two datasets, added from ``discovery/source.sideseeing.street-captures@1``
through the Discovery Catalog's own add path, as ``build_example_storage.py``
adds the storage examples' datasets, so an example can name them by a stable
id:

    datasets/data.sideseeing.west-loop-walk@1/      the walk's video: a collection
                                                   of one row, its file left in
                                                   the bucket
    datasets/data.sideseeing.west-loop-walk-gps@1/  the walk's GPS fixes, a table

The bucket on data.urbantk.org is read anonymously over HTTPS: the walk's
entry in its listing, the video's details (PyAV opens the file at its URL and
reads its header, nothing else of its 2.8 GB), the walk's ``gps.csv`` and its
``metadata.json``. A deployment that mounts the bucket reads the video's
details from its file the same way when the walk is added, and the index
keeps them, so a node knows how long the video is before it reads it.

Two checks are printed, with what they found:

- when the walk began, as its folder names it in Chicago time, against the
  start times ``metadata.json`` records: the app's button
  (``buttonStartDateTime``) and the video's recording (``mediaStartDateTime``);
- whether every fix lies within the video: its ``t_s``, its ``datetime_utc``
  less the walk's ``taken_at``, between 0 and the video's duration.

Every date the datasets record is pinned, so a rebuild writes the same files.
Needs network access to data.urbantk.org, and PyAV, pandas and DuckDB, which
``curio.builtin@1`` installs. Run from the repository root:

    PYTHONPATH=$PWD python scripts/build_example_sideseeing.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "discovery" / "source.sideseeing.street-captures@1"
CATALOG = REPO / "datasets"

#: The walk's folder in the bucket, named by when it began in Chicago.
WALK = "chicago/west-loop/2026-10-26-16-03-17-016"
VIDEO = f"{WALK}/video.mp4"
GPS = f"{WALK}/gps.csv"
METADATA = f"{WALK}/metadata.json"

#: When the walk began in UTC, as its folder's name gives it in Chicago.
TAKEN_AT = datetime(2026, 10, 26, 21, 3, 17, 16000)

#: The collection block's fingerprint an add of the walk on curio-dev
#: recorded on 2026-11-17: the same one here means the bucket holds the same
#: file.
DEV_FINGERPRINT = "695e509b7e75d1516f04a506948985c127e0fcd30b48958af99c6398dfc02a2d"

#: Every date the committed datasets record, the day they were built.
PINNED_ISO = "2026-11-17T00:00:00Z"

PUBLISHER = "SideSeeing"

#: Each committed dataset: its id, its name, what it holds, and its tags.
WALK_DATASET = (
    "data.sideseeing.west-loop-walk",
    "SideSeeing West Loop walk",
    "A walk along the sidewalks of Chicago's West Loop on 2026-10-26, recorded with the SideSeeing app "
    "on a phone: its video, 14 minutes looking down at the sidewalk, with faces and license plates "
    "blurred. The video stays in the SideSeeing bucket on data.urbantk.org, read in place where the "
    "deployment mounts the bucket and once cached elsewhere.",
    ["sideseeing", "sidewalks", "chicago", "videos"],
)
GPS_DATASET = (
    "data.sideseeing.west-loop-walk-gps",
    "SideSeeing West Loop walk GPS",
    "The GPS fixes of the SideSeeing West Loop walk, 1,292 of them over its 14 minutes: latitude, "
    "longitude and accuracy in meters, at datetime_utc. began names the walk.",
    ["sideseeing", "sidewalks", "chicago", "gps"],
)

#: The box around the fixes the West Loop extract is cut at reaches this far
#: past them, in degrees (about 220 m north and south, 170 m east and west),
#: so the map shows the streets across the walk's.
BOX_MARGIN = 0.002


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


def probe_video_at_its_url(provider, relpath: str) -> dict:
    """What ``probe.probe_video`` reads of the file *relpath*, with PyAV
    opening it at its URL in the bucket, in the one format its first bytes
    say it is, as the probe opens a file on disk."""
    import av

    from utk_curio.backend.app.discovery.application import probe

    head = provider.open(relpath, byte_range=(0, 32)).read()
    reader = probe.KIND_READERS["video"].get(probe.sniff(head) or "")
    if reader is None:
        raise SystemExit(f"{relpath}: its first bytes are no video Curio reads")
    url = provider.file_url(relpath)

    def open_at_its_url(_path, _kind):
        return av.open(url, format=reader, timeout=probe.AV_TIMEOUT_SECONDS)

    with mock.patch.object(probe, "open_container", open_at_its_url):
        details = probe.probe_video(Path(relpath))
    if details.get("probe_error"):
        raise SystemExit(f"{relpath} could not be read: {details['probe_error']}")
    return details


def add_walk(acquire, manifest, provider, placed: list[Path]) -> tuple[Path, dict]:
    """The walk's video as an add of it picked from the ``walks`` resource
    indexes it, with the details its file holds."""
    import pandas as pd

    from utk_curio.backend.app.discovery.application import cache_collection

    acquire.acquire(manifest, "walks", files=[VIDEO], title=WALK_DATASET[1])
    built = placed.pop()
    index = built / "data" / "index.parquet"
    row = pd.read_parquet(index).iloc[0]
    details = probe_video_at_its_url(provider, VIDEO)
    # Written as Cache files writes what it reads of a cached file: only what
    # the index lacks, so the time the folder's name gives stays.
    cache_collection.record_details(str(index), {row["file_id"]: details})
    return built, details


def add_gps(manifest, provider, install_path, placed: list[Path]) -> Path:
    """The walk's fixes as an add of the ``gps`` resource gives every walk's:
    one table, read by the add's own combine code (``combine_tables``) with
    ``datetime_utc`` a time in UTC, and ``began`` and ``source_file`` naming
    the walk, with the provenance the add records for one file it combines.
    An add of the one file would copy the CSV as it is."""
    from utk_curio.backend.app.discovery.application import combine_tables, index_collection, scan

    selection = scan.narrow(scan.parse_resource_id(manifest, "gps"), files=[GPS])
    result = scan.scan(manifest, provider, selection=selection)
    files = [found for group in result.groups for found in group.files]
    if [found.relpath for found in files] != [GPS]:
        raise SystemExit(f"the bucket lists {[found.relpath for found in files]}, not {GPS}")

    def stage(found, into: Path, index: int) -> Path:
        local = into / f"part-{index:06d}.csv"
        bound = found.size + 1024 * 1024
        with local.open("wb") as handle:
            provider.stream(found.relpath, handle.write, max_bytes=bound, ceiling=bound)
        try:
            local.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise SystemExit(f"{found.relpath} is not UTF-8, which an add transcodes first") from None
        return local

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        combined = combine_tables.combine(selection.spec, files, stage=stage, tmp=work, dest=work / "gps.parquet")
        install_path(
            combined.path, combined.path.name, "parquet",
            title=GPS_DATASET[1],
            discovery_source={
                "sourceId": manifest.dir_name,
                "sourceName": manifest.name,
                "resourceId": "gps",
                "fileCount": len(files),
                "fields": ",".join(selection.spec.template.names),
                "fetchedAt": PINNED_ISO,
                "fingerprint": index_collection.fingerprint(files),
                "narrowed": True,
                "sourcePath": GPS,
            },
            description=f"Read from {GPS} of {manifest.name}.",
        )
    return placed.pop()


def _commit(built: Path, dataset_id: str, title: str, description: str, tags: list[str]) -> Path:
    """Move one added dataset into ``datasets/`` under its committed id."""
    import pandas as pd

    from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest

    raw = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    data = built / raw["dataFile"]
    frame = pd.read_parquet(data)
    discovered = dict(raw.get("discoverySource") or {}, fetchedAt=PINNED_ISO)
    collection = raw.get("collection")
    if collection:
        # What its details count, as Cache files records it in the block.
        collection = dict(collection, indexedAt=PINNED_ISO, probeErrors=int(frame["probe_error"].notna().sum()))
    out = {
        "id": dataset_id,
        "name": title,
        "version": "1.0.0",
        "format": raw["format"],
        "description": description,
        "publisher": PUBLISHER,
        # The source states no license.
        "license": "",
        "tags": tags,
        "dataFile": raw["dataFile"],
        "compatibility": {"major": 1},
        "sourceLabel": raw.get("discoverySource", {}).get("sourceName") or "SideSeeing street captures",
        "createdAt": PINNED_ISO,
        "updatedAt": PINNED_ISO,
        "rowCount": len(frame),
        "featureCount": None,
        "schema": None,
        "discoverySource": discovered,
    }
    if collection:
        out["collection"] = collection
    target = CATALOG / f"{dataset_id}@1"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(built / "data", target / "data")
    (target / "manifest.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    # The catalog reads it as it reads every committed dataset.
    load_dataset_manifest(target)
    return target


def _utc(text: str) -> datetime:
    """An ISO time with a zone, as a naive time in UTC."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


#: The start times ``metadata.json`` records, by what each marks.
START_TIMES = {
    "buttonStartDateTime": "the app's start button",
    "mediaStartDateTime": "the video's recording",
    "videoStartDateTime": "the video",
}


def check_start(walk_row, metadata: dict) -> None:
    """When the walk began, by its folder, against each start time
    ``metadata.json`` records."""
    times = metadata.get("time") or {}
    taken_at = walk_row["taken_at"].to_pydatetime()
    print("\nCheck 1: when the walk began, by its folder's name, against metadata.json")
    print(f"  folder {WALK.rsplit('/', 1)[-1]}: began {walk_row['began']} in Chicago, taken_at {walk_row['taken_at']} UTC")
    for key, what in START_TIMES.items():
        if not times.get(key):
            print(f"  time.{key}: not in metadata.json")
            continue
        gap = (_utc(times[key]) - taken_at).total_seconds()
        print(f"  time.{key}, {what}: {times[key]}, {gap:+.3f} s from taken_at")
    for key in sorted(set(times) - set(START_TIMES)):
        print(f"  time.{key}: {times[key]}")


def check_fixes(walk_row, gps) -> None:
    """Whether every fix's ``t_s`` lies between 0 and the video's duration."""
    import pandas as pd

    taken_at = pd.Timestamp(walk_row["taken_at"]).tz_localize("UTC")
    t_s = (gps["datetime_utc"] - taken_at).dt.total_seconds()
    duration = float(walk_row["duration_s"])
    inside = t_s.between(0, duration)
    gaps = gps["datetime_utc"].diff().dt.total_seconds().dropna()
    print("\nCheck 2: every fix's t_s, datetime_utc less taken_at, within the video's 0 to its duration")
    print(f"  {len(gps):,} fixes, {gaps.median():.3f} s apart at the median; the video lasts {duration:.3f} s")
    print(f"  t_s {t_s.min():.3f} to {t_s.max():.3f} s; before the video: {int((t_s < 0).sum())}, "
          f"after its end: {int((t_s > duration).sum())}")
    for when in t_s[~inside]:
        print(f"  a fix at t_s {when:.3f} s, {when - duration if when > duration else when:+.3f} s outside")
    print(f"  {int(inside.sum()):,} of {len(gps):,} fixes lie within the video")


def box_around(gps) -> tuple[float, float, float, float]:
    """South, west, north and east of the fixes, ``BOX_MARGIN`` past them,
    as ``build_example_pbfs.py``'s ``AREAS`` takes a box."""
    south = round(float(gps["latitude"].min()) - BOX_MARGIN, 4)
    north = round(float(gps["latitude"].max()) + BOX_MARGIN, 4)
    west = round(float(gps["longitude"].min()) - BOX_MARGIN, 4)
    east = round(float(gps["longitude"].max()) + BOX_MARGIN, 4)
    return south, west, north, east


def build() -> int:
    state = tempfile.mkdtemp(prefix="curio-example-sideseeing-")
    os.environ["CURIO_STATE_DIR"] = state
    try:
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
        install_path = _install(placed)
        acquire = StorageAcquire(
            user_key="1",
            storage_for=lambda _m: provider,
            install_path=install_path,
            import_layers=None,
            find_held=lambda *_a: None,
        )

        built_walk, details = add_walk(acquire, manifest, provider, placed)
        built_gps = add_gps(manifest, provider, install_path, placed)
        walk = _commit(built_walk, *WALK_DATASET)
        gps_dir = _commit(built_gps, *GPS_DATASET)

        walk_manifest = json.loads((walk / "manifest.json").read_text(encoding="utf-8"))
        walk_row = pd.read_parquet(walk / "data" / "index.parquet").iloc[0]
        gps = pd.read_parquet(gps_dir / json.loads((gps_dir / "manifest.json").read_text(encoding="utf-8"))["dataFile"])
        metadata = json.loads(provider.open(METADATA, max_bytes=1024 * 1024).read().decode("utf-8"))

        print(f"wrote {walk.relative_to(REPO)} and {gps_dir.relative_to(REPO)}")
        print("\nThe walk's row")
        for column in ("relpath", "bytes", "began", "taken_at", "duration_s", "fps", "width", "height", "codec", "mtime"):
            print(f"  {column}: {walk_row[column]}")
        print(f"  probe, as read at the file's URL: {json.dumps(details, default=str)}")
        fingerprint = walk_manifest["collection"]["fingerprint"]
        print(f"  fingerprint {fingerprint}: {'the one' if fingerprint == DEV_FINGERPRINT else 'NOT the one'} "
              "curio-dev's add recorded")
        print("\nThe GPS table")
        print(f"  {len(gps):,} rows; columns {list(gps.columns)}")
        print(f"  types {dict((name, str(kind)) for name, kind in gps.dtypes.items())}")
        print(f"  a box around the fixes (S, W, N, E), {BOX_MARGIN} degrees past them: {box_around(gps)}")

        if walk_row["taken_at"].to_pydatetime() != TAKEN_AT:
            raise SystemExit(f"taken_at is {walk_row['taken_at']}, not {TAKEN_AT}")
        check_start(walk_row, metadata)
        check_fixes(walk_row, gps)
        return 0
    finally:
        shutil.rmtree(state, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(build())
