"""A dataflow's history lives beside its spec, not in it.

``spec.trill.json`` holds the dataflow. The two history sections a dataflow
carries from a file or an earlier Curio, each node's runs and edits
(``nodeProvenance``) and the dataflow's versions (``dataflowProvenance``, each
a whole copy of the dataflow), are kept in logs in the project's ``history/``
folder (``projects/storage.py``), and every reader of the storage gets the
whole document back. When the dataflow's doc first opens, they are imported as
its points (``collaboration/history.py``), which is its history from then on:
an edit writes the live dataflow and at most a point, no load carries the
history, and a copy keeps it only for those who may read it.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading

import pytest

from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.projects.seed import _repo_root
from utk_curio.backend.app.projects.services import _user_dir_key

REPO = _repo_root()
EXAMPLES = REPO / "docs" / "examples"
CROWN_HEIGHTS = EXAMPLES / "dataflows" / "crown-heights-1550-bedford-shadow.json"
CHICAGO_LOOP = EXAMPLES / "dataflows" / "chicago-loop-shadow-towers.json"
SMALL_EXAMPLE = EXAMPLES / "01-vega-lite-chained-transforms.json"
VALIDATOR = REPO / "scripts" / "validate_trill.py"
HISTORY = ("nodeProvenance", "dataflowProvenance")
KiB = 1024
#: What an edit to Crown Heights may write, with its 90 versions on record.
EDIT_BUDGET = 100 * KiB


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _text(doc) -> str:
    """A document as JSON text, members in their order: two documents with
    the same text are the same document, down to the order of every object."""
    return json.dumps(doc)


def _shipped() -> list:
    """Every dataflow Curio ships."""
    paths = sorted(EXAMPLES.glob("*.json")) + sorted((EXAMPLES / "dataflows").glob("*.json"))
    out = []
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("dataflow"), dict):
            out.append(path)
    return out


def _load_versions(spec: dict, start: int = 1_790_000_000_000) -> dict:
    """The versions a load records for a dataflow with no history, as
    ``useWorkflowOperations.recordLoadProvenance`` records them through
    ``TrillGenerator.addNewVersionProvenance``: one per node, then one per
    connection, each a whole copy of the dataflow as it stood, with its node
    in the graph and an edge from the version before."""
    dataflow = spec["dataflow"]
    nodes, edges = dataflow.get("nodes") or [], dataflow.get("edges") or []
    rest = {k: v for k, v in dataflow.items() if k not in ("nodes", "edges", "timestamp")}
    name = dataflow.get("name") or ""
    versions: dict = {}
    graph_nodes: list = []
    graph_edges: list = []
    latest = ""
    for step in range(len(nodes) + len(edges)):
        stamp = start + step + 1
        key = f"{name}_{stamp}"
        held_nodes = nodes[: step + 1] if step < len(nodes) else nodes
        held_edges = [] if step < len(nodes) else edges[: step - len(nodes) + 1]
        versions[key] = {"dataflow": {"nodes": held_nodes, "edges": held_edges, **rest, "timestamp": stamp}}
        graph_nodes.append({
            "id": key,
            "label": f"{name} ({stamp})",
            "timestamp": stamp,
            "preview": {
                "nodes": [
                    {"id": n.get("id"), "type": n.get("type"), "category": None, "x": n.get("x", 0),
                     "y": n.get("y", 0), "w": n.get("width"), "h": n.get("height")}
                    for n in held_nodes
                ],
                "edges": [{"source": e.get("source"), "target": e.get("target")} for e in held_edges],
            },
        })
        if latest:
            change = "Node added" if step < len(nodes) else "Connection added"
            graph_edges.append({"id": f"{latest}_to_{key}", "source": latest, "target": key, "label": change})
        latest = key
    return {
        "id": dataflow.get("provenance_id") or name,
        "latest": latest,
        "graph": {"id": dataflow.get("provenance_id") or name, "nodes": graph_nodes, "edges": graph_edges},
        "versions": versions,
    }


def _entry(entry_id: int, parent, code: str, **extra) -> dict:
    """One entry of a node's history as the canvas files it: a run, or an edit."""
    return {
        "id": entry_id, "parentId": parent, "code": code, "inputs": [], "outputs": [],
        "startTime": f"Oct 28 2026 10:{entry_id:02d}:00", "endTime": f"Oct 28 2026 10:{entry_id:02d}:01",
        **extra,
    }


def _runs(spec: dict) -> dict:
    """One run filed for each node, holding its code."""
    return {
        node["id"]: [_entry(index, None, node.get("content") or "", inputs=["DATAFRAME"], outputs=["DATAFRAME"])]
        for index, node in enumerate(spec["dataflow"].get("nodes") or [], start=1)
    }


def _with_history(spec: dict) -> dict:
    """*spec* as a save sends it once the dataflow was opened and run."""
    doc = json.loads(json.dumps(spec))
    doc["nodeProvenance"] = _runs(doc)
    doc["dataflowProvenance"] = _load_versions(doc)
    return doc


def _fixture() -> dict:
    """A dataflow whose history has every shape a saved one holds: runs and
    edits (one with the code it replaced), a key from before #448, a node
    with no entry yet, one since removed and a value that is no list, a
    version put back (``latest`` names an older one), a version id with its
    ``_2`` suffix, numbers with a fraction, text that is not ASCII, and
    members the schema leaves open."""
    name = "History fixture"
    nodes = [
        {"id": "load-1", "type": "curio.builtin/data-loading", "x": 0, "y": 0, "content": "return 1"},
        {"id": "py-2", "type": "curio.builtin/computation-analysis", "x": 320.5, "y": -40,
         "content": "return input_0 * 2  # métrica ✓"},
        {"id": "10", "type": "curio.builtin/computation-analysis", "x": 640, "y": 0, "content": ""},
    ]
    edges = [{"id": "e-1", "source": "load-1", "target": "py-2"}]
    dataflow = {"nodes": nodes, "edges": edges, "name": name, "task": "", "timestamp": 1790000000000,
                "provenance_id": name}

    def version(stamp: int, held_nodes: list, held_edges: list) -> dict:
        return {"dataflow": {"nodes": held_nodes, "edges": held_edges, "name": name, "task": "",
                             "timestamp": stamp, "provenance_id": name}}

    def preview(held_nodes: list) -> dict:
        return {"nodes": [{"id": n["id"], "type": n["type"], "category": "computation", "x": n["x"], "y": n["y"],
                           "w": None, "h": None} for n in held_nodes], "edges": []}

    first, second, third = f"{name}_1790000000001", f"{name}_1790000000002", f"{name}_1790000000002_2"
    return {
        "dataflow": dataflow,
        "nodeProvenance": {
            "py-2": [
                _entry(1, None, "return input_0"),
                _entry(2, 1, nodes[1]["content"], kind="edit", label="Node Builder", before="return input_0"),
            ],
            "loading@1-load-1": [_entry(3, None, "return 1", outputs=["DATAFRAME"])],
            "10": [],
            "removed-9": [_entry(4, None, "x = 1")],
            "stale": None,
        },
        "dataflowProvenance": {
            "id": name,
            "latest": second,
            "graph": {
                "id": name,
                "nodes": [
                    {"id": first, "label": f"{name} (1790000000001)", "timestamp": 1790000000001,
                     "preview": preview(nodes[:1])},
                    {"id": second, "label": f"{name} (1790000000002)", "timestamp": 1790000000002,
                     "preview": preview(nodes[:2])},
                    {"id": third, "label": f"{name} (1790000000002)", "timestamp": 1790000000002,
                     "preview": preview(nodes)},
                ],
                "edges": [
                    {"id": f"{first}_to_{second}", "source": first, "target": second, "label": "Node added"},
                    {"id": f"{second}_to_{third}", "source": second, "target": third, "label": "Node added"},
                ],
                "layout": {"zoom": 0.75},
            },
            "versions": {
                first: version(1790000000001, nodes[:1], []),
                second: version(1790000000002, nodes[:2], edges),
                third: version(1790000000002, nodes, edges),
            },
            "note": "a member the schema leaves open",
        },
    }


def _assert_split(folder, doc: dict) -> None:
    """The spec file on disk holds no history, and each section *doc* holds
    is in its log beside it."""
    on_disk = json.loads((folder / "spec.trill.json").read_text(encoding="utf-8"))
    held = [key for key in HISTORY if key in on_disk]
    assert not held, f"the spec file still holds {held}"
    for key in HISTORY:
        if key in doc:
            log = folder / storage.HISTORY_DIR / storage.HISTORY_FILES[key]
            assert log.is_file(), f"no log beside the spec holds {key}"


def _files(folder) -> dict:
    """Each file under *folder*, by its path there: its inode, size and bytes."""
    out = {}
    for path in folder.rglob("*"):
        if path.is_file():
            stat = path.stat()
            out[path.relative_to(folder).as_posix()] = (stat.st_ino, stat.st_size, path.read_bytes())
    return out


def _written(before: dict, after: dict) -> tuple:
    """The bytes a write put under a folder, and what it did to each file it
    changed: a file new or swapped in counts whole, one that grew in place its
    growth, and one rewritten in place whole."""
    total, how = 0, {}
    for name, (inode, size, data) in sorted(after.items()):
        old = before.get(name)
        if old == (inode, size, data):
            continue
        if old is None or old[0] != inode:
            total += size
            how[name] = f"written whole, {size} bytes"
        elif data.startswith(old[2]):
            total += size - old[1]
            how[name] = f"grew by {size - old[1]} bytes"
        else:
            total += size
            how[name] = f"rewritten in place, {size} bytes"
    return total, how


def _create(client, token, name: str, spec: dict) -> str:
    resp = client.post("/api/projects", data=json.dumps({"name": name, "spec": spec}), headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _get(client, token, project_id: str) -> dict:
    resp = client.get(f"/api/projects/{project_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["spec"]


def _put(client, token, project_id: str, body: dict) -> dict:
    resp = client.put(f"/api/projects/{project_id}", data=json.dumps(body), headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _opened(user_key: str, project_id: str) -> None:
    """Open the dataflow's doc, as a tab or a writer does: its first open
    imports the history it carries."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    with dataflow_docs._held(project_id, user_key):
        pass


def _imported(user_key: str, project_id: str) -> list:
    """The ids of the earlier versions the dataflow's points hold, in order."""
    from utk_curio.backend.app.collaboration import history

    return [point["id"] for point in history.points(user_key, project_id) if point["kind"] == "imported"]


def _assert_no_history_in_spec(folder) -> None:
    on_disk = json.loads((folder / "spec.trill.json").read_text(encoding="utf-8"))
    held = [key for key in HISTORY if key in on_disk]
    assert not held, f"the spec file still holds {held}"


# ---------------------------------------------------------------------------
# What a save writes
# ---------------------------------------------------------------------------

def test_an_edit_to_crown_heights_with_its_90_versions_writes_under_100_kib(client, user_and_token, tmp_curio):
    """Crown Heights saved with the 90 versions its first open recorded, each a
    whole copy of its 33 nodes and 57 connections, and a run of each node: its
    doc's first open imports them as its points. An edit after that sends the
    whole document again, as a page saves, and writes the live dataflow: no
    version again."""
    user, token = user_and_token
    user_key = _user_dir_key(user)
    first = _with_history(json.loads(CROWN_HEIGHTS.read_text(encoding="utf-8")))
    assert len(first["dataflowProvenance"]["versions"]) == 90
    project_id = _create(client, token, "Crown Heights", first)
    folder = storage.project_dir(user_key, project_id)
    _opened(user_key, project_id)
    assert _imported(user_key, project_id) == list(first["dataflowProvenance"]["versions"])

    loaded = _get(client, token, project_id)
    node = next(n for n in loaded["dataflow"]["nodes"] if isinstance(n.get("content"), str) and n["content"])
    node["content"] += "\n# an edit\n"
    before = _files(folder)
    _put(client, token, project_id, {"spec": loaded})
    wrote, how = _written(before, _files(folder))

    spec_size = (folder / "spec.trill.json").stat().st_size
    assert wrote < EDIT_BUDGET, (
        f"the edit wrote {wrote / KiB:.1f} KiB, the spec file being {spec_size / KiB:.1f} KiB: {how}"
    )
    _assert_no_history_in_spec(folder)
    after = _get(client, token, project_id)
    assert next(n for n in after["dataflow"]["nodes"] if n["id"] == node["id"])["content"] == node["content"]
    assert _imported(user_key, project_id) == list(first["dataflowProvenance"]["versions"]), (
        "the reopened dataflow's history is not the one saved"
    )


def test_later_changes_add_a_point_at_most_and_never_write_the_history_again(client, user_and_token, tmp_curio):
    """After its first open imported its history, each change adds at most one
    point to the dataflow's points, never writing them again, and one that
    makes no version writes nothing to the history: an edit, a node added (a
    version), a version put back (a version), a run (an entry), a rename and
    categories set from the Projects page, and a dataset write. The imported
    sections are never written again."""
    from utk_curio.backend.app.collaboration import history

    user, token = user_and_token
    user_key = _user_dir_key(user)
    project_id = _create(client, token, "Chicago Loop",
                         _with_history(json.loads(CHICAGO_LOOP.read_text(encoding="utf-8"))))
    folder = storage.project_dir(user_key, project_id)
    _opened(user_key, project_id)
    points = folder / storage.HISTORY_DIR / history.POINTS_FILE
    aside = folder / storage.HISTORY_DIR / storage.IMPORTED_DIR

    def files() -> dict:
        held = {path.name: (path.stat().st_ino, path.read_bytes()) for path in sorted(aside.iterdir())}
        assert sorted(held) == ["entries.jsonl", "versions.jsonl"], sorted(held)
        return {"points": (points.stat().st_ino, points.read_bytes()), **held}

    def no_point(step: str, change) -> None:
        before = files()
        change()
        assert files() == before, f"{step} wrote to the history"

    def one_point(step: str, change) -> None:
        before = files()
        change()
        after = files()
        inode, data = after["points"]
        assert inode == before["points"][0], f"{step} wrote the points again"
        assert data.startswith(before["points"][1]), f"{step} changed a point it was handed"
        added = data[len(before["points"][1]):].count(b"\n")
        assert added == 1, f"{step} added {added} points"
        assert {k: v for k, v in after.items() if k != "points"} == {k: v for k, v in before.items() if k != "points"}, (
            f"{step} wrote the imported history"
        )

    edited = _get(client, token, project_id)
    node = next(n for n in edited["dataflow"]["nodes"] if isinstance(n.get("content"), str) and n["content"])
    node["content"] += "\n# an edit\n"
    no_point("an edit", lambda: _put(client, token, project_id, {"spec": edited}))

    added = _get(client, token, project_id)
    copy = json.loads(json.dumps(node))
    copy["id"] = "added-node"
    added["dataflow"]["nodes"].append(copy)
    one_point("a node added", lambda: _put(client, token, project_id, {"spec": added}))

    oldest = _imported(user_key, project_id)[0]

    def put_back() -> None:
        resp = client.post(f"/api/projects/{project_id}/history/{oldest}/put-back", headers=_auth(token))
        assert resp.status_code == 200, resp.get_data(as_text=True)

    one_point("a version put back", put_back)

    def run() -> None:
        target = _get(client, token, project_id)["dataflow"]["nodes"][0]["id"]
        resp = client.post(f"/api/projects/{project_id}/history/nodes/{target}/runs", headers=_auth(token),
                           data=json.dumps({"code": "return input_0", "inputs": ["DATAFRAME"],
                                            "outputs": ["DATAFRAME"]}))
        assert resp.status_code == 201, resp.get_data(as_text=True)

    one_point("a run", run)

    no_point("a rename", lambda: _put(client, token, project_id, {"name": "Renamed"}))
    no_point(
        "categories set", lambda: _put(client, token, project_id, {"categories": {"city": ["Chicago"]}}),
    )
    no_point(
        "a dataset write", lambda: storage.mutate_dataflow_datasets(user_key, project_id, lambda refs: list(refs)),
    )


# ---------------------------------------------------------------------------
# What every reader gets
# ---------------------------------------------------------------------------

def _assert_reads_back(doc: dict) -> None:
    storage.write_spec("1", "history", doc)
    folder = storage.project_dir("1", "history")
    _assert_split(folder, doc)
    assert _text(storage.read_spec("1", "history")) == _text(doc)
    assert _text(storage.read_spec_in(folder)) == _text(doc)
    # A backend writer reads the document and writes it back with its change.
    storage.write_spec("1", "history", storage.read_spec("1", "history"))
    assert _text(storage.read_spec("1", "history")) == _text(doc)


@pytest.mark.parametrize("path", _shipped(), ids=lambda path: path.stem)
def test_a_shipped_dataflow_reads_back_with_its_history_as_it_was_written(path, tmp_curio):
    _assert_reads_back(_with_history(json.loads(path.read_text(encoding="utf-8"))))


def test_a_history_of_every_shape_reads_back_as_it_was_written(tmp_curio):
    _assert_reads_back(_fixture())


def test_loads_and_saves_carry_no_history_and_the_agents_read_the_imported_one(client, user_and_token, tmp_curio):
    """The owner's load, the shared link's load and a save's answer carry no
    history: the Provenance drawer reads it from its own routes, the owner's
    and the editors' alone. The agents' ``node.history.read`` reads the history
    the dataflow was saved with, imported as its points when the save opened
    its doc."""
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.projects.node_provenance import rekey_node_provenance

    user, token = user_and_token
    user_key = _user_dir_key(user)
    doc = _fixture()
    project_id = _create(client, token, "History fixture", doc)
    _assert_split(storage.project_dir(user_key, project_id), doc)

    loaded = _get(client, token, project_id)
    shared = client.get(f"/api/projects/{project_id}/shared").get_json()["spec"]
    answered = _put(client, token, project_id, {"spec": loaded})["spec"]
    for name, spec in (("load", loaded), ("shared link", shared), ("save's answer", answered)):
        assert not set(spec) & set(HISTORY), (name, sorted(spec))
    assert _imported(user_key, project_id) == list(doc["dataflowProvenance"]["versions"])

    node_ids = [node["id"] for node in doc["dataflow"]["nodes"]]
    keyed = rekey_node_provenance(doc["nodeProvenance"], node_ids)
    for node_id in node_ids:
        status, text = tools.execute_read_tool(
            "node.history.read", user_key=user_key, project_id=project_id, target=None, params={"nodeId": node_id},
        )
        assert status == "ok", (node_id, text)
        listed = [entry["id"] for entry in json.loads(text)["entries"]]
        assert listed == sorted((entry["id"] for entry in keyed.get(node_id) or []), reverse=True), node_id


def test_the_validator_checks_the_history_beside_a_projects_spec(tmp_curio):
    """``scripts/validate_trill.py`` reads a project's spec with its history:
    a valid one passes, and an entry the schema refuses is reported."""
    doc = _with_history(json.loads(SMALL_EXAMPLE.read_text(encoding="utf-8")))
    storage.write_spec("1", "valid", doc)
    folder = storage.project_dir("1", "valid")
    _assert_split(folder, doc)
    result = subprocess.run([sys.executable, str(VALIDATOR), str(folder / "spec.trill.json")],
                            capture_output=True, text=True, cwd=str(REPO))
    assert result.returncode == 0, result.stdout + result.stderr

    node_id = next(iter(doc["nodeProvenance"]))
    doc["nodeProvenance"][node_id][0]["kind"] = "undo"
    storage.write_spec("1", "invalid", doc)
    folder = storage.project_dir("1", "invalid")
    _assert_split(folder, doc)
    result = subprocess.run([sys.executable, str(VALIDATOR), str(folder / "spec.trill.json")],
                            capture_output=True, text=True, cwd=str(REPO))
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"nodeProvenance.{node_id}.0.kind" in result.stderr, result.stderr


# ---------------------------------------------------------------------------
# A spec saved with its history inside, and copies
# ---------------------------------------------------------------------------

def test_a_spec_that_still_holds_its_history_is_split_on_its_first_write(tmp_curio):
    """No migration: a spec file saved with its history inside reads as it
    is, and any write moves the history beside it, here a dataset install's.
    A crash after the logs and before the spec file leaves that spec file,
    which is read as it is, and its next write splits it again."""
    doc = _fixture()
    folder = storage.ensure_project_dir("1", "saved-before")
    (folder / "spec.trill.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    assert _text(storage.read_spec("1", "saved-before")) == _text(doc)

    ref = {"datasetId": "data.curio.example@1"}
    _spec, changed = storage.mutate_dataflow_datasets("1", "saved-before", lambda refs: [*refs, ref])
    assert changed
    _assert_split(folder, doc)
    expected = json.loads(json.dumps(doc))
    expected["dataflow"]["datasets"] = [ref]
    assert _text(storage.read_spec("1", "saved-before")) == _text(expected)

    newer = storage.read_spec("1", "saved-before")
    newer["nodeProvenance"]["py-2"].append(_entry(9, 2, "return 0"))
    storage.write_spec("1", "saved-before", newer)
    (folder / "spec.trill.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    assert _text(storage.read_spec("1", "saved-before")) == _text(expected)
    storage.write_spec("1", "saved-before", storage.read_spec("1", "saved-before"))
    _assert_split(folder, expected)
    assert _text(storage.read_spec("1", "saved-before")) == _text(expected)


def test_a_write_that_leaves_the_history_out_keeps_what_a_spec_file_held(tmp_curio):
    """A spec file saved with its history inside, before any log, then a write
    that hands over the dataflow alone, as the server's doc writes it: the
    history the file held is moved into its logs, not lost with the file."""
    doc = _fixture()
    folder = storage.ensure_project_dir("1", "saved-before")
    (folder / "spec.trill.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    live = json.loads(json.dumps({key: value for key, value in doc.items() if key not in HISTORY}))
    live["dataflow"]["nodes"][0]["content"] = "return 2"

    storage.write_spec("1", "saved-before", live)

    read = storage.read_spec("1", "saved-before")
    for key in HISTORY:
        assert read.get(key) == doc[key], f"the write lost the {key} its spec file held"
    _assert_split(folder, doc)
    assert _text(read) == _text({**live, **{key: doc[key] for key in HISTORY}})


def test_a_loaded_file_and_a_duplicate_keep_the_history_and_a_watchers_copy_starts_its_own(
        client, user_and_token, db, tmp_curio):
    """File > Load saves a dataflow file with its history as a new dataflow,
    whose first open imports it; the Projects page's Duplicate copies that
    history with the dataflow. Another account's Save a copy of the shared link
    starts its own: the link carries no history, and its watcher may not read
    the dataflow's."""
    from utk_curio.backend.app.users.models import User, UserSession

    alice, token = user_and_token
    alice_key = _user_dir_key(alice)
    doc = _fixture()
    versions = list(doc["dataflowProvenance"]["versions"])

    loaded = _create(client, token, "Loaded from a file", json.loads(json.dumps(doc)))
    _opened(alice_key, loaded)
    assert _imported(alice_key, loaded) == versions

    duplicate = client.post(f"/api/projects/{loaded}/duplicate", headers=_auth(token))
    assert duplicate.status_code == 201, duplicate.get_data(as_text=True)
    _opened(alice_key, duplicate.get_json()["id"])
    assert _imported(alice_key, duplicate.get_json()["id"]) == versions

    bob = User(username="bob", name="Bob", email="bob@test.com")
    db.session.add(bob)
    db.session.flush()
    db.session.add(UserSession(user_id=bob.id, token="bob-token"))
    db.session.commit()
    shared = client.get(f"/api/projects/{loaded}/shared", headers=_auth("bob-token")).get_json()["spec"]
    assert not set(shared) & set(HISTORY), sorted(shared)
    copy = client.post(
        "/api/projects",
        data=json.dumps({"name": "Bob's copy", "spec": shared, "copy_of": loaded}),
        headers=_auth("bob-token"),
    )
    assert copy.status_code == 201, copy.get_data(as_text=True)
    _opened(_user_dir_key(bob), copy.get_json()["id"])
    assert _imported(_user_dir_key(bob), copy.get_json()["id"]) == [], "a watcher's copy took the history"


def test_an_example_put_back_to_its_shipped_copy_keeps_no_history(app, db, tmp_curio):
    """The shared guest's examples are put back to their shipped copies at
    every start: one saved with a history comes back with none, whether its
    history is in its logs or still inside a spec file saved before them."""
    from utk_curio.backend.app.projects import seed
    from utk_curio.backend.app.users.models import User
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    guest = User(username=CURIO_SHARED_GUEST_USERNAME, name="Guest", is_guest=True)
    db.session.add(guest)
    db.session.commit()
    example = next(entry for entry in seed.shipped_dataflows() if entry.path.name == SMALL_EXAMPLE.name)
    project_id = seed._example_id(example.key, guest)
    user_key = _user_dir_key(guest)
    assert seed.seed_example_projects(guest, only_keys=[example.key]) == 1
    shipped = storage.read_spec(user_key, project_id)

    saved = _with_history(shipped)
    storage.write_spec(user_key, project_id, saved)
    _assert_split(storage.project_dir(user_key, project_id), saved)
    assert seed.seed_example_projects(guest, only_keys=[example.key]) == 1
    back = storage.read_spec(user_key, project_id)
    assert [key for key in HISTORY if key in back] == [], "the example came back with its old history"
    assert back == shipped

    folder = storage.project_dir(user_key, project_id)
    (folder / "spec.trill.json").write_text(json.dumps(saved, indent=2), encoding="utf-8")
    assert seed.seed_example_projects(guest, only_keys=[example.key]) == 1
    back = storage.read_spec(user_key, project_id)
    assert [key for key in HISTORY if key in back] == [], "the example came back with the history its file held"
    assert back == shipped


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------

def test_two_writers_that_do_not_hold_the_spec_lock_add_an_entry_once(tmp_curio, monkeypatch):
    """Most backend writers write a spec without the spec lock. Two that send
    the same new entry at once, each reading the log before the other adds
    to it, would both add it: the history lock lets one read only after the
    other wrote."""
    doc = _fixture()
    storage.write_spec("1", "two-writers", doc)
    _assert_split(storage.project_dir("1", "two-writers"), doc)
    sent = json.loads(json.dumps(doc))
    sent["nodeProvenance"]["py-2"].append(_entry(7, 2, "return 7"))

    real = storage._replay
    both_read = threading.Barrier(2, timeout=1.0)

    def replay(data, section):
        # Each writer waits here for the other, so both would read the log
        # before either adds to it. A writer kept out by the lock never comes,
        # and the wait ends after a second.
        if threading.current_thread().name.startswith("writer"):
            try:
                both_read.wait()
            except threading.BrokenBarrierError:
                pass
        return real(data, section)

    monkeypatch.setattr(storage, "_replay", replay)
    failures: list = []

    def write() -> None:
        try:
            storage.write_spec("1", "two-writers", sent)
        except Exception as exc:  # noqa: BLE001 - reported below
            failures.append(exc)

    writers = [threading.Thread(target=write, name=f"writer-{n}") for n in (1, 2)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=30)
    assert not failures, failures
    listed = [entry["id"] for entry in storage.read_spec("1", "two-writers")["nodeProvenance"]["py-2"]]
    assert listed == [1, 2, 7]


def test_two_writes_of_one_spec_at_once_both_land(tmp_curio, monkeypatch):
    """Two threads of one process writing one project's spec at once write it
    under the same temporary name, then swap that file in. With nothing
    between them, the second swap finds the file gone and its write fails:
    the history lock lets the second write start only once the first ended."""
    doc = _fixture()
    storage.write_spec("1", "two-at-once", doc)
    revision = storage.spec_revision("1", "two-at-once")
    real = storage.os.replace
    both_swap = threading.Barrier(2, timeout=1.0)

    def replace(source, target):
        # Each writer waits here for the other, so both have written the
        # temporary file before either swaps it in. A writer kept out by the
        # lock never comes, and the wait ends after a second.
        if threading.current_thread().name.startswith("writer") and str(target).endswith("spec.trill.json"):
            try:
                both_swap.wait()
            except threading.BrokenBarrierError:
                pass
        return real(source, target)

    monkeypatch.setattr(storage.os, "replace", replace)
    failures: list = []
    sent = []
    for n in (1, 2):
        edited = json.loads(json.dumps(doc))
        edited["dataflow"]["nodes"][0]["content"] = f"return {n}"
        sent.append(edited)

    def write(edited: dict) -> None:
        try:
            storage.write_spec("1", "two-at-once", edited)
        except Exception as exc:  # noqa: BLE001 - reported below
            failures.append(repr(exc))

    writers = [threading.Thread(target=write, args=(edited,), name=f"writer-{n}") for n, edited in enumerate(sent)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=30)
    assert not failures, failures
    assert storage.spec_revision("1", "two-at-once") == revision + 2
    assert _text(storage.read_spec("1", "two-at-once")) in {_text(edited) for edited in sent}


def test_a_read_during_a_write_gets_all_of_it_or_none(tmp_curio, monkeypatch):
    """A write puts the history in its log, then the spec file. A reader that
    comes between them waits for the write, so it never gets the new history
    beside the old dataflow."""
    doc = _fixture()
    storage.write_spec("1", "mid-write", doc)
    _assert_split(storage.project_dir("1", "mid-write"), doc)
    sent = json.loads(json.dumps(doc))
    sent["dataflow"]["nodes"][1]["content"] = "return input_0 * 3"
    sent["nodeProvenance"]["py-2"].append(_entry(8, 2, "return input_0 * 3"))

    real = storage._write_json_atomically
    reached, release = threading.Event(), threading.Event()

    def held(path, payload):
        if threading.current_thread().name == "writer" and path.name == "spec.trill.json":
            reached.set()
            release.wait(timeout=30)
        return real(path, payload)

    monkeypatch.setattr(storage, "_write_json_atomically", held)
    seen: list = []
    writer = threading.Thread(target=lambda: storage.write_spec("1", "mid-write", sent), name="writer")
    reader = threading.Thread(target=lambda: seen.append(storage.read_spec("1", "mid-write")), name="reader")
    writer.start()
    assert reached.wait(30), "the write never reached its spec file"
    reader.start()
    reader.join(timeout=0.5)
    waited = reader.is_alive()
    release.set()
    writer.join(timeout=30)
    reader.join(timeout=30)
    assert waited, "the reader did not wait for the write"
    assert seen and _text(seen[0]) == _text(sent), "the reader got part of the write"
