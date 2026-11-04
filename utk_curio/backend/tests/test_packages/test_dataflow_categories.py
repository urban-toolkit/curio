"""``dataflowCategories``: the tags and data types a package, or one of its
templates, declares for the dataflows that use it.

One reader cleans the field for the package and the dataset manifests
(``packages/domain/dataflow_categories.py``), as the Projects rail's hand-set
categories are cleaned (``projects/categories.py`` ``normalize_hand``): each
value trimmed, its spaces collapsed and cut to 40 characters, a value that
repeats an earlier one in another case dropped, and at most 20 values. A value
of the wrong type is refused. The schema declares the field at the package and
the template level, and the shipped packages declare exactly ``SHIPPED``.

The reader is imported inside each test: a module that cannot import would
stop the whole backend suite from collecting.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.domain.manifest import (
    ManifestError,
    package_manifest_from_dict,
)
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.tests.test_packages.conftest import _manifest_dict

REPO = Path(__file__).resolve().parents[4]
SCHEMA_PATH = REPO / "docs" / "schemas" / "node-package.v4.json"
# The committed catalog, as the shipped packages are what these tests are about.
CATALOG = REPO / "packages"

#: Every declaration the shipped packages make, by ``(package folder, template
#: id)``, the template id None for one at the top of the manifest.
SHIPPED = {
    ("curio.builtin@1", "spatial-join"): {"dataTypes": ["Geometries"]},
    ("curio.media@1", "video-frames"): {"dataTypes": ["Imagery", "Video"]},
    ("curio.media@1", "split-audio"): {"dataTypes": ["Audio"]},
    ("curio.media@1", "mosaic-rasters"): {"dataTypes": ["Rasters"]},
    # Scout: SCOUT on every node, Rasters on its two raster nodes alone.
    ("curio.scout@1", None): {"tags": ["SCOUT"]},
    ("curio.scout@1", "raster-calculator"): {"dataTypes": ["Rasters"]},
    ("curio.scout@1", "rasterize-buildings"): {"dataTypes": ["Rasters"]},
    ("model.scout.deep-umbra@1", None): {"tags": ["SCOUT"]},
    ("model.scout.weather-gnn@1", None): {"tags": ["SCOUT"]},
}

#: Values of the wrong type, each refused wherever the field is.
WRONG_TYPES = [
    pytest.param("SCOUT", id="a-string"),
    pytest.param(["SCOUT"], id="a-list"),
    pytest.param({"tags": "SCOUT"}, id="tags-a-string"),
    pytest.param({"tags": None}, id="tags-null"),
    pytest.param({"tags": [3]}, id="a-number-in-tags"),
    pytest.param({"dataTypes": [["Rasters"]]}, id="a-list-in-data-types"),
    pytest.param({"dataTypes": {"Rasters": True}}, id="data-types-an-object"),
    pytest.param({"tags": ["SCOUT"], "datatypes": ["Rasters"]}, id="an-unknown-key"),
]


def _clean(raw):
    from utk_curio.backend.app.packages.domain.dataflow_categories import clean_dataflow_categories

    return clean_dataflow_categories(raw, where="manifest.json.dataflowCategories")


def _parse(raw: dict):
    return package_manifest_from_dict(raw, manifest_path=Path("manifest.json"), dir_name="ai.test.demo@1")


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _with_package_level(value) -> dict:
    raw = _manifest_dict()
    raw["dataflowCategories"] = value
    return raw


def _with_template_level(value) -> dict:
    raw = _manifest_dict()
    raw["templates"][0]["dataflowCategories"] = value
    return raw


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("values", [
    ["  Flood ", "flood", "", "Rain   gauges", "FLOOD", "Rain gauges"],
    ["Hydrology", "x" * 41, "y" * 40 + " z", "   "],
    [f"Tag {n}" for n in range(25)] + ["tag 0"],
    [f"T{n}" for n in range(19)] + ["t0", "t1", "Last", "After"],
])
def test_a_list_is_cleaned_as_the_rails_hand_set_tags_are(values):
    """Trimmed, spaces collapsed, cut to 40 characters, the first spelling of a
    repeat kept, and at most 20: what ``normalize_hand`` keeps of the same list."""
    from utk_curio.backend.app.projects.categories import normalize_hand

    expected = normalize_hand({"tags": values})["tags"]
    assert _clean({"tags": values, "dataTypes": values}) == {"tags": expected, "dataTypes": expected}


def test_the_reader_keeps_what_a_declaration_says():
    assert _clean({"tags": [" SCOUT "], "dataTypes": ["Rasters", "rasters", "Imagery"]}) == {
        "tags": ["SCOUT"], "dataTypes": ["Rasters", "Imagery"],
    }
    assert _clean({"dataTypes": ["Rasters"]}) == {"dataTypes": ["Rasters"]}
    assert _clean({"tags": ["Hydrology"]}) == {"tags": ["Hydrology"]}


@pytest.mark.parametrize("raw", [
    None,
    {},
    {"tags": []},
    {"tags": [], "dataTypes": []},
    {"tags": ["", "   "]},
])
def test_no_value_declares_nothing(raw):
    assert _clean(raw) is None


def test_the_field_its_lists_and_its_limits():
    from utk_curio.backend.app.packages.domain import dataflow_categories

    assert dataflow_categories.FIELD == "dataflowCategories"
    assert dataflow_categories.SECTIONS == ("tags", "dataTypes")
    assert dataflow_categories.MAX_VALUE_LENGTH == 40
    assert dataflow_categories.MAX_VALUES == 20


@pytest.mark.parametrize("raw", WRONG_TYPES)
def test_the_reader_refuses_a_wrong_type(raw):
    from utk_curio.backend.app.packages.domain.dataflow_categories import DataflowCategoriesError

    with pytest.raises(DataflowCategoriesError, match="dataflowCategories"):
        _clean(raw)


def test_the_reader_imports_the_standard_library_only():
    """The dataset manifest reads the field with it too, so it stands alone."""
    import ast
    import sys

    from utk_curio.backend.app.packages.domain import dataflow_categories

    tree = ast.parse(Path(dataflow_categories.__file__).read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"a relative import at line {node.lineno}"
            imported.append(node.module)
    outside = {name for name in imported if name.split(".")[0] not in sys.stdlib_module_names}
    assert outside == set()


# ---------------------------------------------------------------------------
# The package manifest
# ---------------------------------------------------------------------------

def test_a_package_and_its_template_keep_what_they_declare():
    raw = _manifest_dict()
    raw["dataflowCategories"] = {"tags": ["Hydrology", "hydrology"], "dataTypes": ["Rasters"]}
    raw["templates"][0]["dataflowCategories"] = {"dataTypes": [" Imagery "]}
    manifest = _parse(raw)
    assert manifest.dataflow_categories == {"tags": ["Hydrology"], "dataTypes": ["Rasters"]}
    assert manifest.templates[0].dataflow_categories == {"dataTypes": ["Imagery"]}


def test_a_package_that_declares_nothing_has_no_categories():
    manifest = _parse(_manifest_dict())
    assert manifest.dataflow_categories is None
    assert manifest.templates[0].dataflow_categories is None


@pytest.mark.parametrize("build", [_with_package_level, _with_template_level], ids=["package", "template"])
@pytest.mark.parametrize("value", WRONG_TYPES)
def test_the_package_parser_refuses_a_wrong_type(build, value):
    with pytest.raises(ManifestError, match="dataflowCategories"):
        _parse(build(value))


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------

def test_the_schema_declares_the_field_at_the_package_and_the_template_level():
    from utk_curio.backend.app.packages.domain.dataflow_categories import MAX_VALUE_LENGTH, MAX_VALUES

    schema = _schema()
    ref = "#/$defs/dataflowCategories"
    assert schema["properties"]["dataflowCategories"]["$ref"] == ref
    assert schema["$defs"]["template"]["properties"]["dataflowCategories"]["$ref"] == ref
    definition = schema["$defs"]["dataflowCategories"]
    assert definition["type"] == "object"
    assert definition["additionalProperties"] is False
    assert set(definition["properties"]) == {"tags", "dataTypes"}
    for section in definition["properties"].values():
        assert section["type"] == "array"
        assert section["maxItems"] == MAX_VALUES
        assert section["items"]["type"] == "string"
        assert section["items"]["maxLength"] == MAX_VALUE_LENGTH


@pytest.mark.parametrize("build", [_with_package_level, _with_template_level], ids=["package", "template"])
@pytest.mark.parametrize("value", WRONG_TYPES)
def test_the_schema_refuses_what_the_parser_refuses(build, value):
    from jsonschema import Draft202012Validator

    errors = list(Draft202012Validator(_schema()).iter_errors(build(value)))
    assert errors, f"the schema takes {value!r}"


@pytest.mark.parametrize("build", [_with_package_level, _with_template_level], ids=["package", "template"])
def test_the_schema_and_the_parser_take_a_declaration(build):
    from jsonschema import Draft202012Validator

    raw = build({"tags": ["SCOUT"], "dataTypes": ["Rasters", "Imagery"]})
    assert list(Draft202012Validator(_schema()).iter_errors(raw)) == []
    _parse(raw)


def test_the_schema_refuses_a_value_the_parser_cuts():
    """The schema states the limits a manifest is written to; the parser keeps
    the first 40 characters of a longer value, as the rail does."""
    from jsonschema import Draft202012Validator

    raw = _with_package_level({"tags": ["x" * 41]})
    assert list(Draft202012Validator(_schema()).iter_errors(raw))
    assert _parse(raw).dataflow_categories == {"tags": ["x" * 40]}


# ---------------------------------------------------------------------------
# What the shipped packages declare
# ---------------------------------------------------------------------------

def test_the_shipped_packages_declare_exactly_these():
    found = {}
    for path in sorted(CATALOG.glob("*/manifest.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        folder = path.parent.name
        if "dataflowCategories" in raw:
            found[(folder, None)] = raw["dataflowCategories"]
        for template in raw.get("templates") or []:
            if "dataflowCategories" in template:
                found[(folder, template["id"])] = template["dataflowCategories"]
    assert found == SHIPPED


@pytest.mark.parametrize("folder, template_id", sorted(SHIPPED, key=str))
def test_each_shipped_declaration_loads_as_it_is_written(folder, template_id):
    manifest = load_package_manifest(CATALOG / folder)
    if template_id is None:
        declared = manifest.dataflow_categories
    else:
        (template,) = [t for t in manifest.templates if t.template_id == template_id]
        declared = template.dataflow_categories
    assert declared == SHIPPED[(folder, template_id)]
