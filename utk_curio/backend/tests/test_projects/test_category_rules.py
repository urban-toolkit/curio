"""``projects/category_rules.json``: the tags and data types Curio finds in a
dataflow itself, as data.

A package, a template, a model or a dataset declares its own tags and data
types in its manifest (``dataflowCategories``). The table holds the rest: what
a dataflow's code shows (the modules it imports, the files it names), what the
core fields of the manifests it uses show (the grammar a template draws with, a
model's type, a dataset's format, a collection's kind), and the order the
names are listed in. So it names no package, model, dataset or source.

Each row gives exactly what ``derive`` gives a dataflow with that one signal,
and a dataflow with every signal lists every name in the table's order.

The table is read inside each test, so a missing table fails these tests and
nothing else.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.projects import categories
from utk_curio.backend.app.projects.categories import derive

REPO = Path(__file__).resolve().parents[4]
PACKAGES = REPO / "packages"
DATASETS = REPO / "datasets"
DISCOVERY = REPO / "discovery"
SCHEMA = REPO / "docs" / "schemas" / "node-package.v4.json"

#: The table's sections.
SECTIONS = {"code", "grammars", "modelTypes", "datasetFormats", "collectionKinds", "displayOrder"}
#: What a row of ``code`` looks for in a dataflow's code.
CODE_SIGNALS = {"imports", "fileExtensions", "dataUris"}
#: What a row gives.
GIVES = ("tags", "dataTypes")
#: A node type no rule reads.
PLAIN = "curio.builtin/computation-analysis"
#: The prefixes of the ids Curio's packages, models and datasets have.
PREFIXES = ("curio.", "scout.", "model.", "data.", "ai.")


def _rules() -> dict:
    path = Path(categories.__file__).with_name("category_rules.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _node(content: str, node_type: str = PLAIN, node_id: str = "n") -> dict:
    return {"id": node_id, "type": node_type, "content": content}


def _derive(nodes: list[dict], dataset_kind=None) -> dict:
    return derive({"dataflow": {"nodes": nodes, "edges": []}}, dataset_kind)


def _sorted(out: dict) -> dict:
    return {"tags": sorted(out["tags"]), "data_type": sorted(out["data_type"])}


def _given(*rows: dict) -> dict:
    """What *rows* give together, as ``_sorted`` puts ``derive``'s answer."""
    return {
        "tags": sorted({name for row in rows for name in row.get("tags", [])}),
        "data_type": sorted({name for row in rows for name in row.get("dataTypes", [])}),
    }


def _rows(rules: dict) -> list[dict]:
    """Every row of the table that gives names."""
    rows = list(rules["code"])
    for row in rules["grammars"].values():
        rows.append(row)
        rows += list(row.get("specKeys", {}).values())
    for section in ("modelTypes", "datasetFormats", "collectionKinds"):
        rows += list(rules[section].values())
    return rows


def _strings(value):
    """Every key and every string in *value*."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def _shipped_ids() -> set[str]:
    """The id of every package, model, dataset and source Curio ships."""
    ids = set()
    for root in (PACKAGES, DATASETS, DISCOVERY):
        for path in root.glob("*/manifest.json"):
            ids.add(json.loads(path.read_text(encoding="utf-8"))["id"])
    return ids


def _artifact_names(text: str, ids: set[str]) -> list[str]:
    """The shipped ids, and the prefixes of ids, that *text* names."""
    prefixes = set(PREFIXES) | {artifact_id.split(".")[0] + "." for artifact_id in ids}
    named = [artifact_id for artifact_id in ids if artifact_id in text]
    named += [p for p in sorted(prefixes) if re.search(rf"(?<![\w-]){re.escape(p)}", text)]
    return named


def _builtin_template_drawing_with(grammar: str) -> str:
    """The node type of the built-in template whose ``grammarId`` is *grammar*."""
    manifest = json.loads((PACKAGES / "curio.builtin@1" / "manifest.json").read_text(encoding="utf-8"))
    ids = [t["id"] for t in manifest["templates"] if t.get("grammarId") == grammar]
    assert len(ids) == 1, (grammar, ids)
    return f"{manifest['id']}/{ids[0]}"


def _model_node_types(model_type: str) -> list[str]:
    """The node types of every shipped model package whose model is a *model_type*."""
    found = []
    for path in sorted(PACKAGES.glob("*/manifest.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("kind") == "model" and (raw.get("model") or {}).get("type") == model_type:
            found += [f"{raw['id']}/{template['id']}" for template in raw["templates"]]
    return found


# ---------------------------------------------------------------------------
# What the table may name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "curio.scout/raster-calculator",
    "scout.",
    "model.scout.",
    "model.curio.ddrnet23-slim",
    "data.scout.wrf-rain",
    "curio.builtin/vis-vega",
    "ai.utk.uhvi",
    "source.osm.openstreetmap",
])
def test_the_scan_finds_an_id_or_a_prefix(text):
    assert _artifact_names(text, _shipped_ids())


@pytest.mark.parametrize("text", [
    "rasterio", "PIL", "tiff", "image/", "vega-lite", "autk-grammar", "semantic-segmentation",
    "GPU compute", "OpenStreetMap", "metadata.json",
])
def test_the_scan_passes_a_name_that_is_not_an_id(text):
    assert _artifact_names(text, _shipped_ids()) == []


def test_the_table_names_no_package_model_dataset_or_source():
    ids = _shipped_ids()
    assert {"curio.builtin", "curio.scout", "model.scout.deep-umbra", "data.scout.wrf-rain"} <= ids
    named = {text: _artifact_names(text, ids) for text in _strings(_rules())}
    assert {text: found for text, found in named.items() if found} == {}


# ---------------------------------------------------------------------------
# Its shape
# ---------------------------------------------------------------------------

def test_the_table_has_its_sections_and_each_row_gives_names_a_manifest_could_declare():
    from utk_curio.backend.app.packages.domain.dataflow_categories import clean_dataflow_categories

    rules = _rules()
    assert set(rules) == SECTIONS
    for row in rules["code"]:
        assert set(row) & CODE_SIGNALS, row
        assert set(row) <= CODE_SIGNALS | set(GIVES), row
    for row in _rows(rules):
        given = {key: row[key] for key in GIVES if key in row}
        assert given, row
        assert clean_dataflow_categories(given, where="category_rules.json") == given


def test_the_display_order_lists_every_name_the_rows_give_and_no_other():
    rules = _rules()
    order = rules["displayOrder"]
    assert set(order) == set(GIVES)
    for section in GIVES:
        names = order[section]
        assert len(set(names)) == len(names), names
        assert set(names) == {name for row in _rows(rules) for name in row.get(section, [])}


def test_the_model_types_are_the_schemas():
    enum = json.loads(SCHEMA.read_text(encoding="utf-8"))["$defs"]["model"]["properties"]["type"]["enum"]
    assert set(_rules()["modelTypes"]) <= set(enum)


# ---------------------------------------------------------------------------
# Each row gives what derive gives
# ---------------------------------------------------------------------------

def test_each_imported_module_gives_what_its_row_says():
    rows = [row for row in _rules()["code"] if row.get("imports")]
    assert rows
    for row in rows:
        for module in row["imports"]:
            for code in (
                f"import {module}\n",
                f"from {module} import thing\n",
                f"def run():\n    import {module} as m\n    return m\n",
            ):
                assert _sorted(_derive([_node(code)])) == _given(row), code


def test_each_file_named_in_code_gives_what_its_row_says():
    rows = [row for row in _rules()["code"] if row.get("fileExtensions") or row.get("dataUris")]
    assert rows
    for row in rows:
        codes = [f'path = "folder/file.{extension}"\n' for extension in row.get("fileExtensions", [])]
        codes += [f'url = "data:{media}x-sample;base64,AAAA"\n' for media in row.get("dataUris", [])]
        assert codes, row
        for code in codes:
            assert _sorted(_derive([_node(code)])) == _given(row), code


def test_each_grammar_gives_what_its_row_says():
    grammars = _rules()["grammars"]
    assert grammars
    for grammar, row in grammars.items():
        node_type = _builtin_template_drawing_with(grammar)
        assert _sorted(_derive([_node("{}", node_type)])) == _given(row), grammar
        for key, extra in row.get("specKeys", {}).items():
            spec = json.dumps({key: {}})
            assert _sorted(_derive([_node(spec, node_type)])) == _given(row, extra), (grammar, key)


def test_a_spec_key_gives_its_names_under_its_own_grammar_only():
    grammars = _rules()["grammars"]
    for grammar, row in grammars.items():
        node_type = _builtin_template_drawing_with(grammar)
        for other, other_row in grammars.items():
            for key in other_row.get("specKeys", {}):
                if key in row.get("specKeys", {}):
                    continue
                spec = json.dumps({key: {}})
                assert _sorted(_derive([_node(spec, node_type)])) == _given(row), (grammar, other, key)


def test_each_model_type_gives_what_its_row_says():
    model_types = _rules()["modelTypes"]
    assert model_types
    for model_type, row in model_types.items():
        node_types = _model_node_types(model_type)
        assert node_types, f"Curio ships no {model_type} model"
        for node_type in node_types:
            assert _sorted(_derive([_node("", node_type)])) == _given(row), node_type


def test_each_dataset_format_and_collection_kind_gives_what_its_row_says():
    rules = _rules()
    cases = [((fmt, None), row) for fmt, row in rules["datasetFormats"].items()]
    cases += [((None, kind), row) for kind, row in rules["collectionKinds"].items()]
    assert cases
    code = 'rows = curio_load_data("one-dataset")\n'
    for found, row in cases:
        out = _derive([_node(code)], lambda _dataset_id, found=found: found)
        assert _sorted(out) == _given(row), found


def test_a_dataflow_with_every_signal_lists_every_name_in_the_display_order():
    rules = _rules()
    lines = []
    for row in rules["code"]:
        lines += [f"import {module}" for module in row.get("imports", [])]
        lines += [f'path = "file.{extension}"' for extension in row.get("fileExtensions", [])]
        lines += [f'url = "data:{media}x-sample;base64,AAAA"' for media in row.get("dataUris", [])]
    datasets = {f"format-{fmt}": (fmt, None) for fmt in rules["datasetFormats"]}
    datasets.update({f"kind-{kind}": (None, kind) for kind in rules["collectionKinds"]})
    lines += [f'rows = curio_load_data("{dataset_id}")' for dataset_id in datasets]
    nodes = [_node("\n".join(lines) + "\n", node_id="code")]
    for grammar, row in rules["grammars"].items():
        spec = json.dumps({key: {} for key in row.get("specKeys", {})})
        nodes.append(_node(spec, _builtin_template_drawing_with(grammar), node_id=grammar))
    for model_type in rules["modelTypes"]:
        nodes.append(_node("", _model_node_types(model_type)[0], node_id=model_type))
    out = _derive(nodes, lambda dataset_id: datasets.get(dataset_id, (None, None)))
    assert out == {
        "tags": rules["displayOrder"]["tags"],
        "data_type": rules["displayOrder"]["dataTypes"],
    }
