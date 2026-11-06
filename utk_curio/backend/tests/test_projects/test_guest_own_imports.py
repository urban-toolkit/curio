"""What one hosted guest adds to the Data Catalog is theirs alone.

Every hosted guest (a guest on a Curio started with ``--deploy``) signs in to
the one shared guest account, whose dataset store every guest reads. A file a
hosted guest imports, and a dataset they download from the Discovery Catalog,
are kept in that store for them alone until the server starts again, as a
node's output they add to an example is (``projects/visitor_copies.py``).
These tests sign two visitors, A and B, in to that account, as
``test_guest_copy_leaks.py`` does:

- A imports a file and downloads a dataset from a storage source, a folder
  read from disk with no socket: A finds both everywhere, B nowhere, by
  listing or by id, and both go when the server starts;
- an agent's run for A reads A's upload and A's added output by id, on the
  server's request and on a job's own thread; one for B reads neither;
- without ``--deploy`` the shared guest is the one local user, whose uploads
  and downloads are the account's.
"""
from __future__ import annotations

import io
import json

from utk_curio.backend import config
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.tests.test_agents.test_run_node_datasets import (
    ATTACHMENT,
    COMPUTATION,
    _loader,
    _run_through_the_node_after,
)
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_discovery.conftest import (  # noqa: F401  (fixtures)
    _reset_discovery_process_state,
    discovery_dir,
    storage_folder,
    storage_source,
    workers_finish_first,
)
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (  # noqa: F401  (fixtures)
    VISITOR_A,
    VISITOR_B,
    _copy_of,
    _digests,
    _in_the_dataflow,
    _play,
    app,
    example,
    sandbox,
)
from utk_curio.backend.tests.test_projects.test_guest_store_leaks import _listing, _listings_of, _live

#: The storage source of ``storage_source``, and its row of one table.
SOURCE = "source.example.folder@1"
STATIONS = "stations"


def _import(client, token: str) -> str:
    """The id of the file the visitor signed in as *token* imports, as the
    Data Catalog's Import does."""
    resp = client.post(
        "/api/datasets/import", headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(b"tree,height\noak,12\n"), "trees.csv")}, content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _download(client, token: str) -> str:
    """The id of the dataset the visitor signed in as *token* adds to the Data
    Catalog from the storage source's stations row, once its download's
    worker has ended (``workers_finish_first``)."""
    resp = client.post(f"/api/discovery/sources/{SOURCE}/resources/{STATIONS}/acquire",
                       headers=auth_headers(token), json={})
    assert resp.status_code in (200, 202), resp.get_data(as_text=True)
    body = resp.get_json()
    if "jobId" not in body:
        return body["dataset"]["id"]
    job = client.get(f"/api/discovery/jobs/{body['jobId']}", headers=auth_headers(token)).get_json()
    assert job["status"] == "completed", job
    return job["dataset"]["id"]


def _listed(client, token: str, query: dict) -> set[str]:
    return {item["id"] for item in _listing(client, token, **query)}


def test_a_hosted_guests_uploads_and_downloads_are_theirs_alone(client, example, storage_source, monkeypatch):
    from utk_curio.backend.app.projects import visitor_copies

    workers_finish_first(monkeypatch)
    # Each visitor's Data Catalog lists the store once, as their canvases do,
    # before anything is measured.
    for token in (VISITOR_A, VISITOR_B):
        _listing(client, token, dataflowId=example)
    before = _digests(example)

    uploaded, downloaded = _import(client, VISITOR_A), _download(client, VISITOR_A)
    mine = {uploaded, downloaded}

    # A finds both in every listing and by id.
    for query in _listings_of(example):
        assert mine <= _listed(client, VISITOR_A, query), query
    for dataset_id in mine:
        shown = client.get(f"/api/datasets/{dataset_id}", headers=auth_headers(VISITOR_A))
        assert shown.status_code == 200, shown.get_data(as_text=True)
    # B finds neither: not listed, and not read, previewed, downloaded or added
    # to B's dataflow by id.
    for query in _listings_of(example):
        assert not mine & _listed(client, VISITOR_B, query), query
    for dataset_id in mine:
        for read in (f"/api/datasets/{dataset_id}", f"/api/datasets/{dataset_id}/preview",
                     f"/api/datasets/{dataset_id}/download"):
            resp = client.get(read, query_string={"dataflowId": example}, headers=auth_headers(VISITOR_B))
            assert resp.status_code == 404, (read, resp.status_code)
        added = client.post(f"/api/dataflows/{example}/datasets/install", data=json.dumps({"datasetId": dataset_id}),
                            headers=auth_headers(VISITOR_B))
        assert added.status_code == 404, added.get_data(as_text=True)
    # B's download of the same row is B's own.
    theirs = _download(client, VISITOR_B)
    assert theirs not in mine
    assert theirs not in _listed(client, VISITOR_A, {})

    # A's upload added to the example goes in A's copy of it alone.
    added = client.post(f"/api/dataflows/{example}/datasets/install", data=json.dumps({"datasetId": uploaded}),
                        headers=auth_headers(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)
    assert uploaded in _in_the_dataflow(client, VISITOR_A, example)
    assert uploaded not in _in_the_dataflow(client, VISITOR_B, example)

    # They go when the server starts, and the store and the example are as
    # they were.
    visitor_copies.drop_all()
    for token in (VISITOR_A, VISITOR_B):
        assert not (mine | {theirs}) & _listed(client, token, {}), token
    assert _digests(example) == before


def _with_a_loader(example: str, *dataset_ids: str) -> None:
    """The example loads *dataset_ids*: a Data Loading node whose code names
    them, and a Python node after it with an agent's chat attached, as a chat
    that runs it has one. Written before any visitor's first change makes
    their copy of the example, so each copy starts from it."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    code = "".join(f'd{i} = curio_load_data("{d}")\n' for i, d in enumerate(dataset_ids)) + "return d0\n"
    with dataflow_docs.writing(GUEST_KEY, example, dataflow_docs.by_curio(GUEST_KEY, "test")) as spec:
        dataflow = spec["dataflow"]
        dataflow["nodes"] = [*dataflow["nodes"], _loader(code), {
            "id": "after", "type": COMPUTATION, "content": "return input_0\n",
            "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {},
        }]
        dataflow["edges"] = [*dataflow["edges"], {"id": "reactflow__edge-loadout-afterin",
                                                  "source": "load", "target": "after"}]
        dataflow["agentAttachments"] = [{
            "attachmentId": ATTACHMENT, "coord": "agent.curio.node-builder@1",
            "target": {"kind": "node", "targetId": "after"},
        }]


def _a_upload_and_an_added_output(client, example: str, sandbox) -> tuple[str, str]:
    """A's upload, and the output of the example's node a that A adds to the
    example as the Data Catalog lists it, each by id. The example loads both
    (:func:`_with_a_loader`)."""
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    uploaded = _import(client, VISITOR_A)
    output = computed_dataset_id("a", _copy_of(VISITOR_A, example))
    _with_a_loader(example, uploaded, output)
    made = sandbox["artifacts"]["a"]
    _play(client, VISITOR_A, example, "a")
    live = next(item for item in _listing(client, VISITOR_A, dataflowId=example, liveOutputs=_live("a", made))
                if item.get("producerNodeId") == "a")
    added = client.post(f"/api/dataflows/{example}/datasets/install",
                        data=json.dumps({"datasetId": live["id"], "sourceItem": live, "nodeTitle": "a"}),
                        headers=auth_headers(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)
    assert added.get_json()["id"] == output
    return uploaded, output


def test_an_agents_run_for_a_hosted_guest_reads_their_own_datasets_alone(client, example, sandbox, monkeypatch):
    uploaded, output = _a_upload_and_an_added_output(client, example, sandbox)

    # The run through the node after the loader, from the agent's chat.
    done, sent = _run_through_the_node_after(client, VISITOR_A, example, monkeypatch)
    assert done["order"] == ["load", "after"], done
    assert set(sent[0].get("dataset_paths") or {}) == {uploaded, output}, sent[0]

    done, sent = _run_through_the_node_after(client, VISITOR_B, example, monkeypatch)
    assert done["order"] == ["load", "after"], done
    assert not sent[0].get("dataset_paths"), sent[0]


def test_an_agents_job_for_a_hosted_guest_reads_their_own_datasets_on_its_thread(app, client, example, sandbox):
    """A Solve's job runs on a thread of its own, which holds no request: the
    paths of a dataset its code names after it started are read there
    (``grounding._session_dataset_paths``), for the visitor whose request
    started it."""
    from utk_curio.backend.app.agents.application.turns import grounding
    from utk_curio.backend.app.agents.infrastructure import agent_jobs
    from utk_curio.backend.app.users.models import User

    uploaded, output = _a_upload_and_an_added_output(client, example, sandbox)
    code = f'a = curio_load_data("{uploaded}")\nb = curio_load_data("{output}")\nreturn a\n'
    read: dict = {}

    def _reading(token: str):
        guest = User.query.filter_by(username=config.CURIO_SHARED_GUEST_USERNAME).one()
        read[token] = grounding._session_dataset_paths(_copy_of(token, example), guest, {}, [code])
        yield "done", {}

    for token in (VISITOR_A, VISITOR_B):
        with app.test_request_context(headers=auth_headers(token)):
            job = agent_jobs.start_job(
                user_key=GUEST_KEY, project_id=_copy_of(token, example), attachment_id=f"att-{token}",
                kind="solve-node", job_id=f"job-{token}", events=_reading(token),
            )
        job.thread.join(timeout=60)
        assert not job.thread.is_alive(), token

    assert set(read[VISITOR_A]) == {uploaded, output}, read
    assert read[VISITOR_B] == {}, read


def test_without_deploy_the_local_guests_uploads_and_downloads_are_the_accounts(
    client, example, storage_source, monkeypatch,
):
    """Without ``--deploy`` the shared guest is the one local user: whatever
    sign-in asks, it reads what the account holds, and a start keeps it."""
    from utk_curio.backend.app.projects import visitor_copies

    workers_finish_first(monkeypatch)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)

    held = {_import(client, VISITOR_A), _download(client, VISITOR_A)}

    visitor_copies.drop_all()
    for token in (VISITOR_A, VISITOR_B):
        assert held <= _listed(client, token, {}), token
