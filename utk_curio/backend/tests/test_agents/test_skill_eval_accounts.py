"""Each run of the skill evaluations, and each try of it, is in an evaluation account of its own.

``agent_eval.py skills`` hands each worker its runs (``skill_eval_worker``).
A run adds to its account the model packages its test case names
(``models``) and the packages its dataflow lists. When a worker's runs shared
one account, what one run added stayed for the worker's later runs: a run's
catalogs, its ``models.search`` and the packages its node code could load
hung on which runs had landed on its worker before it, which a fixed
benchmark must not.

Each run, and each try of it, signs in to a new account, made as the
worker's first is, with the same display name. Of the account before it, it
keeps only what the endpoint was found to do beyond text
(``chat_capabilities``): whether its model calls tools natively, which Curio
asks an endpoint its table does not know once, with a charged request, and
each account remembers.

The runs are the worker's own (``Worker.run``, its seams installed as a
worker's are, by ``test_skill_eval_calls._worker``, which puts them back
after the test), on the scripted provider (``testing_provider``), which
grades too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.tests.test_agents import test_skill_eval_calls as calls
from utk_curio.backend.tests.test_agents.test_skill_eval_calls import scripted  # noqa: F401 - the runs' fixture

REPO_ROOT = Path(__file__).resolve().parents[4]
#: Node-functions' case 3 names this model, which models.search lists by its id.
MODEL, MODEL_ID = "model.curio.ddrnet23-slim@1", "model.curio.ddrnet23-slim"
#: A package a case's dataflow may list, which no new account holds.
PACKAGE = "curio.vega-lite@1"
#: The display name of every evaluation account.
ACCOUNT_NAME = "Skill evaluation"


def _task(run: int, *, models: tuple = (), dataflow: Path | None = None):
    """Run *run* of scenarios' case 2 with the skill, on the Dataflow
    Builder's chat, its case naming *models* and its dataflow *dataflow*."""
    from utk_curio.backend.app.agents.evaluation import skill_evals

    return skill_evals.Task(
        kind=skill_evals.TASK, skill="scenarios", key=f"eval-2/with_skill/run-{run}",
        condition=skill_evals.WITH_SKILL, run=run, message=calls.MESSAGE,
        context=skill_evals.Context(agent=calls.DFB, dataflow=dataflow, models=models), case=2,
        expected_output="A plan with a scenario, and a duplicate of it whose values double the height factor.",
        assertions=calls.ASSERTIONS,
    )


def _held(worker) -> set[str]:
    """The packages the account the worker is signed in to holds, as its
    Package Catalog shows them."""
    resp = worker.client.get("/api/packages/catalog", headers=worker.headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {row["dirName"] for row in resp.get_json()["packages"] if row.get("installed")}


def _listed(worker) -> list[str]:
    """The models that account's models.search lists."""
    from utk_curio.backend.app.agents.application import tools

    status, text = tools.execute_read_tool("models.search", user_key=worker.user_key, project_id="", target=None,
                                           params={})
    assert status == "ok", text
    return [row["id"] for row in json.loads(text)["models"]]


@pytest.mark.usefixtures("scripted")
def test_a_run_holds_no_model_or_package_an_earlier_run_s_case_added(
        client, user_and_token, tmp_path, monkeypatch):
    """The first run's case names a model and its dataflow lists a package:
    its account holds both, as its Package Catalog and its models.search
    show. The worker's next run, of a case that names neither, is in an
    account of its own, with the same display name, that holds neither."""
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.users.models import User

    # The package catalog Curio ships, as the worker's runner copies it.
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(REPO_ROOT / "packages"))
    worker = calls._worker(client, user_and_token, tmp_path, monkeypatch)
    flow = tmp_path / "flow.json"
    flow.write_text(json.dumps({"dataflow": {"nodes": [], "edges": [], "packages": [PACKAGE]}}), encoding="utf-8")
    seen = []
    for task in (_task(1, models=(MODEL,), dataflow=flow), _task(2)):
        testing_provider.push_replies("The plan is in.", calls._grade(task))
        record = worker.run(task)
        assert "error" not in record, record
        seen.append((worker.user_key, _held(worker), _listed(worker)))
    (first, first_held, first_listed), (second, second_held, second_listed) = seen
    assert {MODEL, PACKAGE} <= first_held, f"the first run's account holds {sorted(first_held)}"
    assert first_listed == [MODEL_ID], f"the first run's models.search lists {first_listed}"
    assert not {MODEL, PACKAGE} & second_held, f"the second run's account holds {sorted(second_held)}"
    assert second_listed == [], f"the second run's models.search lists {second_listed}"
    assert second != first, "the second run was in the first run's account"
    names = {_user_dir_key(user): user.name for user in User.query.all()}
    assert names[first] == names[second] == ACCOUNT_NAME


@pytest.mark.usefixtures("scripted")
def test_each_try_of_a_run_is_in_an_account_of_its_own(
        client, user_and_token, tmp_path, monkeypatch):
    """The model's server failed the first try (a 503), after the try had
    added its case's model to its account. The run is tried again in a new
    account, which holds no model until that try adds it."""
    from utk_curio.tools import skill_eval_worker

    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(REPO_ROOT / "packages"))
    monkeypatch.setattr(skill_eval_worker, "RETRY_WAITS_S", (0,))
    worker = calls._worker(client, user_and_token, tmp_path, monkeypatch)
    tries = []
    attempt = worker._attempt

    def _attempt(*args):
        tries.append((worker.user_key, _listed(worker)))
        return attempt(*args)

    monkeypatch.setattr(worker, "_attempt", _attempt)
    task = _task(1, models=(MODEL,))
    testing_provider.push_replies({"error": "the server is busy", "status": 503}, "The plan is in.", calls._grade(task))
    record = worker.run(task)
    assert "error" not in record and record["attempts"] == 2, record
    assert len({key for key, _ in tries}) == 2, f"the tries were in the accounts {tries}"
    assert [listed for _, listed in tries] == [[], []], f"a try's account held a model before it added one: {tries}"
    assert _listed(worker) == [MODEL_ID]


def test_each_account_starts_with_what_the_endpoint_was_found_to_do(app, monkeypatch):
    """The suite's endpoint is one Curio's table does not know, so a run's
    first call asks it, once, whether its model calls tools natively, and the
    account remembers the answer. The next run's account starts with it: no
    run asks again, and each speaks the protocol a run before it found, a run
    whose native tools the endpoint refused among them."""
    from utk_curio.backend.app.agents.infrastructure import chat_capabilities, provider_config, providers
    from utk_curio.tools import skill_eval_worker

    asked = []

    def _probe(config, usage_out=None):
        asked.append(config.model)
        return True, "the model called the tool it was offered", providers.TRIAL_CALLED

    monkeypatch.setattr(providers, "probe_native_tools", _probe)
    worker = skill_eval_worker.Worker.__new__(skill_eval_worker.Worker)
    worker._sign_in()
    accounts = [worker.user_key]
    endpoint = provider_config.deployment_config(worker.user_key)
    assert chat_capabilities.chat_capabilities(endpoint, worker.user_key).protocol == "native"
    assert len(asked) == 1
    worker._sign_in()
    accounts.append(worker.user_key)
    found = chat_capabilities.chat_capabilities(endpoint, worker.user_key)
    assert (found.protocol, found.source) == ("native", chat_capabilities.SOURCE_REMEMBERED)
    assert len(asked) == 1, "a new account asked the endpoint again"
    # This run's native tools are refused, and its fenced retry gets past.
    chat_capabilities.record_native_refusal(endpoint, worker.user_key, "Error code: 400")
    worker._sign_in()
    accounts.append(worker.user_key)
    found = chat_capabilities.chat_capabilities(endpoint, worker.user_key)
    assert (found.protocol, found.source) == ("fenced", chat_capabilities.SOURCE_REMEMBERED)
    assert len(asked) == 1, "a new account asked the endpoint again"
    assert len(set(accounts)) == 3
