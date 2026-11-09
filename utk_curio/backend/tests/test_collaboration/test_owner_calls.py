"""A change made for an account rather than for one dataflow reaches each
dataflow's owner (``collaboration/owner_calls.py``).

Adding an agent, a package or a dataset to all projects, removing one from the
account, migrating dataset ids and making a dataflow are asked of whichever
backend process the request reached, and each writes dataflows any process may
own. The process that does not own a dataflow sends the change to its owner,
an internal call over 127.0.0.1 signed with the secret only the start's
backends hold, and the owner makes it through the dataflow's doc. Here the
owner is a server in the test that keeps each call it gets; the last tests
send such a call to this app as the owner.

Each test checks what the process did before it imports anything a checkout
without the internal calls lacks.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from types import SimpleNamespace

import pytest

from ._processes import as_process, owned_by, owner_of
from ._support import make_project, make_user
from .test_dataflow_docs import SPEC, room  # noqa: F401 - room is a fixture

#: The secret the start's backends show each other.
SECRET = "the start's own secret"
#: The header it travels in.
TOKEN_HEADER = "X-Curio-Backend-Token"

#: What the owner answers each change with, once made.
_ANSWERS = {
    "agents.install": {"agents": [], "installed": [], "required": []},
    "agents.uninstall": {"agents": [], "detached": []},
    "packages.detach": True,
    "packages.add": True,
    "datasets.install": {},
    "datasets.uninstall": {},
    "datasets.remove-references": True,
}


class _Owner:
    """The process that owns the dataflows, as another process reaches it: a
    WSGI app that keeps each internal call it gets and answers it as the owner
    does once it made the change."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = json.loads(environ["wsgi.input"].read(length) or b"{}")
        parts = environ.get("PATH_INFO", "").strip("/").split("/")
        operation = parts[-1]
        self.calls.append({
            "path": environ.get("PATH_INFO"), "operation": operation,
            "dataflow": parts[2] if len(parts) == 4 and parts[:2] == ["internal", "dataflows"] else None,
            "token": environ.get("HTTP_X_CURIO_BACKEND_TOKEN"), "body": body,
        })
        reply = json.dumps({"ok": True, "result": _ANSWERS.get(operation)}).encode()
        start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(reply)))])
        return [reply]

    def made(self, dataflow_id: str) -> list:
        """Each change sent for *dataflow_id*, in order: its operation and arguments."""
        return [(call["operation"], call["body"].get("arguments")) for call in self.calls
                if call["dataflow"] == dataflow_id]


@pytest.fixture()
def owner_elsewhere(doc_app, monkeypatch):
    """This process as the second of two backends; the first, which owns the
    dataflows the tests make, is a server on 127.0.0.1 at the port the
    launcher names for it."""
    from werkzeug.serving import make_server

    owner = _Owner()
    server = make_server("127.0.0.1", 0, owner, threaded=True)
    thread = threading.Thread(target=server.serve_forever, name="owner-process", daemon=True)
    thread.start()
    as_process(monkeypatch, 1)
    monkeypatch.setenv("CURIO_BACKEND_PORTS", f"{server.server_port},{server.server_port + 1}")
    monkeypatch.setenv("CURIO_BACKEND_TOKEN", SECRET)
    try:
        yield owner
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _an_account_with_a_dataflow(name: str, spec: dict | None = None):
    """An account and a dataflow of it that the first process owns:
    ``(user, its store's key, the dataflow's id)``."""
    from utk_curio.backend.app.projects import storage

    user, _session = make_user(name)
    key = str(user.id)
    project_id = make_project(user, owned_by(0))
    storage.write_spec(key, project_id, copy.deepcopy(spec or SPEC))
    return user, key, project_id


def _file(key: str, project_id: str) -> str:
    """The dataflow's spec file, by the digest of its bytes."""
    from utk_curio.backend.app.projects import storage

    return hashlib.sha256((storage.project_dir(key, project_id) / storage.SPEC_FILE).read_bytes()).hexdigest()


def _no_doc_here(project_id: str) -> None:
    from utk_curio.backend.app.collaboration import dataflow_docs

    assert dataflow_docs._open_entry(project_id) is None, "the process that does not own the dataflow opened its doc"


def _signed(owner: _Owner) -> None:
    assert owner.calls and {call["token"] for call in owner.calls} == {SECRET}, (
        f"a change reached the owner without the start's secret: {owner.calls}"
    )


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def test_an_agent_added_to_and_removed_from_all_projects_is_written_by_each_dataflows_owner(owner_elsewhere, doc_app):
    from utk_curio.backend.app.agents.application import lifecycle

    application, _socketio = doc_app
    user, key, project_id = _an_account_with_a_dataflow("erin")
    before = _file(key, project_id)
    coord = lifecycle.default_agent_coords()[0]

    with application.test_request_context():
        lifecycle.import_agent(key, coord, user=user)
        lifecycle.remove_import(key, coord, user=user)

    assert _file(key, project_id) == before, "the process that does not own the dataflow wrote it itself"
    _no_doc_here(project_id)
    assert owner_elsewhere.made(project_id) == [
        ("agents.install", {"coord": coord}),
        ("agents.uninstall", {"coord": coord}),
    ]
    _signed(owner_elsewhere)


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------

def test_a_package_removed_from_the_account_leaves_each_dataflow_by_its_owner(owner_elsewhere):
    from utk_curio.backend.app.packages.application import project_packages
    from utk_curio.backend.app.packages.domain.spec_packages import set_project_packages

    _user, key, project_id = _an_account_with_a_dataflow(
        "fay", set_project_packages(copy.deepcopy(SPEC), ["example.tools@1"]),
    )
    before = _file(key, project_id)

    detached = project_packages.detach_from_all_projects(key, "example.tools@1")

    assert _file(key, project_id) == before, "the process that does not own the dataflow wrote it itself"
    _no_doc_here(project_id)
    assert owner_elsewhere.made(project_id) == [("packages.detach", {"dir_name": "example.tools@1"})]
    assert detached == [project_id]
    _signed(owner_elsewhere)


def test_a_package_added_to_all_projects_reaches_each_dataflow_by_its_owner(owner_elsewhere, monkeypatch):
    from utk_curio.backend.app.packages.application import defaults_install, store_install

    monkeypatch.setattr(store_install, "_ensure_user_store_install", lambda _key, _dir_name: SimpleNamespace(
        packages=(), import_errors={}, installed=None, copied=False,
    ))
    user, key, project_id = _an_account_with_a_dataflow("gus")
    before = _file(key, project_id)

    added = defaults_install.install_to_defaults(user, "example.tools@1")

    assert _file(key, project_id) == before, "the process that does not own the dataflow wrote it itself"
    _no_doc_here(project_id)
    assert owner_elsewhere.made(project_id) == [("packages.add", {"added": ["example.tools@1"]})]
    assert added["projects"] == [{"id": project_id, "ok": True, "alreadyPresent": False}]
    _signed(owner_elsewhere)


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

def test_a_dataset_added_to_and_removed_from_all_projects_reaches_each_dataflow_by_its_owner(owner_elsewhere, doc_app):
    from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService

    application, _socketio = doc_app
    user, key, project_id = _an_account_with_a_dataflow("hal")
    before = _file(key, project_id)

    with application.test_request_context():
        service = DatasetCatalogService(user)
        added = service.install_dataset_to_defaults("imported.example.x1")
        removed = service.remove_dataset_from_defaults("imported.example.x1")

    assert _file(key, project_id) == before
    _no_doc_here(project_id)
    assert owner_elsewhere.made(project_id) == [
        ("datasets.install", {"user_id": user.id, "dataset_id": "imported.example.x1"}),
        ("datasets.uninstall", {"user_id": user.id, "dataset_id": "imported.example.x1",
                                "delete_orphaned_import": False}),
    ]
    assert added["projects"] == [{"id": project_id, "ok": True}], added
    assert removed["projects"] == [{"id": project_id, "ok": True}], removed
    _signed(owner_elsewhere)


def test_a_dataset_deleted_from_the_account_leaves_each_dataflow_by_its_owner(owner_elsewhere, doc_app):
    from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService

    application, _socketio = doc_app
    spec = copy.deepcopy(SPEC)
    spec["dataflow"]["datasets"] = [
        {"datasetId": "imported.example.x1", "dirName": "imported.example.x1@1", "origin": "imported"},
    ]
    user, key, project_id = _an_account_with_a_dataflow("ivy", spec)
    before = _file(key, project_id)

    with application.test_request_context():
        deleted = DatasetCatalogService(user).delete_dataset("imported.example.x1")

    assert _file(key, project_id) == before, "the process that does not own the dataflow wrote it itself"
    _no_doc_here(project_id)
    assert owner_elsewhere.made(project_id) == [
        ("datasets.remove-references", {"user_id": user.id, "dataset_id": "imported.example.x1"}),
    ]
    assert deleted["removedFrom"] == [project_id], deleted
    _signed(owner_elsewhere)


def test_a_dataset_ids_migration_renames_each_dataflows_ref_by_its_owner(owner_elsewhere):
    from utk_curio.backend.app.datasets.application import migrations
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import write_legacy_computed_dir

    user, key, project_id = _an_account_with_a_dataflow("jo")
    legacy_id = write_legacy_computed_dir(key, "loader")
    spec = copy.deepcopy(SPEC)
    spec["dataflow"]["datasets"] = [{"datasetId": legacy_id, "dirName": f"{legacy_id}@1",
                                     "origin": "computed", "producerNodeId": "loader"}]
    from utk_curio.backend.app.projects import storage

    storage.write_spec(key, project_id, spec)
    before = _file(key, project_id)

    migrations.migrate_computed_dataset_ids(key)

    new_id = computed_dataset_id("loader", project_id)
    assert _file(key, project_id) == before, "the process that does not own the dataflow wrote it itself"
    _no_doc_here(project_id)
    assert owner_elsewhere.made(project_id) == [
        ("datasets.rewrite-ref", {"old_id": legacy_id, "new_id": new_id, "new_dir_name": f"{new_id}@1"}),
    ]
    _signed(owner_elsewhere)


# ---------------------------------------------------------------------------
# A dataflow made in a process that does not own it
# ---------------------------------------------------------------------------

#: A new dataflow whose create drops a dataset ref of a chart, which the create
#: then writes again.
_MADE = {
    "dataflow": {
        "name": "Made elsewhere",
        "nodes": [{"id": "chart", "type": "curio.builtin/vis-vega", "x": 0, "y": 0, "content": "{}",
                   "out": "DEFAULT", "in": "DATAFRAME", "goal": "", "metadata": {"keywords": []}}],
        "edges": [],
        "datasets": [{"datasetId": "computed.made.chart", "dirName": "computed.made.chart@1",
                      "origin": "computed", "producerNodeId": "chart"}],
    },
}


def test_a_dataflow_made_where_it_does_not_belong_is_written_on_by_its_owner(owner_elsewhere, doc_app, monkeypatch, caplog):
    """File > New in the process that does not own the new dataflow's id:
    the create writes its files there and keeps no doc, and the writes that
    follow it, the create's second write and the account's datasets for all
    projects, are made by the dataflow's owner."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.datasets import defaults as dataset_defaults
    from utk_curio.backend.app.projects import models as project_models

    application, _socketio = doc_app
    user, session = make_user("kai")
    made = owned_by(0)
    monkeypatch.setattr(project_models, "uuid4", lambda: uuid.UUID(made))
    dataset_defaults.add_to_dataset_defaults(str(user.id), "imported.example.x1")

    reply = application.test_client().post(
        "/api/projects", json={"name": "Made elsewhere", "spec": copy.deepcopy(_MADE), "outputs": []},
        headers={"Authorization": f"Bearer {session.token}"},
    )

    assert reply.status_code == 201, reply.get_data(as_text=True)
    assert reply.get_json()["id"] == made
    assert dataflow_docs._open_entry(made) is None, "the process that does not own the new dataflow opened its doc"
    assert [operation for operation, _arguments in owner_elsewhere.made(made)] == [
        "projects.write-created", "datasets.install",
    ]
    written = owner_elsewhere.made(made)[0][1]
    assert written["spec"]["dataflow"]["datasets"] == [], "the create's second write is not the one it makes"
    assert any("[owner-guard]" in record.getMessage() and "create" in record.getMessage() and made in record.getMessage()
               for record in caplog.records), caplog.text
    _signed(owner_elsewhere)


# ---------------------------------------------------------------------------
# The owner's side of a call
# ---------------------------------------------------------------------------

def test_the_owner_makes_a_change_another_process_sends_and_its_tabs_get_it(room, monkeypatch):
    """As the dataflow's owner, the app makes a change another process sends,
    signed with the start's secret, through the dataflow's doc: alice's tab
    gets it. A call without the secret, or with another, is refused; and a
    process that does not own the dataflow refuses the change rather than
    send it on."""
    from utk_curio.backend.app.projects import storage

    spec = copy.deepcopy(SPEC)
    spec["dataflow"]["datasets"] = [{"datasetId": "computed.loader", "dirName": "computed.loader@1",
                                     "origin": "computed", "producerNodeId": "loader"}]
    storage.write_spec(room.owner_key, room.project_id, spec)
    owner = owner_of(room.project_id)
    as_process(monkeypatch, owner)
    monkeypatch.setenv("CURIO_BACKEND_TOKEN", SECRET)
    alice = room.tab("alice")
    assert alice.sync()["ok"] is True
    client = room.application.test_client()
    path = f"/internal/dataflows/{room.project_id}/datasets.rewrite-ref"
    body = {"account": room.owner_key, "arguments": {
        "old_id": "computed.loader", "new_id": "computed.renamed.loader",
        "new_dir_name": "computed.renamed.loader@1",
    }}

    unsigned = client.post(path, json=body)
    wrong = client.post(path, json=body, headers={TOKEN_HEADER: "another secret"})
    made = client.post(path, json=body, headers={TOKEN_HEADER: SECRET})

    assert made.status_code == 200 and made.get_json()["ok"] is True, made.get_data(as_text=True)
    assert unsigned.status_code == 403 and wrong.status_code == 403, (unsigned.status_code, wrong.status_code)
    assert alice.dataflow()["datasets"][0]["datasetId"] == "computed.renamed.loader", "the owner's tab missed the change"
    assert room.on_disk()["dataflow"]["datasets"][0]["datasetId"] == "computed.renamed.loader"
    as_process(monkeypatch, 1 - owner)
    misrouted = client.post(path, json=body, headers={TOKEN_HEADER: SECRET})
    assert misrouted.status_code == 421, misrouted.get_data(as_text=True)
    assert room.project_id in misrouted.get_json()["error"]


def test_every_change_a_process_sends_is_one_its_owner_knows(doc_app):
    """Each change an account-level writer sends is registered by the time
    the app serves, in every process, so an owner never answers that it does
    not know one."""
    from utk_curio.backend.app.collaboration import owner_calls

    assert set(owner_calls.operations()) >= {
        "agents.install", "agents.uninstall", "packages.detach", "packages.add",
        "datasets.install", "datasets.uninstall", "datasets.remove-references", "datasets.rewrite-ref",
        "datasets.stamp-published", "datasets.clear-published", "projects.write-created",
    }, sorted(owner_calls.operations())


def test_a_change_sent_while_holding_its_dataflows_spec_lock_is_refused_not_left_waiting(owner_elsewhere):
    """The owner takes the dataflow's spec lock, which works across processes,
    to make a change; one sent while this thread holds that lock would wait
    for it until the call gave up, so it is refused at once."""
    from utk_curio.backend.app.agents.application import lifecycle
    from utk_curio.backend.app.collaboration import owner_calls
    from utk_curio.backend.app.projects import storage

    _user, key, project_id = _an_account_with_a_dataflow("lou")

    with storage.spec_write_lock(key, project_id):
        with pytest.raises(Exception) as refused:
            owner_calls.run(lifecycle.install_in_project, key, project_id, coord="agent.curio.node-builder@1")

    assert "spec lock" in str(refused.value), refused.value
    assert owner_elsewhere.calls == []
