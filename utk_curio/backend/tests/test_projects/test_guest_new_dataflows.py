"""A hosted guest's File > New is a dataflow of its own, kept until the
server starts again (``projects/visitor_copies.py``).

Every hosted guest (a guest on a Curio started with ``--deploy``) signs in to
the one shared guest account. These tests sign two visitors, A and B, in to
it, as two browsers do, and have A make a dataflow as its File > New makes
one, on its first action that needs one. A's plays, datasets and gallery work
on it as an account's do on its own dataflow; B, who knows its id, finds no
such dataflow and writes nothing for it; the shared account's example and
dataset store are byte for byte what they were; and the next start drops it.
The sandbox is the fake ``test_guest_copy_leaks.py`` plays against.
"""
from __future__ import annotations

import io
import json

from utk_curio.backend import config
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.runs.models import KeptStepOutput
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (  # noqa: F401 - fixtures
    VISITOR_A,
    VISITOR_B,
    _computed_in_the_store,
    _digests,
    _node,
    _open,
    _play,
    _results,
    app,
    example,
    sandbox,
)
from utk_curio.common.kept_sessions import is_kept_session


def _new_dataflow(client, token: str) -> str:
    """The visitor signed in as *token* makes a dataflow, a to b, as its
    File > New makes one on its first action that needs one; its id."""
    created = client.post("/api/projects", data=json.dumps({
        "name": "Mine",
        "spec": {"dataflow": {
            "name": "Mine", "nodes": [_node("a"), _node("b")],
            "edges": [{"id": "a-b", "source": "a", "target": "b", "targetHandle": "in"}],
        }},
        "outputs": [],
    }), headers=auth_headers(token))
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.get_json()["kept_for_visit"] is True
    return created.get_json()["id"]


def _copy_folder_of(token: str, project_id: str):
    """Where a copy of *project_id* for *token*'s visitor would be."""
    from utk_curio.backend.app.projects import visitor_copies

    return storage.project_dir(GUEST_KEY, visitor_copies.copy_id(token, project_id))


def test_a_hosted_guests_plays_on_its_new_dataflow_are_kept_on_it_for_it_alone(client, example, sandbox):
    from utk_curio.backend.app.execution import runtime_journal

    before = _digests(example)
    mine = _new_dataflow(client, VISITOR_A)
    made_a, made_b = sandbox["artifacts"]["a"], sandbox["artifacts"]["b"]

    reply = _play(client, VISITOR_A, mine, "a")
    _play(client, VISITOR_A, mine, "b", inputs=[made_a])

    # Nothing joins the Data Catalog, which every guest's lists.
    assert reply["installedDataset"] is None
    assert _computed_in_the_store() == []
    # b read a's output in the session A's play kept it in, and A's canvas
    # opens with both, as an account's dataflow opens with its runs' results.
    assert is_kept_session(sandbox["runs"]["b"]["session_id"])
    assert _results(client, VISITOR_A, mine) == {"a": made_a, "b": made_b}
    assert KeptStepOutput.query.filter_by(project_id=mine).count() == 2
    # Its outcome is in the dataflow's own journal, which its agents read.
    assert runtime_journal.read_record(GUEST_KEY, mine, "a")["status"] == "ok"
    resp = client.get("/nodeRuntime", query_string={"dataflowId": mine, "nodeId": "a"},
                      headers=auth_headers(VISITOR_A))
    assert resp.status_code == 200 and resp.get_json()["run"]["status"] == "ok"
    # A reads its outputs on the dataflow's route, in the session that made them.
    reads = len(sandbox["reads"])
    client.get(f"/api/projects/{mine}/outputs/get", query_string={"fileName": made_a},
               headers=auth_headers(VISITOR_A))
    assert len(sandbox["reads"]) == reads + 1
    assert is_kept_session(sandbox["reads"][-1]["sessionId"])
    assert _digests(example) == before


def test_another_guest_finds_none_of_a_guests_new_dataflow_and_writes_nothing_for_it(
    client, example, sandbox, monkeypatch,
):
    from utk_curio.backend.app.execution import runtime_journal

    # A dataset every guest's Data Catalog lists, which B may add to a
    # dataflow of B's own.
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    shared = client.post(
        "/api/datasets/import", headers={"Authorization": f"Bearer {VISITOR_A}"},
        data={"file": (io.BytesIO(b"tree,height\noak,12\n"), "trees.csv")}, content_type="multipart/form-data",
    )
    assert shared.status_code == 201, shared.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    before = _digests(example)
    mine = _new_dataflow(client, VISITOR_A)
    made_a = sandbox["artifacts"]["a"]
    _play(client, VISITOR_A, mine, "a")
    reads = len(sandbox["reads"])

    for method, path, payload in (
        ("GET", f"/api/projects/{mine}?results=last", None),
        ("GET", f"/api/projects/{mine}/outputs/get?fileName={made_a}", None),
        ("GET", f"/api/projects/{mine}/history", None),
        ("POST", f"/api/projects/{mine}/history/nodes/a/edits", {"label": "B's"}),
        ("GET", f"/api/packages/projects/{mine}", None),
        ("POST", f"/api/dataflows/{mine}/datasets/install", {"datasetId": shared.get_json()["id"]}),
        ("GET", f"/api/agents/projects/{mine}/attachments", None),
    ):
        answer = client.open(path, method=method, headers=auth_headers(VISITOR_B),
                             data=json.dumps(payload) if payload is not None else None)
        assert answer.status_code == 404, (method, path, answer.get_data(as_text=True))
    assert len(sandbox["reads"]) == reads

    # B's play and render report naming A's dataflow keep, record and add
    # nothing, there or anywhere.
    reply = _play(client, VISITOR_B, mine, "a")
    assert reply["installedDataset"] is None
    assert _computed_in_the_store() == []
    assert KeptStepOutput.query.filter_by(project_id=mine).count() == 1
    reported = client.post("/nodeRuntime", data=json.dumps({
        "dataflowId": mine, "nodeId": "b", "status": "error", "message": "B's chart failed",
    }), headers=auth_headers(VISITOR_B))
    assert reported.status_code == 204, reported.get_data(as_text=True)
    assert runtime_journal.read_render_record(GUEST_KEY, mine, "b") is None
    resp = client.get("/nodeRuntime", query_string={"dataflowId": mine, "nodeId": "a"},
                      headers=auth_headers(VISITOR_B))
    assert resp.status_code == 200 and resp.get_json() == {"nodeId": "a", "run": None, "render": None}
    # No copy of A's dataflow was made for B, and A's is as A left it.
    assert not _copy_folder_of(VISITOR_B, mine).exists()
    assert [n["id"] for n in _open(client, VISITOR_A, mine)["spec"]["dataflow"]["nodes"]] == ["a", "b"]
    assert _digests(example) == before


def test_a_hosted_guests_dataset_add_lands_on_its_new_dataflow_alone(client, example):
    imported = client.post(
        "/api/datasets/import", headers={"Authorization": f"Bearer {VISITOR_A}"},
        data={"file": (io.BytesIO(b"tree,height\noak,12\n"), "trees.csv")}, content_type="multipart/form-data",
    )
    assert imported.status_code == 201, imported.get_data(as_text=True)
    uploaded = imported.get_json()["id"]
    before = _digests(example)
    mine = _new_dataflow(client, VISITOR_A)

    added = client.post(f"/api/dataflows/{mine}/datasets/install", data=json.dumps({"datasetId": uploaded}),
                        headers=auth_headers(VISITOR_A))

    assert added.status_code == 200, added.get_data(as_text=True)
    in_mine = _open(client, VISITOR_A, mine)["spec"]["dataflow"].get("datasets") or []
    assert [r["datasetId"] for r in in_mine] == [uploaded]
    listed = client.get("/api/datasets/catalog", query_string={"dataflowId": mine},
                        headers=auth_headers(VISITOR_A))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    assert any(i.get("id") == uploaded and i.get("installed") is True for i in listed.get_json()["items"])
    # The example every guest opens holds none of it.
    assert (_open(client, VISITOR_B, example)["spec"]["dataflow"].get("datasets") or []) == []
    assert _digests(example) == before


def test_a_hosted_guests_gallery_lists_its_new_dataflows_first_and_names_its_copies(client, example):
    first = _new_dataflow(client, VISITOR_A)
    second = _new_dataflow(client, VISITOR_A)
    renamed = client.put(f"/api/projects/{example}", data=json.dumps({"name": "My example"}),
                         headers=auth_headers(VISITOR_A))
    assert renamed.status_code == 200, renamed.get_data(as_text=True)

    def gallery(token):
        resp = client.get("/api/projects", headers=auth_headers(token))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        return [(p["id"], p["name"], p["kept_for_visit"], p["is_example"]) for p in resp.get_json()]

    # A's own new dataflows come first, newest first, marked; its card of the
    # example bears the name A gave its copy of it.
    assert gallery(VISITOR_A) == [
        (second, "Mine", True, False), (first, "Mine", True, False), (example, "My example", False, False),
    ]
    # B's gallery is the example as it ships.
    assert gallery(VISITOR_B) == [(example, "Example", False, False)]


def test_the_next_start_drops_a_guests_new_dataflows_and_makes_no_row_of_one(client, db, example, sandbox):
    from utk_curio.backend.app.projects import services, visitor_copies
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.users.models import User

    before = _digests(example)
    mine = _new_dataflow(client, VISITOR_A)
    _play(client, VISITOR_A, mine, "a")
    # A dataflow the start could not drop, with a manifest beside its spec, as
    # an account's dataflow has, is still no dataflow of the account's.
    storage.write_manifest(GUEST_KEY, mine, 1, [], name="Mine", description=None, thumbnail_accent="peach",
                           produced_at={})
    guest = User.query.filter_by(username=config.CURIO_SHARED_GUEST_USERNAME).one()

    assert services.reconcile_guest_projects(guest) == 0
    assert db.session.get(Project, mine) is None

    assert visitor_copies.drop_all() == 1
    assert storage.read_spec(GUEST_KEY, mine) is None
    assert KeptStepOutput.query.filter_by(project_id=mine).count() == 0
    assert client.get(f"/api/projects/{mine}", headers=auth_headers(VISITOR_A)).status_code == 404
    listed = client.get("/api/projects", headers=auth_headers(VISITOR_A)).get_json()
    assert [p["id"] for p in listed] == [example]
    assert services.reconcile_guest_projects(guest) == 0
    assert _digests(example) == before
