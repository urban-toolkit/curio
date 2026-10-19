"""What packages, models and datasets declare reaches a dataflow's tags and data types.

A package (at its top level, or in one of its templates), a model package and
a dataset name the tags and data types a dataflow that uses them is filed
under on the Projects rail, in ``dataflowCategories``. ``categories.derive``
reads them through one lookup per request (``categories.ManifestLookup``): a
node's package and template, the model package a ``curio_load_model`` call
names, and a dataset the dataflow names. The lookup reads the account's copy
of each manifest and the catalog's, and unions what the two declare, since an
account's copy dates from when it was added. A model's type gives what the
rules table says for it. Names the table does not list follow its names,
alphabetically; ``categories.py`` and the table name no package, model or
dataset.

Each test imports what it uses from the app inside its body, so a module that
cannot import fails these tests and nothing else.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

#: A tag and a data type no rule of ``category_rules.json`` gives.
HYDROLOGY = {"tags": ["Hydrology"], "dataTypes": ["Point clouds"]}
#: A node type no manifest in these tests' folders holds: a Python node.
PYTHON_NODE = "curio.builtin/computation-analysis@1"
NOTHING = {"tags": [], "data_type": []}


# ---------------------------------------------------------------------------
# Helpers: manifests in folders the lookup reads
# ---------------------------------------------------------------------------

def _package(root: Path, package_id: str, major: int = 1, *, declares=None, templates=("gauge",), model_type=None):
    """Write a package manifest as the lookup reads it under *root*."""
    raw = {
        "id": package_id,
        "compatibility": {"major": major},
        "templates": [{"id": t} if isinstance(t, str) else t for t in templates],
    }
    if declares is not None:
        raw["dataflowCategories"] = declares
    if model_type is not None:
        raw["kind"] = "model"
        raw["model"] = {"type": model_type}
    folder = root / f"{package_id}@{major}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")


def _dataset(root: Path, dataset_id: str, *, declares=None, fmt: str = "csv"):
    """Write a dataset manifest as the lookup reads it under *root*."""
    raw = {
        "id": dataset_id, "name": dataset_id, "version": "1.0.0", "format": fmt,
        "dataFile": f"data/rows.{fmt}", "tags": [], "compatibility": {"major": 1},
    }
    if declares is not None:
        raw["dataflowCategories"] = declares
    folder = root / f"{dataset_id}@1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")


def _lookup(packages=(), datasets=()):
    """A lookup over these package folders and these dataset folders, the
    account's first."""
    from utk_curio.backend.app.projects.categories import DatasetKinds, ManifestLookup, TemplateGrammars

    return ManifestLookup(
        packages=TemplateGrammars(None, roots=list(packages)),
        datasets=DatasetKinds(None, roots=list(datasets)),
    )


def _node(node_type, content: str = "", node_id: str = "n") -> dict:
    return {"id": node_id, "type": node_type, "content": content}


def _derive(nodes, lookup, *, packages=None, datasets=None) -> dict:
    from utk_curio.backend.app.projects.categories import derive

    dataflow = {"nodes": nodes, "edges": []}
    if packages is not None:
        dataflow["packages"] = packages
    if datasets is not None:
        dataflow["datasets"] = datasets
    return derive({"dataflow": dataflow}, lookup=lookup)


# ---------------------------------------------------------------------------
# Helpers: a package installed or published as Curio does it
# ---------------------------------------------------------------------------

def _archive(package_id: str, declares: dict, template_id: str = "gauge") -> bytes:
    """A ``.curio.zip`` of a package of one Python template that declares *declares*."""
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
        "dataflowCategories": declares,
        "templates": [{
            "id": template_id,
            "label": "Gauge",
            "category": "computation",
            "engine": "python",
            "editor": "code",
            "hasCode": True,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "templateDir": f"starters/{template_id}",
            "defaultTemplate": f"starters/{template_id}/Default.py",
        }],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr(f"starters/{template_id}/Default.py", "def run():\n    return {}\n")
    return buffer.getvalue()


def _store_dataset(user_key: str, dataset_id: str, declares: dict) -> None:
    """A dataset in *user_key*'s store that declares *declares*, its manifest
    written as Curio writes one."""
    from utk_curio.backend.app.datasets.domain.manifest import DatasetManifest, write_manifest
    from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir

    folder = user_datasets_dir(user_key) / f"{dataset_id}@1"
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "gauges.csv").write_text("gauge,mm\nA,3\n", encoding="utf-8")
    write_manifest(DatasetManifest(
        id=dataset_id, name="Rain gauges", version="1.0.0", format="csv", description="",
        publisher="Data Catalog", license="", tags=["rain"], data_file="data/gauges.csv", major=1,
        source_label="Imported", dataflow_categories=declares,
    ), folder)


#: A gauge node of ``acme.hydro`` that reads the account's rain gauges.
GAUGES = [_node("acme.hydro/gauge@1", 'rows = curio_load_data("imported.rain-gauges")\nreturn rows', "a")]
#: What the package and the dataset declare, with Tables for the dataset's csv.
DECLARED = {"tags": ["Hydrology", "Rain gauges"], "data_type": ["Tables", "Point clouds"]}


def _save(user, nodes):
    from utk_curio.backend.app.projects import services
    from utk_curio.backend.app.projects.schemas import ProjectCreate

    spec = {"dataflow": {"name": "Mine", "nodes": nodes, "edges": []}}
    return services.save_project(user, ProjectCreate(name="Mine", spec=spec, outputs=[]))


def _listed(user, project_id):
    from utk_curio.backend.app.projects import services

    return next(s for s in services.list_projects(user) if s.id == project_id)


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

def test_what_an_accounts_package_and_dataset_declare_reaches_its_dataflows(app, db, user_and_token):
    """A package the account imported and a dataset in its store name a tag
    and a data type no rule knows; a dataflow with the package's node that
    reads the dataset shows them when it is saved and when it is listed."""
    from utk_curio.backend.app.packages import service as packages_service
    from utk_curio.backend.app.projects.categories import ManifestLookup, derive

    user, _ = user_and_token
    key = str(user.id)
    packages_service.install_package_from_archive(key, _archive("acme.hydro", HYDROLOGY))
    _store_dataset(key, "imported.rain-gauges", {"tags": ["Rain gauges"]})

    detail = _save(user, GAUGES)

    assert detail.categories["auto"] == DECLARED
    assert _listed(user, detail.id).categories["auto"] == DECLARED
    # The account's store is the account's: a lookup with no account reads
    # the catalog alone, which holds neither.
    spec = {"dataflow": {"nodes": GAUGES, "edges": []}}
    assert derive(spec, lookup=ManifestLookup(key)) == DECLARED
    assert derive(spec, lookup=ManifestLookup(None)) == NOTHING


def test_the_shared_guest_reads_the_guest_store(app, db, shared_guest):
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.packages import service as packages_service

    packages_service.install_package_from_archive(GUEST_KEY, _archive("acme.hydro", HYDROLOGY))
    _store_dataset(GUEST_KEY, "imported.rain-gauges", {"tags": ["Rain gauges"]})

    detail = _save(shared_guest, GAUGES)

    assert detail.categories["auto"] == DECLARED
    assert _listed(shared_guest, detail.id).categories["auto"] == DECLARED


def test_a_package_published_to_the_catalog_reaches_an_accounts_dataflows(
    app, db, user_and_token, tmp_path, monkeypatch,
):
    """The catalog's copy counts with none in the account's store."""
    from utk_curio.backend.app.packages.repositories.catalog_dir import publish_package_archive_to_catalog_dir
    from utk_curio.backend.app.packages.service import catalog_root, user_packages_dir

    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(tmp_path / "catalog"))
    publish_package_archive_to_catalog_dir(_archive("acme.hydro", HYDROLOGY), catalog_root())
    user, _ = user_and_token

    detail = _save(user, [_node("acme.hydro/gauge@1", node_id="a")])

    assert not (user_packages_dir(str(user.id)) / "acme.hydro@1").exists()
    expected = {"tags": ["Hydrology"], "data_type": ["Point clouds"]}
    assert detail.categories["auto"] == expected
    assert _listed(user, detail.id).categories["auto"] == expected


# ---------------------------------------------------------------------------
# What a package, a template and a model declare
# ---------------------------------------------------------------------------

def test_a_package_and_each_of_its_templates_declare(tmp_path):
    """A node gets what its package declares and what its own template does,
    not another template's. What the package declares counts for a node whose
    template its manifest no longer holds."""
    store = tmp_path / "packages"
    _package(store, "acme.hydro", declares={"tags": ["Hydrology"]}, templates=[
        {"id": "gauge", "dataflowCategories": {"dataTypes": ["Point clouds"]}},
        {"id": "plot", "dataflowCategories": {"tags": ["Rainfall"]}},
    ])
    _package(store, "acme.maps", templates=[{"id": "relief", "dataflowCategories": {"tags": ["Terrain"]}}])
    lookup = _lookup(packages=[store])

    assert _derive([_node("acme.hydro/gauge@1")], lookup) == {"tags": ["Hydrology"], "data_type": ["Point clouds"]}
    assert _derive([_node("acme.hydro/plot@1")], lookup) == {"tags": ["Hydrology", "Rainfall"], "data_type": []}
    assert _derive([_node("acme.hydro/retired@1")], lookup) == {"tags": ["Hydrology"], "data_type": []}
    assert _derive([_node("acme.maps/relief@1")], lookup) == {"tags": ["Terrain"], "data_type": []}
    assert _derive([_node("acme.maps/retired@1")], lookup) == NOTHING


def test_a_model_loaded_in_code_brings_what_its_package_declares(tmp_path):
    store = tmp_path / "packages"
    _package(store, "model.acme.flood", declares=HYDROLOGY, model_type="image-to-image", templates=["estimate"])
    lookup = _lookup(packages=[store])

    code = 'model = curio_load_model("model.acme.flood")\nreturn model'
    assert _derive([_node(PYTHON_NODE, code)], lookup) == {"tags": ["Hydrology"], "data_type": ["Point clouds"]}
    assert _derive([_node(PYTHON_NODE, "return None")], lookup) == NOTHING


@pytest.mark.parametrize("model_type, expected", [
    ("semantic-segmentation", {"tags": ["Computer vision"], "data_type": ["Imagery"]}),
    ("image-to-image", NOTHING),
    ("node-regression", NOTHING),
])
def test_a_models_type_gives_what_the_table_says_for_it(tmp_path, model_type, expected):
    """Whether a node of the model's package runs it or a Python node loads
    it, as with a model downloaded from the Discovery Catalog into the
    account's store (its package id ``imported.x<hex>``), which declares
    nothing."""
    store = tmp_path / "packages"
    _package(store, "imported.x5e9c", model_type=model_type, templates=["segment"])
    lookup = _lookup(packages=[store])

    assert _derive([_node("imported.x5e9c/segment@1")], lookup) == expected
    loads = 'model = curio_load_model("imported.x5e9c")\nreturn model'
    assert _derive([_node(PYTHON_NODE, loads)], lookup) == expected


def test_a_scout_named_package_model_or_dataset_that_declares_nothing_is_not_scout(tmp_path):
    store, data = tmp_path / "packages", tmp_path / "datasets"
    _package(store, "scout.extras", templates=["tool"])
    _package(store, "model.scout.extra", model_type="image-to-image", templates=["run"])
    _dataset(data, "data.scout.extra")
    code = 'model = curio_load_model("model.scout.extra")\nrows = curio_load_data("data.scout.extra")\n'
    nodes = [_node("scout.extras/tool@1", code), _node("model.scout.extra/run@1", node_id="m")]

    out = _derive(nodes, _lookup(packages=[store], datasets=[data]), datasets=[{"dirName": "data.scout.extra@1"}])

    assert out["tags"] == []


# ---------------------------------------------------------------------------
# Two copies of a manifest
# ---------------------------------------------------------------------------

def test_a_stale_store_copy_gets_what_the_catalogs_copy_declares(tmp_path):
    """The account's copies were added before the package and the dataset
    declared anything, and before the template named its grammar."""
    store, catalog = tmp_path / "store" / "packages", tmp_path / "catalog" / "packages"
    data_store, data_catalog = tmp_path / "store" / "datasets", tmp_path / "catalog" / "datasets"
    _package(store, "acme.hydro", templates=["gauge"])
    _package(catalog, "acme.hydro", declares=HYDROLOGY, templates=[{"id": "gauge", "grammarId": "vega-lite"}])
    _dataset(data_store, "data.acme.gauges")
    _dataset(data_catalog, "data.acme.gauges", declares={"tags": ["Rain gauges"]})
    lookup = _lookup(packages=[store, catalog], datasets=[data_store, data_catalog])

    out = _derive([_node("acme.hydro/gauge@1", 'rows = curio_load_data("data.acme.gauges")\n')], lookup)

    assert out == {"tags": ["Vega-Lite", "Hydrology", "Rain gauges"], "data_type": ["Tables", "Point clouds"]}
    assert lookup.packages("acme.hydro/gauge@1") == "vega-lite"


def test_the_lockfile_picks_the_major_of_a_node_type_or_model_that_names_none(tmp_path):
    store = tmp_path / "packages"
    _package(store, "acme.hydro", 1, declares={"tags": ["Hydrology"]})
    _package(store, "acme.hydro", 2, declares={"tags": ["Rainfall"]})
    _package(store, "model.acme.flood", 1, declares={"tags": ["Flood one"]}, model_type="image-to-image")
    _package(store, "model.acme.flood", 2, declares={"tags": ["Flood two"]}, model_type="image-to-image")
    lookup = _lookup(packages=[store])
    nodes = [_node("acme.hydro/gauge", 'model = curio_load_model("model.acme.flood")\nreturn model')]

    # The highest major, with no lockfile.
    assert _derive(nodes, lookup)["tags"] == ["Flood two", "Rainfall"]
    # The lockfile's.
    lockfile = ["acme.hydro@1", "model.acme.flood@1"]
    assert _derive(nodes, lookup, packages=lockfile)["tags"] == ["Flood one", "Hydrology"]
    # A node type's own major, whatever the lockfile says.
    assert _derive([_node("acme.hydro/gauge@2")], lookup, packages=lockfile)["tags"] == ["Rainfall"]


def test_a_node_type_with_no_package_in_it_matches_nothing(tmp_path):
    """A legacy node type such as ``VIS_VEGA``, a package id alone, or a type
    that leaves its package's folder."""
    from utk_curio.backend.app.projects.categories import derive

    store = tmp_path / "packages"
    _package(store, "acme.hydro", declares=HYDROLOGY)
    lookup = _lookup(packages=[store])
    assert _derive([_node("acme.hydro/gauge")], lookup) == {"tags": ["Hydrology"], "data_type": ["Point clouds"]}

    for node_type in ("VIS_VEGA", "AUTK_GRAMMAR", "acme.hydro", "acme.hydro@1", "../acme.hydro/gauge@1",
                      "acme.hydro/../gauge@1", "acme.hydro/gauge@x"):
        assert _derive([_node(node_type, '{"compute": [{}]}')], lookup) == NOTHING, node_type
    # Against the packages Curio ships, a legacy Vega-Lite or Autark type is
    # not the built-in node.
    legacy = [_node("VIS_VEGA", "{}"), _node("AUTK_GRAMMAR", '{"compute": [{}]}', "m")]
    assert derive({"dataflow": {"nodes": legacy, "edges": []}}) == NOTHING


# ---------------------------------------------------------------------------
# Reading and ordering the names
# ---------------------------------------------------------------------------

def test_a_declared_name_follows_the_tables_names_alphabetically(tmp_path):
    """The table's names come first, in its order, so Computer vision still
    precedes SCOUT; Hydrology and any other declared name follow, sorted
    ignoring case."""
    store = tmp_path / "packages"
    _package(store, "acme.hydro", declares={"tags": ["Rainfall", "hydrology"], "dataTypes": ["Point clouds"]})
    _package(store, "acme.survey", declares={"tags": ["SCOUT"]}, templates=["walk"])
    _package(store, "model.acme.segments", model_type="semantic-segmentation", templates=["segment"])
    nodes = [
        _node("acme.survey/walk@1", "import pandas as pd\n", "a"),
        _node("acme.hydro/gauge@1", node_id="b"),
        _node("model.acme.segments/segment@1", node_id="c"),
    ]

    out = _derive(nodes, _lookup(packages=[store]))

    assert out == {
        "tags": ["Pandas", "Computer vision", "hydrology", "Rainfall", "SCOUT"],
        "data_type": ["Tables", "Imagery", "Point clouds"],
    }


def test_a_declared_name_is_the_tables_name_in_another_case(tmp_path):
    """Names merge ignoring case: the table's spelling wins, and between two
    declarations the first one's."""
    store = tmp_path / "packages"
    _package(store, "acme.tables", declares={"tags": ["pandas", "Hydrology"], "dataTypes": ["TABLES", "rasters"]},
             templates=["clean"])
    _package(store, "acme.hydro", declares={"tags": ["HYDROLOGY"]})
    nodes = [_node("acme.tables/clean@1", "import pandas as pd\n", "a"), _node("acme.hydro/gauge@1", node_id="b")]

    out = _derive(nodes, _lookup(packages=[store]))

    assert out == {"tags": ["Pandas", "Hydrology"], "data_type": ["Tables", "Rasters"]}


def test_a_declaration_is_read_with_its_bad_values_skipped_and_its_lists_capped(tmp_path):
    """An account's manifest no parser checked: a value that is not a string,
    a list that is not a list and an unknown key are skipped; each value is
    trimmed and cut to 40 characters, and a list keeps its first 20 values."""
    store = tmp_path / "packages"
    many = [f"Tag {n:02}" for n in range(30)]
    _package(store, "acme.hydro", declares={
        "tags": ["  Flood   risk ", 3, None, ["Nested"], {"name": "x"}, "x" * 50, *many],
        "dataTypes": "Point clouds",
        "colors": ["Red"],
    })

    out = _derive([_node("acme.hydro/gauge@1")], _lookup(packages=[store]))

    kept = ["Flood risk", "x" * 40, *many[:18]]
    assert out == {"tags": sorted(kept, key=str.casefold), "data_type": []}


# ---------------------------------------------------------------------------
# The code names no artifact
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["categories.py", "category_rules.json"])
def test_the_rules_name_no_package_model_or_dataset(name):
    """``categories.py`` reads every package, model and dataset through its
    manifests, and the table holds only what code and the manifests' core
    fields show: neither names an id Curio ships or a prefix of one
    (``test_category_rules``'s scan)."""
    from utk_curio.backend.app.projects import categories
    from utk_curio.backend.tests.test_projects.test_category_rules import _artifact_names, _shipped_ids

    text = Path(categories.__file__).with_name(name).read_text(encoding="utf-8")
    assert _artifact_names(text, _shipped_ids()) == []
