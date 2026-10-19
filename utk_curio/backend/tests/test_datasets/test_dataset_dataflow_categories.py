"""A dataset manifest's ``dataflowCategories``: the tags and data types a
dataflow that reads the dataset shows on the Projects rail.

It is not the manifest's ``tags``, which stay the catalog's own lowercase
keywords ("netcdf", "scout"). The dataset parser cleans the field with the
package manifests' reader (``packages/domain/dataflow_categories.py``) and
refuses a value of the wrong type. ``build_manifest_dict`` writes it right
after ``tags`` when the dataset declares some and leaves it out when not, so
the manifest of a dataset that declares none, a computed output's, keeps its
keys. A dataset published to the catalog keeps what it declares. The 13 SCOUT
datasets declare the SCOUT tag and no other dataset declares anything; the 12
that ``scripts/build_scout_flood_datasets.py`` and
``scripts/scout/scout_checkout.py`` write are byte for byte what the scripts
would write again.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.manifest import (
    DatasetManifest,
    ManifestError,
    _parse_manifest,
    build_manifest_dict,
    load_dataset_manifest,
)

REPO = Path(__file__).resolve().parents[4]
CATALOG = REPO / "datasets"

#: SCOUT's flood rasters, written by ``scripts/build_scout_flood_datasets.py``.
FLOOD = (
    ["data.scout.flood-nbs-classes"]
    + [
        f"data.scout.flood-depth-{period}-{kind}"
        for period in ("2020-2040", "2050-2080", "2080-2100")
        for kind in ("nbs", "no-nbs")
    ]
)
#: SCOUT's WRF forecast, written by ``scripts/scout/crop_routing_data.py``
#: through ``scout_checkout.write_manifest``.
WRF = [f"data.scout.wrf-{name}" for name in ("rain", "t2", "rh2", "wspd10", "wdir10")]
#: Every dataset that declares ``dataflowCategories``, and what it declares.
SHIPPED = {
    f"{dataset_id}@1": {"tags": ["SCOUT"]}
    for dataset_id in [*FLOOD, *WRF, "data.scout.loop-buildings"]
}


def _raw(**extra) -> dict:
    return {
        "id": "data.test.rain",
        "name": "Rain",
        "version": "1.0.0",
        "format": "csv",
        "dataFile": "data/rain.csv",
        "tags": ["rain", "chicago"],
        **extra,
    }


def _manifest(**fields) -> DatasetManifest:
    """A manifest every field of which reads back as it is written."""
    return DatasetManifest(
        id="data.test.rain", name="Rain", version="1.0.0", format="csv",
        description="", publisher="Data Catalog", license="", tags=["rain"],
        data_file="data/rain.csv", major=1, source_label="Data Catalog", **fields,
    )


def test_the_parser_keeps_a_cleaned_declaration_beside_the_catalog_tags():
    manifest = _parse_manifest(
        _raw(dataflowCategories={"tags": [" SCOUT ", "scout"], "dataTypes": ["Rasters", "", "Imagery"]}),
        where="manifest.json",
    )
    assert manifest.dataflow_categories == {"tags": ["SCOUT"], "dataTypes": ["Rasters", "Imagery"]}
    assert manifest.tags == ["rain", "chicago"]


@pytest.mark.parametrize("raw", [
    _raw(),
    _raw(dataflowCategories=None),
    _raw(dataflowCategories={}),
    _raw(dataflowCategories={"tags": [], "dataTypes": ["  "]}),
], ids=["absent", "null", "empty", "no-value"])
def test_a_dataset_that_declares_nothing_has_no_categories(raw):
    assert _parse_manifest(raw, where="manifest.json").dataflow_categories is None


@pytest.mark.parametrize("value", [
    "SCOUT",
    ["SCOUT"],
    {"tags": "SCOUT"},
    {"tags": [None]},
    {"dataTypes": [{"name": "Rasters"}]},
    {"tags": ["SCOUT"], "categories": ["Flood"]},
], ids=["a-string", "a-list", "tags-a-string", "a-null-tag", "an-object-data-type", "an-unknown-key"])
def test_the_parser_refuses_a_wrong_type(value):
    with pytest.raises(ManifestError, match="dataflowCategories"):
        _parse_manifest(_raw(dataflowCategories=value), where="manifest.json")


def test_a_declaration_is_written_after_the_tags_and_read_back():
    declared = {"tags": ["SCOUT"], "dataTypes": ["Rasters"]}
    written = build_manifest_dict(_manifest(dataflow_categories=declared))
    keys = list(written)
    assert keys[keys.index("tags") + 1] == "dataflowCategories"
    assert written["dataflowCategories"] == declared
    again = _parse_manifest(json.loads(json.dumps(written)), where="manifest.json")
    assert again.dataflow_categories == declared
    assert build_manifest_dict(again) == written


def test_a_manifest_without_a_declaration_is_written_without_the_key():
    written = build_manifest_dict(_manifest())
    assert "dataflowCategories" not in written
    assert list(written) == list(build_manifest_dict(_manifest(dataflow_categories=None)))
    again = _parse_manifest(json.loads(json.dumps(written)), where="manifest.json")
    assert again.dataflow_categories is None
    assert build_manifest_dict(again) == written


def test_the_shipped_datasets_declare_exactly_these():
    found = {}
    for path in sorted(CATALOG.glob("*/manifest.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "dataflowCategories" in raw:
            found[path.parent.name] = raw["dataflowCategories"]
    assert found == SHIPPED


@pytest.mark.parametrize("folder", sorted(SHIPPED))
def test_each_shipped_declaration_loads_as_it_is_written(folder):
    manifest = load_dataset_manifest(CATALOG / folder)
    assert manifest.dataflow_categories == SHIPPED[folder]
    assert "scout" in manifest.tags


def test_a_published_dataset_keeps_what_it_declares(app, db, user_and_token, tmp_path, monkeypatch):
    """Publishing writes the catalog's manifest from the dataset's item in the
    account's listing, which the dataset index builds and which does not hold
    the field: the published copy still declares what the account's does."""
    from utk_curio.backend.app.datasets.domain.manifest import write_manifest
    from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(catalog))
    user, _ = user_and_token
    declared = {"tags": ["Rain gauges"], "dataTypes": ["Point clouds"]}
    folder = user_datasets_dir(str(user.id)) / "imported.rain-gauges@1"
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "gauges.csv").write_text("gauge,mm\nA,3\nB,5\n", encoding="utf-8")
    write_manifest(DatasetManifest(
        id="imported.rain-gauges", name="Rain gauges", version="1.0.0", format="csv",
        description="", publisher="alice", license="", tags=["rain"], data_file="data/gauges.csv",
        major=1, source_label="Imported", dataflow_categories=declared,
    ), folder)

    DatasetCatalogService(user=user).publish_dataset("imported.rain-gauges", {})

    published = load_dataset_manifest(catalog / "imported.rain-gauges@1")
    assert published.dataflow_categories == declared


@pytest.mark.parametrize("dataset_id", [*FLOOD, *WRF])
def test_a_script_written_scout_manifest_is_what_its_script_writes(dataset_id):
    """Both scripts write ``build_manifest_dict``'s keys in its order, indented
    by two, with a newline at the end."""
    path = CATALOG / f"{dataset_id}@1" / "manifest.json"
    text = path.read_text(encoding="utf-8")
    manifest = load_dataset_manifest(path.parent)
    assert json.dumps(build_manifest_dict(manifest), indent=2) + "\n" == text
