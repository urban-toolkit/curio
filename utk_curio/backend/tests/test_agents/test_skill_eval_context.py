"""A skill evaluation's run sends the context a browser's chat sends beside each message (memo dev/44).

The canvas composes it on every send (``composeAgentRunContext`` in
``src/services/agents/agentRunContext.ts``), from the reads the agent's
manifest declares: ``Target node: {...}`` for the node the agent is attached
to, ``Current Trill: {...}`` for the whole dataflow, and the rest. A run of
``agent_eval.py skills`` posts its message to the same route, so it posts
this beside it (``evaluation/run_context.py``), or its model would be told
less than a user's model is: a Node Builder attached to a chart would not
know which node "this chart" is.

The composer is the canvas's, repeated in Python, so its cases here are the
canvas's own (``src/tests/attach/agentRunContext.test.ts``), on the saved
dataflow an evaluation's run holds in place of the live canvas, and every
label it writes must be one the TypeScript writes.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

from utk_curio.backend.tests._support.agent_routes import _auth

REPO_ROOT = Path(__file__).resolve().parents[4]
#: The canvas's composer, whose labels the twin must write as it does.
CANVAS_COMPOSER = (REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "services" / "agents"
                   / "agentRunContext.ts")
NAME = "wf"
GOAL = "analyze heat risk"
#: The canvas of the TypeScript cases, as the server holds it: a node with
#: code and a goal, and a second node with neither code nor a run.
SPEC = {"dataflow": {
    "nodes": [
        {"id": "n1", "type": "CODE", "x": 0, "y": 0, "content": "print('old')", "out": "DEFAULT", "in": "DEFAULT",
         "goal": "load the data"},
        {"id": "n2-unsaved", "type": "CODE", "x": 10, "y": 10, "content": "", "goal": "brand new"},
    ],
    "edges": [],
    "name": NAME,
    "task": GOAL,
    "timestamp": 1_700_000_000_000,
}}
WIRED = {"dataflow": {**SPEC["dataflow"], "edges": [
    {"id": "e1", "source": "n1", "target": "n2-unsaved", "sourceHandle": "out", "targetHandle": "in"}]}}
ON_N1 = {"kind": "node", "targetId": "n1"}
ON_N2 = {"kind": "node", "targetId": "n2-unsaved"}
CANVAS = {"kind": "canvas"}


def _compose(reads, target, spec=SPEC):
    from utk_curio.backend.app.agents.evaluation import run_context

    return run_context.compose(reads, target, spec, name=NAME, goal=GOAL)


def _trill(spec=SPEC) -> str:
    from utk_curio.backend.app.agents.evaluation import run_context

    return json.dumps(run_context.trill(spec, NAME, GOAL), ensure_ascii=False, separators=(",", ":"))


# --- The canvas's cases -------------------------------------------------------------


def test_a_node_attachments_content_reads_compose_labeled_fragments_byte_for_byte():
    context = _compose(["dataflowContext", "nodeId", "subtask", "workflowGoal"], ON_N1)
    assert context == ("Current Trill: " + _trill() + "\n" + "Node ID: n1\n" + "Subtask: load the data\n"
                       + "Task: analyze heat risk")
    # The target's code rides the Trill, and so does every other node.
    assert "print('old')" in context
    assert "n2-unsaved" in context


def test_the_trill_is_the_one_the_canvas_composes_its_name_its_task_and_no_packages():
    trill = json.loads(_trill())["dataflow"]
    assert list(trill)[:7] == ["nodes", "edges", "name", "task", "timestamp", "provenance_id", "packages"]
    assert (trill["name"], trill["task"], trill["provenance_id"], trill["packages"]) == (NAME, GOAL, NAME, [])
    assert [node["id"] for node in trill["nodes"]] == ["n1", "n2-unsaved"]


def test_generic_reads_compose_labeled_fragments_in_declared_order():
    context = _compose(["dataflowContext", "workflowGoal"], CANVAS)
    assert context.startswith("Current Trill: ")
    assert "\nTask: analyze heat risk" in context


def test_node_scoped_reads_resolve_from_the_attached_node_which_never_ran():
    payload = json.loads(_compose(["nodeContext"], ON_N1))
    assert payload["id"] == "n1"
    assert payload["current_input"] == "no upstream input (declared: DEFAULT)"
    assert payload["current_output"] == "never-executed (declared: DEFAULT)"


def test_node_scoped_reads_are_omitted_for_canvas_attachments():
    assert _compose(["nodeContent", "nodeType", "currentTask"], CANVAS) is None


def test_agents_with_no_composable_reads_yield_none():
    assert _compose(["userMessage"], CANVAS) is None


def test_the_researcher_sees_the_dataflow_once_and_on_a_node_that_node_first():
    reads = ["mission", "targetContext", "installedTemplates", "dataflowContext"]
    on_canvas = _compose(reads, CANVAS)
    assert on_canvas == "Workflow: wf\nMission: analyze heat risk\nCurrent Trill: " + _trill()
    on_node = _compose(reads, ON_N1)
    mission, target, dataflow = (on_node.index("Mission: analyze heat risk"), on_node.index("Target node: "),
                                 on_node.index("Current Trill: " + _trill()))
    assert mission < target < dataflow
    snapshot = json.loads(on_node[target + len("Target node: "):].split("\n")[0])
    assert snapshot["id"] == "n1"
    assert snapshot["content"] == "print('old')"
    assert "never-executed" in snapshot["current_output"]
    assert "n2-unsaved" in on_node


def test_a_canvas_attachment_that_does_not_read_target_context_still_gets_dataflow_context():
    assert _compose(["dataflowContext"], CANVAS) == "Current Trill: " + _trill()


def test_the_dataflow_builder_composes_its_mission_and_the_whole_graph_and_no_template_roster():
    context = _compose(["mission", "graphContext", "installedTemplates"], CANVAS, WIRED)
    assert "Mission: analyze heat risk" in context
    assert "Workflow: wf" in context
    assert '"source":"n1"' in context
    assert "n2-unsaved" in context
    assert "Installed node templates:" not in context


def test_the_node_builder_on_the_canvas_composes_the_whole_graph_as_its_target():
    context = _compose(["nodeIntent", "targetContext", "externalSelection", "connectionSide"], CANVAS, WIRED)
    assert context.startswith("Current Trill:")
    assert '"source":"n1"' in context
    assert "Node intent:" not in context
    assert "Connection:" not in context


def test_the_node_builder_on_a_node_composes_its_snapshot_and_its_intent():
    context = _compose(["nodeIntent", "targetContext"], ON_N1, WIRED)
    assert context.startswith("Node intent: load the data\nTarget node: ")
    snapshot = json.loads(context.split("Target node: ", 1)[1])
    assert snapshot == {"id": "n1", "type": "CODE", "goal": "load the data", "content": "print('old')",
                        "current_input": "no upstream input (declared: DEFAULT)",
                        "current_output": "never-executed (declared: DEFAULT)"}


def test_the_node_builder_on_a_connection_names_both_its_ends():
    context = _compose(["nodeIntent", "targetContext", "externalSelection", "connectionSide"],
                       {"kind": "connection", "targetId": "e1"}, WIRED)
    assert context.endswith("\nConnection: the output of node n1 into the input of node n2-unsaved")
    assert context.startswith("Current Trill: ")


def _input_of(spec, read: str, target=ON_N2):
    """The ``current_input`` of the node *target* names, as the read *read* composes it."""
    context = _compose([read], target, spec)
    return json.loads(context[len("Target node: "):] if read == "targetContext" else context)["current_input"]


def test_a_node_wired_to_one_that_has_not_run_waits_for_input_from_it_through_both_node_reads():
    # 10-30, step 44's live runs: "no upstream input" read as a chart nothing
    # feeds, and the agent built a new loader for a chart wired to one.
    waiting = "waiting for input: wired from node n1 (CODE), which has not run"
    assert _input_of(WIRED, "targetContext") == waiting
    assert _input_of(WIRED, "nodeContext") == waiting


def test_a_node_wired_twice_from_one_node_names_it_once():
    twice = {"dataflow": {**SPEC["dataflow"], "edges": [
        {"id": "e1", "source": "n1", "target": "n2-unsaved", "sourceHandle": "out", "targetHandle": "in"},
        {"id": "e2", "source": "n1", "target": "n2-unsaved", "sourceHandle": "out", "targetHandle": "in_1"}]}}
    assert _input_of(twice, "targetContext") == "waiting for input: wired from node n1 (CODE), which has not run"


def test_a_node_wired_from_more_than_six_names_six_and_counts_the_rest():
    many = {"dataflow": {
        "nodes": [{"id": f"n{i}", "type": "CODE"} for i in range(8)] + [{"id": "sink", "type": "CODE"}],
        "edges": [{"id": f"e{i}", "source": f"n{i}", "target": "sink"} for i in range(8)],
    }}
    assert _input_of(many, "nodeContext", {"kind": "node", "targetId": "sink"}) == (
        "waiting for input: wired from "
        + "; ".join(f"node n{i} (CODE), which has not run" for i in range(6)) + "; and 2 more")


def test_a_node_joined_to_another_only_by_an_interaction_edge_still_has_no_upstream_input():
    # As the canvas saves an interaction edge (TrillGenerator).
    joined = {"dataflow": {**SPEC["dataflow"], "edges": [
        {"type": "Interaction", "id": "i1", "source": "n1", "target": "n2-unsaved", "sourceHandle": "in/out",
         "targetHandle": "in/out"}]}}
    assert _input_of(joined, "targetContext") == "no upstream input"


def test_the_dataset_finder_gets_at_least_the_mission_on_a_canvas():
    context = _compose(["mission", "nodeContext", "catalog"], CANVAS, WIRED)
    assert "Mission: analyze heat risk" in context
    assert "catalog" not in context


def test_an_empty_canvas_yields_none_for_mission_less_reads():
    from utk_curio.backend.app.agents.evaluation import run_context

    empty = {"dataflow": {"nodes": [], "edges": []}}
    assert run_context.compose(["mission", "catalog"], CANVAS, empty, name="", goal="") is None


def test_every_label_the_twin_writes_is_one_the_canvas_writes():
    from utk_curio.backend.app.agents.evaluation import run_context

    canvas = CANVAS_COMPOSER.read_text(encoding="utf-8")
    missing = [label for label in run_context.LABELS if f'"{label}' not in canvas and f'{label}"' not in canvas]
    assert not missing, f"agentRunContext.ts writes none of {missing}"
    summaries = (CANVAS_COMPOSER.parents[2] / "utils" / "nodeRuntimeSummary.ts").read_text(encoding="utf-8")
    assert f'"{run_context.NEVER_EXECUTED}"' in summaries
    assert f"`{run_context.NO_INPUT}${{declared(data.in)}}`" in summaries
    assert "` (declared: ${value.trim()})`" in summaries
    # A node wired to others, with no input yet, and the nodes wired into it.
    wired = getattr(run_context, "WIRED_INPUT", None)
    assert wired, "the twin has no words for a node wired to others that has no input yet"
    unwritten = [word for word in wired if f'"{word}"' not in summaries]
    assert not unwritten, f"nodeRuntimeSummary.ts writes none of {unwritten}"
    assert f"const LISTED_SLOTS = {getattr(run_context, 'LISTED', None)};" in summaries


# --- What a run sends -----------------------------------------------------------------


def _worker(client, token):
    """A worker of ``agent_eval.py skills`` on this test's app and account."""
    from utk_curio.tools import skill_eval_worker

    worker = skill_eval_worker.Worker.__new__(skill_eval_worker.Worker)
    worker.client, worker.headers, worker.secrets = client, _auth(token), {}
    worker.seams = skill_eval_worker._Seams()
    return worker


def _sent_to_the_model(monkeypatch) -> list:
    from utk_curio.backend.app.agents.application.turns import titles

    sent = []

    def _fake_run(config, messages, **kwargs):
        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        sent.append(messages)
        return "ok"

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _fake_run)
    return sent


def _task(tmp_path, target: str, node: str | None):
    from utk_curio.backend.app.agents.evaluation import skill_evals

    flow = tmp_path / "flow.json"
    flow.write_text(json.dumps({"dataflow": {
        "nodes": [
            {"id": "scores", "type": "curio.builtin/data-loading", "title": "Neighborhood scores",
             "content": "import pandas as pd\n\nreturn pd.DataFrame({'side': ['North'], 'score': [0.5]})",
             "goal": "Return the scores.", "in": "DEFAULT", "out": "DEFAULT"},
            {"id": "scores-chart", "type": "curio.builtin/vis-vega", "title": "Scores chart", "content": "",
             "goal": "", "in": "DEFAULT", "out": "DEFAULT"},
        ],
        "edges": [{"id": "e1", "source": "scores", "target": "scores-chart", "sourceHandle": "out",
                   "targetHandle": "in"}],
        "name": "Scores", "task": "",
    }}), encoding="utf-8")
    context = skill_evals.Context(agent="agent.curio.node-builder@1", dataflow=flow, target=target, node=node)
    message = "Write the Scores chart's Vega-Lite spec."
    return skill_evals.Task(kind=skill_evals.TASK, skill="vega-lite-starter", key="eval-1/with_skill/run-1",
                            condition=skill_evals.WITH_SKILL, run=1, message=message, context=context, case=1)


def _context_messages(sent: list) -> list[str]:
    from utk_curio.backend.app.agents.application.turns import policy

    frame = policy.context_frame()
    return [m["content"] for messages in sent for m in messages
            if m.get("role") == "user" and str(m.get("content") or "").startswith(frame)]


def test_a_run_on_a_node_tells_the_model_the_node_as_a_browser_does(
        client, user_and_token, tmp_curio, tmp_path, monkeypatch):
    sent = _sent_to_the_model(monkeypatch)
    _, token = user_and_token
    task = _task(tmp_path, "node", "scores-chart")
    record: dict = {}
    status, _body, _project, _before = _worker(client, token)._attempt(task, task.message, tmp_path, record)
    assert status == 200 and "error" not in record, record
    contexts = _context_messages(sent)
    assert contexts, "the model was sent no context beside the message"
    snapshot = json.loads(contexts[0].split("Target node: ", 1)[1].split("\n")[0])
    assert (snapshot["id"], snapshot["type"], snapshot["content"]) == ("scores-chart", "curio.builtin/vis-vega", "")
    # Wired to the loader, which has not run: not a chart nothing feeds.
    assert snapshot["current_input"] == ("waiting for input (declared: DEFAULT): wired from node scores "
                                         "(curio.builtin/data-loading), which has not run")
    assert snapshot["current_output"] == "never-executed (declared: DEFAULT)"
    assert record["contextChars"] == len(contexts[0].split("\n", 1)[1])


def test_a_run_on_the_canvas_tells_the_model_the_whole_dataflow_as_a_browser_does(
        client, user_and_token, tmp_curio, tmp_path, monkeypatch):
    sent = _sent_to_the_model(monkeypatch)
    _, token = user_and_token
    task = _task(tmp_path, "canvas", None)
    record: dict = {}
    status, _body, _project, _before = _worker(client, token)._attempt(task, task.message, tmp_path, record)
    assert status == 200 and "error" not in record, record
    contexts = _context_messages(sent)
    assert contexts, "the model was sent no context beside the message"
    trill = json.loads(contexts[0].split("Current Trill: ", 1)[1].split("\n")[0])
    assert [node["id"] for node in trill["dataflow"]["nodes"]] == ["scores", "scores-chart"]
    assert trill["dataflow"]["edges"][0]["source"] == "scores"
