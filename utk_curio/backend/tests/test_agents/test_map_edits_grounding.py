"""Map Edits grounds the agents.

A Map Edits node (its type id is still ``curio.builtin/edit-features``) keeps
its edits in its code: one ``curio_edit_features(...)`` call, which the node
writes and reads back. Code the node cannot read is refused wherever an agent
writes a node's code: at the mint of ``node.create`` and of
``node.content.write``, and in Solve, verified or not, before the sandbox
runs it. A run's report of ids no feature has is a made-up id, read from the
run's whole output, past the tail a record keeps too. And Solve's context
gives a node the Map Edits calls of its neighbours.

Every test imports what it tests inside itself, so a checkout without it
fails test by test rather than at collection.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import (
    _attach,
    _create_tail,
    _install,
    _proposals,
    _run,
    _script,
    _tool_results,
)

NB = "agent.curio.node-builder@1"
DFB = "agent.curio.dataflow-builder@1"
DL = "curio.builtin/data-loading"
CA = "curio.builtin/computation-analysis"
EDIT = "curio.builtin/edit-features"

NOTE = (
    "# Map Edits writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
)
NO_EDITS = NOTE + "return curio_edit_features(input_0, [])\n"
#: An edit the node does not make, and the node's own words for it.
UNREADABLE = 'return curio_edit_features(input_0, [{"op": "delete", "ids": [2]}], key="building_id")\n'
PROBLEM = (
    'Edit 1 has the op "delete", which is none of remove, set, restore, scale, '
    "offset, expr, add, geometry, add_column."
)
#: Building 2 removed, as the node writes it.
REMOVE_TWO = NOTE + 'return curio_edit_features(input_0, [\n    {"op": "remove", "ids": [2]},\n], key="building_id")\n'
LOADER = "return 1\n"


def _seed_builtin(user_key: str) -> None:
    """The shipped built-in package in *user_key*'s store, so the project's
    templates are Curio's own, Map Edits among them."""
    from utk_curio import shipped
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    target = user_packages_dir(user_key) / "curio.builtin@1"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(shipped.path("packages") / "curio.builtin@1" / "manifest.json", target / "manifest.json")


def _project(client, user, token, nodes, edges=()) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    _seed_builtin(_user_dir_key(user))
    body = {"name": "p", "spec": {"dataflow": {"nodes": nodes, "edges": list(edges), "packages": []}}, "outputs": []}
    response = client.post("/api/projects", json=body, headers=_auth(token))
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["id"]


def _write_tail(node_id: str, content: str) -> str:
    request = {"toolRequest": {"tool": "node.content.write", "params": {"nodeId": node_id, "content": content}}}
    return "```curio.v1\n" + json.dumps(request) + "\n```"


def _refusals(calls, tool: str) -> list[str]:
    """The refusals of *tool* the model was handed."""
    return [text for text in _tool_results(calls[-1], tool) if "refused" in text.split("\n", 1)[0]]


class TestTheMintsHoldAnAgentsCodeToTheNodesReader:
    """Code the node cannot read is never proposed: the model is told why, in
    the node's own words, and corrects it."""

    def test_node_create_refuses_map_edits_code_the_node_cannot_read(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project = _project(client, user, token, [{"id": "n1", "type": DL, "content": LOADER, "x": 0, "y": 0}])
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [_create_tail(UNREADABLE, node_type=EDIT), "I could not write it."])
        body = _run(client, token, project, att, "add a Map Edits node that removes building 2")
        assert not _proposals(body), "code the Map Edits node cannot read was proposed"
        [refusal] = _refusals(calls, "node.create")
        assert "Map Edits" in refusal and PROBLEM in refusal, refusal

    def test_node_content_write_refuses_map_edits_code_the_node_cannot_read(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project = _project(client, user, token, [
            {"id": "load", "type": DL, "content": LOADER, "x": 0, "y": 0},
            {"id": "edit", "type": EDIT, "content": NO_EDITS, "goal": "Remove building 2", "x": 700, "y": 0},
        ], [{"id": "e", "source": "load", "target": "edit", "sourceHandle": "out", "targetHandle": "in"}])
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB, target={"kind": "node", "targetId": "edit"})
        calls = _script(monkeypatch, [_write_tail("edit", UNREADABLE), "I could not write it."])
        body = _run(client, token, project, att, "remove building 2")
        assert not _proposals(body), "code the Map Edits node cannot read was proposed"
        [refusal] = _refusals(calls, "node.content.write")
        assert "Map Edits" in refusal and PROBLEM in refusal, refusal


#: The two buildings a Map Edits node edits in the Solve tests.
BUILDINGS = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"building_id": 1}},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"building_id": 2}},
]}


def _sandbox_says(edits) -> list[str]:
    """The lines the sandbox's step prints for *edits* on the two buildings, as
    the sandbox hands a run's output back: one per line, none empty."""
    from utk_curio.sandbox.util.feature_edits import edit_features

    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        edit_features({"dataType": "geodataframe", "data": json.loads(json.dumps(BUILDINGS))}, edits, key="building_id")
    return [line for line in printed.getvalue().split("\n") if line]


def _code(edits) -> str:
    return NOTE + "return curio_edit_features(input_0, [\n" + "".join(
        f"    {json.dumps(edit)},\n" for edit in edits
    ) + '], key="building_id")\n'


#: What tells the codes of these tests apart in the code a run sends.
MADE_UP_MARK = '"ids": [999]'
REMOVE_TWO_MARK = '{"op": "remove", "ids": [2]}'


class _Sandbox:
    """A fake sandbox: the loader passes, and a Map Edits node's run prints
    what the step prints for the edits its code holds (*printed*, by a mark
    of the code)."""

    def __init__(self, printed: dict[str, list[str]]):
        self.printed = printed
        self.calls: list[dict] = []

    def __call__(self, endpoint, payload):
        self.calls.append(payload)
        if str(payload.get("nodeType") or "").startswith(EDIT):
            said = next((lines for mark, lines in self.printed.items() if mark in payload["code"]), [])
            return {"stdout": list(said), "stderr": "", "output": {"path": "art-edit", "dataType": "dict"}}
        return {"stdout": [], "stderr": "", "output": {"path": "art-load", "dataType": "geodataframe"}}


def _solve_spec(goal="Remove building 2 by its building_id"):
    return {"dataflow": {
        "name": "wf", "task": "a what-if without building 2",
        "nodes": [
            {"id": "load", "type": DL, "goal": "Buildings", "content": LOADER},
            {"id": "edit", "type": EDIT, "goal": goal, "content": ""},
        ],
        "edges": [{"id": "e", "source": "load", "target": "edit", "targetHandle": "in"}],
    }}


def _solve_rounds(app, replies, sandbox, spec=None):
    from utk_curio.backend.tests.test_agents.test_verified_rounds import KEY, _rounds

    _seed_builtin(KEY)
    spec = spec or _solve_spec()
    return _rounds(app, spec["dataflow"]["nodes"][1], replies=replies, exec_fn=sandbox, spec=spec)


class TestSolveHoldsAnAgentsCodeToTheNodesReader:
    def test_code_the_node_cannot_read_is_refused_before_the_sandbox_and_corrected(self, app, tmp_curio):
        sandbox = _Sandbox({REMOVE_TWO_MARK: _sandbox_says([{"op": "remove", "ids": [2]}])})
        _events, outcome, inputs = _solve_rounds(app, [UNREADABLE, REMOVE_TWO], sandbox)
        assert [attempt["kind"] for attempt in outcome["attempts"]] == ["map-edits", "executed"], outcome["attempts"]
        assert outcome["verdict"] == "pass" and outcome["candidate"] == REMOVE_TWO
        # The code the node cannot read never ran.
        assert not any('"delete"' in call["code"] for call in sandbox.calls), sandbox.calls
        # The correction was told why, in the node's own words.
        assert "Map Edits" in inputs[1]["validationError"] and PROBLEM in inputs[1]["validationError"]

    def test_an_unverified_solve_never_writes_code_the_node_cannot_read(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """``verify: false`` writes content without running it, and holds a
        Map Edits node's code to the node's reader as a verified Solve does."""
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        project = _project(client, user, token, [])
        plan = {
            "goal": "a what-if without building 2",
            "nodes": [
                {"ref": "load", "nodeType": DL, "title": "Buildings", "intent": "synthetic sample buildings, by building_id"},
                {"ref": "edit", "nodeType": EDIT, "title": "Building 2 removed", "intent": "Remove building 2 by its building_id"},
            ],
            "edges": [{"from": "load", "to": "edit"}],
        }
        plan_tail = "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"

        def _reply(calls):
            frame = calls[-1][-1]["content"]
            if "[delegated task" not in frame:
                return plan_tail
            if f'"nodeType": "{EDIT}"' in frame:
                return UNREADABLE
            return 'import pandas as pd\nreturn pd.DataFrame({"building_id": [1, 2]})'

        _install(client, token, project, DFB, NB)
        att = _attach(client, token, project, DFB)
        _script(monkeypatch, [_reply])
        [proposal] = _proposals(_run(client, token, project, att, "plan a what-if without building 2"))
        applied = client.post(
            f"/api/agents/projects/{project}/attachments/{att}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        ).get_json()
        edit = next(n["id"] for n in applied["appliedGraph"]["nodes"] if str(n.get("type", "")).startswith(EDIT))
        body = client.post(
            f"/api/agents/projects/{project}/attachments/{att}/solve",
            json={"verify": False}, headers=_auth(token),
        ).get_json()
        result = body["results"][edit]
        assert result["status"] == "failed", result
        assert "Map Edits" in result["error"], result
        spec = projects_storage.read_spec(_user_dir_key(user), project)
        assert next(n for n in spec["dataflow"]["nodes"] if n["id"] == edit)["content"] == ""


class TestSolveReadsMadeUpIdsFromTheWholeRun:
    """The sandbox's step reports an id no feature has, and the run goes on: a
    Map Edits node an agent filled with made-up ids passes the sandbox. Solve
    reads the report and the round fails, with the step's own line."""

    def test_an_id_no_feature_has_fails_the_round_with_the_steps_own_line(self, app, tmp_curio):
        made_up = [{"op": "remove", "ids": [999]}]
        said = _sandbox_says(made_up)
        [line] = [text for text in said if "has no feature with building_id 999" in text]
        sandbox = _Sandbox({
            MADE_UP_MARK: said,
            REMOVE_TWO_MARK: _sandbox_says([{"op": "remove", "ids": [2]}]),
        })
        _events, outcome, inputs = _solve_rounds(app, [_code(made_up), REMOVE_TWO], sandbox)
        assert [attempt["kind"] for attempt in outcome["attempts"]] == ["map-edits", "executed"], outcome["attempts"]
        assert line in outcome["attempts"][0]["detail"]
        assert line in inputs[1]["validationError"]
        assert outcome["candidate"] == REMOVE_TWO

    def test_a_report_line_past_the_tail_a_record_keeps_is_read_too(self, app, tmp_curio):
        """The report comes first, and 40 adds of features the layer already
        has follow it, each a line: over 2,000 characters, more than the tail
        of a run's output that a record keeps."""
        made_up = [{"op": "remove", "ids": [999]}] + [
            {"op": "add", "id": 1, "geometry": {"type": "Point", "coordinates": [0, k]}} for k in range(40)
        ]
        said = _sandbox_says(made_up)
        [line] = [text for text in said if "has no feature with building_id 999" in text]
        after = "\n".join(said[said.index(line) + 1:])
        assert len(after) > 2000, len(after)
        sandbox = _Sandbox({
            MADE_UP_MARK: said,
            REMOVE_TWO_MARK: _sandbox_says([{"op": "remove", "ids": [2]}]),
        })
        _events, outcome, inputs = _solve_rounds(app, [_code(made_up), REMOVE_TWO], sandbox)
        assert [attempt["kind"] for attempt in outcome["attempts"]] == ["map-edits", "executed"], outcome["attempts"]
        assert line in inputs[1]["validationError"]


class TestSolveContextGivesTheNeighboursCalls:
    """A node's context names its Map Edits neighbours' calls, so what an
    agent writes below a what-if knows what it changed."""

    def _spec(self, edit_code):
        return {"dataflow": {
            "name": "wf", "task": "shade without the towers",
            "nodes": [
                {"id": "load", "type": DL, "goal": "Buildings", "content": LOADER},
                {"id": "edit", "type": EDIT, "goal": "Remove the towers", "content": edit_code},
                {"id": "shade", "type": CA, "goal": "Shade per park", "content": ""},
            ],
            "edges": [
                {"id": "e1", "source": "load", "target": "edit"},
                {"id": "e2", "source": "edit", "target": "shade"},
            ],
        }}

    def test_an_upstream_map_edits_node_gives_its_call(self, tmp_curio):
        from utk_curio.backend.app.agents.domain import node_context

        context = node_context.compose_node_context("4242", "p-context", self._spec(REMOVE_TWO), "shade")
        [row] = [row for row in context["upstream"] if row["id"] == "edit"]
        assert row.get("mapEditsCall") == REMOVE_TWO, row
        # The loader is no Map Edits node: its row is as before.
        [loader] = [row for row in context["upstream"] if row["id"] == "load"]
        assert "mapEditsCall" not in loader

    def test_a_long_call_is_cut_and_says_so(self, tmp_curio):
        from utk_curio.backend.app.agents.domain import node_context

        many = _code([{"op": "remove", "ids": list(range(k * 100, k * 100 + 100))} for k in range(10)])
        context = node_context.compose_node_context("4242", "p-context", self._spec(many), "shade")
        [row] = [row for row in context["upstream"] if row["id"] == "edit"]
        call = row.get("mapEditsCall") or ""
        assert call.startswith(many[:500]) and len(call) < len(many), len(call)
        assert "truncated" in call
