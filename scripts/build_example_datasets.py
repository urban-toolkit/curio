#!/usr/bin/env python3
"""Ingest the curated examples' data files into the committed Data Catalog.

WHY
---
The gallery examples used to read their inputs from ``docs/examples/data/`` by a
launch-CWD-relative path baked into each node's code. That works on a git
checkout and nowhere else: ``MANIFEST.in`` does not ship ``docs/``, so a
``pip install utk-curio`` has no such tree, and an isolated sandbox cannot reach
one. Moving the data into ``<repo_root>/datasets/`` lets the nodes address it by
id through ``curio_dataset_path("<id>")``, which resolves per execution.

Three of the sources were zipped CSV/GeoJSON exports. ``zip`` is not a catalog
format (``domain/manifest.py::SUPPORTED_FORMATS``), so they are re-encoded as
Parquet, which *is* supported and is smaller than the zips it replaces. One CSV
(Milan weather) was semicolon-delimited; the catalog's generated loader emits a
bare ``pd.read_csv`` with no ``sep``, so it is re-saved comma-delimited rather
than shipping a dataset whose own loader snippet cannot read it.

HOW
---
Parquet is written through the same helpers the sandbox uses
(``utk_curio/sandbox/util/codec.py``, via ``parsers.save_dataset_parquet``)
rather than a hand-rolled ``to_parquet``, because those helpers define the format
the catalog's loader snippet reads back: object columns holding dicts/lists are
JSON-encoded and the column list is recorded in a ``<file>.decode.json``
sidecar, which ``loader_snippet("parquet")`` looks for. Rolling our own write
would produce a file the generated loader silently mis-reads.

Manifest ``rowCount``/``featureCount`` are taken from the frame actually
written, never hand-typed: the pre-existing catalog manifests all drifted from
their data files (see the docstring of
``utk_curio/backend/tests/dataset_catalog_coverage.py``) and that is a wart
worth not repeating.

This is AUTHORING-ONLY tooling. It is not imported at runtime.

MEMORY
------
``04-labels.json.zip`` decompresses to a ~165 MB GeoJSON with list-valued
columns; ``gpd.read_file`` on it wants several GB of RAM. The script prints the
row count and dtypes of every frame it writes so the result can be sanity
checked before committing.

USAGE
-----
    conda run -n curio python scripts/build_example_datasets.py
    conda run -n curio python scripts/build_example_datasets.py --only green-roofs
    # then review, and commit the resulting datasets/<id>@1/ directories

Idempotent: re-running overwrites each dataset directory it owns.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend.app.datasets.domain.manifest import (  # noqa: E402
    DatasetManifest,
    build_manifest_dict,
    load_dataset_manifest,
)
from utk_curio.sandbox.util.codec import (  # noqa: E402
    PARQUET_DECODE_SIDECAR_SUFFIX,
    _prepare_frame_for_parquet,
    _serialize_parquet_meta,
    _write_dataframe_parquet,
)

SRC_DIR = REPO_ROOT / "docs" / "examples" / "data"
CATALOG_DIR = REPO_ROOT / "datasets"

#: Migration date, stamped as the Curio *record's* createdAt/updatedAt. Not
#: ``sourceUpdatedAt``: that field means "last-modified date of the original
#: file", which we do not know for any of these (the checkout mtimes are not
#: it), so it stays null and the vintage lives in the description instead.
STAMP = "2026-08-27T00:00:00Z"


class Dataset:
    """One catalog entry to build, and how to build it."""

    def __init__(
        self,
        *,
        slug: str,
        dataset_id: str,
        name: str,
        fmt: str,
        source: str,
        data_file: str,
        description: str,
        publisher: str,
        source_label: str,
        license: str,
        tags: list[str],
        mode: str,
        zip_member: str | None = None,
        source_sep: str | None = None,
    ) -> None:
        self.slug = slug
        self.dataset_id = dataset_id
        self.name = name
        self.fmt = fmt
        self.source = source
        self.data_file = data_file
        self.description = description
        self.publisher = publisher
        self.source_label = source_label
        self.license = license
        self.tags = tags
        # copy | recsv | parquet_table | parquet_geo
        self.mode = mode
        self.zip_member = zip_member
        self.source_sep = source_sep

    @property
    def dir_name(self) -> str:
        return f"{self.dataset_id}@1"

    @property
    def root(self) -> Path:
        return CATALOG_DIR / self.dir_name

    @property
    def dest(self) -> Path:
        return self.root / self.data_file


DATASETS: list[Dataset] = [
    Dataset(
        slug="chicago-labels",
        dataset_id="data.projectsidewalk.chicago-labels",
        name="Project Sidewalk Chicago Labels",
        fmt="parquet",
        source="04-labels.json.zip",
        zip_member="04-labels.json",
        data_file="data/chicago-labels.parquet",
        mode="parquet_geo",
        description=(
            "Crowdsourced sidewalk accessibility labels for Chicago: curb "
            "ramps, missing ramps, obstacles and surface problems as labelled "
            "points with severity and validation counts. Converted to "
            "GeoParquet from the original zipped GeoJSON export."
        ),
        publisher="Project Sidewalk",
        source_label="Project Sidewalk",
        license="Project Sidewalk API terms",
        tags=["sidewalk", "accessibility", "chicago", "points", "parquet"],
    ),
    Dataset(
        slug="green-roofs",
        dataset_id="data.cityofchicago.green-roofs",
        name="Chicago Green Roofs",
        fmt="csv",
        source="10-green_roofs.csv",
        data_file="data/green-roofs.csv",
        mode="copy",
        description=(
            "Inventory of green (vegetated) roofs on Chicago buildings, with "
            "square footage, address and building attributes."
        ),
        publisher="City of Chicago",
        source_label="Chicago Data Portal",
        license="Open Data",
        tags=["green-roofs", "chicago", "buildings", "csv"],
    ),
    Dataset(
        slug="speed-camera-violations",
        dataset_id="data.cityofchicago.speed-camera-violations",
        name="Chicago Speed Camera Violations",
        fmt="parquet",
        source="07-speed_camera_violations.zip",
        data_file="data/speed-camera-violations.parquet",
        mode="parquet_table",
        description=(
            "Daily speed-camera violation counts per camera, with camera "
            "location and address. Converted to Parquet from the original "
            "zipped CSV export; date columns are kept as the source strings so "
            "consumers keep parsing them explicitly."
        ),
        publisher="City of Chicago",
        source_label="Chicago Data Portal",
        license="Open Data",
        tags=["violations", "speed-camera", "chicago", "temporal", "parquet"],
    ),
    Dataset(
        slug="red-light-violations",
        dataset_id="data.cityofchicago.red-light-violations",
        name="Chicago Red-Light Violations",
        fmt="parquet",
        source="08-red_light_violations.zip",
        data_file="data/red-light-violations.parquet",
        mode="parquet_table",
        description=(
            "Daily red-light camera violation counts per intersection, with "
            "camera location. Converted to Parquet from the original zipped "
            "CSV export; date columns are kept as the source strings so "
            "consumers keep parsing them explicitly."
        ),
        publisher="City of Chicago",
        source_label="Chicago Data Portal",
        license="Open Data",
        tags=["violations", "red-light", "chicago", "temporal", "parquet"],
    ),
    Dataset(
        slug="energy-usage-2010",
        dataset_id="data.cityofchicago.energy-usage-2010",
        name="Chicago Energy Usage 2010",
        fmt="csv",
        source="11-energy_usage.csv",
        data_file="data/energy-usage-2010.csv",
        mode="copy",
        description=(
            "Aggregated 2010 electricity and gas consumption by census block "
            "and building type, with monthly totals and building-age columns."
        ),
        publisher="City of Chicago",
        source_label="Chicago Data Portal",
        license="Open Data",
        tags=["energy", "buildings", "chicago", "csv"],
    ),
    Dataset(
        slug="milan-mrt",
        dataset_id="data.urbanlab.milan-mrt",
        name="Milan Mean Radiant Temperature",
        fmt="geotiff",
        source="09-milan_mrt.tif",
        data_file="data/milan-mrt.tif",
        mode="copy",
        description=(
            "Mean radiant temperature raster for Milan on 2022-07-22 at noon, "
            "the thermal input to a UTCI heat-exposure calculation. "
            "Pre-downsampled by a factor of 4 per dimension and "
            "float16-quantized so the file fits in the repo; UTCI precision "
            "(about 0.06 C in this range) is unaffected."
        ),
        publisher="Urban Analytics Lab",
        source_label="Curio tutorial data",
        license="Research use",
        tags=["raster", "milan", "thermal", "mrt", "geotiff"],
    ),
    Dataset(
        slug="milan-era5-weather",
        dataset_id="data.urbanlab.milan-era5-weather",
        name="Milan ERA5 Hourly Weather",
        fmt="csv",
        source="09-milan_weather.csv",
        data_file="data/milan-era5-weather.csv",
        mode="recsv",
        source_sep=";",
        description=(
            "Hourly ERA5 reanalysis weather for Milan on 2022-07-22: dew "
            "point, wind speed and relative humidity, the meteorological "
            "inputs to a UTCI calculation. Re-saved comma-delimited from the "
            "original semicolon-delimited export."
        ),
        publisher="Urban Analytics Lab",
        source_label="ERA5 (Copernicus)",
        license="Copernicus licence",
        tags=["weather", "era5", "milan", "csv"],
    ),
    Dataset(
        slug="milan-census-gt65",
        dataset_id="data.urbanlab.milan-census-gt65",
        name="Milan Census Polygons (over 65)",
        fmt="geojson",
        source="09-milan_census.geojson",
        data_file="data/milan-census-gt65.geojson",
        mode="copy",
        description=(
            "Milan census tract polygons trimmed to the gt_65 column "
            "(resident population over 65), the exposure denominator for a "
            "heat vulnerability analysis."
        ),
        publisher="Urban Analytics Lab",
        source_label="ISTAT",
        license="ISTAT open data",
        tags=["census", "milan", "demographics", "geojson"],
    ),
]


def _write_manifest(dataset: Dataset, *, row_count, feature_count) -> None:
    manifest = DatasetManifest(
        id=dataset.dataset_id,
        name=dataset.name,
        version="1.0.0",
        format=dataset.fmt,
        description=dataset.description,
        publisher=dataset.publisher,
        license=dataset.license,
        tags=list(dataset.tags),
        data_file=dataset.data_file,
        major=1,
        created_at=STAMP,
        updated_at=STAMP,
        source_updated_at=None,
        feature_count=feature_count,
        row_count=row_count,
        schema=None,
        source_label=dataset.source_label,
    )
    payload = build_manifest_dict(manifest)
    (dataset.root / "manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _report(frame) -> None:
    print(f"    {len(frame)} rows, {len(frame.columns)} columns")
    for column, dtype in frame.dtypes.items():
        print(f"      {column}: {dtype}")


def _write_sidecar(dataset: Dataset, meta_json) -> None:
    """Persist the object-column decode list next to the parquet.

    ``loader_snippet("parquet")`` reads this sidecar to restore dict/list cells
    that had to be JSON-encoded on write; without it those columns reload as
    JSON strings. It rides along on install because a hub install is a
    whole-directory copytree, and ``constants.SIDECAR_SUFFIXES`` keeps a
    directory scan from cataloguing it as a stray JSON dataset.
    """
    path = dataset.dest.parent / (dataset.dest.name + PARQUET_DECODE_SIDECAR_SUFFIX)
    if meta_json:
        path.write_text(meta_json, encoding="utf-8")
        print(f"    wrote sidecar {path.name}")
    elif path.exists():
        path.unlink()


def _count_plain(dataset: Dataset):
    """Counts for a byte-copied file, parsed from the file itself."""
    if dataset.fmt == "csv":
        import csv as _csv

        with open(dataset.dest, newline="", encoding="utf-8") as handle:
            rows = [row for row in _csv.reader(handle) if row]
        return len(rows) - 1, None
    if dataset.fmt == "geojson":
        doc = json.loads(dataset.dest.read_text(encoding="utf-8"))
        return None, len(doc.get("features") or [])
    # A raster has neither rows nor features; leave both null rather than
    # inventing a pixel count the catalog UI would render as a row count.
    return None, None


def _build_copy(dataset: Dataset, src: Path):
    shutil.copy2(src, dataset.dest)
    return _count_plain(dataset)


def _build_recsv(dataset: Dataset, src: Path):
    import pandas as pd

    frame = pd.read_csv(src, sep=dataset.source_sep)
    frame.to_csv(dataset.dest, index=False)
    print(f"    re-delimited to {len(frame)} rows, {len(frame.columns)} columns")
    print(f"    columns: {list(frame.columns)}")
    return len(frame), None


def _build_parquet_table(dataset: Dataset, src: Path):
    import pandas as pd

    # Default dtype inference and NO parse_dates: the parquet is "the CSV, in
    # parquet". Example 03 passes date_format='%m/%d/%Y' deliberately because
    # the export uses US dates, and baking timestamps in here would hide that
    # from the walkthrough.
    frame = pd.read_csv(src)
    _report(frame)
    prepared, encoded = _prepare_frame_for_parquet(frame)
    _write_dataframe_parquet(prepared, dataset.dest)
    _write_sidecar(dataset, _serialize_parquet_meta(encoded_object_columns=encoded))
    return len(frame), None


def _build_parquet_geo(dataset: Dataset, src: Path):
    import geopandas as gpd

    # The exact call example 01 makes today, so the parquet captures what the
    # example currently loads rather than what some other reader would produce.
    uri = f"zip://{src.as_posix()}!{dataset.zip_member}"
    print(f"    reading {uri} (expect high peak memory)")
    frame = gpd.read_file(uri)
    _report(frame)
    prepared, encoded = _prepare_frame_for_parquet(
        frame, geometry_col=frame.geometry.name
    )
    prepared.to_parquet(dataset.dest, compression="zstd")
    _write_sidecar(dataset, _serialize_parquet_meta(encoded_object_columns=encoded))
    if encoded:
        print(f"    JSON-encoded object columns: {encoded}")
    return len(frame), len(frame)


BUILDERS = {
    "copy": _build_copy,
    "recsv": _build_recsv,
    "parquet_table": _build_parquet_table,
    "parquet_geo": _build_parquet_geo,
}


def build(dataset: Dataset) -> None:
    src = SRC_DIR / dataset.source
    if not src.exists():
        raise SystemExit(
            f"source {src} is missing. This script reads the pre-migration "
            f"files in docs/examples/data/; check out a revision that still "
            f"has them, or drop {dataset.slug} from DATASETS."
        )

    print(f"  {dataset.dataset_id} ({dataset.fmt}) <- {dataset.source}")
    if dataset.root.exists():
        shutil.rmtree(dataset.root)
    dataset.dest.parent.mkdir(parents=True, exist_ok=True)

    row_count, feature_count = BUILDERS[dataset.mode](dataset, src)
    _write_manifest(dataset, row_count=row_count, feature_count=feature_count)

    # Validate through the backend's own loader, so a manifest this script can
    # write but the catalog cannot read fails here rather than at scan time
    # (where registry._iter_manifests swallows ManifestError and the dataset
    # simply goes invisible).
    loaded = load_dataset_manifest(dataset.root)
    assert loaded.id == dataset.dataset_id, loaded.id
    assert loaded.dir_name == dataset.dir_name, loaded.dir_name

    size_mb = dataset.dest.stat().st_size / 1e6
    print(
        f"    -> {dataset.dest.relative_to(REPO_ROOT).as_posix()} "
        f"({size_mb:.1f} MB, rowCount={row_count}, featureCount={feature_count})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        action="append",
        metavar="SLUG",
        help="build just this dataset (repeatable); default is all of them",
    )
    parser.add_argument("--list", action="store_true", help="print the slugs and exit")
    args = parser.parse_args()

    if args.list:
        for dataset in DATASETS:
            print(f"{dataset.slug:26} {dataset.dataset_id} ({dataset.fmt})")
        return 0

    selected = DATASETS
    if args.only:
        wanted = set(args.only)
        unknown = wanted - {d.slug for d in DATASETS}
        if unknown:
            raise SystemExit(f"unknown slug(s): {sorted(unknown)}")
        selected = [d for d in DATASETS if d.slug in wanted]

    print(f"Building {len(selected)} dataset(s) into {CATALOG_DIR}")
    for dataset in selected:
        build(dataset)

    total = sum(p.stat().st_size for p in CATALOG_DIR.rglob("*") if p.is_file())
    print(f"\ndatasets/ now holds {total / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
