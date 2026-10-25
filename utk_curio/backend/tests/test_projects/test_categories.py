"""Dataflow categories: what the Projects rail filters by.

``shipped_categories.json`` is the placement the owner approved for the 44
shipped dataflows (2026-09-30), and the scenarios, quad-cities-flood-vulnerability,
chicago-loop-shadow-towers, chicago-rain-wind-routing and netcdf-hourly-rain test dataflows and
example 24 placed by the same rules (#662, 2026-10-05), example 25 (#576),
example 26 (#819), the lower-manhattan-park-shade test dataflow (the plan for
#914, 2026-10-17) and the scenario comparison charts test dataflow (from
komar41's #914), with the computed ``SCOUT`` tag on the six SCOUT dataflows
(2026-10-17), and ``Pandas`` and ``Tables`` on quad-cities-flood-vulnerability once it builds a
table of the riverside tracts' depth by period (2026-10-18), and ``SCOUT`` on
the charts dataflow once its charts are SCOUT's package's nodes (2026-10-18),
which tag it ``Vega-Lite`` too: a template whose ``grammarId`` is
``vega-lite`` draws as the Vega-Lite node does. ``Rasters`` is on example 24
and chicago-loop-shadow-towers since SCOUT's raster nodes declare it for the
dataflows they are in (2026-10-18). Both are Scout's nodes since 2026-10-20
(``curio.scout@1``): the package declares ``SCOUT`` and its two raster
templates ``Rasters``, so the placement did not move. The routing dataflow
gained ``Vega-Lite`` when its four charts became Scout's Bars nodes,
example 06 ``Vega-Lite`` and ``SCOUT`` when its chart did, and
chicago-loop-shadow-towers, lower-manhattan-park-shade and
quad-cities-flood-vulnerability ``Vega-Lite`` when their charts did
(2026-10-20).
The automatic sections must reproduce it from the files alone, and the
hand-set ones live in the files themselves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.categories import (
    DatasetKinds,
    derive,
    hand_categories,
    normalize_hand,
)
from utk_curio.backend.app.projects.schemas import ProjectCreate, ProjectUpdate
from utk_curio.backend.app.projects.shipped import (
    SOURCE_EXAMPLE,
    SOURCE_TEST,
    SOURCE_USE_CASE,
    shipped_dataflows,
)

GOLDEN = json.loads(
    (Path(__file__).parent / "shipped_categories.json").read_text(encoding="utf-8")
)
SHIPPED = {s.key: s for s in shipped_dataflows()}

CITIES = {"Chicago", "Seattle", "Niterói", "Boston", "Milan", "New York"}
TOPICS = {
    "Mobility and streets", "Greenery", "Heat and climate", "Building and energy", "Sensors",
}
LEVELS = {"Beginner", "Intermediate", "Advanced"}


def _spec(key: str) -> dict:
    return json.loads(SHIPPED[key].path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The approved placement
# ---------------------------------------------------------------------------

def test_the_golden_file_covers_every_shipped_dataflow():
    assert set(GOLDEN) == set(SHIPPED)
    assert len(SHIPPED) == 56


@pytest.mark.parametrize("key", sorted(SHIPPED))
def test_automatic_categories_match_the_approved_placement(key):
    kinds = DatasetKinds(None)
    assert derive(_spec(key), kinds) == GOLDEN[key]


@pytest.mark.parametrize("key", sorted(SHIPPED))
def test_each_shipped_file_declares_its_hand_categories(key):
    hand = hand_categories(_spec(key))
    assert len(hand.get("complexity", [])) == 1, key
    assert set(hand["complexity"]) <= LEVELS
    assert set(hand.get("city", [])) <= CITIES
    assert set(hand.get("topic", [])) <= TOPICS
    assert "tags" not in hand, "shipped files get their tags from the nodes"
    if SHIPPED[key].source == SOURCE_TEST:
        assert hand["complexity"] == ["Beginner"]


def test_sources():
    by_source = {}
    for entry in SHIPPED.values():
        by_source.setdefault(entry.source, []).append(entry.key)
    assert sorted(by_source[SOURCE_USE_CASE]) == ["09-heterogeneous-data-linked-views"]
    assert len(by_source[SOURCE_EXAMPLE]) == 25
    assert len(by_source[SOURCE_TEST]) == 30


def test_no_spec_stores_a_source():
    """The source comes from the id; a stored one would follow a duplicate."""
    for key in SHIPPED:
        dataflow = _spec(key)["dataflow"]
        assert "source" not in dataflow.get("categories", {}), key


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def test_normalize_trims_dedupes_and_keeps_one_complexity():
    assert normalize_hand({
        "tags": ["  Flood ", "flood", "", 3, "Rain   gauges"],
        "complexity": ["Beginner", "Advanced"],
        "source": ["example"],
        "topic": [],
    }) == {"tags": ["Flood", "Rain gauges"], "complexity": ["Advanced"]}


def test_derive_reads_node_types_imports_and_datasets():
    spec = {"dataflow": {"nodes": [
        {"type": "curio.builtin/autk-grammar@1", "content": '{"compute": [{}]}'},
        {"type": "curio.builtin/computation-analysis", "content": "import geopandas as gpd"},
    ], "edges": [], "datasets": [{"dirName": "data.x@1"}]}}
    derived = derive(spec, lambda _id: ("geotiff", None))
    assert derived == {
        "tags": ["Autark", "GeoPandas", "GPU compute"],
        "data_type": ["Geometries", "Rasters"],
    }


def test_an_empty_dataflow_has_no_automatic_categories():
    assert derive({"dataflow": {"nodes": [], "edges": []}}) == {"tags": [], "data_type": []}


# ---------------------------------------------------------------------------
# The SCOUT tag: a node or model from a SCOUT package, or a SCOUT dataset
# ---------------------------------------------------------------------------

def _tags(nodes: list[dict], datasets: list[dict] | None = None) -> list[str]:
    """The automatic tags of a dataflow of *nodes*, without a dataset lookup."""
    dataflow = {"nodes": nodes, "edges": []}
    if datasets is not None:
        dataflow["datasets"] = datasets
    return derive({"dataflow": dataflow})["tags"]


@pytest.mark.parametrize("node_type", [
    "curio.scout/rasterize-buildings@1",
    "curio.scout/raster-calculator@1",
])
def test_a_node_from_a_scout_package_tags_the_dataflow_scout(node_type):
    node = {"id": "a", "type": node_type, "content": ""}
    assert _tags([node]) == ["SCOUT"]


def test_a_node_from_a_scout_model_package_tags_the_dataflow_scout():
    node = {"id": "a", "type": "model.scout.deep-umbra/accumulated-shadow@1", "content": ""}
    assert _tags([node]) == ["SCOUT"]


def test_a_scout_model_loaded_in_a_code_node_tags_the_dataflow_scout():
    node = {
        "id": "a",
        "type": "curio.builtin/computation-analysis@1",
        "content": 'model = curio_load_model("model.scout.weather-gnn")\nreturn model',
    }
    assert _tags([node]) == ["SCOUT"]


@pytest.mark.parametrize("content, datasets", [
    ('gdf = curio_load_data("data.scout.loop-buildings")\nreturn gdf', None),
    ('path = curio_data_path("data.scout.wrf-rain")\nreturn path', None),
    ("", [{"datasetId": "data.scout.flood-nbs-classes", "dirName": "data.scout.flood-nbs-classes@1"}]),
], ids=["loaded-in-code", "path-in-code", "in-the-dataflow-datasets"])
def test_a_scout_dataset_alone_tags_the_dataflow_scout(content, datasets):
    """netcdf-hourly-rain has no SCOUT node, only SCOUT's datasets."""
    node = {"id": "a", "type": "curio.builtin/data-loading@1", "content": content}
    assert _tags([node], datasets) == ["SCOUT"]


def test_the_park_shade_dataflow_is_tagged_scout_by_its_package_nodes_alone():
    """``lower-manhattan-park-shade`` reads no SCOUT dataset: it loads
    OpenStreetMap's buildings and parks from an extract. SCOUT's rasterizer and
    Deep Umbra's nodes tag it, as computed tags are, with nothing hand-set."""
    key = "dataflows/lower-manhattan-park-shade"
    spec = _spec(key)
    assert not spec["dataflow"].get("datasets")
    assert "SCOUT" in derive(spec, DatasetKinds(None))["tags"]
    assert "tags" not in hand_categories(spec)
    nodes = spec["dataflow"]["nodes"]
    without = {"dataflow": {**spec["dataflow"], "nodes": [
        n for n in nodes if not n["type"].startswith(("curio.scout/", "model.scout."))
    ]}}
    assert "SCOUT" not in derive(without, DatasetKinds(None))["tags"]


def test_the_flood_dataflow_is_tagged_scout_by_its_raster_calculators_alone():
    """``quad-cities-flood-vulnerability`` reads SCOUT's datasets, and its
    Raster Calculators are Scout's (``curio.scout``) nodes: with no dataset
    and no code, its nodes alone still tag it, as computed tags are. Since
    its charts became Scout's Bars, Points and Grouped bars (the plan
    answering komar41's review, step 6.3), they tag it ``Vega-Lite`` too;
    without them, its Raster Calculators alone still tag it ``SCOUT``."""
    spec = _spec("dataflows/quad-cities-flood-vulnerability")
    assert "tags" not in hand_categories(spec)
    nodes = spec["dataflow"]["nodes"]
    calculators = [n for n in nodes if n["type"] == "curio.scout/raster-calculator"]
    assert len(calculators) == 7
    charts = {n["id"]: n["type"] for n in nodes if n["type"].startswith("curio.scout/") and n not in calculators}
    assert sorted(charts.values()) == ["curio.scout/bars", "curio.scout/grouped-bars", "curio.scout/points"]
    bare = {"dataflow": {
        **{k: v for k, v in spec["dataflow"].items() if k != "datasets"},
        "nodes": [{**n, "content": ""} for n in nodes],
    }}
    assert derive(bare, DatasetKinds(None))["tags"] == ["Autark", "Vega-Lite", "SCOUT"]
    no_charts = {"dataflow": {**bare["dataflow"], "nodes": [n for n in bare["dataflow"]["nodes"] if n["id"] not in charts]}}
    assert derive(no_charts, DatasetKinds(None))["tags"] == ["Autark", "SCOUT"]


def test_the_charts_dataflow_is_tagged_scout_and_vega_lite_by_its_package_nodes_alone():
    """``scenario-comparison-charts`` reads no SCOUT dataset and has no
    ``curio.builtin/vis-vega`` node: its nine charts, all Scout's, give it both
    tags, by their package's ``dataflowCategories`` and by their template's
    grammar."""
    spec = _spec("dataflows/scenario-comparison-charts")
    nodes = spec["dataflow"]["nodes"]
    charts = [n for n in nodes if n["type"].startswith("curio.scout/")]
    assert len(charts) == 9
    assert not any(n["type"].startswith("curio.builtin/vis-vega") for n in nodes)
    assert derive(spec, DatasetKinds(None))["tags"] == ["Vega-Lite", "SCOUT"]
    without = {"dataflow": {**spec["dataflow"], "nodes": [n for n in nodes if n not in charts]}}
    assert derive(without, DatasetKinds(None))["tags"] == []


# ---------------------------------------------------------------------------
# A grammar's tag: a node whose template draws with it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_id", [
    "lines-with-band", "curves-by-group", "bars-with-error-bars", "ensemble-strips",
    "stacked-bars-with-totals", "donuts", "weighted-matrix", "dots-with-a-range",
    "bars", "grouped-bars", "lines", "points", "pie", "lollipops", "table",
])
def test_a_scout_comparison_chart_is_a_vega_lite_node(template_id):
    """Its template names the ``vega-lite`` grammar in the shipped manifest,
    as the Vega-Lite node's does, versioned or not."""
    for node_type in (f"curio.scout/{template_id}", f"curio.scout/{template_id}@1"):
        node = {"id": "a", "type": node_type, "content": "{}"}
        assert _tags([node]) == ["Vega-Lite", "SCOUT"], node_type


def test_a_template_is_tagged_by_its_grammar_whatever_package_it_is_in():
    """An account's own package whose template draws with Vega-Lite or with
    Autark tags the dataflow as the built-in node does; one that names no
    grammar, or an unknown node type, tags nothing."""
    grammars = {"acme.charts/bars": "vega-lite", "acme.maps/heat": "autk-grammar", "acme.code/clean": None}
    resolve = lambda node_type: grammars.get(node_type.split("@", 1)[0])  # noqa: E731

    def tags(node_type, content=""):
        spec = {"dataflow": {"nodes": [{"id": "a", "type": node_type, "content": content}], "edges": []}}
        return derive(spec, template_grammar=resolve)

    assert tags("acme.charts/bars@2")["tags"] == ["Vega-Lite"]
    heat = tags("acme.maps/heat@1", '{"compute": [{}]}')
    assert heat == {"tags": ["Autark", "GPU compute"], "data_type": ["Geometries"]}
    assert tags("acme.code/clean")["tags"] == []
    assert tags("acme.unknown/x")["tags"] == []


def test_the_grammar_of_a_template_in_the_accounts_store_is_read(tmp_path, monkeypatch):
    """``TemplateGrammars`` reads the account's packages first, then the ones
    Curio ships, as ``DatasetKinds`` reads datasets, by the node's major or,
    unversioned, the highest one."""
    from utk_curio.backend.app.packages import service as packages_service
    from utk_curio.backend.app.projects.categories import TemplateGrammars

    store = tmp_path / "packages"
    for major, grammar in ((1, "vega-lite"), (2, "autk-grammar")):
        folder = store / f"acme.charts@{major}"
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({
            "id": "acme.charts",
            "templates": [{"id": "bars", "grammarId": grammar}, {"id": "table"}],
        }), encoding="utf-8")
    monkeypatch.setattr(packages_service, "user_packages_dir", lambda _key: store)

    grammars = TemplateGrammars("someone")
    assert grammars("acme.charts/bars@1") == "vega-lite"
    assert grammars("acme.charts/bars@2") == "autk-grammar"
    assert grammars("acme.charts/bars") == "autk-grammar"
    assert grammars("acme.charts/table") is None
    assert grammars("acme.charts/missing") is None
    # Curio's own packages answer after the account's.
    assert grammars("curio.builtin/vis-vega@1") == "vega-lite"
    assert grammars("curio.scout/donuts") == "vega-lite"
    assert TemplateGrammars(None)("acme.charts/bars") is None


def test_a_dataflow_that_only_mentions_scout_is_not_tagged_scout():
    """Comments, links and look-alike package, model and dataset ids."""
    code = (
        "# SCOUT's buildings, as in https://github.com/urban-toolkit/scout.\n"
        'gdf = curio_load_data("data.utk.chicago-boundary")\n'
        'rows = curio_load_data("data.scouting.counts")\n'
        'model = curio_load_model("model.scouting.shade")\n'
        "return gdf"
    )
    nodes = [
        {"id": "a", "type": "curio.builtin/data-loading@1", "content": code},
        {"id": "b", "type": "scouting.tools/count@1", "content": ""},
        {"id": "c", "type": "model.scouting.shade/estimate@1", "content": ""},
        {"id": "d", "type": "acme.scout/route@1", "content": ""},
    ]
    datasets = [{"dirName": "data.scouting.counts@1"}, {"datasetId": "data.utk.scout-towers"}]
    assert _tags(nodes, datasets) == []


# ---------------------------------------------------------------------------
# Saving and editing
# ---------------------------------------------------------------------------

def _save(user, categories=None, nodes=None):
    dataflow = {"name": "Mine", "nodes": nodes or [], "edges": []}
    if categories is not None:
        dataflow["categories"] = categories
    return services.save_project(
        user, ProjectCreate(name="Mine", spec={"dataflow": dataflow}, outputs=[])
    )


def _on_disk(user, project_id):
    return storage.read_spec(str(user.id), project_id)["dataflow"].get("categories")


def test_a_user_dataflow_gets_automatic_tags_from_its_nodes(app, db, user_and_token):
    user, _ = user_and_token
    detail = _save(user, nodes=[{"id": "a", "type": "curio.builtin/vis-vega", "content": "{}"}])

    assert detail.categories["source"] is None
    assert detail.categories["auto"]["tags"] == ["Vega-Lite"]
    summary = next(s for s in services.list_projects(user) if s.id == detail.id)
    assert summary.categories["auto"]["tags"] == ["Vega-Lite"]
    assert summary.is_example is False


def test_a_categories_only_update_writes_the_spec(app, db, user_and_token):
    user, _ = user_and_token
    detail = _save(user)

    updated = services.update_project(
        user, detail.id, ProjectUpdate(categories={"topic": ["Greenery"], "city": ["Milan"]}),
    )

    assert updated.categories["hand"] == {"city": ["Milan"], "topic": ["Greenery"]}
    assert _on_disk(user, detail.id) == {"city": ["Milan"], "topic": ["Greenery"]}


def test_a_save_without_the_key_keeps_the_categories(app, db, user_and_token):
    """An agent's graph edit or any writer that does not know the field."""
    user, _ = user_and_token
    detail = _save(user, categories={"topic": ["Sensors"]})

    spec = {"dataflow": {"name": "Mine", "nodes": [], "edges": []}}
    services.update_project(user, detail.id, ProjectUpdate(spec=spec))

    assert _on_disk(user, detail.id) == {"topic": ["Sensors"]}


def test_a_save_with_an_empty_key_clears_them(app, db, user_and_token):
    user, _ = user_and_token
    detail = _save(user, categories={"topic": ["Sensors"]})

    spec = {"dataflow": {"name": "Mine", "nodes": [], "edges": [], "categories": {}}}
    services.update_project(user, detail.id, ProjectUpdate(spec=spec))

    assert _on_disk(user, detail.id) is None


def test_a_duplicate_is_the_users_own_and_keeps_its_categories(app, db, user_and_token):
    user, _ = user_and_token
    detail = _save(user, categories={"city": ["Boston"]})

    copy = services.duplicate_project(user, detail.id)

    assert copy.categories["source"] is None
    assert copy.categories["hand"] == {"city": ["Boston"]}


def test_categories_must_be_an_object():
    with pytest.raises(ValueError):
        ProjectUpdate(categories=["Greenery"])
