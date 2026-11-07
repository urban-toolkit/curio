"""Solve's run of an invited editor's node reads the collections it loads as his Play does.

Solve runs each attempt it checks on a thread of its own
(``VerifiedRounds._validate_with``), where the collections the code loads were
looked up (``validation.validate_candidate``, ``resolve_spec_collections``).
alice's dataflow lists a collection of hers, and bob, an editor she invited,
solves a node that loads it. The lookup reads what her dataflow lists from her
store through the database (``DiscoveryService._the_owners_copy``), and that
thread had no app context, so the sandbox was sent no collection. The lookup
was also made under the dataflow's store, hers, so what bob's node derives
went to her media folder, while his Play and an agent's Run node write it to
his own.

The thread an attempt runs on must not ask the database at all: given a
context of the app, the attempts of a plan's nodes looked up every
``curio_load_data`` id their code named, several at once, and on the unit
suite's in-memory SQLite, one connection every thread shares, that crashed the
suite. The last two tests record each collection lookup by the thread that
makes it, in both Solves.

Every test imports what it tests inside itself, so a checkout without it fails
test by test.
"""
from __future__ import annotations

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_agent_queue import file_backed  # noqa: F401  (fixture)


def _bobs_solve_of_a_node_loading_alices_collection(client, db, user_and_token, tmp_path, monkeypatch):
    """bob's Solve this node, on alice's node that loads a collection her
    dataflow lists from her store, the sandbox stood in for: ``(alice, bob,
    the collection's id, what the sandbox was sent)``."""
    from utk_curio.backend.app.discovery.infrastructure import storage
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.tests.test_agents.test_editor_run_node_collections import BOB_TOKEN, _account
    from utk_curio.backend.tests.test_agents.test_verified_rounds import TestSolveNode
    from utk_curio.backend.tests.test_datasets.test_editor_datasets import REPO, SERVICE, _a_collection

    monkeypatch.setenv(storage.ENV_ROOT, str(REPO / "discovery"))
    alice, alice_token = user_and_token
    bob = _account(db, "bob", BOB_TOKEN)
    # Images a service gave alice: her store keeps their files in her media folder.
    collection = _a_collection(alice, tmp_path, source_id=SERVICE)
    solve = TestSolveNode()
    ctx = solve._setup(client, alice, alice_token, monkeypatch,
                       content=f'photos = curio_load_collection("{collection}")\nreturn photos')
    added = client.post(
        f"/api/dataflows/{ctx['pid']}/datasets/install",
        json={"datasetId": collection}, headers=_auth(alice_token),
    )
    assert added.status_code == 200, added.get_data(as_text=True)
    access.add_editor(alice, ctx["pid"], "bob")

    events = solve._solve_node(client, BOB_TOKEN, ctx)

    assert ctx["payloads"], f"bob's Solve never reached the sandbox: {events[-1]}"
    return alice, bob, collection, ctx["payloads"][0]


def test_an_editors_solve_sends_the_sandbox_a_collection_the_owners_dataflow_lists(
    client, db, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    from utk_curio.backend.app.discovery.application import cache_collection

    alice, _bob, collection, sent = _bobs_solve_of_a_node_loading_alices_collection(
        client, db, user_and_token, tmp_path, monkeypatch,
    )

    assert sent.get("collections") == {collection: {
        "kind": "audio",
        "objects": str(cache_collection.objects_dir(str(alice.id), collection, create=False)),
    }}, sent.get("collections")


def test_what_an_editors_solve_derives_goes_to_his_media_folder(
    client, db, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    alice, bob, _collection, sent = _bobs_solve_of_a_node_loading_alices_collection(
        client, db, user_and_token, tmp_path, monkeypatch,
    )

    assert sent.get("media_dir") == str(media_dirs.media_work_root(str(bob.id))), (
        f"bob's Solve derives into {sent.get('media_dir')}"
    )
    alices_media = media_dirs.media_work_root(str(alice.id))
    assert not alices_media.exists(), sorted(str(p) for p in alices_media.rglob("*"))


def _lookups_by_thread(monkeypatch) -> dict:
    """From now on, each lookup a collection takes is noted with where it
    was made: ``DiscoveryService.collection``, and the store lookup that
    reads a dataflow from the database (``InstalledDatasetRepository._dataflow_store``).
    ``on_an_attempt`` holds those made while an attempt runs
    (``validation.validate_candidate``, on the thread Solve runs it on),
    ``off_the_request`` those made on any thread but the test's, where the
    test client serves the request that starts the Solve; ``attempts``
    counts the attempts run."""
    import threading

    from utk_curio.backend.app.agents.domain import validation
    from utk_curio.backend.app.datasets.repositories.installed import InstalledDatasetRepository
    from utk_curio.backend.app.discovery.service import DiscoveryService

    running = threading.local()
    noted: dict = {"attempts": 0, "on_an_attempt": [], "off_the_request": []}
    validate = validation.validate_candidate
    dataflow_store = InstalledDatasetRepository._dataflow_store
    collection = DiscoveryService.collection

    def _note(lookup: str, name: str) -> None:
        if getattr(running, "attempt", False):
            noted["on_an_attempt"].append((lookup, name))
        if threading.current_thread() is not threading.main_thread():
            noted["off_the_request"].append((lookup, name))

    def _validating(*args, **kwargs):
        noted["attempts"] += 1
        running.attempt = True
        try:
            return validate(*args, **kwargs)
        finally:
            running.attempt = False

    def _dataflow_store(self, dataflow_id):
        _note("_dataflow_store", dataflow_id)
        return dataflow_store(self, dataflow_id)

    def _collection(self, dataset_id):
        _note("collection", dataset_id)
        return collection(self, dataset_id)

    monkeypatch.setattr(validation, "validate_candidate", _validating)
    monkeypatch.setattr(InstalledDatasetRepository, "_dataflow_store", _dataflow_store)
    monkeypatch.setattr(DiscoveryService, "collection", _collection)
    return noted


def test_an_editors_solve_asks_no_database_on_the_thread_an_attempt_runs_on(
    client, db, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """bob's Solve this node of alice's node: the lookup of her collection,
    which reads her dataflow from the database, is made before his attempt
    runs, never on its thread, and the attempt still loads it."""
    noted = _lookups_by_thread(monkeypatch)

    _alice, _bob, collection, sent = _bobs_solve_of_a_node_loading_alices_collection(
        client, db, user_and_token, tmp_path, monkeypatch,
    )

    assert noted["attempts"], "bob's Solve ran no attempt"
    assert noted["on_an_attempt"] == [], (
        f"bob's attempts looked collections up on their own thread: {noted['on_an_attempt']}"
    )
    assert set(sent.get("collections") or {}) == {collection}, sent.get("collections")


def test_a_plans_solve_looks_its_collections_up_once_when_it_starts(file_backed, tmp_path, monkeypatch):
    """The Dataflow Builder's Solve of a plan whose Data Loading node loads a
    collection of the account's and a table of its Data Catalog, both by id,
    and the computation it feeds. Every collection the dataflow's Data
    Catalog lists is looked up in the request that starts the Solve: no
    attempt looks one up on its own thread, and no thread of the Solve looks
    up an id that request read, the table's included. The loader's attempt
    still loads the collection. It runs on a file database, which gives each
    thread a connection of its own, as a server's does."""
    from utk_curio.backend.app.discovery.infrastructure import storage
    from utk_curio.backend.tests.test_agents.test_verified_rounds import TestVerifiedSolve
    from utk_curio.backend.tests.test_datasets.test_editor_datasets import REPO, _a_collection

    client, user, token = file_backed
    monkeypatch.setenv(storage.ENV_ROOT, str(REPO / "discovery"))
    # Recordings in a folder of the shipped storage source.
    collection = _a_collection(user, tmp_path)
    solve = TestVerifiedSolve()
    ctx = solve._setup(client, user, token, monkeypatch, dl_replies=[
        f'recordings = curio_load_collection("{collection}")\n'
        'heat = curio_load_data("{DATASET}")\n'
        "return heat"
    ])
    noted = _lookups_by_thread(monkeypatch)

    body = solve._solve(client, token, ctx)

    assert body["results"][ctx["load"]]["status"] == "solved", body["results"]
    assert noted["attempts"], "the Solve ran no attempt"
    assert noted["on_an_attempt"] == [], (
        f"the plan's attempts looked collections up on their own thread: {noted['on_an_attempt']}"
    )
    collection_lookups = [made for made in noted["off_the_request"] if made[0] == "collection"]
    assert collection_lookups == [], (
        f"the Solve's threads looked up ids the request that started it had read: {collection_lookups}"
    )
    loading = [payload for payload in ctx["exec_payloads"] if collection in payload["code"]]
    assert loading, "the loader never reached the sandbox"
    assert set(loading[0].get("collections") or {}) == {collection}, loading[0].get("collections")
