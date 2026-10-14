"""The dashboard page's own settings, ``dataflow.dashboard``: where its Run
button stands. Saved as the page writes them, and kept by a save that does not
know the field, as the hand categories and the scenarios are.
"""
from __future__ import annotations

from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.schemas import ProjectCreate, ProjectUpdate

PLACED = {"runButton": {"x": 640, "y": -20}}


def _spec(dashboard=None):
    nodes = [{"id": "a", "type": "curio.builtin/computation-analysis", "content": "", "x": 0, "y": 0}]
    dataflow = {"name": "Mine", "nodes": nodes, "edges": []}
    if dashboard is not None:
        dataflow["dashboard"] = dashboard
    return {"dataflow": dataflow}


def _on_disk(user, project_id):
    return storage.read_spec(str(user.id), project_id)["dataflow"].get("dashboard")


def test_a_save_keeps_where_the_run_button_stands(app, db, user_and_token):
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Mine", spec=_spec(PLACED), outputs=[]))
    assert _on_disk(user, detail.id) == PLACED


def test_a_save_that_moves_it_writes_the_new_place(app, db, user_and_token):
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Mine", spec=_spec(PLACED), outputs=[]))
    moved = {"runButton": {"x": 10, "y": 20}}
    services.update_project(user, detail.id, ProjectUpdate(spec=_spec(moved)))
    assert _on_disk(user, detail.id) == moved


def test_a_save_without_the_key_keeps_it(app, db, user_and_token):
    """An agent's graph edit, or any writer that does not know the field."""
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Mine", spec=_spec(PLACED), outputs=[]))
    services.update_project(user, detail.id, ProjectUpdate(spec=_spec()))
    assert _on_disk(user, detail.id) == PLACED


def test_a_dataflow_never_placed_has_no_key(app, db, user_and_token):
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Mine", spec=_spec(), outputs=[]))
    services.update_project(user, detail.id, ProjectUpdate(spec=_spec()))
    assert _on_disk(user, detail.id) is None
