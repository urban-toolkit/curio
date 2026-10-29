"""Every backend writer of a dataflow goes through its doc
(``collaboration/dataflow_docs.py``), so only the doc writes a dataflow and a
tab in the dataflow's room gets each change as it is made.

A writer gets the dataflow as it is now, changes it, and its write is one
transaction that applies only what it changed: a node's code lands only where
the doc still holds the code the writer read, and the writer is told when it
does not. The agents' sections are written beside the doc. The whole-dataflow
PUT is the one write that makes the doc match what it sends, a dataflow made
anew starts through a create, and a tab bound to the doc saves its history
alone. Readers of an open dataflow read the doc, never a file behind it.

The tabs are pycrdt docs syncing over a Flask-SocketIO test client
(``_ydoc_client.py``); each asserts what reaches it through its own socket.
"""

from __future__ import annotations

import ast
import copy
import shutil
import types
from pathlib import Path

import pytest

from .test_dataflow_docs import SPEC, _code, _imported_entries, _type, room  # noqa: F401 - room is a fixture

#: The agent the writers here write as.
BUILDER = "agent.curio.node-builder@1"


def _auth(room, name: str = "alice") -> dict:
    return {"Authorization": f"Bearer {room.tokens[name]}", "Content-Type": "application/json"}


def _with_attachments(room) -> None:
    """alice's dataflow with two of the Node Builder's attachments on it."""
    from utk_curio.backend.app.projects import storage

    spec = copy.deepcopy(SPEC)
    spec["dataflow"]["agents"] = [BUILDER]
    spec["dataflow"]["agentAttachments"] = [
        {"attachmentId": "t1", "coord": BUILDER, "target": {"kind": "node", "targetId": "loader"},
         "sessionId": "s1", "revision": 1},
        {"attachmentId": "t2", "coord": BUILDER, "target": {"kind": "node", "targetId": "chart"},
         "sessionId": "s2", "revision": 1},
    ]
    storage.write_spec(room.owner_key, room.project_id, spec)


def _titles(room) -> dict:
    return {a["attachmentId"]: a.get("title") for a in room.on_disk()["dataflow"]["agentAttachments"]}


def test_only_the_doc_writes_a_dataflow():
    """``storage.write_spec`` writes ``spec.trill.json``: nothing in Curio but
    the doc calls it, names it or imports it."""
    package = Path(__file__).resolve().parents[3]
    found = []
    for path in sorted(package.rglob("*.py")):
        rel = path.relative_to(package).as_posix()
        if (
            "/tests/" in f"/{rel}" or "node_modules" in path.parts
            or rel == "backend/app/collaboration/dataflow_docs.py"
        ):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                (isinstance(node, ast.Attribute) and node.attr == "write_spec")
                or (isinstance(node, ast.Name) and node.id == "write_spec")
                or (isinstance(node, ast.ImportFrom) and any(alias.name == "write_spec" for alias in node.names))
            ):
                found.append(f"{rel}:{node.lineno}")
    assert found == [], f"a dataflow is written outside its doc: {found}"


def test_a_writer_changes_only_what_it_changed_and_a_tab_gets_it(room):
    """A writer reads the dataflow, works, then writes: the code it wrote for
    a node lands only where the node still holds the code it read. alice typed
    in the loader meanwhile, so her code stays and the writer is told; its
    other changes reach her tab, from a transaction its actor is the origin
    of, and the file has them at once."""
    from utk_curio.backend.app.collaboration.dataflow_docs import by_agent, live, write

    from ._ydoc_client import Origins

    alice = room.tab("alice")
    alice.sync()
    spec = live(room.owner_key, room.project_id)
    alice.edit(_type("# alice\n"))
    loader, chart = spec["dataflow"]["nodes"]
    loader["content"] = "y = 2\n"
    chart["content"] = '{"mark": "bar"}'
    spec["dataflow"]["name"] = "Written"
    origins = Origins(room.project_id)
    actor = by_agent(BUILDER, room.owner_key, "solve")
    told: list = []

    written = write(room.owner_key, room.project_id, spec, actor, on_refused=told.extend)

    assert written.refused == ("loader",) and told == ["loader"], written
    seen = alice.dataflow()
    assert _code(seen) == "# alice\nx = 1\n", "the writer's code replaced what alice typed"
    assert _code(seen, "chart") == '{"mark": "bar"}' and seen["name"] == "Written"
    assert origins.seen and set(origins.seen) == {actor}, origins.seen
    on_disk = room.on_disk()
    assert _code(on_disk["dataflow"]) == "# alice\nx = 1\n" and on_disk["dataflow"]["name"] == "Written"
    assert on_disk["dataflow"]["agents"] == SPEC["dataflow"]["agents"]
    assert _imported_entries(room) == len(SPEC["nodeProvenance"]["loader"]), "the write touched the history"


def test_a_writer_writes_the_spec_it_was_handed_and_nothing_when_it_changed_nothing(room):
    """What a writer hands back is the spec it was handed, which knows what it
    read; a copy is refused rather than written over what changed meanwhile.
    A spec handed back unchanged writes nothing."""
    from utk_curio.backend.app.collaboration.dataflow_docs import live, person, write

    spec = live(room.owner_key, room.project_id)
    before = room.revision()
    assert write(room.owner_key, room.project_id, spec, person(room.owner_key, "save")).wrote is False
    assert room.revision() == before
    with pytest.raises(TypeError):
        write(room.owner_key, room.project_id, dict(spec), person(room.owner_key, "save"))


def test_the_agents_sections_are_written_beside_the_doc_one_attachment_at_a_time(room):
    """Two writers each rename their own attachment from what they both read:
    both names land, and a tab in the room gets none of it, since the agents'
    sections never enter the doc."""
    from utk_curio.backend.app.collaboration.dataflow_docs import live, person, write

    _with_attachments(room)
    alice = room.tab("alice")
    alice.sync()
    first, second = live(room.owner_key, room.project_id), live(room.owner_key, room.project_id)
    first["dataflow"]["agentAttachments"][0]["title"] = "First"
    second["dataflow"]["agentAttachments"][1]["title"] = "Second"

    write(room.owner_key, room.project_id, first, person(room.owner_key, "attachment"))
    write(room.owner_key, room.project_id, second, person(room.owner_key, "attachment"))

    assert _titles(room) == {"t1": "First", "t2": "Second"}
    alice.pump()
    assert b"First" not in alice.doc.get_update() and b"Second" not in alice.doc.get_update()


def test_an_attachment_write_keeps_what_a_tab_wrote_while_it_worked(room, monkeypatch):
    """A rename of an attachment is read, then written. alice's code reached
    the file while it ran (the doc wrote it): the rename writes the agents'
    sections only, so her code stays in the file and in the doc."""
    from utk_curio.backend.app.agents.application import attachment_management, attachments

    _with_attachments(room)
    alice = room.tab("alice")
    alice.sync()
    set_title = attachments.set_title

    def renamed_while_alice_typed(spec, attachment_id, title, *, edited):
        alice.edit(_type("# alice\n"))
        assert room.docs.flush(room.project_id) is True
        return set_title(spec, attachment_id, title, edited=edited)

    monkeypatch.setattr(attachments, "set_title", renamed_while_alice_typed)

    attachment_management.update_attachment_title(room.owner_key, room.project_id, "t1", "Renamed")

    on_disk = room.on_disk()["dataflow"]
    assert _titles(room)["t1"] == "Renamed"
    assert _code(on_disk) == "# alice\nx = 1\n", "the rename wrote back the dataflow it read"
    assert _code(room.live()["dataflow"]) == "# alice\nx = 1\n"


def test_a_title_written_after_its_dataflow_was_deleted_brings_back_no_folder(room, monkeypatch):
    """A conversation's title is written once its model call answers. A
    dataflow deleted meanwhile stays deleted: no write brings its folder back."""
    from utk_curio.backend.app.agents.application import attachments
    from utk_curio.backend.app.agents.application.turns import titles

    _with_attachments(room)
    set_title = attachments.set_title
    calls = []

    def deleted_meanwhile(spec, attachment_id, title, *, edited):
        calls.append(title)
        shutil.rmtree(room.folder())
        return set_title(spec, attachment_id, title, edited=edited)

    monkeypatch.setattr(attachments, "set_title", deleted_meanwhile)
    monkeypatch.setattr(titles, "_turn_text", lambda config, messages, **kwargs: "Parks near water")

    titles._generate_conversation_title(
        room.owner_key, room.project_id, "t1", "map the parks", types.SimpleNamespace(config_id=None),
    )

    assert calls == ["Parks near water"], "the title was never set"
    assert not room.folder().exists(), "the title's write brought the deleted dataflow's folder back"


def test_a_dataset_install_reaches_a_tab_in_the_room(room):
    """Installing a dataset into the dataflow writes its ref through the doc:
    alice's tab gets it, from a transaction named after who installed it."""
    from utk_curio.backend.app.collaboration.dataflow_docs import Actor
    from utk_curio.backend.app.datasets.repositories.installed import InstalledDatasetRepository

    from ._ydoc_client import Origins

    alice = room.tab("alice")
    alice.sync()
    origins = Origins(room.project_id, "dataflow")
    ref = {"datasetId": "data.utk.parks", "dirName": "data.utk.parks@1", "origin": "imported"}

    InstalledDatasetRepository(room.users["alice"]).mutate_refs(room.project_id, lambda refs: [*refs, ref])

    assert alice.dataflow().get("datasets") == [ref], "the install never reached the tab"
    assert [origin.by for origin in origins.seen if isinstance(origin, Actor)] == [room.owner_key]
    assert room.on_disk()["dataflow"]["datasets"] == [ref]


def test_the_whole_dataflow_put_makes_the_doc_match_it_for_every_tab(room):
    """The PUT (scripts, tests, the Projects page) is the one write that is
    not a writer's change: its transaction makes the doc match the dataflow it
    sends, and every tab in the room gets it."""
    alice, bob = room.tab("alice"), room.tab("bob")
    alice.sync()
    bob.sync()
    sent = room.on_disk()
    sent["dataflow"]["name"] = "Put"
    sent["dataflow"]["nodes"][1]["content"] = '{"mark": "point"}'

    resp = room.application.test_client().put(
        f"/api/projects/{room.project_id}", json={"spec": sent}, headers=_auth(room),
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    for tab in (alice, bob):
        seen = tab.dataflow()
        assert seen["name"] == "Put" and _code(seen, "chart") == '{"mark": "point"}', "a tab missed the PUT"
    assert room.on_disk()["dataflow"]["name"] == "Put"


def test_a_create_makes_an_open_doc_match_it_and_a_closed_one_start_anew(room):
    """A dataflow made anew (an example's shipped copy written over the one it
    replaces): a doc open with a tab becomes it, as the same doc; one not open
    is built anew from it, with a new id, when a tab next opens it."""
    from utk_curio.backend.app.collaboration.dataflow_docs import by_curio, create

    alice = room.tab("alice")
    alice.sync()
    doc_id = alice.doc_id
    seeded = copy.deepcopy(SPEC)
    seeded["dataflow"]["name"] = "Seeded"

    create(room.owner_key, room.project_id, seeded, by_curio(room.owner_key, "seed"))

    assert alice.dataflow()["name"] == "Seeded" and room.docs.doc_id_of(room.project_id) == doc_id
    room.docs.reset_for_tests()
    seeded["dataflow"]["name"] = "Seeded again"
    create(room.owner_key, room.project_id, seeded, by_curio(room.owner_key, "seed"))
    fresh = room.tab("alice")
    assert fresh.sync()["docId"] != doc_id, "the create kept the doc it replaces"
    assert fresh.dataflow()["name"] == "Seeded again"


def test_a_save_that_sends_no_dataflow_writes_only_the_docs_change_and_reads_no_history(room):
    """A tab bound to the doc saves its outputs, never the dataflow: the doc's
    change is written first and the dataflow's revision moves for it alone,
    and the doc keeps what alice typed. A history such a save still carries,
    as a tab of an earlier Curio sends it, is not read: the dataflow's points
    are its history (``collaboration/history.py``)."""
    from utk_curio.backend.app.projects import storage

    alice = room.tab("alice")
    alice.sync()
    alice.edit(_type("# typed\n"))
    before = room.revision()
    history = {"nodeProvenance": {"loader": [{"id": "v1"}, {"id": "v2"}]}}

    resp = room.application.test_client().put(
        f"/api/projects/{room.project_id}", json={"history": history, "outputs": []}, headers=_auth(room),
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    answered = resp.get_json()["spec"]
    assert _code(answered["dataflow"]) == "# typed\nx = 1\n", "the save answered with a dataflow behind the doc"
    assert not set(answered) & set(storage.HISTORY_KEYS), "the save answered with history sections"
    assert storage.history_sections(room.owner_key, room.project_id) == {}, "the history was written beside the spec"
    assert _imported_entries(room) == len(SPEC["nodeProvenance"]["loader"]), "the save changed the history"
    on_disk = room.on_disk()
    assert _code(on_disk["dataflow"]) == "# typed\nx = 1\n"
    assert room.revision() == before + 1, "the save wrote the spec beyond the doc's own change"
    assert _code(alice.dataflow()) == "# typed\nx = 1\n"
    assert _code(room.live()["dataflow"]) == "# typed\nx = 1\n"


def test_a_load_reads_an_edit_the_doc_holds_and_has_not_written(room):
    alice = room.tab("alice")
    alice.sync()
    alice.edit(_type("# typed\n"))
    assert _code(room.on_disk()["dataflow"]) == "x = 1\n", "the doc wrote the change already"

    resp = room.application.test_client().get(f"/api/projects/{room.project_id}", headers=_auth(room))

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert _code(resp.get_json()["spec"]["dataflow"]) == "# typed\nx = 1\n", "the load read a file behind the doc"


def test_a_server_runs_start_reads_an_edit_the_doc_holds_and_has_not_written(room, monkeypatch):
    from utk_curio.backend.app.execution import run_engine
    from utk_curio.backend.app.runs import service as runs_service

    alice = room.tab("alice")
    alice.sync()
    alice.edit(_type("# typed\n"))
    planned = []

    def recorded(spec, **kwargs):
        planned.append(spec)
        raise run_engine.PlanError("recorded")

    monkeypatch.setattr(run_engine, "plan_run", recorded)
    with pytest.raises(runs_service.RunError):
        runs_service.start_run(room.users["alice"], room.tokens["alice"], room.project_id, target_node_id="loader")

    assert planned, "the run never planned"
    assert _code(planned[0]["dataflow"]) == "# typed\nx = 1\n", "the run started from a file behind the doc"
