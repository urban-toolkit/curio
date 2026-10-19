"""``docs/schemas/dataset.v1.json`` and the dataset manifest parser agree.

A shipped dataset's manifest is written by hand or by the script that builds
the dataset, and Curio writes every other one with ``build_manifest_dict``: an
import, a Discovery Catalog download or collection, a node's saved output, a
published dataset. The schema is what a dataset author writes against, as
``node-package.v4.json`` is for a package (``test_packages/test_builtin_package.py``)
and ``discovery-source.v1.json`` for a source
(``test_discovery/test_schema_matches_validator.py``). Here:

- every shipped manifest validates, as written and as Curio writes it back;
- what Curio writes for each kind of dataset validates: an import, a published
  dataset, a node's output (one file, or a bundle of parts), a collection;
- the schema declares the fields the parser reads, no more and no fewer, and
  the writer writes those; the schema requires the fields the parser requires;
- a value the parser refuses, the schema refuses: the format, a collection's
  kind (which the source's parser decides), ``dataflowCategories``,
  ``downloadOnFirstUse`` and every other typed field.

The value lists are the code's (``SUPPORTED_FORMATS``, ``COLLECTION_KINDS``,
``DATASET_ID_RE``), never restated. One rule is between two fields, which
JSON Schema cannot compare: ``downloadOnFirstUse`` names the ``dataFile`` and
no other file. The schema takes one path at most and says the rest in words;
the parser holds it (``test_dataset_download_on_first_use.py``).

The schema is read inside each test, never at import.
"""

from __future__ import annotations

import functools
import io
import json
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.manifest import (
    SUPPORTED_FORMATS,
    ManifestError,
    _parse_manifest,
    build_manifest_dict,
    load_dataset_manifest,
    manifest_text,
)
from utk_curio.backend.app.discovery.domain.manifest import COLLECTION_KINDS, RESOURCE_KINDS

REPO = Path(__file__).resolve().parents[4]
SCHEMA_PATH = REPO / "docs" / "schemas" / "dataset.v1.json"
PACKAGE_SCHEMA_PATH = REPO / "docs" / "schemas" / "node-package.v4.json"
CATALOG = REPO / "datasets"
#: The Discovery Catalog's example storage source, whose folder ships with Curio.
EXAMPLE_SOURCE = REPO / "discovery" / "source.curio.example-storage@1"
#: Its rows that land as a collection, one per kind of file it holds.
COLLECTED = [
    resource["id"]
    for resource in json.loads((EXAMPLE_SOURCE / "manifest.json").read_text(encoding="utf-8"))["resources"]
    if resource["kind"] in COLLECTION_KINDS
]

DATA_FILE = "data/rain.csv"

#: A manifest in which every field holds a value, so the parser reads each one.
EVERY_FIELD = {
    "id": "data.test.rain",
    "name": "Rain",
    "version": "1.0.0",
    "format": "csv",
    "description": "Rain at each gauge.",
    "publisher": "Curio",
    "license": "MIT",
    "tags": ["rain", "chicago"],
    "dataflowCategories": {"tags": ["Weather"], "dataTypes": ["Tables"]},
    "dataFile": DATA_FILE,
    "downloadOnFirstUse": [DATA_FILE],
    "compatibility": {"major": 1},
    "sourceLabel": "Curio",
    "rowCount": 2,
    "featureCount": 2,
    "schema": {"fields": [{"name": "mm", "type": "DOUBLE", "nullable": False}]},
    "createdAt": "2026-10-01T00:00:00Z",
    "updatedAt": "2026-10-02T00:00:00Z",
    "sourceUpdatedAt": "2026-09-30T00:00:00Z",
    "sourceEncoding": "windows-1252",
    "groupId": "netcdf.rain",
    "layerName": "rain",
    "producerNodeId": "node-2",
    "producerNodeType": "curio.builtin/data-transformation",
    "producerDataflowId": "flow-1",
    "producerDataflowName": "Rain",
    "upstreamInputs": [
        {"nodeId": "node-1", "nodeType": "curio.builtin/data-loading"},
        {"datasetId": "data.utk.chicago-boundary"},
    ],
    "discoverySource": {
        "sourceId": "source.curio.example-storage@1",
        "sourceName": "Example storage",
        "resourceId": "stations",
        "fetchedAt": "2026-10-01T00:00:00Z",
        "contentSha256": "0" * 64,
    },
    "collection": None,
}

#: A collection dataset: the index of files kept where they are.
A_COLLECTION = {
    "id": "imported.xa1b2c3d4e5f6",
    "name": "Noise",
    "version": "1.0.0",
    "format": "collection",
    "dataFile": "data/index.parquet",
    "collection": {
        "kind": "audio",
        "sourceId": "source.curio.example-storage@1",
        "resourceId": "noise",
        "fileCount": 3,
    },
}


@functools.lru_cache(maxsize=None)
def _validator():
    from jsonschema import Draft202012Validator

    return Draft202012Validator(_schema())


def _schema() -> dict:
    assert SCHEMA_PATH.is_file(), f"no schema at {SCHEMA_PATH}"
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _errors(raw: dict) -> list[str]:
    """What the schema finds wrong with *raw*, one line each."""
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '(manifest)'}: {error.message}"
        for error in _validator().iter_errors(raw)
    ]


def _assert_valid(raw: dict) -> None:
    errors = _errors(raw)
    assert not errors, "\n".join(errors)


def _parse(raw: dict):
    return _parse_manifest(raw, where="manifest.json")


def _written(folder: Path) -> dict:
    """The manifest.json a folder holds, as written."""
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


class _Reads(dict):
    """A manifest that notes each key the parser reads from it."""

    def __init__(self, raw: dict):
        super().__init__(raw)
        self.read: set[str] = set()

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        self.read.add(key)
        return super().__contains__(key)


def _fields_the_parser_reads() -> tuple[set[str], set[str]]:
    """The keys the parser reads from a manifest, and from its compatibility."""
    compatibility = _Reads(EVERY_FIELD["compatibility"])
    raw = _Reads({**EVERY_FIELD, "compatibility": compatibility})
    _parse(raw)
    return raw.read, compatibility.read


# ---------------------------------------------------------------------------
# The schema itself
# ---------------------------------------------------------------------------

def test_the_schema_is_a_2020_12_schema():
    from jsonschema import Draft202012Validator

    schema = _schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("docs/schemas/dataset.v1.json")
    Draft202012Validator.check_schema(schema)


def test_the_schema_declares_the_fields_the_parser_reads_and_the_writer_writes():
    """Both ways: a field the parser reads is declared, and a declared field
    is one the parser reads. The writer, given every field, writes them all."""
    read, compatibility_read = _fields_the_parser_reads()
    assert {"id", "format", "dataFile", "compatibility"} <= read
    schema = _schema()
    declared = set(schema["properties"])
    assert declared == read, {
        "read but not declared": sorted(read - declared),
        "declared but never read": sorted(declared - read),
    }
    assert set(schema["properties"]["compatibility"]["properties"]) == compatibility_read
    written = set(build_manifest_dict(_parse(EVERY_FIELD)))
    assert written == declared, {
        "written but not declared": sorted(written - declared),
        "declared but never written": sorted(declared - written),
    }


def test_the_schema_requires_the_fields_the_parser_requires():
    """Each field in turn left out of a manifest that holds every one: the
    parser refuses the manifest exactly when the schema requires the field."""
    required = set()
    for key in EVERY_FIELD:
        raw = {k: v for k, v in EVERY_FIELD.items() if k != key}
        try:
            _parse(raw)
        except ManifestError:
            required.add(key)
            assert _errors(raw), f"the schema takes a manifest without {key}"
        else:
            assert not _errors(raw), (key, _errors(raw))
    assert required
    assert set(_schema()["required"]) == required


def test_the_format_enum_is_the_formats_curio_stores():
    assert _schema()["properties"]["format"]["enum"] == sorted(SUPPORTED_FORMATS)


def test_the_id_pattern_is_the_parsers():
    from utk_curio.backend.app.datasets.infrastructure.storage import DATASET_ID_RE

    assert _schema()["properties"]["id"]["pattern"] == DATASET_ID_RE.pattern


def test_a_collections_kind_is_a_kind_a_source_collects():
    """A collection's kind is the kind of the source row its files belong to:
    one the source's parser takes, and not a table, which lands as a table."""
    assert _schema()["properties"]["collection"]["properties"]["kind"]["enum"] == sorted(COLLECTION_KINDS)


def test_dataflow_categories_are_declared_as_the_package_schema_declares_them():
    """Both manifest parsers clean the field with one reader
    (``packages/domain/dataflow_categories.py``), so both schemas declare it
    alike."""
    schema = _schema()
    package = json.loads(PACKAGE_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["dataflowCategories"]["$ref"] == "#/$defs/dataflowCategories"
    assert schema["$defs"]["dataflowCategories"] == package["$defs"]["dataflowCategories"]


# ---------------------------------------------------------------------------
# What the parser refuses, the schema refuses
# ---------------------------------------------------------------------------

REFUSED = [
    # The fields the parser requires: blank, or of another type.
    ("id", "   "),
    ("id", 7),
    ("id", "rain"),
    ("id", "Data.Test.Rain"),
    ("id", "data.test.rain@1"),
    ("name", "  "),
    ("name", 3),
    ("version", " "),
    ("version", 1),
    ("dataFile", " "),
    ("dataFile", [DATA_FILE]),
    # A format Curio does not store.
    ("format", "xlsx"),
    ("format", "osm"),
    ("format", "gpkg"),
    ("format", ""),
    ("format", ["csv"]),
    # A major version outside the folder names Curio reads.
    ("compatibility", {"major": -1}),
    ("compatibility", {"major": 10000}),
    ("compatibility", {"major": "one"}),
    ("compatibility", {"major": None}),
    # A list or an object of another type.
    ("tags", "rain"),
    ("tags", {"rain": 1}),
    ("schema", "mm"),
    ("schema", ["mm"]),
    ("discoverySource", "portal"),
    ("discoverySource", ["portal"]),
    ("collection", "audio"),
    ("collection", ["audio"]),
    ("rowCount", "many"),
    ("featureCount", "many"),
    # dataflowCategories of the wrong type.
    ("dataflowCategories", "SCOUT"),
    ("dataflowCategories", ["SCOUT"]),
    ("dataflowCategories", {"tags": "SCOUT"}),
    ("dataflowCategories", {"tags": [None]}),
    ("dataflowCategories", {"dataTypes": [{"name": "Rasters"}]}),
    ("dataflowCategories", {"tags": ["SCOUT"], "categories": ["Flood"]}),
    # downloadOnFirstUse that no reader would download.
    ("downloadOnFirstUse", DATA_FILE),
    ("downloadOnFirstUse", {"path": DATA_FILE}),
    ("downloadOnFirstUse", [3]),
    ("downloadOnFirstUse", [""]),
    ("downloadOnFirstUse", ["/data/rain.csv"]),
    ("downloadOnFirstUse", ["data\\rain.csv"]),
    ("downloadOnFirstUse", ["data/../rain.csv"]),
    ("downloadOnFirstUse", ["./data/rain.csv"]),
    ("downloadOnFirstUse", ["data//rain.csv"]),
    ("downloadOnFirstUse", ["manifest.json"]),
    ("downloadOnFirstUse", ["integrity.json"]),
    ("downloadOnFirstUse", [DATA_FILE, DATA_FILE]),
    ("downloadOnFirstUse", [DATA_FILE, "data/other.csv"]),
]


@pytest.mark.parametrize(
    "field, value", REFUSED, ids=[f"{field}-{index}" for index, (field, _value) in enumerate(REFUSED)]
)
def test_a_value_the_parser_refuses_the_schema_refuses(field, value):
    raw = {**EVERY_FIELD, field: value}
    # A ManifestError, or the ValueError int() raises for a count.
    with pytest.raises(ValueError):
        _parse(raw)
    assert _errors(raw), f"the schema takes {field} = {value!r}"


@pytest.mark.parametrize("field, value", [
    ("compatibility", {"major": 0}),
    ("compatibility", {"major": 9999}),
    ("tags", []),
    ("dataflowCategories", {}),
    ("downloadOnFirstUse", []),
    ("upstreamInputs", []),
], ids=["major-0", "major-9999", "no-tags", "no-categories", "no-file-left-out", "no-inputs"])
def test_a_value_at_the_edge_both_take(field, value):
    raw = {**EVERY_FIELD, field: value}
    _parse(raw)
    _assert_valid(raw)


@pytest.mark.parametrize("change", ["absent", "null", "empty"])
def test_a_collection_dataset_needs_its_collection(change):
    raw = dict(A_COLLECTION)
    if change == "absent":
        del raw["collection"]
    else:
        raw["collection"] = None if change == "null" else {}
    with pytest.raises(ManifestError, match="collection"):
        _parse(raw)
    assert _errors(raw), f"the schema takes a collection dataset whose collection is {change}"


def test_a_collection_dataset_with_its_collection_is_taken():
    _parse(A_COLLECTION)
    _assert_valid(A_COLLECTION)


@pytest.mark.parametrize("kind", ["podcasts", ""])
def test_a_kind_the_source_parser_refuses_is_refused(kind):
    from utk_curio.backend.app.discovery.domain import manifest as source_manifest

    with pytest.raises(source_manifest.ManifestError, match="kind"):
        source_manifest._parse_resource(
            {"id": "files", "kind": kind, "path": "files/{name}.wav"}, where="resources[0]"
        )
    raw = {**A_COLLECTION, "collection": {**A_COLLECTION["collection"], "kind": kind}}
    assert _errors(raw), f"the schema takes a collection of kind {kind!r}"


def test_a_table_is_never_a_collection():
    tables = sorted(set(RESOURCE_KINDS) - set(COLLECTION_KINDS))
    assert tables
    for kind in tables:
        raw = {**A_COLLECTION, "collection": {**A_COLLECTION["collection"], "kind": kind}}
        assert _errors(raw), f"the schema takes a collection of kind {kind!r}"


# ---------------------------------------------------------------------------
# The shipped datasets
# ---------------------------------------------------------------------------

def test_every_shipped_manifest_validates_as_written_and_as_curio_writes_it():
    folders = sorted(path.parent for path in CATALOG.glob("*/manifest.json"))
    assert folders, f"no datasets under {CATALOG}"
    failures = []
    for folder in folders:
        rewritten = json.loads(manifest_text(load_dataset_manifest(folder)))
        for label, raw in (("as shipped", _written(folder)), ("as Curio writes it", rewritten)):
            failures += [f"{folder.name} {label}: {error}" for error in _errors(raw)]
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# What Curio writes for each kind of dataset
# ---------------------------------------------------------------------------

def _import(user, filename: str, data: bytes, **kwargs) -> dict:
    from werkzeug.datastructures import FileStorage

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    return DatasetCatalogService(user=user).import_dataset(
        FileStorage(stream=io.BytesIO(data), filename=filename), **kwargs
    )


def test_an_imported_file(app, db, user_and_token):
    """An upload in another encoding, with the date of its source file and the
    link it was downloaded from."""
    user, _ = user_and_token
    item = _import(
        user, "cities.csv", "city,note\nCafé,naïve\nZürich,Öl\n".encode("cp1252"),
        source_updated_at="2026-09-30T12:00:00Z",
        discovery_source={"resourceUrl": "https://example.org/cities.csv"},
    )
    raw = _written(Path(item["path"]).parents[1])
    assert raw["id"] == item["id"] and raw["sourceEncoding"]
    assert raw["sourceUpdatedAt"] and raw["discoverySource"]["manual"] is True
    _assert_valid(raw)


def test_a_published_dataset(app, db, user_and_token, tmp_path, monkeypatch):
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(catalog))
    user, _ = user_and_token
    item = _import(user, "gauges.csv", b"gauge,mm\nA,3\nB,5\n")

    DatasetCatalogService(user=user).publish_dataset(item["id"], {"license": "CC-BY-4.0"})

    raw = _written(catalog / f"{item['id']}@1")
    assert raw["license"] == "CC-BY-4.0"
    _assert_valid(raw)


def test_a_node_output(app):
    from utk_curio.backend.app.datasets.install.installer import install_computed_file_for_node

    result = install_computed_file_for_node(
        "1", b"gauge,mm\nA,3\n", "rain.csv", "csv",
        node_id="node-2", dataflow_id="flow-1", node_type="curio.builtin/data-transformation",
        dataflow_name="Rain", upstream_inputs=EVERY_FIELD["upstreamInputs"],
    )
    raw = _written(result.dest)
    assert raw["producerNodeId"] == "node-2" and raw["upstreamInputs"]
    _assert_valid(raw)


def test_a_node_output_of_several_parts(app, tmp_path):
    from utk_curio.backend.app.datasets.install.bundle import (
        BundlePart,
        install_computed_bundle_for_node,
    )

    part = tmp_path / "part0.json"
    part.write_text(json.dumps({"mm": 3}), encoding="utf-8")
    result = install_computed_bundle_for_node(
        "1",
        [BundlePart(index=0, artifact_id="a1", kind="dict", format="json",
                    label="Object, part 1", source_path=part)],
        node_id="node-3", parent_artifact_id="parent-1", dataflow_id="flow-1",
    )
    raw = _written(result.dest)
    assert raw["format"] == "bundle" and raw["schema"]["bundleParts"]
    _assert_valid(raw)


@pytest.mark.parametrize("resource_id", COLLECTED)
def test_a_collection_added_from_a_storage_source(app, db, user_and_token, resource_id):
    """The add a Discovery Catalog job runs, on the example storage source,
    with the service the routes build. Its collection and discoverySource
    keys are all ones the schema declares."""
    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.app.discovery.service import DiscoveryService
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, _ = user_and_token
    added = DiscoveryService(_user_dir_key(user), user=user)._storage_acquire.acquire(
        load_source_manifest(EXAMPLE_SOURCE), resource_id
    )
    raw = _written(Path(added["dataset"]["path"]).parents[1])
    assert raw["format"] == "collection" and raw["collection"]["kind"] in COLLECTION_KINDS
    _assert_valid(raw)
    properties = _schema()["properties"]
    for block in ("collection", "discoverySource"):
        undeclared = set(raw[block]) - set(properties[block]["properties"])
        assert not undeclared, f"{block} holds keys the schema does not declare: {sorted(undeclared)}"
