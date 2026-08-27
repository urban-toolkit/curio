"""Every committed catalog dataset is loadable and has an E2E recipe.

The browser suite (``test_frontend/test_dataset_catalog_datasets_e2e.py``)
parametrizes over the same ``catalog_datasets()`` list and proves each dataset
really loads through a node. That costs a Chromium boot per dataset, so this
module front-runs the failures that do not need one: a dataset whose data file
is missing, truncated or unparseable, and - the reason this file exists - a
dataset whose *format* nobody has written an E2E recipe for.

Without that last check, adding (say) a ``shp`` or ``bundle`` dataset to
``datasets/`` would be caught only after the e2e job spins up a browser, if at
all. With it, the gap is a sub-second failure naming the exact table to extend.

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
    elif fmt == "parquet":
        import pyarrow.parquet as pq

        parquet_file = pq.ParquetFile(dataset.data_file)
        assert parquet_file.metadata.num_row_groups >= 1, (
            "a parquet dataset needs at least one row group; a footer-only "
            "file parses but carries nothing"
        )
        assert int(markers["CURIO_E2E_ROWS"]) >= 1
        assert int(markers["CURIO_E2E_NCOLS"]) >= 1
        assert markers["CURIO_E2E_COLS"]
        assert markers["CURIO_E2E_GEO"] in {"0", "1"}, markers["CURIO_E2E_GEO"]
    elif fmt == "geotiff":
        import rasterio

        with rasterio.open(dataset.data_file) as raster:
            assert raster.count >= 1, "a geotiff dataset needs at least one band"
            assert raster.width >= 1 and raster.height >= 1
            assert raster.crs is not None, (
                "a catalog geotiff must carry a CRS, or nothing downstream can "
                "place its pixels"
            )
        assert int(markers["CURIO_E2E_BANDS"]) >= 1
        assert int(markers["CURIO_E2E_VALID"]) >= 1
        assert markers["CURIO_E2E_DTYPES"]
    else:  # pragma: no cover - plan_for() gates this
        pytest.fail(
            f"format {fmt!r} has a FormatPlan but no parse check here; add one "
            f"alongside it so a malformed file is caught without a browser"
        )


@pytest.mark.parametrize("dataset", CATALOG, ids=_ids(CATALOG))
def test_manifest_counts_match_the_committed_file(dataset: CatalogDataset):
    """A declared count must agree with the file it describes.

    Manifest drift is what forced every expectation in
    ``dataset_catalog_coverage`` to be parsed from the data file rather than read
    from the manifest: ``acs-neighborhood-profile`` advertised 2408 rows over 3,
    and ``chicago-community-areas`` 77 features over 2. Both are fixed; this
    pins them so a decorative number cannot creep back in as more datasets land.

    Only asserted where a count is declared. ``None`` means "unknown", which is
    honest - a raster legitimately has neither rows nor features.
    """
    markers = expected_markers(dataset)
    fmt = dataset.manifest.format

    if fmt in {"csv", "parquet"} and dataset.manifest.row_count is not None:
        assert dataset.manifest.row_count == int(markers["CURIO_E2E_ROWS"]), (
            f"{dataset.dataset_id}: manifest rowCount "
            f"{dataset.manifest.row_count} but the file has "
            f"{markers['CURIO_E2E_ROWS']}"
        )
    if fmt == "geojson" and dataset.manifest.feature_count is not None:
        assert dataset.manifest.feature_count == int(markers["CURIO_E2E_FEATURES"]), (
            f"{dataset.dataset_id}: manifest featureCount "
            f"{dataset.manifest.feature_count} but the file has "
            f"{markers['CURIO_E2E_FEATURES']}"
        )


_CSVS = [dataset for dataset in CATALOG if dataset.manifest.format == "csv"]


@pytest.mark.parametrize("dataset", _CSVS, ids=_ids(_CSVS))
def test_catalog_csvs_are_comma_delimited(dataset: CatalogDataset):
    """The generated loader emits a bare ``pd.read_csv`` with no ``sep``.

    A ``;``-delimited catalog CSV therefore loads as a single column whose name
    is the whole header line - and the e2e would *not* catch it, because
    ``_csv_expectations`` parses with the same default dialect and agrees with
    the same wrong answer. ``09-milan_weather`` shipped that way under
    docs/examples/data, where example 09's node passed ``delimiter=';'``
    explicitly; nothing in the catalog can, so it was re-saved comma-delimited
    on the way in. Sniff rather than trust.
    """
    sample = dataset.data_file.read_text(encoding="utf-8-sig").splitlines()[:5]
    assert sample, f"{dataset.data_file} is empty"

    # The raw count runs first because csv.Sniffer can be fooled by quoted
    # commas; the two together are hard to slip past.
    header = sample[0]
    assert header.count(",") >= header.count(";"), (
        f"{dataset.dataset_id}: header looks ';'-delimited ({header[:120]!r}). "
        f"The catalog loader snippet cannot pass a delimiter - re-save the file "
        f"comma-delimited."
    )
    dialect = csv.Sniffer().sniff("\n".join(sample), delimiters=",;\t|")
    assert dialect.delimiter == ",", (
        f"{dataset.dataset_id}: csv.Sniffer reads the delimiter as "
        f"{dialect.delimiter!r}, not ','"
    )


def test_dataset_slugs_and_e2e_usernames_are_unique():
    """Two lossy id transforms, each able to silently merge two datasets.

    ``CatalogDataset.slug`` strips dots so ``save_workflow_test_screenshot``
    cannot truncate at one; two datasets collapsing onto one baseline file would
    leave one of them visually unchecked and the other diffed against the wrong
    picture. The e2e's ``_username`` takes the last id segment and truncates to
    30 characters, and ``ds_speed_camera_violations`` is already 26 - two ids
    agreeing in their first 30 would share a login, and therefore a dataset
    store.
    """
    slugs = [dataset.slug for dataset in CATALOG]
    assert len(set(slugs)) == len(slugs), sorted(slugs)

    def username(dataset: CatalogDataset) -> str:
        # Deliberately duplicated from test_dataset_catalog_datasets_e2e rather
        # than imported: importing that module would drag Playwright into this
        # fast guard, which its whole point is to avoid.
        tail = dataset.dataset_id.rsplit(".", 1)[-1].replace("-", "_")
        return f"ds_{tail}"[:30]

    names = [username(dataset) for dataset in CATALOG]
    assert len(set(names)) == len(names), sorted(names)


def test_the_shipped_catalog_stays_within_its_size_budget():
    """``MANIFEST.in`` ships all of ``datasets/`` to PyPI.

    The example-data migration took this directory from 1.4 MB to tens of MB in
    one commit (while removing more than that from ``docs/examples/data``). This
    is not a style rule: every megabyte here is a megabyte in every
    ``pip install utk-curio``, and PyPI caps a single file at 100 MB.
    """
    root = CATALOG[0].root.parent
    total = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    assert total < 64 * 1024 * 1024, (
        f"datasets/ is {total / 1e6:.1f} MB. Either shrink the new dataset or "
        f"exclude it in MANIFEST.in - do not just raise this number."
    )
