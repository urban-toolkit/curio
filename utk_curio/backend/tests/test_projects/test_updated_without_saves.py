"""A dataflow's "Updated" time follows its changes, though no tab saves it.

Every change reaches the dataflow's spec through its doc, which writes no
project row, so the time the Projects page and the Scenario Catalog show is the
later of the row's and the spec's last write. Opening a dataflow, or reading
its history, writes no spec.
"""
import json
import time
from datetime import datetime


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _create(client, token, name="Updated"):
    resp = client.post("/api/projects", data=json.dumps({
        "name": name,
        "spec": {"dataflow": {"name": name, "nodes": [
            {"id": "a", "type": "curio.builtin/computation-analysis", "x": 0, "y": 0, "content": "return 1"},
        ], "edges": []}},
        "outputs": [],
    }), headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _listed(client, token, pid) -> str:
    resp = client.get("/api/projects", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return next(p for p in resp.get_json() if p["id"] == pid)["updated_at"]


def test_a_change_the_doc_writes_moves_the_updated_time(client, user_and_token, tmp_curio):
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    pid = _create(client, token)
    before = _listed(client, token, pid)
    time.sleep(0.05)

    ukey = _user_dir_key(user)
    spec = dataflow_docs.live(ukey, pid)
    spec["dataflow"]["nodes"][0]["content"] = "return 2"
    dataflow_docs.write(ukey, pid, spec, dataflow_docs.person(ukey, "edit"))

    after = _listed(client, token, pid)
    assert datetime.fromisoformat(after) > datetime.fromisoformat(before), (before, after)


def test_opening_a_dataflow_writes_no_spec(client, user_and_token, tmp_curio):
    """So the spec's last write is a change's, never an open's."""
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    pid = _create(client, token)
    ukey = _user_dir_key(user)
    spec_file = storage.project_dir(ukey, pid) / storage.SPEC_FILE
    written, revision = spec_file.stat().st_mtime_ns, storage.spec_revision(ukey, pid)
    time.sleep(0.05)

    assert client.get(f"/api/projects/{pid}", headers=_auth(token)).status_code == 200
    assert client.get(f"/api/projects/{pid}/history", headers=_auth(token)).status_code == 200

    assert spec_file.stat().st_mtime_ns == written
    assert storage.spec_revision(ukey, pid) == revision
