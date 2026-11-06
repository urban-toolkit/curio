"""The skill evaluations' grader sees each task a run delegated, in its place among the calls.

``agent_eval.py skills`` grades a test case's answer by its reply, by what it
changed in its dataflow and by the tools it called (``skill_eval_worker``).
A delegation is no tool call: it never goes through
``tool_rounds._execute_tool_request``, where the worker notes a run's calls,
and a run's record keeps none of its inputs. So neither the grader nor the
run's ``outputs/calls.json`` listed one. In step 8's archived runs of
catalogs' case 2, all 6 runs delegated dataset.discover to the Dataset
Finder, and the grader failed "... or it delegates finding them to the
Dataset Finder" in 4 of 6, with evidence such as "did not actually call the
Dataset Finder tool (the tools called list is empty)".

The worker notes each delegation where a native ``delegate`` call and a
fenced delegateRequest meet, as it starts and as it ends, and shows it in its
place among the calls, as a call of ``delegate``: the capability it asked
for, the agent that took it, its status and the inputs the model wrote for
it, scrubbed, then cut. A delegation no agent took shows its capability and
status alone, and skill.read is still never shown.

Each run is the worker's own (``Worker.run``, its seams installed as a
worker's are, by ``test_skill_eval_calls._worker``, which puts them back
after the test), on the scripted provider (``testing_provider``), which
answers the delegated runs and grades too.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.tests.test_agents import test_skill_eval_calls as calls
from utk_curio.backend.tests.test_agents.test_skill_eval_calls import scripted  # noqa: F401 - the fixture below

#: Every run here is on the scripted model, with nothing queued before or after it.
pytestmark = pytest.mark.usefixtures("scripted")

NB = "agent.curio.node-builder@1"
DF = "agent.curio.dataset-finder@1"
CA = "curio.builtin/python-computation"
#: The tool a delegation is a call of, natively and as the grader is shown it.
DELEGATE = "delegate"
SKILL = "catalogs"
#: Catalogs' case 2, which the Node Builder's chat answers.
MESSAGE = ("The City of Chicago's data portal has a building footprints dataset. "
           "Get it into this project so a node can load it.")
ASSERTIONS = (
    "The answer creates no loader node whose code holds a URL, a file name or a dataset id that no tool returned.",
    "The answer says the footprints come into the Data Catalog as a dataset, downloaded from the portal through "
    "the Discovery Catalog or the Dataset Finder, or it delegates finding them to the Dataset Finder.",
    "The answer does not claim the footprints are already in the Data Catalog, or that a node can load them "
    "before they are downloaded.",
)
#: What the run asks the Dataset Finder for, and the Node Builder's content writer.
FIND = {"intent": "building footprints of the City of Chicago, from its data portal"}
WRITE = {"nodeType": CA, "intent": "count the building footprints of each community area"}
#: The Dataset Finder's reply: one portal row, with no URL to probe.
CANDIDATES = "One source fits.\n```curio.v1\n" + json.dumps({"datasetCandidates": {"lanes": {
    "external": [{"name": "Building Footprints", "sourceType": "portal", "provider": "City of Chicago"}],
    "catalog": [],
}}}) + "\n```"
#: The content writer's reply: the code of the new node.
CODE = "import pandas as pd\n\nreturn pd.DataFrame({'area': [], 'footprints': []})"
FINAL = "The Dataset Finder found a source on the portal: pick it, and a node will load it."
#: The protocols a run delegates in: native, and fenced.
FORMS = ("native call", "fenced block")


def _task():
    """A run of catalogs' case 2 with the skill, on the Node Builder's chat
    over an empty dataflow."""
    from utk_curio.backend.app.agents.evaluation import skill_evals

    return skill_evals.Task(
        kind=skill_evals.TASK, skill=SKILL, key="eval-2/with_skill/run-1", condition=skill_evals.WITH_SKILL,
        run=1, message=MESSAGE, context=skill_evals.Context(agent=NB, dataflow=None), case=2,
        expected_output="The footprints come into the Data Catalog first, or the search goes to the Dataset Finder.",
        assertions=ASSERTIONS,
    )


def _asks(form: str, tool: str, params: dict):
    """A reply that calls *tool* with *params* in *form*."""
    if form == "native call":
        return calls._call(tool, dict(params))
    return "```curio.v1\n" + json.dumps({"toolRequest": {"tool": tool, "params": params}}) + "\n```"


def _delegates(form: str, capability: str, inputs: dict):
    """A reply that delegates *capability* with *inputs* in *form*."""
    if form == "native call":
        return calls._call(DELEGATE, {"capability": capability, "inputs": dict(inputs)})
    return "```curio.v1\n" + json.dumps({"delegateRequest": {"capability": capability, "inputs": inputs}}) + "\n```"


def _delegations(shown: list) -> list:
    """The delegations among the calls the grader was shown."""
    return [call for call in shown if call.get("tool") == DELEGATE]


@pytest.mark.parametrize("form", FORMS)
def test_the_grader_sees_each_delegation_in_its_place_among_the_calls(
        form, client, user_and_token, tmp_path, monkeypatch):
    """The run loads the skill, asks the Dataset Finder for the footprints,
    reads the dataflow, then has the Node Builder write a loader's code. The
    grader is shown both delegations in their places around the read, each
    with its capability, the agent that took it, its outcome and the inputs
    the model wrote for it, not those the runtime added (the catalog listing,
    the reply's contract); nothing of a delegated run's own record, and no
    skill.read, whichever protocol made them. A person reading the results
    reads the same."""
    worker = calls._worker(client, user_and_token, tmp_path, monkeypatch)
    task = _task()
    testing_provider.script_chat_capabilities(tools=form == "native call")
    testing_provider.push_replies(
        _asks(form, "skill.read", {"name": SKILL}),
        _delegates(form, "dataset.discover", FIND), CANDIDATES,
        _asks(form, "dataflow.read", {}),
        _delegates(form, "node.content.generate", WRITE), CODE,
        FINAL, calls._grade(task),
    )
    record = worker.run(task)
    assert "error" not in record, record
    assert record["loadedSkills"] == [SKILL], record
    shown = calls._shown_to_the_grader()
    assert [(call.get("tool"), call.get("capability"), call.get("agent"), call.get("status")) for call in shown] == [
        (DELEGATE, "dataset.discover", DF, "ok"),
        ("dataflow.read", None, None, "ok"),
        (DELEGATE, "node.content.generate", NB, "ok"),
    ], f"the grader was shown {shown}"
    found, written = _delegations(shown)
    assert found.get("inputs") == FIND, found
    assert written.get("inputs") == WRITE, written
    for delegation in (found, written):
        assert set(delegation) == {"tool", "capability", "agent", "status", "inputs"}, delegation
    assert SKILL not in json.dumps(shown), f"the grader can tell the run held {SKILL}: {shown}"
    assert calls._kept(worker, task) == shown
    assert testing_provider.pending() == 0


def test_a_delegation_no_agent_takes_shows_its_capability_and_status_alone(
        client, user_and_token, tmp_path, monkeypatch):
    """A capability no agent declares is refused before any agent runs: the
    grader is shown the delegation by its capability and status, and no
    inputs, which reached no agent."""
    worker = calls._worker(client, user_and_token, tmp_path, monkeypatch)
    task = _task()
    testing_provider.script_chat_capabilities(tools=True)
    testing_provider.push_replies(
        _delegates("native call", "nothing.declares.this", FIND), "No agent here finds datasets.", calls._grade(task))
    record = worker.run(task)
    assert "error" not in record, record
    shown = calls._shown_to_the_grader()
    assert shown == [{"tool": DELEGATE, "capability": "nothing.declares.this", "status": "refused"}], (
        f"the grader was shown {shown}")
    assert calls._kept(worker, task) == shown
    assert testing_provider.pending() == 0


def test_a_delegations_inputs_are_scrubbed_then_cut_as_a_calls_arguments_are(
        client, user_and_token, tmp_path, monkeypatch):
    """The inputs a delegation was given reach the grader and calls.json with
    the endpoint's secrets taken out, then each text cut where a change's
    texts are cut, in that order: a cut through a secret would leave a part
    of it that no redaction matches."""
    from utk_curio.common.redaction import REDACTED_TEMPLATE
    from utk_curio.tools import skill_eval_worker

    secret = "s3cr3t-0123456789-abcdef"
    worker = calls._worker(client, user_and_token, tmp_path, monkeypatch, secrets={"eval-key": secret})
    monkeypatch.setattr(skill_eval_worker, "PREVIEW_MAX_CHARS", 40)
    task = _task()
    testing_provider.script_chat_capabilities(tools=True)
    testing_provider.push_replies(
        _delegates("native call", "dataset.discover", {"intent": "x" * 30 + secret + " building footprints"}),
        CANDIDATES, FINAL, calls._grade(task),
    )
    record = worker.run(task)
    assert "error" not in record, record
    shown = calls._shown_to_the_grader()
    delegations = _delegations(shown)
    assert len(delegations) == 1, f"the grader was shown {shown}"
    inputs = delegations[0].get("inputs")
    assert isinstance(inputs, dict), f"the grader was not shown the delegation's inputs: {delegations[0]}"
    redacted = "x" * 30 + REDACTED_TEMPLATE.format(name="eval-key") + " building footprints"
    assert inputs.get("intent") == redacted[:40], inputs
    kept = calls._kept(worker, task)
    assert kept == shown
    pieces = {secret[at:at + 8] for at in range(len(secret) - 7)}
    texts = json.dumps(shown) + json.dumps(kept)
    assert not [piece for piece in pieces if piece in texts], "a part of the endpoint's key reached the grader"
    assert testing_provider.pending() == 0
