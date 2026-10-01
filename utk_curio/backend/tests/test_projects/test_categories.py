"""Dataflow categories: what the Projects rail filters by.

``shipped_categories.json`` is the placement the owner approved for the 44
shipped dataflows (2026-09-30). The automatic sections must reproduce it from
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
    assert len(SHIPPED) == 44


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
    assert len(by_source[SOURCE_EXAMPLE]) == 22
    assert len(by_source[SOURCE_TEST]) == 21


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
