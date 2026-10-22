"""Built-in nodes are known by what their templates declare, not by name.

A dashboard walks through the nodes that show what reaches them, a run on the
server hands on what a download, a Parameter node or a note receives, and the
Data Catalog counts a dataset's consumers from the nodes after the one that
loads it. Each reads the ``behavior`` a node's template declares (or, for the
node that loads a dataset, its ``loadsDataset`` flag, which the agents read
too) through the package manifests, so a package template named like a
built-in one is not taken for it, and one that declares a built-in's behavior
is treated as that built-in is.

The node types here come from ``acme.tools@1``, a package in a catalog of its
own (``CURIO_PACKAGES_ROOT``) that does not hold ``curio.builtin``: the
built-in nodes beside them are still known. A node type is read only through
the package id grammar, so one that leaves the catalog reads nothing. The
modules under test are imported inside each test, so a checkout without a name
fails each test on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DATASET = "acme.parcels"
LOADS_IT = f'import pandas as pd\nreturn pd.read_csv(curio_data_path("{DATASET}"))\n'

RENDER_SPEC = json.dumps({"map": {"layerRefs": []}})
DATA_SPEC = json.dumps({"data": [{"type": "osm"}]})

#: Templates of ``acme.tools@1`` named like built-in ones: each is a plain code node.
NAMED_LIKE_A_BUILTIN = (
    "data-loading", "data-export", "vis-vega", "vis-simple", "data-pool",
    "autk-grammar", "note", "parameter",
)


def _port() -> dict:
    return {"cardinality": "1", "types": ["DATAFRAME", "GEODATAFRAME"]}


def _template(template_id: str, behavior: str, *, category: str = "computation", inputs: int = 1,
              editor: str = "code", has_code: bool = True, grammar: str | None = None,
              loads_dataset: bool = False) -> dict:
    return {
        "id": template_id,
        "label": template_id.replace("-", " ").title(),
        "category": category,
        "engine": "python",
        "editor": editor,
        "hasCode": has_code,
        "behavior": behavior,
        "inputPorts": [_port() for _ in range(inputs)],
        "outputPorts": [_port()],
        **({"grammarId": grammar} if grammar else {}),
        **({"loadsDataset": True} if loads_dataset else {}),
    }


def _manifest(package_id: str, templates: list[dict]) -> dict:
    return {
        "id": package_id,
        "name": package_id,
        "version": "1.0.0",
        "compatibility": {"major": 1},
        "templates": templates,
    }


ACME = _manifest("acme.tools", [
    *(_template(template_id, "code") for template_id in NAMED_LIKE_A_BUILTIN),
    # Templates that declare a built-in's behavior, under names of their own.
    _template("pool", "data-pool", category="data", editor="none", has_code=False),
    _template("download", "data-export", category="data", editor="none", has_code=False),
    _template("sticky", "note", category="flow", inputs=0, editor="none", has_code=False),
    _template("bars", "vega", category="vis_grammar", editor="grammar", has_code=False, grammar="vega-lite"),
    # Templates that declare loadsDataset bring data into the dataflow, as Data Loading does.
    _template("fetch-parcels", "code", category="data", inputs=0, loads_dataset=True),
    _template("geocode", "code", loads_dataset=True),
    # A data template with no input that declares no loader is a node that reads what it names.
    _template("fetch-roads", "code", category="data", inputs=0),
])

#: A manifest outside the catalog, which a node type that climbs out of it would reach.
OUTSIDE = _manifest("outside", [
    _template("chart", "vega", category="data", inputs=0, editor="grammar", has_code=False,
              grammar="vega-lite"),
])


@pytest.fixture
def catalog(tmp_path, monkeypatch) -> Path:
    """A package catalog holding ``acme.tools@1`` and no ``curio.builtin``,
    beside a folder named like a package that is not in it."""
    root = tmp_path / "catalog"
    (root / "acme.tools@1").mkdir(parents=True)
    (root / "acme.tools@1" / "manifest.json").write_text(json.dumps(ACME), encoding="utf-8")
    (tmp_path / "outside@1").mkdir()
    (tmp_path / "outside@1" / "manifest.json").write_text(json.dumps(OUTSIDE), encoding="utf-8")
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
    return root


def node(node_id: str, node_type: str, content: str = "", **fields) -> dict:
    return {"id": node_id, "type": node_type, "content": content, **fields}


def edge(source: str, target: str) -> dict:
    return {"id": f"{source}-{target}", "source": source, "target": target}


def spec_of(nodes, edges=()) -> dict:
    return {"dataflow": {"nodes": list(nodes), "edges": list(edges)}}


def _between_a_producer_and_a_chart(node_type: str, content: str = "") -> dict:
    """``py`` -> *node_type* -> a pinned Vega-Lite chart."""
    return spec_of(
        [
            node("py", "curio.builtin/computation-analysis@1"),
            node("middle", node_type, content),
            node("chart", "curio.builtin/vis-vega@1", "{}", dashboardPinned=True),
        ],
        [edge("py", "middle"), edge("middle", "chart")],
    )


def _consumers(spec: dict) -> list[str]:
    from utk_curio.backend.app.datasets.application.export import _dataset_consumer_nodes_in_spec

    return [c["nodeId"] for c in _dataset_consumer_nodes_in_spec(spec, DATASET, "flow-1") or []]


def _loading(loader_type: str) -> dict:
    """A node of *loader_type* that names the dataset in its code, and a node after it."""
    return spec_of(
        [node("loader", loader_type, LOADS_IT), node("after", "curio.builtin/computation-analysis@1")],
        [edge("loader", "after")],
    )


# ---------------------------------------------------------------------------
# The dashboard payload
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_id, content", [
    ("vis-vega", "{}"),
    ("vis-simple", ""),
    ("data-pool", ""),
    ("autk-grammar", RENDER_SPEC),
])
def test_a_package_template_named_like_a_view_makes_the_rows_a_tile_reads(catalog, template_id, content):
    from utk_curio.backend.app.projects.dashboard_payload import dashboard_source_node_ids

    spec = _between_a_producer_and_a_chart(f"acme.tools/{template_id}@1", content)
    assert dashboard_source_node_ids(spec) == {"middle"}


@pytest.mark.parametrize("template_id", ["pool", "bars"])
def test_a_package_template_that_declares_a_views_behavior_is_walked_through(catalog, template_id):
    from utk_curio.backend.app.projects.dashboard_payload import dashboard_source_node_ids

    spec = _between_a_producer_and_a_chart(f"acme.tools/{template_id}@1", "{}")
    assert dashboard_source_node_ids(spec) == {"py"}


def test_only_the_autark_node_is_refused_for_loading_its_own_data(catalog):
    from utk_curio.backend.app.projects.dashboard_payload import (
        DashboardCannotBeStandaloneError,
        build_dashboard_payload,
    )

    def never(filename):
        raise AssertionError(f"nothing is read: {filename}")

    named = spec_of([node("map", "acme.tools/autk-grammar@1", DATA_SPEC, dashboardPinned=True)])
    build_dashboard_payload(spec=named, output_refs=[], fetch_envelope=never)

    autark = spec_of([node("map", "curio.builtin/autk-grammar@1", DATA_SPEC, dashboardPinned=True)])
    with pytest.raises(DashboardCannotBeStandaloneError):
        build_dashboard_payload(spec=autark, output_refs=[], fetch_envelope=never)


def test_the_builtin_views_are_walked_through_where_the_catalog_lacks_them(catalog):
    from utk_curio.backend.app.projects.dashboard_payload import dashboard_source_node_ids

    for node_type, content in (
        ("curio.builtin/vis-vega@1", "{}"),
        ("curio.builtin/vis-simple", ""),
        ("curio.builtin/data-pool@1", ""),
        ("curio.builtin/autk-grammar", RENDER_SPEC),
    ):
        assert dashboard_source_node_ids(_between_a_producer_and_a_chart(node_type, content)) == {"py"}, node_type


# ---------------------------------------------------------------------------
# A run on the server
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_id, content", [
    ("data-export", ""),
    ("note", "# A note"),
    ("parameter", ""),
    ("vis-vega", "{}"),
    ("vis-simple", ""),
    ("data-pool", ""),
    ("autk-grammar", RENDER_SPEC),
])
def test_a_run_does_not_forward_a_package_template_named_like_a_builtin(catalog, template_id, content):
    from utk_curio.backend.app.execution.run_plan import node_role

    named = node("n", f"acme.tools/{template_id}@1", content)
    assert node_role(named) == "browser"
    roster = {f"acme.tools/{template_id}": {"executable": True, "engine": "python", "contentKind": "code"}}
    assert node_role(named, roster) == "run"


@pytest.mark.parametrize("template_id", ["download", "sticky", "pool", "bars"])
def test_a_run_forwards_a_package_template_that_declares_a_forwarded_behavior(catalog, template_id):
    from utk_curio.backend.app.execution.run_plan import node_role

    assert node_role(node("n", f"acme.tools/{template_id}@1", "{}")) == "forward"


@pytest.mark.parametrize("node_type, content, role", [
    ("curio.builtin/data-export@1", "", "forward"),
    ("curio.builtin/note@1", "# A note", "forward"),
    ("curio.builtin/parameter", "", "forward"),
    ("curio.builtin/vis-vega@1", "{}", "forward"),
    ("curio.builtin/vis-simple", "", "forward"),
    ("curio.builtin/data-pool@1", "", "forward"),
    ("curio.builtin/autk-grammar", RENDER_SPEC, "forward"),
    ("curio.builtin/data-loading@1", "", "run"),
])
def test_builtin_nodes_keep_their_roles_where_the_catalog_lacks_them(catalog, node_type, content, role):
    from utk_curio.backend.app.execution.run_plan import node_role

    assert node_role(node("n", node_type, content)) == role


# ---------------------------------------------------------------------------
# A dataset's consumers in the Data Catalog
# ---------------------------------------------------------------------------

def test_a_package_template_named_data_loading_consumes_the_dataset_it_names(catalog):
    assert _consumers(_loading("acme.tools/data-loading@1")) == ["loader"]


def test_a_package_template_declared_as_a_loader_carries_the_dataset_to_the_node_after_it(catalog):
    assert _consumers(_loading("acme.tools/fetch-parcels@1")) == ["after"]


def test_a_loader_that_takes_an_input_carries_the_dataset_to_the_node_after_it(catalog):
    assert _consumers(_loading("acme.tools/geocode@1")) == ["after"]


def test_a_data_template_with_no_input_that_declares_no_loader_consumes_the_dataset_it_names(catalog):
    assert _consumers(_loading("acme.tools/fetch-roads@1")) == ["loader"]


@pytest.mark.parametrize("loader_type", [
    "curio.builtin/data-loading@1", "curio.builtin/data-loading", "DATA_LOADING",
])
def test_the_builtin_loader_carries_the_dataset_where_the_catalog_lacks_it(catalog, loader_type):
    assert _consumers(_loading(loader_type)) == ["after"]


def test_a_template_loads_data_when_either_copy_of_its_package_declares_it(catalog, tmp_path):
    """An account's copy of a package can be older than the catalog's, so
    either copy declaring ``loadsDataset`` is enough, as for the agents
    (``packages.template_flags``)."""
    from utk_curio.backend.app.datasets.application.export import loads_data
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    store = tmp_path / "store"
    (store / "acme.tools@1").mkdir(parents=True)
    accounts_copy = _manifest("acme.tools", [
        _template("fetch-parcels", "code", category="data", inputs=0),
        _template("fetch-roads", "code", category="data", inputs=0, loads_dataset=True),
        _template("data-loading", "code"),
    ])
    (store / "acme.tools@1" / "manifest.json").write_text(json.dumps(accounts_copy), encoding="utf-8")
    packages = TemplateGrammars(None, roots=[store, catalog])

    # The catalog's copy declares it and the account's does not, then the other way round.
    assert loads_data("acme.tools/fetch-parcels@1", packages)
    assert loads_data("acme.tools/fetch-roads@1", packages)
    # Neither copy declares it.
    assert not loads_data("acme.tools/data-loading@1", packages)


#: The committed package catalog.
SHIPPED_PACKAGES = Path(__file__).resolve().parents[4] / "packages"


def _shipped_node_types() -> list[str]:
    """Every node type the committed packages hold, with its major."""
    node_types = []
    for path in sorted(SHIPPED_PACKAGES.glob("*@*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        major = manifest["compatibility"]["major"]
        node_types += [f"{manifest['id']}/{template['id']}@{major}" for template in manifest.get("templates") or []]
    return node_types


def test_the_committed_packages_hold_a_loader_and_other_nodes():
    # Guards the walk below: an empty or one-sided list would pass vacuously.
    node_types = _shipped_node_types()
    assert "curio.builtin/data-loading@1" in node_types
    assert "curio.builtin/computation-analysis@1" in node_types


@pytest.mark.parametrize("node_type", [*_shipped_node_types(), "DATA_LOADING"])
def test_the_data_catalog_takes_a_node_for_a_loader_when_the_agents_do(node_type):
    """The Data Catalog's lineage and the agents read the same declaration,
    so a shipped node is a loader to both or to neither: Data Loading is one,
    and the package loaders that declare nothing (curio.weather's, UHVI's)
    are not."""
    from utk_curio.backend.app.agents.application import source_grounding
    from utk_curio.backend.app.datasets.application.export import loads_data

    assert loads_data(node_type) == source_grounding.loads_dataset(node_type)


# ---------------------------------------------------------------------------
# A node type is read through the package id grammar only
# ---------------------------------------------------------------------------

#: Node types that are not ``<package id>/<template id>[@<major>]``.
MALFORMED = [
    "../outside/chart@1",
    "../outside/chart",
    "ACME.tools/pool@1",
    "acme.tools/pool@01",
    "acme.tools/pool@1@2",
    "acme.tools/pool/chart@1",
    "acme/pool@1",
    " acme.tools/pool@1",
]


@pytest.mark.parametrize("node_type", MALFORMED)
def test_a_malformed_node_type_reads_nothing(catalog, node_type):
    from utk_curio.backend.app.projects.template_grammars import (
        NOTHING,
        TemplateGrammars,
        draws_with_vega_lite,
    )

    assert TemplateGrammars(None).node(node_type) == NOTHING
    assert not draws_with_vega_lite(node_type)


def test_a_node_type_that_climbs_out_of_the_catalog_is_nothing_the_manifest_there_declares(catalog):
    from utk_curio.backend.app.execution.run_plan import node_role
    from utk_curio.backend.app.projects.dashboard_payload import dashboard_source_node_ids
    from utk_curio.backend.app.projects.services import _is_sink_node_type

    escaping = "../outside/chart@1"
    assert dashboard_source_node_ids(_between_a_producer_and_a_chart(escaping, "{}")) == {"middle"}
    assert node_role(node("n", escaping, "{}")) == "browser"
    assert not _is_sink_node_type(escaping)
    assert _consumers(_loading(escaping)) == ["loader"]
