"""A grade run of the skill evaluations (``skill_eval_worker.py``).

The worker grades a prepared answer of the grader truth with the model
measured, through the grade every task run gets: the same page, messages,
output cap and parse. No agent runs and no model is called: the provider is
replaced, and it answers as a grader would.
"""

from __future__ import annotations

import json
import types

from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn


def test_a_grade_run_grades_its_answer_with_the_model_measured_and_runs_no_agent(tmp_path, monkeypatch):
    from utk_curio.backend.app.agents.evaluation import skill_evals
    from utk_curio.tools import skill_eval_worker

    asked: list = []

    def _fake_run(config, messages, max_output_tokens=None, usage_out=None, **kwargs):
        asked.append((config.model, messages[-1]["content"], max_output_tokens))
        return ChatTurn(text=json.dumps({"assertion_results": [
            {"text": "a", "passed": True, "evidence": "It sets the multiplier."},
            {"text": "b", "passed": False, "evidence": "It names no node."}]}), stop_reason="stop")

    monkeypatch.setattr(providers, "run_chat_turn", _fake_run)
    monkeypatch.setattr(skill_eval_worker.provider_config, "resolve_llm",
                        lambda *args, **kwargs: types.SimpleNamespace(model="measured-model"))
    # The benchmark's one grader is named, but a grade run measures its own model as a grader.
    monkeypatch.setenv(skill_eval_worker.ENV_GRADER, "the-benchmark-grader")
    worker = skill_eval_worker.Worker.__new__(skill_eval_worker.Worker)
    worker.results, worker.user_key, worker.secrets = tmp_path, "grader", {}
    worker.endpoint = types.SimpleNamespace(model="measured-model")
    answer = {"name": "wrong-value", "kind": "mutant", "fails": [1], "reply": "I set the multiplier to 3.",
              "changes": {"changed": {}, "cards": [], "awaiting_review": []},
              "calls": [{"tool": "node.settings.write", "status": "applied",
                         "arguments": {"widgets": {"number_multiplier": 3}}}]}
    task = skill_evals.Task(
        kind=skill_evals.GRADE, skill="widgets", key="truth/eval-1/wrong-value/run-1",
        condition=skill_evals.WITH_SKILL, run=1, message="Set the multiplier to 25.",
        context=skill_evals.Context(agent="agent.curio.node-builder@1", dataflow=None), case=1,
        assertions=("The answer sets number_multiplier to 25.", "The answer names the node it changes."),
        answer=answer)

    record = worker.run(task)

    assert [(model, cap) for model, _, cap in asked] == [("measured-model", skill_eval_worker.GRADER_MAX_TOKENS)]
    assert "I set the multiplier to 3." in asked[0][1] and '"number_multiplier": 3' in asked[0][1]
    assert record["grading"]["grader"]["model"] == "measured-model" and "error" not in record
    assert (record["kind"], record["answer"], record["answerKind"], record["fails"]) == (
        skill_evals.GRADE, "wrong-value", "mutant", [1])
    assert [item["passed"] for item in record["grading"]["assertion_results"]] == [True, False]
    folder = tmp_path / task.path
    assert json.loads((folder / "run.json").read_text(encoding="utf-8")) == record
    assert (folder / "outputs" / "reply.md").read_text(encoding="utf-8") == "I set the multiplier to 3.\n"
    assert json.loads((folder / "outputs" / "calls.json").read_text(encoding="utf-8")) == answer["calls"]
    assert json.loads((folder / "outputs" / "changes.json").read_text(encoding="utf-8")) == answer["changes"]
