"""A project's graph preview gives each node the category its template declares.

The Projects page draws a dataflow's graph as boxes, each with a bar in the
color of its node's category: the ``category`` the node's template declares
in its package's manifest (``data``, ``computation``, ``vis_grammar``,
``vis_simple`` or ``flow``). The listing reads it through the lookup that
reads the dataflow's tags (``categories.ManifestLookup``), one per request, so
a package in the account's store counts as one in the catalog does. A node
type no manifest holds gets none, and its box is grey.

Each test imports what it uses from the app inside its body, so a module that
cannot import fails these tests and nothing else.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
BUILTIN_MANIFEST = REPO / "packages" / "curio.builtin@1" / "manifest.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _package(root: Path, package_id: str, major: int = 1, *, templates: dict):
    """A package manifest under *root*, as the lookup reads it: one template
    per ``{template id: category}`` of *templates*, None naming no category."""
    raw = {
        "id": package_id,
        "compatibility": {"major": major},
        "templates": [
            {"id": template_id, **({"category": category} if category is not None else {})}
            for template_id, category in templates.items()
        ],
    }
    folder = root / f"{package_id}@{major}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")


def _lookup(*roots: Path):
    """A lookup over these package folders, the first one the account's."""
    from utk_curio.backend.app.projects.categories import DatasetKinds, ManifestLookup, TemplateGrammars

    return ManifestLookup(
        packages=TemplateGrammars(None, roots=list(roots)),
        datasets=DatasetKinds(None, roots=[]),
    )


def _node(node_id: str, node_type, x: int = 0) -> dict:
    return {"id": node_id, "type": node_type, "content": "", "x": x, "y": 0}


def _preview(nodes, lookup, *, packages=None) -> dict:
    """``{node id: category}`` of the preview a listing gives *nodes*."""
    from utk_curio.backend.app.projects.services import _extract_graph_preview

    dataflow = {"nodes": nodes, "edges": []}
    if packages is not None:
        dataflow["packages"] = packages
    preview = _extract_graph_preview({"dataflow": dataflow}, lookup)
    return {node["id"]: node["category"] for node in preview["nodes"]}


def _archive(package_id: str, templates: dict) -> bytes:
    """A ``.curio.zip`` of a package of Python templates, one per
    ``{template id: category}`` of *templates*."""
    manifest = {
        "id": package_id,
        "version": "1.0.0",
        "name": package_id,
        "publisher": "Test",
        "description": "Test package",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [],
        "dependencies": {"packages": {}, "python": {}, "js": {}},
        "createdAt": "2026-06-01T12:00:00Z",
        "templates": [
            {
                "id": template_id,
                "label": template_id.title(),
                "category": category,
                "engine": "python",
                "editor": "code",
                "hasCode": True,
                "hasWidgets": False,
                "hasGrammar": False,
                "inputPorts": [],
                "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                "templateDir": f"starters/{template_id}",
                "defaultTemplate": f"starters/{template_id}/Default.py",
            }
            for template_id, category in templates.items()
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        for template_id in templates:
            archive.writestr(f"starters/{template_id}/Default.py", "def run():\n    return {}\n")
    return buffer.getvalue()


#: A gauge node and a chart node of ``acme.hydro``, a built-in loader, a node
#: of a package no manifest holds, and a legacy type with no package in it.
NODES = [
    _node("load", "curio.builtin/data-loading@1"),
    _node("gauge", "acme.hydro/gauge@1", 300),
    _node("chart", "acme.hydro/chart", 600),
    _node("gone", "acme.gone/gauge@1", 900),
    _node("legacy", "VIS_VEGA", 1200),
]
#: What each of :data:`NODES` is drawn with.
CATEGORIES = {"load": "data", "gauge": "vis_simple", "chart": "flow", "gone": None, "legacy": None}


def _install(user_key: str) -> None:
    from utk_curio.backend.app.packages import service as packages_service

    packages_service.install_package_from_archive(
        user_key, _archive("acme.hydro", {"gauge": "vis_simple", "chart": "flow"}),
    )


def _listed_preview(user, nodes) -> dict:
    """Save *nodes* as one of *user*'s projects and give ``{node id:
    category}`` of the preview the Projects page lists it with."""
    from utk_curio.backend.app.projects import services
    from utk_curio.backend.app.projects.schemas import ProjectCreate

    spec = {"dataflow": {"name": "Gauges", "nodes": nodes, "edges": [{"id": "e1", "source": "load", "target": "gauge"}]}}
    detail = services.save_project(user, ProjectCreate(name="Gauges", spec=spec, outputs=[]))
    summary = next(s for s in services.list_projects(user) if s.id == detail.id)
    assert [n["id"] for n in summary.graph_preview["nodes"]] == [n["id"] for n in nodes]
    assert summary.graph_preview["edges"] == [{"source": "load", "target": "gauge"}]
    return {n["id"]: n["category"] for n in summary.graph_preview["nodes"]}


@pytest.fixture()
def shared_guest(db):
    """The shared guest, whose dataflows and packages live under the guest key."""
    from utk_curio.backend.app.users.models import User
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    guest = User(username=CURIO_SHARED_GUEST_USERNAME, name="Guest", is_guest=True)
    db.session.add(guest)
    db.session.commit()
    return guest


# ---------------------------------------------------------------------------
# Through saving and listing
# ---------------------------------------------------------------------------

def test_a_package_node_in_the_accounts_store_gets_its_category_in_the_listing(app, db, user_and_token):
    """A package the account imported gives its nodes the categories its
    templates declare, with or without a major; a built-in node gets its
    own, and a type no manifest holds gets none."""
    user, _ = user_and_token
    _install(str(user.id))

    assert _listed_preview(user, NODES) == CATEGORIES


def test_the_shared_guest_reads_the_guest_store(app, db, shared_guest):
    from utk_curio.backend.app.common.user_storage import GUEST_KEY

    _install(GUEST_KEY)

    assert _listed_preview(shared_guest, NODES) == CATEGORIES


def test_another_accounts_package_gives_no_category(app, db, user_and_token):
    """The account's store is the account's: a lookup with no account, or
    with another one, reads the catalog alone, which does not hold it."""
    from utk_curio.backend.app.projects.categories import ManifestLookup

    user, _ = user_and_token
    _install(str(user.id))
    nodes = [_node("gauge", "acme.hydro/gauge@1")]

    assert _preview(nodes, ManifestLookup(str(user.id))) == {"gauge": "vis_simple"}
    assert _preview(nodes, ManifestLookup(None)) == {"gauge": None}
    assert _preview(nodes, ManifestLookup(str(user.id + 1000))) == {"gauge": None}


# ---------------------------------------------------------------------------
# Reading the manifests
# ---------------------------------------------------------------------------

def test_every_builtin_template_gets_the_category_its_manifest_declares():
    """With and without a major: the box of every built-in kind is the
    color of the category ``curio.builtin@1`` declares for it."""
    from utk_curio.backend.app.projects.categories import ManifestLookup

    manifest = json.loads(BUILTIN_MANIFEST.read_text(encoding="utf-8"))
    declared = {template["id"]: template["category"] for template in manifest["templates"]}
    assert declared, "curio.builtin@1 declares no template"
    nodes = []
    for template_id in declared:
        nodes.append(_node(f"{template_id}@1", f"{manifest['id']}/{template_id}@1"))
        nodes.append(_node(template_id, f"{manifest['id']}/{template_id}"))

    out = _preview(nodes, ManifestLookup.shipped())

    assert out == {
        **{f"{template_id}@1": category for template_id, category in declared.items()},
        **{template_id: category for template_id, category in declared.items()},
    }


def test_a_type_no_manifest_holds_gets_none(tmp_path):
    """A package no folder holds, a template its package does not hold, a
    legacy type with no package in it, a type that leaves its package's
    folder, and a type that is not a string."""
    store = tmp_path / "packages"
    _package(store, "acme.hydro", templates={"gauge": "data"})
    lookup = _lookup(store)
    types = [
        "acme.gone/gauge@1", "acme.hydro/missing@1", "VIS_VEGA", "acme.hydro", "acme.hydro@1",
        "../acme.hydro/gauge@1", "acme.hydro/../gauge@1", "acme.hydro/gauge@x", "", None, 3, ["acme.hydro/gauge@1"],
        {"type": "acme.hydro/gauge@1"},
    ]
    nodes = [_node(f"n{i}", node_type) for i, node_type in enumerate(types)]

    assert _preview(nodes, lookup) == {f"n{i}": None for i in range(len(types))}
    assert _preview([_node("ok", "acme.hydro/gauge@1")], lookup) == {"ok": "data"}


def test_a_template_that_names_no_category_gets_none(tmp_path):
    store = tmp_path / "packages"
    _package(store, "acme.hydro", templates={"gauge": None, "chart": 7, "table": "vis_simple"})
    nodes = [_node("gauge", "acme.hydro/gauge@1"), _node("chart", "acme.hydro/chart@1"),
             _node("table", "acme.hydro/table@1")]

    assert _preview(nodes, _lookup(store)) == {"gauge": None, "chart": None, "table": "vis_simple"}


def test_the_lockfile_picks_the_major_of_a_type_that_names_none(tmp_path):
    store = tmp_path / "packages"
    _package(store, "acme.hydro", 1, templates={"gauge": "data"})
    _package(store, "acme.hydro", 2, templates={"gauge": "computation"})
    lookup = _lookup(store)

    # The highest major, with no lockfile.
    assert _preview([_node("n", "acme.hydro/gauge")], lookup) == {"n": "computation"}
    # The lockfile's.
    assert _preview([_node("n", "acme.hydro/gauge")], lookup, packages=["acme.hydro@1"]) == {"n": "data"}
    # A node type's own major, whatever the lockfile says.
    assert _preview([_node("n", "acme.hydro/gauge@2")], lookup, packages=["acme.hydro@1"]) == {"n": "computation"}


def test_the_accounts_copy_names_the_category_before_the_catalogs(tmp_path):
    """The account's copy is the one its canvas draws the node from; the
    catalog's counts where the account's names none."""
    account, catalog = tmp_path / "account", tmp_path / "catalog"
    _package(account, "acme.hydro", templates={"gauge": "data", "chart": None})
    _package(catalog, "acme.hydro", templates={"gauge": "computation", "chart": "vis_grammar", "table": "flow"})
    nodes = [_node("gauge", "acme.hydro/gauge@1"), _node("chart", "acme.hydro/chart@1"),
             _node("table", "acme.hydro/table@1")]

    assert _preview(nodes, _lookup(account, catalog)) == {"gauge": "data", "chart": "vis_grammar", "table": "flow"}


def test_each_node_keeps_its_box(tmp_path):
    """The category joins what the preview always gave each node."""
    from utk_curio.backend.app.projects.services import _extract_graph_preview

    store = tmp_path / "packages"
    _package(store, "acme.hydro", templates={"gauge": "data"})
    spec = {"dataflow": {"nodes": [
        {"id": "a", "type": "acme.hydro/gauge@1", "x": 10, "y": 20, "width": 300, "height": 200},
        {"id": "b", "type": "acme.gone/gauge@1"},
    ], "edges": [{"id": "e", "source": "a", "target": "b", "sourceHandle": "out"}]}}

    assert _extract_graph_preview(spec, _lookup(store)) == {
        "nodes": [
            {"id": "a", "type": "acme.hydro/gauge@1", "category": "data", "x": 10, "y": 20, "w": 300, "h": 200},
            {"id": "b", "type": "acme.gone/gauge@1", "category": None, "x": 0, "y": 0, "w": None, "h": None},
        ],
        "edges": [{"source": "a", "target": "b"}],
    }
