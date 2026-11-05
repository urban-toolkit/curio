"""The Skill evaluations workflow's report, and what fails a run of it.

``scripts/skill_evals_report.py`` reads each model's ``agent_eval.py skills``
folder and writes ``curio-skill-evals-report.html``, the job summary and each
model's numbers for the next runs to compare with; its :func:`gate` decides
whether the run fails. These feed it run folders made up here, shaped as the
runner writes them, and check the real floors and prices files' shape.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


report = _load("skill_evals_report")

WHOLE = {"kinds": ["trigger", "task"], "runs": 3, "conditions": ["with_skill", "without_skill"], "cases": None}
SMOKE = {"kinds": ["task"], "runs": 1, "conditions": ["with_skill"], "cases": 1}
HAIKU, GEMMA = "claude-haiku-5-5", "gemma4"


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _turn(protocol: str) -> dict:
    return {"role": "agent", "text": "Done.", "execution": {"pins": {"toolProtocol": protocol}}}


def _results(out: Path) -> Path:
    """One model's run folder: trees measured whole (a failed assertion, a cut
    call, a fenced turn and a trigger run left in an error), birds by its
    smoke case."""
    folder = out / "results" / report.slug(HAIKU) / "skills-20261104-200000"
    _write(folder / "run.json", {"run": folder.name, "model": HAIKU, "runs": 3, "kinds": ["trigger", "task"],
                                 "commit": "abc123", "measures": {"trees": WHOLE, "birds": SMOKE}})
    _write(folder / "summary.json", {"finished": "2026-11-04T21:00:00+00:00", "skills": [
        {"skill": "trees", "errors": 1,
         "triggers": {"queries": 2, "judged": 1, "passed": 1, "should_trigger_rate": 0.5,
                      "should_not_trigger_rate": 0.0, "errors": 1, "runs": 5, "handed_off": 0},
         "benchmark": {"with_skill": {"pass_rate": {"mean": 0.5}, "runs": 2, "used": {"runs": 1}},
                       "without_skill": {"pass_rate": {"mean": 0.25}, "runs": 2}}},
        {"skill": "birds", "errors": 0, "triggers": None,
         "benchmark": {"with_skill": {"pass_rate": {"mean": 0.5}, "runs": 1, "used": {"runs": 1}},
                       "without_skill": {"pass_rate": {"mean": None}, "runs": 0}}},
    ]})
    run = folder / "trees" / "eval-1" / "with_skill" / "run-1"
    _write(run / "run.json", {
        "kind": "task", "skill": "trees", "key": "eval-1/with_skill/run-1", "condition": "with_skill", "run": 1,
        "case": 1, "seconds": 90.0, "modelCalls": [{"outputTokens": 10, "cut": True}, {"outputTokens": 20}],
        "timing": {"input_tokens": 1_000_000, "output_tokens": 100_000},
        "grading": {"assertion_results": [
            {"text": "The answer names the <b>oak</b>.", "passed": False, "evidence": "It names elms."},
            {"text": "The answer counts trees.", "passed": True, "evidence": "12 trees."}],
            "summary": {"passed": 1, "failed": 1, "total": 2, "pass_rate": 0.5},
            "grader": {"model": HAIKU, "attempts": 1, "inputTokens": 1_000_000, "outputTokens": 100_000}},
    })
    _write(run / "transcript.json", [{"role": "user", "text": "Count."}, _turn("native"), _turn("fenced")])
    trigger = folder / "trees" / "triggers" / "q01" / "run-1"
    _write(trigger / "run.json", {"kind": "trigger", "skill": "trees", "key": "triggers/q01/run-1", "run": 1,
                                  "query": 1, "error": "the run answered 502: Connection error.", "seconds": 30.0,
                                  "modelCalls": [], "timing": {"input_tokens": 0, "output_tokens": 0}})
    smoke = folder / "birds" / "eval-1" / "with_skill" / "run-1"
    _write(smoke / "run.json", {
        "kind": "task", "skill": "birds", "key": "eval-1/with_skill/run-1", "condition": "with_skill", "run": 1,
        "case": 1, "seconds": 60.0, "modelCalls": [{"outputTokens": 5}],
        "timing": {"input_tokens": 0, "output_tokens": 0},
        "grading": {"assertion_results": [{"text": "It counts robins.", "passed": True, "evidence": ""}],
                    "summary": {"passed": 1, "failed": 0, "total": 1, "pass_rate": 1.0}}})
    _write(smoke / "transcript.json", [_turn("native")])
    return folder


def _config(tmp_path: Path) -> tuple[Path, Path, Path]:
    floors, prices, previous = tmp_path / "floors.json", tmp_path / "prices.json", tmp_path / "previous"
    _write(floors, {"floors": {HAIKU: {"trees": 0.6, "birds": 0.9}}})
    _write(prices, {"prices": {HAIKU: {"input": 0.10, "output": 0.50}}})
    _write(previous / f"{report.slug(HAIKU)}.json", {"skills": {"trees": {"with_skill": 0.4}}})
    return floors, prices, previous


def test_a_model_s_name_becomes_a_folder_and_artifact_name():
    assert report.slug("openai/Qwen/Qwen3.8-27B") == "openai-Qwen-Qwen3.8-27B"
    assert report.slug(HAIKU) == HAIKU


def test_each_skill_is_read_from_its_summary_and_its_runs_records(tmp_path):
    floors, prices, previous = _config(tmp_path)
    folder = _results(tmp_path)
    run = report.read_model(HAIKU, report.run_folder(folder.parent), floors=report.load_config(floors, "floors"),
                            previous=json.loads((previous / f"{HAIKU}.json").read_text(encoding="utf-8")),
                            price=report.load_config(prices, "prices")[HAIKU])
    rows = {row.skill: row for row in run.rows}
    trees, birds = rows["trees"], rows["birds"]
    assert (trees.with_rate, trees.without_rate, round(trees.delta, 4), trees.used) == (0.5, 0.25, 0.25, 1)
    assert trees.whole and not birds.whole
    assert (trees.runs, trees.errors, trees.model_calls, trees.cut_calls) == (2, 1, 2, 1)
    assert dict(trees.turns) == {"native": 1, "fenced": 1}
    # The grader's tokens count too.
    assert (trees.input_tokens, trees.output_tokens) == (2_000_000, 200_000)
    assert round(run.dollars, 4) == round((2_000_000 * 0.10 + 200_000 * 0.50) / 1e6, 4)
    assert report._change(trees) == "+10"
    assert [failure["assertion"] for failure in trees.failures] == ["The answer names the <b>oak</b>."]
    assert trees.failures[0]["path"] == f"{HAIKU}/{folder.name}/trees/eval-1/with_skill/run-1"
    assert trees.triggers["should_trigger_rate"] == 0.5 and birds.triggers is None


def test_the_node_fails_on_a_probe_an_error_a_runner_and_a_floor_and_only_a_whole_measure_meets_a_floor(tmp_path):
    floors, prices, previous = _config(tmp_path)
    _results(tmp_path)
    runs, problems = report.build(tmp_path, [HAIKU, GEMMA], scope={"measure": "changed", "why": ["trees changed"]},
                                  probes={HAIKU: {"ok": True, "seconds": 1.2},
                                          GEMMA: {"ok": False, "error": "APIConnectionError: Connection error."}},
                                  exits={HAIKU: 1}, previous=previous, floors=floors, prices=prices)
    text = "\n".join(problems)
    assert f"{GEMMA} did not answer its probe: APIConnectionError" in text
    assert f"{HAIKU}'s runner ended with 1" in text
    assert f"{HAIKU}: 1 run(s) left in an error" in text and "triggers/q01/run-1" in text
    assert f"{HAIKU}: trees passed 50% with the skill, under its floor of 60%" in text
    # birds is under its floor too, but its smoke case measures no floor.
    assert "birds" not in text
    assert len(problems) == 4


def test_a_run_with_nothing_wrong_passes(tmp_path):
    floors, prices, previous = _config(tmp_path)
    folder = _results(tmp_path)
    (folder / "trees" / "triggers").joinpath("q01", "run-1", "run.json").unlink()
    _write(floors, {"floors": {HAIKU: {"trees": 0.5}}})
    _, problems = report.build(tmp_path, [HAIKU], scope={}, probes={HAIKU: {"ok": True, "seconds": 1.0}},
                               exits={HAIKU: 0}, previous=previous, floors=floors, prices=prices)
    assert problems == []
    assert "**Passed:**" in (tmp_path / report.SUMMARY).read_text(encoding="utf-8")


def test_the_page_the_summary_and_the_numbers_later_runs_compare_with(tmp_path):
    floors, prices, previous = _config(tmp_path)
    _results(tmp_path)
    report.build(tmp_path, [HAIKU, GEMMA], scope={"measure": "changed", "why": ["trees changed"]},
                 probes={HAIKU: {"ok": True, "seconds": 1.2}, GEMMA: {"ok": False, "error": "502"}},
                 previous=previous, floors=floors, prices=prices, run_url="https://example.invalid/run/1",
                 page_url="https://example.invalid/page")
    page = (tmp_path / report.PAGE).read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    for text in (HAIKU, GEMMA, "trees", "birds", "under its floor of 60%", "trees changed",
                 "The answer names the &lt;b&gt;oak&lt;/b&gt;.", f"{HAIKU}/skills-20261104-200000/trees/eval-1",
                 "https://example.invalid/run/1", "abc123"):
        assert text in page, text
    assert "<b>oak</b>" not in page
    summary = (tmp_path / report.SUMMARY).read_text(encoding="utf-8")
    assert "**Failed:**" in summary and "[Open curio-skill-evals-report.html](https://example.invalid/page)" in summary
    assert f"| `{HAIKU}` | answered in 1.2 s |" in summary and "$0.30" in summary
    assert "| trees | triggers, cases x3 both ways | 50% | 25% | +25 | +10 | 60% (under) | 1 of 2 |" in summary
    numbers = json.loads((tmp_path / report.SUMMARIES / f"{HAIKU}.json").read_text(encoding="utf-8"))
    assert numbers["commit"] == "abc123" and numbers["finished"] == "2026-11-04T21:00:00+00:00"
    assert numbers["skills"]["trees"] == {"with_skill": 0.5, "without_skill": 0.25, "whole": True,
                                          "should_trigger": 0.5, "should_not_trigger": 0.0}
    # A model that ran nothing leaves no numbers to compare with.
    assert not (tmp_path / report.SUMMARIES / f"{GEMMA}.json").exists()


def test_the_benchmark_s_leaderboard_and_main_s_last_run(tmp_path):
    """The page and the summary hold the benchmark of each model's run: its
    leaderboard, each skill's success per model, and the run against main's
    last run of the model, case by case, or why they do not compare."""
    from utk_curio.backend.app.agents.evaluation import benchmark

    floors, prices, previous = _config(tmp_path)
    folder = _results(tmp_path)
    scored = benchmark.score(folder)
    # trees passed half its assertions, birds all of its one: 75% over both cases.
    assert scored["overall"]["success"]["value"] == 0.75
    lower = json.loads(json.dumps(scored))
    for entry in lower["cases"].values():
        entry["with_skill"] = [0.0 for _ in entry.get("with_skill") or []]
    _write(previous / f"{report.slug(HAIKU)}.json", {"skills": {}, "benchmark": lower})
    runs, _ = report.build(tmp_path, [HAIKU], scope={}, probes={HAIKU: {"ok": True, "seconds": 1.0}},
                           previous=previous, floors=floors, prices=prices)
    assert runs[0].scored["cases"] == scored["cases"]
    assert runs[0].compared["overall"]["success"]["verdict"] == benchmark.BETTER
    summary = (tmp_path / report.SUMMARY).read_text(encoding="utf-8")
    assert f"### Benchmark, version {scored['version']}" in summary
    assert f"| {HAIKU} | 75% [50, 100] |" in summary
    assert "Against main's last run" in summary and "every case both measured: better, +75" in summary
    page = (tmp_path / report.PAGE).read_text(encoding="utf-8")
    assert "Each skill's success per model" in page and "Fails on (under 50%)" in page
    numbers = json.loads((tmp_path / report.SUMMARIES / f"{HAIKU}.json").read_text(encoding="utf-8"))
    assert numbers["benchmark"]["cases"] == scored["cases"]

    # A run of main on another set is not compared, and the page says why.
    _write(previous / f"{report.slug(HAIKU)}.json", {"skills": {}, "benchmark": {**lower, "version": "another"}})
    report.build(tmp_path, [HAIKU], scope={}, probes={HAIKU: {"ok": True, "seconds": 1.0}}, previous=previous,
                 floors=floors, prices=prices)
    assert ("No comparison with main's last run: the two runs measured different sets"
            in (tmp_path / report.SUMMARY).read_text(encoding="utf-8"))


def test_the_floors_and_the_prices_files_hold_what_the_report_reads():
    from utk_curio.backend.app.agents.evaluation import skill_evals

    floors = json.loads(report.FLOORS.read_text(encoding="utf-8"))
    assert isinstance(floors.get("about"), str) and isinstance(floors.get("floors"), dict)
    shipped = {evals.name for evals in skill_evals.shipped_evals()}
    for model, per_skill in floors["floors"].items():
        assert isinstance(model, str) and model and isinstance(per_skill, dict), model
        for skill, floor in per_skill.items():
            assert skill in shipped, f"{model}'s floor names {skill}, which holds no evals/evals.json"
            assert isinstance(floor, (int, float)) and 0 <= floor <= 1, (model, skill, floor)
    prices = json.loads(report.PRICES.read_text(encoding="utf-8"))
    assert isinstance(prices.get("about"), str) and prices.get("prices")
    for model, price in prices["prices"].items():
        assert set(price) == {"input", "output"}, model
        assert all(isinstance(value, (int, float)) and value >= 0 for value in price.values()), model
