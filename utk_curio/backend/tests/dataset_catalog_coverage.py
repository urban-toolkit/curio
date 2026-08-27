"""Per-dataset E2E coverage recipes for the committed Data Catalog.

Shared by two layers that must agree on *which* datasets exist and *how* each
one is exercised:

* ``tests/test_frontend/test_dataset_catalog_datasets_e2e.py`` drives a browser
  per dataset - install it, load it through a Data Loading node, feed a
  consumer - and asserts the markers named here.
* ``tests/test_datasets/test_catalog_dataset_coverage.py`` re-parametrizes over
  the same list without a browser, so a dataset whose file is missing or whose
  format has no recipe fails in milliseconds instead of after a Chromium boot.

Stdlib only on purpose (``csv``/``json``): the fast guard must import this
without pulling Playwright in.

WHY THE COMMITTED FILE IS THE ORACLE, NOT THE MANIFEST
------------------------------------------------------
``manifest.json`` is decorative metadata that has drifted from the fixtures it
describes: ``acs-neighborhood-profile`` advertises ``rowCount: 2408`` over 3
committed rows, and ``chicago-community-areas`` advertises ``featureCount: 77``
/ ``MultiPolygon`` over 2 committed ``Polygon`` features. Every expectation here
is therefore parsed out of the data file itself. (This generalises
``_expected_row_count`` in ``test_canvas_authoring_e2e.py``, which makes the
same point for the CSV alone.)

MARKER FORMAT
-------------
A node's inline output box is read as one flat string, so a bare ``"MARKER 3"``
substring check also matches ``"MARKER 30"``. Markers are emitted - and
asserted - fully delimited as ``NAME=value;``.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from utk_curio.backend.app.datasets.domain.manifest import (
    DatasetManifest,
    load_dataset_manifest,
)
from utk_curio.backend.app.datasets.infrastructure.storage import list_catalog_datasets


@dataclass(frozen=True)
class CatalogDataset:
    """One committed catalog entry, as both test layers see it."""

    root: Path
    manifest: DatasetManifest

    @property
    def dataset_id(self) -> str:
        return self.manifest.id

    @property
    def data_file(self) -> Path:
        return self.root / self.manifest.data_file

    @property
    def slug(self) -> str:
        """Dot-free stem for a screenshot baseline filename.

        ``save_workflow_test_screenshot`` runs its argument through
        ``os.path.splitext``, so a raw dataset id would be truncated at its
        last dot - collapsing the two ``data.urbanlab.*`` geojson params onto
        one baseline file.
        """
        return "dataset-" + self.manifest.id.replace(".", "-")


def catalog_datasets() -> list[CatalogDataset]:
    """Every dataset in the committed catalog, sorted by id.

    The single source of truth both test layers parametrize over, so adding a
    directory under ``datasets/`` adds a test rather than needing one written.
    """
    found = [
        CatalogDataset(root=root, manifest=load_dataset_manifest(root))
        for root in list_catalog_datasets()
    ]
    return sorted(found, key=lambda entry: entry.dataset_id)


@dataclass(frozen=True)
class FormatPlan:
    """How to consume - and what to assert about - one dataset format."""

    #: Substring the generated loader node must contain, mirroring
    #: ``snippetForFormat`` in ``datasetLoaderSnippets.ts``.
    loader_marker: str
    #: Downstream Data Transformation source. Prints ``NAME=value;`` markers and
    #: returns a frame the view stage (if any) can chart.
    transform_code: str
    #: Vega-Lite spec for a third, view node - or ``None`` for no view stage.
    vega_spec: str | None
    #: Marker name -> expected value, parsed from the committed data file.
    expectations: Callable[[Path], dict[str, str]]


_CSV_TRANSFORM = '''df = arg
print("CURIO_E2E_ROWS=%d;" % len(df))
print("CURIO_E2E_COLS=%s;" % ",".join(map(str, df.columns)))
return df
'''


def _csv_expectations(data_file: Path) -> dict[str, str]:
    with open(data_file, newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.reader(handle) if row]
    assert rows, f"{data_file} has no rows at all"
    header, body = rows[0], rows[1:]
    return {
        "CURIO_E2E_ROWS": str(len(body)),
        "CURIO_E2E_COLS": ",".join(header),
    }


# Geometry *bounds*, deliberately, not ``.area``: area on an EPSG:4326 frame
# emits a geographic-CRS UserWarning into the output box for no extra signal,
# while bounds are equally impossible to compute unless geopandas really parsed
# the coordinates.
_GEOJSON_TRANSFORM = '''import pandas as pd

gdf = arg
bounds = gdf.geometry.bounds
widths = (bounds["maxx"] - bounds["minx"]).tolist()
print("CURIO_E2E_FEATURES=%d;" % len(gdf))
print("CURIO_E2E_GEOM=%s;" % ",".join(sorted(set(gdf.geom_type))))
print("CURIO_E2E_WIDTH_POSITIVE=%d;" % int(all(w > 0 for w in widths)))
return pd.DataFrame({
    "feature": [str(i) for i in range(len(gdf))],
    "width": widths,
})
'''

# ``data: {name: "data"}`` is how a vis-vega node names its upstream input; see
# docs/examples/02-vega-lite-spatial-density.json for the same wiring.
_GEOJSON_VEGA_SPEC = json.dumps(
    {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "description": "Per-feature bounding-box width of the loaded geometry.",
        "data": {"name": "data"},
        "mark": "bar",
        "encoding": {
            "x": {"field": "feature", "type": "nominal", "axis": {"title": "Feature"}},
            "y": {
                "field": "width",
                "type": "quantitative",
                "axis": {"title": "Width (deg)"},
            },
        },
    },
    indent=2,
)


def _geojson_expectations(data_file: Path) -> dict[str, str]:
    doc = json.loads(data_file.read_text(encoding="utf-8"))
    features = doc.get("features") or []
    assert features, f"{data_file} carries no features"
    return {
        "CURIO_E2E_FEATURES": str(len(features)),
        "CURIO_E2E_GEOM": ",".join(
            sorted({feature["geometry"]["type"] for feature in features})
        ),
        # Every committed geometry is a real polygon, so no bounding box may be
        # degenerate. A zero here means coordinates were dropped in transit.
        "CURIO_E2E_WIDTH_POSITIVE": "1",
    }


FORMAT_PLANS: dict[str, FormatPlan] = {
    "csv": FormatPlan(
        loader_marker="pd.read_csv",
        transform_code=_CSV_TRANSFORM,
        vega_spec=None,
        expectations=_csv_expectations,
    ),
    "geojson": FormatPlan(
        loader_marker="gpd.read_file",
        transform_code=_GEOJSON_TRANSFORM,
        vega_spec=_GEOJSON_VEGA_SPEC,
        expectations=_geojson_expectations,
    ),
}


def plan_for(dataset: CatalogDataset) -> FormatPlan:
    """Return the recipe for *dataset*, or fail with what to go and write.

    A hard failure, never a skip: the promise this module exists to keep is
    that *every* catalog dataset is exercised end to end, and a skip is exactly
    how that promise lapses without anyone noticing.
    """
    plan = FORMAT_PLANS.get(dataset.manifest.format)
    if plan is None:
        raise AssertionError(
            f"dataset {dataset.dataset_id!r} has format "
            f"{dataset.manifest.format!r}, which has no E2E recipe. Add a "
            f"FormatPlan for it to FORMAT_PLANS in "
            f"utk_curio/backend/tests/dataset_catalog_coverage.py "
            f"(known formats: {sorted(FORMAT_PLANS)}). Every dataset in the "
            f"catalog must be covered by at least one end-to-end test."
        )
    return plan


def expected_markers(dataset: CatalogDataset) -> dict[str, str]:
    """Marker name -> expected value for *dataset*, read off its data file."""
    return plan_for(dataset).expectations(dataset.data_file)


def marker_text(name: str, value: str) -> str:
    """The exact delimited string a node's output box must contain."""
    return f"{name}={value};"
