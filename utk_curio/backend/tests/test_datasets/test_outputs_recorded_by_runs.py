"""A run on the server records its outputs without a save, and a save from a
tab that never saw that run cannot put the older outputs back.

Each manifest output carries ``produced_at``, taken from the artifact id's own
millisecond timestamp. When a save and the manifest name different outputs for
one node, the newer one stays, and only the winner is installed in the Data
Catalog: an older output reinstalled over a newer one would leave the manifest
naming a file whose data a reload no longer restores.

``record_node_outputs`` is imported inside each test, so a checkout without it
fails each test on its own instead of failing the whole collection.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers

NODE_TYPE = "curio.builtin/computation-analysis"


def _node(node_id: str, content: str, **fields) -> dict:
    """A node as the canvas saves it: ``saveOutputDataset`` is its Save toggle."""
    return {"id": node_id, "type": NODE_TYPE, "content": content, **fields}


def _dataflow(*nodes, edges=(), name="Run outputs") -> dict:
    return {"dataflow": {"name": name, "nodes": list(nodes), "edges": list(edges)}}


def _both_saving() -> dict:
    """Nodes a and b, each with its Save toggle on."""
    return _dataflow(
        _node("a", "return 1", saveOutputDataset=True),
        _node("b", "return 2", saveOutputDataset=True),
    )


def _create(client, token, name="Run outputs", spec=None) -> str:
    spec = spec or {"dataflow": {"name": name, "nodes": [
        {"id": "a", "type": NODE_TYPE, "content": "return 1"},
        {"id": "b", "type": NODE_TYPE, "content": "return 2"},
    ], "edges": []}}
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": name, "spec": spec, "outputs": []}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _artifact(ms: int, payload) -> str:
    """A JSON artifact as the sandbox names it: ``<ms>_<8 hex>.json``."""
    name = f"{ms}_{uuid.uuid4().hex[:8]}.json"
    (Path(os.environ["CURIO_SHARED_DATA"]) / name).write_text(json.dumps(payload), encoding="utf-8")
    return name


def _save(client, token, project_id, outputs, **body):
    return client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({
            "outputs": [
                {"node_id": node_id, "filename": filename, "data_type": "dict"}
                for node_id, filename in outputs
            ],
            **body,
        }),
        headers=auth_headers(token),
    )


def _record(user, project_id, outputs):
    from utk_curio.backend.app.projects.schemas import OutputRef
    from utk_curio.backend.app.projects.services import record_node_outputs

    return record_node_outputs(user, project_id, [
        OutputRef(node_id=node_id, filename=filename, data_type="dict")
        for node_id, filename in outputs
    ])


def _manifest(user, project_id) -> dict:
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    return storage.read_manifest(_user_dir_key(user), project_id) or {}


def _outputs(user, project_id) -> dict:
    return {o["node_id"]: o["filename"] for o in _manifest(user, project_id).get("outputs", [])}


def _installed(user, project_id, node_id):
    """What a reload would restore for *node_id*: its Data Catalog copy."""
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    path = storage._account_store_computed_file(_user_dir_key(user), project_id, node_id)
    assert path is not None, f"node {node_id} has no installed output"
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_run_records_one_nodes_output_and_keeps_the_others(app, client, user_and_token):
    user, token = user_and_token
    project_id = _create(client, token)
    a = _artifact(1790000000000, {"v": "a"})
    assert _save(client, token, project_id, [("a", a)]).status_code == 200

    b = _artifact(1790000000100, {"v": "b"})
    recorded = _record(user, project_id, [("b", b)])

    assert {(r.node_id, r.filename) for r in recorded} == {("a", a), ("b", b)}
    assert _outputs(user, project_id) == {"a": a, "b": b}
    assert _installed(user, project_id, "b") == {"v": "b"}


def test_recording_changes_neither_the_spec_nor_its_revision(app, client, db, user_and_token):
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    project_id = _create(client, token)
    a = _artifact(1790000000000, {"v": "a"})
    saved = _save(client, token, project_id, [("a", a)]).get_json()
    ukey = _user_dir_key(user)
    spec_file = storage.project_dir(ukey, project_id) / "spec.trill.json"
    spec_bytes = spec_file.read_bytes()
    db.session.expire_all()
    row_revision = db.session.get(Project, project_id).spec_revision

    _record(user, project_id, [("b", _artifact(1790000000100, {"v": "b"}))])

    assert storage.spec_revision(ukey, project_id) == saved["spec_revision"]
    db.session.expire_all()
    assert db.session.get(Project, project_id).spec_revision == row_revision
    assert spec_file.read_bytes() == spec_bytes


def test_a_stale_tab_cannot_put_back_an_older_output(app, client, user_and_token):
    user, token = user_and_token
    project_id = _create(client, token)
    old = _artifact(1790000000000, {"v": "old"})
    new = _artifact(1790000000500, {"v": "new"})
    assert _save(client, token, project_id, [("a", old)]).status_code == 200
    _record(user, project_id, [("a", new)])

    # The tab saves again, still holding the output it ran before the server did.
    stale = _save(client, token, project_id, [("a", old)])

    assert stale.status_code == 200, stale.get_data(as_text=True)
    assert {o["node_id"]: o["filename"] for o in stale.get_json()["outputs"]} == {"a": new}
    assert _outputs(user, project_id) == {"a": new}
    assert _installed(user, project_id, "a") == {"v": "new"}, (
        "the stale save reinstalled the older output over the newer one"
    )


def test_a_newer_output_from_the_tab_wins(app, client, user_and_token):
    user, token = user_and_token
    project_id = _create(client, token)
    old = _artifact(1790000000000, {"v": "old"})
    new = _artifact(1790000000500, {"v": "new"})
    _record(user, project_id, [("a", old)])

    assert _save(client, token, project_id, [("a", new)]).status_code == 200

    assert _outputs(user, project_id) == {"a": new}
    assert _installed(user, project_id, "a") == {"v": "new"}


def test_a_save_still_drops_the_outputs_it_leaves_out(app, client, user_and_token):
    user, token = user_and_token
    project_id = _create(client, token)
    a = _artifact(1790000000000, {"v": "a"})
    b = _artifact(1790000000100, {"v": "b"})
    assert _save(client, token, project_id, [("a", a), ("b", b)]).status_code == 200

    assert _save(client, token, project_id, [("a", a)]).status_code == 200

    assert _outputs(user, project_id) == {"a": a}


def _a_saved_and_b_recorded(client, token, user, spec):
    """a saved by the canvas, then b recorded by a run the canvas has not
    taken in yet. Returns the project id and both outputs."""
    project_id = _create(client, token, spec=spec)
    a = _artifact(1790000000000, {"v": "a"})
    assert _save(client, token, project_id, [("a", a)], spec=spec).status_code == 200
    b = _artifact(1790000000100, {"v": "b"})
    _record(user, project_id, [("b", b)])
    return project_id, a, b


def test_a_save_keeps_an_output_a_run_recorded_that_it_leaves_out(app, client, user_and_token):
    """The save that ends a run can be sent before the canvas holds the output
    the run has just recorded, and a tab that never saw the run holds none.
    Neither may take it out of the dataflow while b is still there as it was."""
    user, token = user_and_token
    spec = _both_saving()
    project_id, a, b = _a_saved_and_b_recorded(client, token, user, spec)
    recorded_at = {o["node_id"]: o.get("produced_at") for o in _manifest(user, project_id)["outputs"]}

    saved = _save(client, token, project_id, [("a", a)], spec=spec)

    assert saved.status_code == 200, saved.get_data(as_text=True)
    assert {o["node_id"]: o["filename"] for o in saved.get_json()["outputs"]} == {"a": a, "b": b}, (
        "a save that left b out took out the output a run had recorded for it"
    )
    assert _outputs(user, project_id) == {"a": a, "b": b}
    kept = {o["node_id"]: o.get("produced_at") for o in _manifest(user, project_id)["outputs"]}
    assert kept["b"] == recorded_at["b"]
    assert _installed(user, project_id, "b") == {"v": "b"}


def test_a_save_drops_the_output_of_a_node_it_deleted(app, client, user_and_token):
    user, token = user_and_token
    project_id, a, _b = _a_saved_and_b_recorded(client, token, user, _both_saving())

    without_b = _dataflow(_node("a", "return 1", saveOutputDataset=True))
    assert _save(client, token, project_id, [("a", a)], spec=without_b).status_code == 200

    assert _outputs(user, project_id) == {"a": a}


def test_a_save_drops_the_output_of_a_node_whose_save_is_off(app, client, user_and_token):
    user, token = user_and_token
    project_id, a, _b = _a_saved_and_b_recorded(client, token, user, _both_saving())

    save_off = _dataflow(
        _node("a", "return 1", saveOutputDataset=True),
        _node("b", "return 2", saveOutputDataset=False),
    )
    assert _save(client, token, project_id, [("a", a)], spec=save_off).status_code == 200

    assert _outputs(user, project_id) == {"a": a}


def test_a_save_drops_the_output_of_a_node_whose_code_changed(app, client, user_and_token):
    user, token = user_and_token
    project_id, a, _b = _a_saved_and_b_recorded(client, token, user, _both_saving())

    edited = _dataflow(
        _node("a", "return 1", saveOutputDataset=True),
        _node("b", "return 3", saveOutputDataset=True),
    )
    assert _save(client, token, project_id, [("a", a)], spec=edited).status_code == 200

    assert _outputs(user, project_id) == {"a": a}


def test_a_save_keeps_the_output_a_pinned_tile_reads_whatever_its_toggle(app, client, user_and_token):
    """A pinned tile's source is recorded with its Save off, by a run and by a
    save alike (``savedSourceNodeIds``), so a save that leaves it out keeps it."""
    user, token = user_and_token
    spec = _dataflow(
        _node("a", "return 1", saveOutputDataset=True),
        _node("b", "return 2", saveOutputDataset=False),
        {"id": "chart", "type": "curio.builtin/vis-vega", "content": "{}", "dashboardPinned": True},
        edges=[{"id": "b-chart", "source": "b", "target": "chart"}],
    )
    project_id, a, b = _a_saved_and_b_recorded(client, token, user, spec)

    assert _save(client, token, project_id, [("a", a)], spec=spec).status_code == 200

    assert _outputs(user, project_id) == {"a": a, "b": b}


def test_an_output_recorded_without_a_stamp_counts_as_oldest(app, client, user_and_token):
    """Manifests written before ``produced_at`` existed: the save wins, as it did."""
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.schemas import OutputRef
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    project_id = _create(client, token)
    unstamped = _artifact(1790000000900, {"v": "unstamped"})
    assert _save(client, token, project_id, [("a", unstamped)]).status_code == 200
    storage.write_manifest(
        _user_dir_key(user), project_id, 1,
        [OutputRef(node_id="a", filename=unstamped, data_type="dict")],
        name="Run outputs",
    )
    assert "produced_at" not in _manifest(user, project_id)["outputs"][0]

    older = _artifact(1790000000000, {"v": "older"})
    assert _save(client, token, project_id, [("a", older)]).status_code == 200

    assert _outputs(user, project_id) == {"a": older}


def test_an_output_is_stamped_with_its_artifacts_time_and_keeps_it(app, client, user_and_token):
    user, token = user_and_token
    project_id = _create(client, token)
    a = _artifact(1790000000000, {"v": "a"})
    expected = datetime.fromtimestamp(1790000000, tz=timezone.utc).isoformat(timespec="milliseconds")
    assert _save(client, token, project_id, [("a", a)]).status_code == 200
    assert _manifest(user, project_id)["outputs"][0]["produced_at"] == expected

    # A rename carries the outputs over, and the same output saved again is
    # the same output: neither is re-stamped.
    renamed = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({"name": "Renamed"}), headers=auth_headers(token),
    )
    assert renamed.status_code == 200
    assert _manifest(user, project_id)["outputs"][0]["produced_at"] == expected
    assert _save(client, token, project_id, [("a", a)]).status_code == 200
    assert _manifest(user, project_id)["outputs"][0]["produced_at"] == expected
