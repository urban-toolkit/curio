"""Every feature an agent builds with is on a knowledge page, and agents read it.

The base entry's ``knowledge/`` holds one page per feature of Curio, and the
preamble every agent reads includes them. A page that reaches no agent, a
built-in template no page names, a kind of chip no page shows and a function
of node code no page gives all fail here:

- a built-in template is on a page when a page of the base entry names it by
  its marker, ``{{template.label:curio.builtin/<id>}}``, beyond the lists the
  preamble draws from the manifest, which name every template whatever is
  written about it;
- a kind of chip is on a page when a page, as agents read it, shows a chip of
  that kind: the kinds are the ones the runtime resolves in the table of
  cases Jest and pytest share (``codeReferences.cases.json``);
- a function is on a page when the functions page gives it
  (``test_node_functions_sandbox.py`` compares it with each engine's code).

``dataflow.read`` lists each node's selection tags, which the selection page
names, and the catalogs page says what each catalog holds and which tools
reach it.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
BASE = REPO_ROOT / "agents" / "agent.curio.builtin@1"
KNOWLEDGE = BASE / "knowledge"
BUILTIN_MANIFEST = REPO_ROOT / "packages" / "curio.builtin@1" / "manifest.json"
CASES = (REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "references"
         / "codeReferences.cases.json")
WRAPPER = REPO_ROOT / "utk_curio" / "sandbox" / "util" / "js_wrapper.mjs"
#: The pages every agent reads in its preamble.
IN_THE_PREAMBLE = ("node-functions.md", "catalogs.md", "selection-chips.md")
_TEMPLATE_MARKER_RE = re.compile(r"\{\{template\.label:curio\.builtin/([a-z0-9-]+)\}\}")
_INCLUDE_RE = re.compile(r"\{\{include:([^{}]+)\}\}")


def _sources() -> dict[str, str]:
    """Every page of the base entry, by its path there, as written."""
    listed = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))["pages"]
    return {page: (BASE / page).read_text(encoding="utf-8") for page in listed}


def _rendered() -> dict[str, str]:
    """Every page of the base entry, by its path there, as agents read it."""
    from utk_curio.backend.app.agents.domain import agent_text

    return {page: agent_text.read(agent_text.page_file(page)) for page in agent_text.pages()}


def _chip_kind(inner: str) -> str | None:
    """The kind of the chip *inner* stands in: a widget, a selection tag, an
    input with its layer and its column if it names them, a scenario chip by
    the list it writes, the dataset of every input or one of its columns. None
    for a scenario word no chip is."""
    from utk_curio.backend.app.execution.code_references import parse_reference

    parsed = parse_reference(inner)
    if parsed["kind"] == "input":
        return " ".join(["input", *(["layer"] if "layer" in parsed else []),
                         *(["column"] if "column" in parsed else [])])
    if parsed["kind"] == "scenario":
        return f"scenario {parsed['chip']}" if parsed["chip"] else None
    return parsed["kind"]


def test_every_knowledge_page_is_listed_and_reaches_the_agents():
    """Each page in ``knowledge/`` is one the base entry lists, and a page or
    prompt an agent reads includes it; the functions, catalogs and selection
    pages ride the preamble, so every agent reads them."""
    from utk_curio.backend.app.agents.domain import builtin

    on_disk = sorted(path.name for path in KNOWLEDGE.glob("*.md"))
    assert set(IN_THE_PREAMBLE) <= set(on_disk), on_disk
    listed = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))["pages"]
    assert sorted(page.split("/", 1)[1] for page in listed if page.startswith("knowledge/")) == on_disk
    written = [path.read_text(encoding="utf-8") for path in (REPO_ROOT / "agents").rglob("*.md")]
    included = {page for text in written for page in _INCLUDE_RE.findall(text)}
    assert not [name for name in on_disk if f"knowledge/{name}" not in included], included
    preamble = (BASE / "default_preamble.md").read_text(encoding="utf-8")
    for name in IN_THE_PREAMBLE:
        assert preamble.count("{{include:knowledge/" + name + "}}") == 1, name
    read = builtin.read_prompt_text("agent.curio.node-builder@1", "system")
    for name in IN_THE_PREAMBLE:
        page = _rendered()["knowledge/" + name].rstrip("\n")
        assert read.count(page) == 1, name


def test_every_built_in_template_is_named_on_a_page():
    templates = [t["id"] for t in json.loads(BUILTIN_MANIFEST.read_text(encoding="utf-8"))["templates"]]
    assert len(templates) >= 13, templates
    named = {found for text in _sources().values() for found in _TEMPLATE_MARKER_RE.findall(text)}
    missing = [template for template in templates if template not in named]
    assert not missing, (
        f"no page of the base entry names the built-in templates {missing}: write what each does on the page "
        "of its feature, naming it as {{template.label:curio.builtin/<id>}}"
    )


def test_every_kind_of_chip_is_on_a_page():
    from utk_curio.backend.app.execution.code_references import REFERENCE_RE

    resolved = {
        kind
        for case in json.loads(CASES.read_text(encoding="utf-8"))["cases"] if not case.get("problems")
        for match in REFERENCE_RE.finditer(case["code"])
        for kind in [_chip_kind(match.group(1))] if kind
    }
    assert {"input layer", "selection", "stacked", "scenario colors"} <= resolved, resolved
    shown = {
        kind
        for text in _rendered().values()
        for match in REFERENCE_RE.finditer(text)
        for kind in [_chip_kind(match.group(1))] if kind
    }
    missing = sorted(resolved - shown)
    assert not missing, f"no page shows a chip of the kinds {missing}"


def test_the_chip_markers_write_the_runtimes_chips():
    """A page shows a chip through a marker, which writes it as the runtime
    does: a layer and its column, a column of every input's rows, a
    selection tag, and the most ids a tag holds."""
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.app.execution.code_references import (
        SELECTION_ID_CAP,
        input_reference_inner,
        parse_reference,
        reference_text,
    )

    def render(marker: str) -> str:
        return contracts.render_template("{{" + marker + "}}")

    assert render("inputs.chip:0:table_osm_roads") == reference_text(
        input_reference_inner(0, None, "table_osm_roads")) == "[!! input_0:table_osm_roads !!]"
    assert render("inputs.chip:1:table_osm_roads.lanes") == "[!! input_1:table_osm_roads.lanes !!]"
    assert render("inputs.chip:0.rain.mm") == "[!! input_0.rain.mm !!]"
    assert render("inputs.stacked_column:sunlight") == "[!! inputs.sunlight !!]"
    assert render("selections.reference:picked") == "[!! selection picked !!]"
    assert render("selections.id_cap") == f"{SELECTION_ID_CAP:,}" == "10,000"
    for marker, kind in (
        ("inputs.chip:0:roads.height", {"kind": "input", "slot": 0, "layer": "roads", "column": "height"}),
        ("inputs.stacked_column:sunlight", {"kind": "stacked", "column": "sunlight"}),
        ("selections.reference:picked", {"kind": "selection", "name": "picked"}),
    ):
        assert parse_reference(render(marker)[4:-4]) == kind, marker
    for bad in ("inputs.chip:0:", "inputs.chip:roads", "selections.reference:2x", "selections.reference:a b"):
        with pytest.raises(contracts.PromptTemplateError):
            render(bad)


def test_every_function_node_code_calls_is_on_the_functions_page():
    from utk_curio.backend.app.agents.domain import node_functions
    from utk_curio.sandbox.isolation.zygote import build_namespace_template
    from utk_curio.sandbox.util.catalog_helpers import _renamed, install_catalog_helpers

    retired = _renamed("old", "new").__qualname__
    namespace: dict = {}
    install_catalog_helpers(namespace, data_path=str, formats=None, collections=None, media_dir=None, models=None)
    python = {name for name, value in namespace.items()
              if name.startswith("curio_") and getattr(value, "__qualname__", "") != retired}
    python |= {name for name in build_namespace_template() if name.startswith("curio_")} | {"curio_secret"}
    javascript = set(re.findall(r"^const (curio_[A-Za-z0-9_]*) =", WRAPPER.read_text(encoding="utf-8"), re.M))
    given = {function.name: function.engines for function in node_functions.read()}
    assert not sorted(python - set(given)), f"node code calls {sorted(python - set(given))}, which no page gives"
    assert not sorted(javascript - set(given)), sorted(javascript - set(given))
    assert {name for name, engines in given.items() if "javascript" in engines} == javascript
    assert set(given) == python | javascript


def test_the_catalogs_page_says_what_each_catalog_holds_and_which_tools_reach_it():
    from utk_curio.backend.app.agents.application.tools import REGISTRY

    page = _rendered()["knowledge/catalogs.md"]
    for catalog in ("Node Catalog", "Model Catalog", "Data Catalog", "Discovery Catalog", "Agent Catalog",
                    "Scenario Catalog"):
        assert f"- {catalog}: " in page, catalog
    for tool in ("packages.catalog", "packages.resolve", "package.install", "models.search", "catalog.search",
                 "dataset.install", "discovery.sources", "discovery.search", "discovery.acquire", "dataflow.read",
                 "scenarios.search"):
        assert tool in REGISTRY and tool in page, tool
    assert 'curio_secret("<name>")' in page
    # A scenario of another project comes in by the user's drag, from the
    # Scenario Catalog drawer's Browse all tab.
    scenarios = next(line for line in page.splitlines() if line.startswith("- Scenario Catalog: "))
    assert "scenarios.search" in scenarios and "Scenario, Browse all" in scenarios


def test_dataflow_read_lists_each_nodes_selection_tags(tmp_curio):
    """A node's selection tags, as its code reads them, each with its view,
    the column that identifies the view's rows and how many ids it holds,
    never the ids; a malformed tag is left out, as the runtime leaves it."""
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.projects import storage as projects_storage

    spec = {"dataflow": {"nodes": [
        {"id": "chart", "type": "curio.builtin/vis-vega", "content": "{}"},
        {"id": "map", "type": "curio.builtin/autk-grammar", "content": "{}"},
        {"id": "pick", "type": "curio.builtin/computation-analysis",
         "content": "return input_0[input_0['osm_id'].isin([!! selection picked !!])]",
         "metadata": {"selections": [
             {"name": "picked", "node": "chart", "column": "osm_id", "ids": [987654321, 987654322]},
             {"name": "towers", "node": "map", "column": "building_id", "count": 12000},
             {"name": "no view", "node": "map", "column": "building_id", "ids": []},
         ]}},
    ], "edges": []}}
    projects_storage.write_spec("42", "p-selections", spec)
    status, text = tools.execute_read_tool(
        "dataflow.read", user_key="42", project_id="p-selections", target=None, params={},
    )
    assert status == "ok"
    rows = {row["id"]: row for row in json.loads(text)["nodes"]}
    assert rows["pick"]["selections"] == [
        {"name": "picked", "view": "chart", "column": "osm_id", "selected": 2},
        {"name": "towers", "view": "map", "column": "building_id", "selected": 12000},
    ]
    assert "selections" not in rows["chart"] and "selections" not in rows["map"]
    assert "987654321" not in text
    assert "selection tags" in tools.REGISTRY["dataflow.read"].description
