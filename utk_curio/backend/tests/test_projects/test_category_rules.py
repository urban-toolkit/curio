"""``projects/category_rules.json``: the tags and data types Curio finds in a
dataflow itself, as data.

A package, a template, a model or a dataset declares its own tags and data
types in its manifest (``dataflowCategories``). The table holds the rest: what
a dataflow's code shows (the modules it imports, the files it names), what the
core fields of the manifests it uses show (the grammar a template draws with, a
dataset's format, a collection's kind, each a vocabulary a schema defines), and
the order the names are listed in. So it names no package, model, model type,
dataset or source, and every collection kind has its row.

Each row gives exactly what ``derive`` gives a dataflow with that one signal,
beside what the manifest behind that signal declares, a model package gives
what it declares alone, and a dataflow with every signal lists every name in
the table's order.

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

#: The table's sections.
SECTIONS = {"code", "grammars", "datasetFormats", "collectionKinds", "displayOrder"}
#: What a row of ``code`` looks for in a dataflow's code.
CODE_SIGNALS = {"imports", "fileExtensions", "dataUris"}
#: What a row gives.
GIVES = ("tags", "dataTypes")
#: A node type no rule reads.
PLAIN = "curio.builtin/python-computation"
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
    for section in ("datasetFormats", "collectionKinds"):
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


def _shipped_model_packages() -> list[dict]:
    """The manifest of every model package Curio ships."""
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(PACKAGES.glob("*/manifest.json"))]
    return [raw for raw in manifests if raw.get("kind") == "model"]


def _shipped_declared_names() -> dict[str, set[str]]:
    """Every name a shipped package, one of its templates or a shipped dataset
    declares in ``dataflowCategories``, by the table's section."""
    names: dict[str, set[str]] = {section: set() for section in GIVES}
    for path in sorted(PACKAGES.glob("*/manifest.json")) + sorted(DATASETS.glob("*/manifest.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        templates = [t for t in raw.get("templates") or [] if isinstance(t, dict)]
        for declared in [raw.get("dataflowCategories") or {}, *(t.get("dataflowCategories") or {} for t in templates)]:
            for section in GIVES:
                names[section] |= set(declared.get(section, []))
    return names


def _kinds_without_a_row(rules: dict, kinds) -> list[str]:
    """The collection kinds among *kinds* the table gives no row, but
    ``files``, whose files are of any type."""
    return sorted(kind for kind in kinds if kind != "files" and kind not in rules["collectionKinds"])


def _declared(node_type: str) -> dict:
    """What *node_type*'s package and its template declare in ``dataflowCategories``,
    as a row of the table."""
    package_id, template_id = node_type.split("/", 1)
    for path in sorted(PACKAGES.glob("*/manifest.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["id"] == package_id:
            template = next(t for t in raw["templates"] if t["id"] == template_id)
            both = _given(raw.get("dataflowCategories") or {}, template.get("dataflowCategories") or {})
            return {"tags": both["tags"], "dataTypes": both["data_type"]}
    raise AssertionError(f"Curio ships no package {package_id}")


# ---------------------------------------------------------------------------
# What the table may name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "curio.rasterization/raster-calculator",
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
    assert {"curio.builtin", "curio.rasterization", "curio.vega-lite", "model.scout.deep-umbra", "data.scout.wrf-rain"} <= ids
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


def test_the_display_order_lists_every_name_the_rows_give_and_only_names_something_gives():
    """Every name a row gives is listed once; a listed name no row gives is
    one a shipped manifest declares, as Computer vision is DDRNet23-Slim's
    and SAM 3's: the table names no model type."""
    rules = _rules()
    order = rules["displayOrder"]
    assert set(order) == set(GIVES)
    declared = _shipped_declared_names()
    for section in GIVES:
        names = order[section]
        assert len(set(names)) == len(names), names
        given = {name for row in _rows(rules) for name in row.get(section, [])}
        assert given <= set(names), (section, sorted(given - set(names)))
        assert set(names) <= given | declared[section], (section, sorted(set(names) - given - declared[section]))


def test_every_collection_kind_but_files_has_a_row():
    """Each kind of collection the Discovery source schema reads
    (``COLLECTION_KINDS``) files a dataflow that reads one under its data
    types; a ``files`` resource's files are of any type, so it gives none. A
    kind added to the schema without its row fails here."""
    from utk_curio.backend.app.discovery.domain.manifest import COLLECTION_KINDS

    rules = _rules()
    assert _kinds_without_a_row(rules, COLLECTION_KINDS) == []
    assert set(rules["collectionKinds"]) == set(COLLECTION_KINDS) - {"files"}
    # The check finds a kind a table leaves out.
    planted = {**rules, "collectionKinds": {k: v for k, v in rules["collectionKinds"].items() if k != "videos"}}
    assert _kinds_without_a_row(planted, COLLECTION_KINDS) == ["videos"]


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


def test_a_shipped_model_package_gives_what_it_declares_alone():
    """A node of a shipped model package gives what its package and its
    template declare, and a ``curio_load_model`` call naming it what its
    package declares: the table gives a model's type nothing, a segmentation
    model's included."""
    models = _shipped_model_packages()
    assert {raw["model"]["type"] for raw in models} >= {"semantic-segmentation", "concept-segmentation"}
    for raw in models:
        for template in raw["templates"]:
            node_type = f"{raw['id']}/{template['id']}"
            assert _sorted(_derive([_node("", node_type)])) == _given(_declared(node_type)), node_type
        loads = f'model = curio_load_model("{raw["id"]}")\n'
        assert _sorted(_derive([_node(loads)])) == _given(raw.get("dataflowCategories") or {}), raw["id"]


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
    # A listed name no row gives comes from a model package that declares it,
    # one whose names are all listed.
    given = {section: {name for row in _rows(rules) for name in row.get(section, [])} for section in GIVES}
    listed = {section: set(rules["displayOrder"][section]) for section in GIVES}
    declaring = []
    for raw in _shipped_model_packages():
        node_type = f"{raw['id']}/{raw['templates'][0]['id']}"
        declared = _declared(node_type)
        if any(set(declared[s]) - given[s] for s in GIVES) and all(set(declared[s]) <= listed[s] for s in GIVES):
            declaring.append(_node("", node_type, node_id=raw["id"]))
    assert declaring
    nodes += declaring
    out = _derive(nodes, lambda dataset_id: datasets.get(dataset_id, (None, None)))
    assert out == {
        "tags": rules["displayOrder"]["tags"],
        "data_type": rules["displayOrder"]["dataTypes"],
    }
