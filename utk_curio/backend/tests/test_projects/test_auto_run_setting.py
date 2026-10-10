"""The "Run stale nodes automatically" toggle (#845) is saved with the
dataflow, at ``dataflow.autoRun``. The canvas always writes it; a writer that
does not know it (an agent's graph edit) keeps the saved value.
"""

from __future__ import annotations

from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.schemas import ProjectCreate, ProjectUpdate


def _save(user, **dataflow_fields):
    dataflow = {"name": "Mine", "nodes": [], "edges": [], **dataflow_fields}
    return services.save_project(
        user, ProjectCreate(name="Mine", spec={"dataflow": dataflow}, outputs=[])
    )


def _on_disk(user, project_id):
    return storage.read_spec(str(user.id), project_id)["dataflow"].get("autoRun")


def test_a_save_without_the_key_keeps_auto_run_on(app, db, user_and_token):
    """#845: an agent's graph edit must not turn the toggle off."""
    user, _ = user_and_token
    detail = _save(user, autoRun=True)

    spec = {"dataflow": {"name": "Mine", "nodes": [], "edges": []}}
    services.update_project(user, detail.id, ProjectUpdate(spec=spec))

    assert _on_disk(user, detail.id) is True


def test_a_save_that_turns_it_off_is_kept(app, db, user_and_token):
    """#845: the canvas writes the key, so off is kept as off."""
    user, _ = user_and_token
    detail = _save(user, autoRun=True)

    spec = {"dataflow": {"name": "Mine", "nodes": [], "edges": [], "autoRun": False}}
    services.update_project(user, detail.id, ProjectUpdate(spec=spec))

    assert _on_disk(user, detail.id) is False
