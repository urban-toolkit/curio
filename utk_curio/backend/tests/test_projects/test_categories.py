"""Dataflow categories: what the Projects rail filters by.

``shipped_categories.json`` is the placement the owner approved for the 44
shipped dataflows (2026-09-30), and the Scenarios, FloodScenarios,
ScoutShadows, WeatherRouting and NetCDF test dataflows and
example 24 placed by the same rules (#662, 2026-10-05), example 25 (#576),
example 26 (#819) and the scenario comparison charts test dataflow (from
komar41's #914), with the computed ``SCOUT`` tag on the five SCOUT dataflows
(2026-10-17). The automatic
sections must reproduce it from
the files alone, and the hand-set ones live in the files themselves.
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
    USE_CASES,
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
    assert len(SHIPPED) == 53


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
    assert sorted(by_source[SOURCE_USE_CASE]) == sorted(USE_CASES)
    assert len(by_source[SOURCE_EXAMPLE]) == 25
    assert len(by_source[SOURCE_TEST]) == 27


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


def test_a_node_from_a_scout_package_tags_the_dataflow_scout():
    node = {"id": "a", "type": "scout.raster-conversion/rasterize-buildings@1", "content": ""}
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
    """FloodScenarios and NetCDF have no SCOUT node, only SCOUT's datasets."""
    node = {"id": "a", "type": "curio.builtin/data-loading@1", "content": content}
    assert _tags([node], datasets) == ["SCOUT"]


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
        {"id": "d", "type": "curio.scout/route@1", "content": ""},
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
