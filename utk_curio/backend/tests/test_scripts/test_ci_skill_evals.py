"""The Skill evaluations workflow's steps: masking the endpoint's host, reading the models, and failing a run that cannot measure.

``scripts/ci_skill_evals.py`` runs in the Skill evaluations workflow: on the runner it
has GitHub mask the base URL's host, and in the CI image it probes each model
of ``CURIO_EVAL_MODELS``, runs those that answer and fails on what the report
says. No model is called here: the probe is replaced, and a model that does
not answer must start no runner.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
KEY = "sk-test-0123456789abcdef"
BASE_URL = "https://models.example.invalid:8443/v1/"


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


node = _load("ci_skill_evals")


def test_the_url_s_host_and_its_host_and_port_are_masked_and_nothing_else_is_printed(monkeypatch, capsys):
    assert node.masks(BASE_URL) == [BASE_URL.rstrip("/"), "models.example.invalid:8443", "models.example.invalid"]
    monkeypatch.setenv(node.ENV_BASE_URL, BASE_URL)
    assert node.cmd_mask(None) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines and all(line.startswith("::add-mask::") for line in lines)
    monkeypatch.delenv(node.ENV_BASE_URL)
    assert node.cmd_mask(None) == 0 and capsys.readouterr().out == ""


def test_the_deploy_masks_the_url_of_the_variable_it_names(monkeypatch, capsys):
    monkeypatch.delenv(node.ENV_BASE_URL, raising=False)
    monkeypatch.setenv("CURIO_DEPLOY_BASE_URL", BASE_URL)
    assert node.main(["mask", "--env", "CURIO_DEPLOY_BASE_URL"]) == 0
    assert capsys.readouterr().out.splitlines() == [f"::add-mask::{value}" for value in node.masks(BASE_URL)]
    assert node.main(["mask"]) == 0 and capsys.readouterr().out == ""


def test_the_models_and_each_one_s_workers_come_from_the_repository_s_variables():
    assert node.models_from('["gemma4", "openai/Qwen/Qwen3.8-27B", "gemma4"]') == ["gemma4", "openai/Qwen/Qwen3.8-27B"]
    assert node.models_from("") == []
    for value in ("gemma4", '{"model": "gemma4"}', '["gemma4", 3]', '[""]'):
        with pytest.raises(ValueError, match="JSON list of model names"):
            node.models_from(value)
    assert node.jobs_for("", "gemma4") == node.DEFAULT_JOBS
    assert node.jobs_for("2", "gemma4") == 2
    per_model = '{"gemma4": 2, "default": 3}'
    assert (node.jobs_for(per_model, "gemma4"), node.jobs_for(per_model, "muse-glimmer")) == (2, 3)
    assert node.jobs_for('{"gemma4": 2}', "muse-glimmer") == node.DEFAULT_JOBS
    for value in ("0", "true", '{"gemma4": "two"}'):
        with pytest.raises(ValueError, match="whole number above 0"):
            node.jobs_for(value, "gemma4")


def test_each_model_is_graded_by_the_first_grader_named_that_is_not_itself():
    assert node.graders_from("") == [] and node.graders_from(" claude-haiku-5-5 ") == ["claude-haiku-5-5"]
    graders = node.graders_from('["openai/Qwen/Qwen3.8-27B", "claude-haiku-5-5", "openai/Qwen/Qwen3.8-27B"]')
    assert graders == ["openai/Qwen/Qwen3.8-27B", "claude-haiku-5-5"]
    assert node.grader_for("gemma4", graders) == "openai/Qwen/Qwen3.8-27B"
    # The best grader's own answers go to the next one.
    assert node.grader_for("openai/Qwen/Qwen3.8-27B", graders) == "claude-haiku-5-5"
    # With no other grader named, a model grades its own answers, as with none named.
    assert node.grader_for("claude-haiku-5-5", ["claude-haiku-5-5"]) is None
    assert node.grader_for("gemma4", []) is None
    for value in ('["gemma4", 3]', "[gemma4", '{"model": "gemma4"}'):
        with pytest.raises(ValueError, match="a model's name or a JSON list of them"):
            node.graders_from(value)


def _scope(tmp_path: Path, scope: dict) -> Path:
    path = tmp_path / "scope-in.json"
    path.write_text(json.dumps(scope), encoding="utf-8")
    return path


def _run(tmp_path, scope_file, out=None):
    import argparse

    out = out or tmp_path / "out"
    return node.cmd_run(argparse.Namespace(scope=str(scope_file), out=str(out), previous=None)), out


def test_a_run_without_the_secrets_says_how_to_measure_a_fork_s_change(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(node.ENV_BASE_URL, raising=False)
    monkeypatch.delenv(node.ENV_API_KEY, raising=False)
    code, _ = _run(tmp_path, _scope(tmp_path, {"measure": "smoke", "measures": {"nodes": {}}}))
    assert code == 1
    assert "dispatch the Full stack build on it with skill_evals" in capsys.readouterr().err


def test_a_scope_that_could_not_be_read_fails_the_node(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(node.ENV_BASE_URL, BASE_URL)
    monkeypatch.setenv(node.ENV_API_KEY, KEY)
    code, _ = _run(tmp_path, _scope(tmp_path, {"version": 1, "error": "KeyError: 'GITHUB_SHA'"}))
    assert code == 1
    assert "the run's scope could not be read: KeyError" in capsys.readouterr().err


def test_a_model_that_does_not_answer_its_probe_runs_nothing_and_fails_the_node(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(node.ENV_BASE_URL, BASE_URL)
    monkeypatch.setenv(node.ENV_API_KEY, KEY)
    monkeypatch.setenv(node.ENV_MODELS, '["gemma4", "claude-haiku-5-5"]')
    monkeypatch.delenv(node.ENV_JOBS, raising=False)
    asked = []

    def probe(model, base_url, api_key, scrub):
        asked.append((model, base_url, api_key))
        return {"ok": False, "error": scrub(f"APIConnectionError: could not reach {BASE_URL} with {KEY}"),
                "attempts": 2}

    def no_runner(*args, **kwargs):
        raise AssertionError("a model that did not answer started a runner")

    monkeypatch.setattr(node, "probe", probe)
    monkeypatch.setattr(node.subprocess, "Popen", no_runner)
    code, out = _run(tmp_path, _scope(tmp_path, {"measure": "smoke", "why": ["agent code changed"],
                                                 "measures": {"nodes": {}}}))
    assert code == 1
    assert sorted(model for model, _, _ in asked) == ["claude-haiku-5-5", "gemma4"]
    captured = capsys.readouterr()
    assert "gemma4 did not answer its probe" in captured.err
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "claude-haiku-5-5 did not answer its probe" in summary
    # No output, the log among them, names the key, the base URL or its host.
    for text in [captured.out, captured.err] + [path.read_text(encoding="utf-8")
                                                for path in out.rglob("*") if path.is_file()]:
        assert KEY not in text and "models.example.invalid" not in text


def test_a_model_whose_grader_does_not_answer_its_probe_runs_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(node.ENV_BASE_URL, BASE_URL)
    monkeypatch.setenv(node.ENV_API_KEY, KEY)
    monkeypatch.setenv(node.ENV_MODELS, '["gemma4"]')
    monkeypatch.setenv(node.ENV_GRADER, '["openai/Qwen/Qwen3.8-27B", "claude-haiku-5-5"]')
    monkeypatch.delenv(node.ENV_JOBS, raising=False)
    asked = []

    def probe(model, base_url, api_key, scrub):
        asked.append(model)
        if model == "openai/Qwen/Qwen3.8-27B":
            return {"ok": False, "error": "InternalServerError 502", "attempts": 2}
        return {"ok": True, "seconds": 1.0}

    def no_runner(*args, **kwargs):
        raise AssertionError("a model whose grader did not answer started a runner")

    monkeypatch.setattr(node, "probe", probe)
    monkeypatch.setattr(node.subprocess, "Popen", no_runner)
    code, out = _run(tmp_path, _scope(tmp_path, {"measure": "smoke", "measures": {"nodes": {}}}))
    assert code == 1
    # Only the grader of gemma4's answers is probed beside it.
    assert sorted(asked) == ["gemma4", "openai/Qwen/Qwen3.8-27B"]
    assert "gemma4 by openai/Qwen/Qwen3.8-27B" in capsys.readouterr().out
    assert ("its grader, openai/Qwen/Qwen3.8-27B, did not answer its probe"
            in (out / "summary.md").read_text(encoding="utf-8"))


def test_a_runner_s_lines_reach_the_log_scrubbed(capsys):
    from utk_curio.backend.app.agents.evaluation import skill_evals
    from utk_curio.backend.app.agents.evaluation.report import scrub

    secrets = skill_evals.Endpoint(base_url=BASE_URL, api_key=KEY, model="gemma4").secrets()

    class Process:
        stdout = io.StringIO(f"[1/2] nodes/eval-1/with_skill/run-1 12.0s\nfailed on {BASE_URL} with {KEY}\n")

    node._stream(Process(), "gemma4", lambda text: scrub(text, values=secrets))
    printed = capsys.readouterr().out
    assert "[gemma4] [1/2] nodes/eval-1/with_skill/run-1 12.0s" in printed
    assert KEY not in printed and "models.example.invalid" not in printed
