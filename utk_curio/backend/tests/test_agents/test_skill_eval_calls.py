"""The skill evaluations' grader sees what each call whose change landed wrote.

``agent_eval.py skills`` grades a test case's answer by its reply, by what it
changed in its dataflow and by the tools it called (``skill_eval_worker``).
What landed holds a plan's duplicate scenario only as the copies it made, with
no duplicateOf and no values, and a run's record keeps the arguments of
refused calls only. So since step 49 the grader failed scenarios' case 2, "a
second scenario whose duplicateOf names the first", in every run, though the
plan landed as asked, and passed "the duplicate's values set a widget of a
copied node to 2" only when it guessed it from the copies (live check of
11-04, main eb6e2d0d03).

The worker notes each tool call where a native call and a fenced block (a
toolRequest, a plan block) meet, and shows the grader, and the run's
``outputs/calls.json``, each call's tool and status, and what each call whose
change landed wrote. A refused call shows its tool and status alone, and
skill.read is never shown.

Each run is the worker's own (``Worker.run``, its seams installed as a
worker's are), on the scripted provider (``testing_provider``), which grades
too. New names are read inside each test, so this module imports on a
checkout without them and each test fails on its own.
"""

from __future__ import annotations

import inspect
import json
import types

import pytest

from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_plan_scenario_routes as scenario_routes
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes_proposals

DFB = "agent.curio.dataflow-builder@1"
PLAN_TOOL = "dataflow.plan.write"
#: A message with no word the scenarios skill's curio-asks names, so the chat
#: lists the skill and is not handed it.
MESSAGE = "Compare the shadows of the buildings as they are with the shadows of buildings twice as tall."
#: Scenarios' case 2's assertions on the duplicate, which the scripted grader passes.
ASSERTIONS = (
    "The answer writes a dataflow plan whose scenarios list holds a selection and a second scenario whose "
    "duplicateOf names the first.",
    "The duplicate's values set a widget of a copied node to 2, and the node it copies declares that widget.",
)
#: The duplicate scenario_routes._plan() writes: what it copies, and its values.
DUPLICATE = ("Real heights", {"shadows_tall": {"height_factor": 2}})
#: The forms a plan's call takes: native, and the two fenced ones.
FORMS = ("native call", "fenced toolRequest", "fenced plan block")


@pytest.fixture()
def scripted(client, user_and_token, tmp_curio):
    """The account's default model is the scripted one, with nothing queued
    before or after the test."""
    testing_provider.reset()
    _, token = user_and_token
    headers = _auth(token)
    created = client.post("/api/agents/llm/configs", headers=headers,
                          json={"label": "Scripted", "apiType": "testing", "model": "scripted"})
    assert created.status_code == 201, created.get_json()
    client.put("/api/agents/llm/default", headers=headers, json={"configId": created.get_json()["config"]["id"]})
    yield
    testing_provider.reset()


def _taken_off_after(monkeypatch) -> None:
    """A worker's seams wrap the backend's functions in place, for the
    worker's whole life: each function of the modules they wrap is set through
    *monkeypatch* first, which puts it back after the test."""
    from utk_curio.backend.app.agents.application import skill_runs, tool_rounds
    from utk_curio.backend.app.agents.application.proposals import plans
    from utk_curio.backend.app.agents.application.turns import prompts, titles
    from utk_curio.backend.app.agents.infrastructure import providers

    for module in (skill_runs, tool_rounds, plans, prompts, titles, providers):
        for name, value in list(vars(module).items()):
            if inspect.isfunction(value):
                monkeypatch.setattr(module, name, value)


def _worker(client, user_and_token, tmp_path, monkeypatch, secrets=None):
    """A worker of ``agent_eval.py skills`` on this test's app and account,
    its seams installed, and the plan's templates in the account's store."""
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.tools import skill_eval_worker

    user, token = user_and_token
    routes_proposals.TestNodeCreate()._write_builtin_package(_user_dir_key(user), templates=scenario_routes.TEMPLATES)
    worker = skill_eval_worker.Worker.__new__(skill_eval_worker.Worker)
    worker.client, worker.headers, worker.secrets = client, _auth(token), dict(secrets or {})
    worker.results, worker.folders, worker.stop_early = tmp_path / "results", {}, True
    worker.user_key, worker.endpoint = _user_dir_key(user), types.SimpleNamespace(model="scripted")
    _taken_off_after(monkeypatch)
    worker.seams = skill_eval_worker._Seams()
    worker.seams.install()
    return worker


def _task():
    """A run of scenarios' case 2 with the skill, on the Dataflow Builder's
    chat over an empty dataflow."""
    from utk_curio.backend.app.agents.evaluation import skill_evals

    return skill_evals.Task(
        kind=skill_evals.TASK, skill="scenarios", key="eval-2/with_skill/run-1", condition=skill_evals.WITH_SKILL,
        run=1, message=MESSAGE, context=skill_evals.Context(agent=DFB, dataflow=None), case=2,
        expected_output="A plan with a scenario, and a duplicate of it whose values double the height factor.",
        assertions=ASSERTIONS,
    )


def _grade(task) -> str:
    """The scripted grader's reply: every assertion passed."""
    return json.dumps({"assertion_results": [{"text": text, "passed": True, "evidence": "scripted"}
                                             for text in task.assertions]})


def _call(tool: str, arguments: dict) -> dict:
    return {"toolCalls": [{"name": tool, "arguments": arguments}]}


def _script(form: str, plan: dict, task) -> None:
    """The run's replies when it makes *plan* in *form*, then the grade."""
    if form == "native call":
        testing_provider.script_chat_capabilities(tools=True)
        replies = [_call(PLAN_TOOL, plan), "The plan is in."]
    elif form == "fenced toolRequest":
        testing_provider.script_chat_capabilities(tools=False)
        block = json.dumps({"toolRequest": {"tool": PLAN_TOOL, "params": plan}})
        replies = [f"```curio.v1\n{block}\n```", "The plan is in."]
    else:
        # A plan block lands and ends the turn.
        testing_provider.script_chat_capabilities(tools=False)
        replies = [scenario_routes._reply(plan)]
    testing_provider.push_replies(*replies, _grade(task))


def _shown_to_the_grader() -> list:
    """The tools the grader was shown: the JSON its message ends with."""
    from utk_curio.backend.app.agents.domain import agent_text

    system = agent_text.section("skill-evals.md", "grader")
    graded = [messages for messages in testing_provider.captured()
              if messages and messages[0].get("content") == system]
    assert len(graded) == 1, f"the grader was asked {len(graded)} times"
    lines = str(graded[0][-1].get("content") or "").rstrip().splitlines()
    for start in range(len(lines) - 1, -1, -1):
        if lines[start].startswith("["):
            try:
                return json.loads("\n".join(lines[start:]))
            except ValueError:
                continue
    raise AssertionError("the grader's message ends with no list of the tools called")


def _duplicate_written(call: dict) -> tuple:
    """What the duplicate scenario of a plan call's arguments copies, and its values."""
    written = call.get("arguments")
    assert isinstance(written, dict), f"the grader was not shown what the plan wrote: {call}"
    plan = written.get("dataflowPlan", written)
    duplicates = [s for s in plan.get("scenarios") or [] if isinstance(s, dict) and s.get("duplicateOf")]
    assert len(duplicates) == 1, f"the plan the grader was shown holds no one duplicate: {plan}"
    return duplicates[0]["duplicateOf"], duplicates[0].get("values")


def _kept(worker, task) -> list:
    """What the run's ``outputs/calls.json`` keeps."""
    path = worker.results / task.path / "outputs" / "calls.json"
    assert path.is_file(), "the run's outputs keep no calls.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("form", FORMS)
def test_the_grader_sees_the_duplicate_scenario_a_landed_plan_wrote(
        form, client, user_and_token, scripted, tmp_path, monkeypatch):
    """The plan of scenarios' case 2 lands: its duplicate becomes copies of
    the nodes it copies, each with copiedFrom and the widget's value, and the
    grader read no duplicateOf in what landed. It now reads the plan the call
    wrote, its duplicate's duplicateOf and values among it, once, whichever
    protocol and form made it; a person reading the results reads the same."""
    worker = _worker(client, user_and_token, tmp_path, monkeypatch)
    task = _task()
    _script(form, scenario_routes._plan(), task)
    record = worker.run(task)
    assert "error" not in record, record
    shown = _shown_to_the_grader()
    plans = [call for call in shown if call.get("tool") == PLAN_TOOL]
    assert [call.get("status") for call in plans] == ["applied"], f"the grader was shown {shown}"
    assert _duplicate_written(plans[0]) == DUPLICATE
    assert _kept(worker, task) == shown
    assert testing_provider.pending() == 0


def test_a_refused_call_shows_its_tool_and_status_alone_and_skill_read_shows_nowhere(
        client, user_and_token, scripted, tmp_path, monkeypatch):
    """A native run loads the skill, has its first plan refused, then lands
    one. The grader is shown both plan calls in order: the refused one by its
    tool and status alone, since it changed nothing, and the one that landed
    with what it wrote. skill.read is not shown, so the grader cannot tell a
    run that held the skill from one that did not."""
    worker = _worker(client, user_and_token, tmp_path, monkeypatch)
    task = _task()
    refused = scenario_routes._plan()
    refused["scenarios"][0]["nodes"] = ["shadows", "ghost"]
    testing_provider.script_chat_capabilities(tools=True)
    testing_provider.push_replies(
        _call("skill.read", {"name": "scenarios"}), _call(PLAN_TOOL, refused), _call(PLAN_TOOL, scenario_routes._plan()),
        "The plan is in.", _grade(task))
    record = worker.run(task)
    assert "error" not in record, record
    assert record["loadedSkills"] == ["scenarios"], record
    shown = _shown_to_the_grader()
    assert [(call.get("tool"), call.get("status")) for call in shown] == [
        (PLAN_TOOL, "refused"), (PLAN_TOOL, "applied")], shown
    assert set(shown[0]) == {"tool", "status"}, f"a refused call's arguments reached the grader: {shown[0]}"
    assert _duplicate_written(shown[1]) == DUPLICATE
    assert _kept(worker, task) == shown
    assert testing_provider.pending() == 0


def test_what_a_landed_call_wrote_is_scrubbed_then_cut_as_a_changes_texts_are(
        client, user_and_token, scripted, tmp_path, monkeypatch):
    """What a call whose change landed wrote reaches the grader and
    calls.json with the endpoint's secrets taken out, then each text cut
    where a change's texts are cut, in that order: a cut through a secret
    would leave a part of it that no redaction matches."""
    from utk_curio.common.redaction import REDACTED_TEMPLATE
    from utk_curio.tools import skill_eval_worker

    secret = "s3cr3t-0123456789-abcdef"
    worker = _worker(client, user_and_token, tmp_path, monkeypatch, secrets={"eval-key": secret})
    monkeypatch.setattr(skill_eval_worker, "PREVIEW_MAX_CHARS", 40)
    task = _task()
    _script("native call", scenario_routes._plan(goal="x" * 30 + secret + " as they are and doubled"), task)
    record = worker.run(task)
    assert "error" not in record, record
    shown = _shown_to_the_grader()
    plans = [call for call in shown if call.get("tool") == PLAN_TOOL]
    assert [call.get("status") for call in plans] == ["applied"], f"the grader was shown {shown}"
    written = plans[0].get("arguments")
    assert isinstance(written, dict), f"the grader was not shown what the plan wrote: {plans[0]}"
    redacted = "x" * 30 + REDACTED_TEMPLATE.format(name="eval-key") + " as they are and doubled"
    assert written.get("goal") == redacted[:40], written
    kept = _kept(worker, task)
    assert kept == shown
    pieces = {secret[at:at + 8] for at in range(len(secret) - 7)}
    texts = json.dumps(shown) + json.dumps(kept)
    assert not [piece for piece in pieces if piece in texts], "a part of the endpoint's key reached the grader"
