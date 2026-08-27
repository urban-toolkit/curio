"""Every committed catalog dataset is loadable and has an E2E recipe.

The browser suite (``test_frontend/test_dataset_catalog_datasets_e2e.py``)
parametrizes over the same ``catalog_datasets()`` list and proves each dataset
really loads through a node. That costs a Chromium boot per dataset, so this
module front-runs the failures that do not need one: a dataset whose data file
is missing, truncated or unparseable, and - the reason this file exists - a
dataset whose *format* nobody has written an E2E recipe for.

Without that last check, adding (say) a parquet dataset to ``datasets/`` would
be caught only after the e2e job spins up a browser, if at all. With it, the
gap is a sub-second failure naming the exact table to extend.

No fixtures: this is pure filesystem inspection against the committed catalog.

Run::

    python -m pytest utk_curio/backend/tests/test_datasets/test_catalog_dataset_coverage.py -v
"""
from __future__ import annotations

import csv
import json

import pytest

from utk_curio.backend.tests.dataset_catalog_coverage import (
    CatalogDataset,
    catalog_datasets,
    expected_markers,
    plan_for,
)

CATALOG = catalog_datasets()


def _ids(datasets: list[CatalogDataset]) -> list[str]:
    return [dataset.dataset_id for dataset in datasets]


def test_the_catalog_is_not_empty():
    """A catalog that scans to nothing would make every test below vacuous."""
    assert CATALOG, (
        "no datasets found under the catalog root; every parametrized test in "
        "this module and in test_dataset_catalog_datasets_e2e.py would "
        "silently collect zero cases"
    )


@pytest.mark.parametrize("dataset", CATALOG, ids=_ids(CATALOG))
def test_dataset_directory_is_well_formed(dataset: CatalogDataset):
    """The manifest matches its directory and points at a real, non-empty file."""
    assert dataset.root.name == dataset.manifest.dir_name, (
        f"{dataset.root.name} does not match the manifest id "
        f"{dataset.manifest.dir_name}"
    )

    data_file = dataset.data_file
    assert data_file.is_file(), (
        f"manifest.dataFile points at {dataset.manifest.data_file!r}, which "
        f"does not exist under {dataset.root}"
    )
    # Guard against a path escaping the dataset dir via ``../``.
    assert dataset.root.resolve() in data_file.resolve().parents, (
        f"{data_file} escapes its dataset directory {dataset.root}"
    )
    assert data_file.stat().st_size > 0, f"{data_file} is empty"


@pytest.mark.parametrize("dataset", CATALOG, ids=_ids(CATALOG))
def test_dataset_has_an_e2e_recipe(dataset: CatalogDataset):
    """The format is one the browser suite knows how to exercise.

    This is the check that keeps "every dataset in the catalog has at least one
    E2E test" true as datasets are added.
    """
    plan = plan_for(dataset)
    assert plan.transform_code.strip(), (
        f"the {dataset.manifest.format} plan has no downstream code, so the "
        f"E2E test would load the dataset and assert nothing about it"
    )
    assert plan.loader_marker


@pytest.mark.parametrize("dataset", CATALOG, ids=_ids(CATALOG))
def test_dataset_parses_and_yields_expectations(dataset: CatalogDataset):
    """The committed file parses, and the E2E markers derive real values.

    Expectations come from the file rather than the manifest, which has drifted
    from it for two of the three committed datasets - so this also pins that the
    parse actually produced content rather than defaulting to zero.
    """
    markers = expected_markers(dataset)
    assert markers, "no expectations derived"
    assert all(value != "" for value in markers.values()), markers

    fmt = dataset.manifest.format
    if fmt == "csv":
        with open(dataset.data_file, newline="", encoding="utf-8") as handle:
            rows = [row for row in csv.reader(handle) if row]
        assert len(rows) >= 2, "a CSV dataset needs a header and at least one row"
        assert int(markers["CURIO_E2E_ROWS"]) > 0
        assert markers["CURIO_E2E_COLS"]
    elif fmt == "geojson":
        doc = json.loads(dataset.data_file.read_text(encoding="utf-8"))
        assert doc.get("type") == "FeatureCollection", doc.get("type")
        assert doc.get("features"), "a geojson dataset needs at least one feature"
        assert int(markers["CURIO_E2E_FEATURES"]) > 0
        assert markers["CURIO_E2E_GEOM"]
    else:  # pragma: no cover - plan_for() gates this
        pytest.fail(
            f"format {fmt!r} has a FormatPlan but no parse check here; add one "
            f"alongside it so a malformed file is caught without a browser"
        )
