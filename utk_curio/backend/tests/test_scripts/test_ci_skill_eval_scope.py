"""What a run of the Skill evaluations workflow measures: what its scope asks, or what the branch changes.

``scripts/ci_skill_eval_scope.py`` runs first in that workflow and decides
whether it calls a model at all, and on which skills. For ``auto``, a changed
skill is measured whole, every skill's test cases for a core skill, one smoke
case per skill for agent text or code, and nothing for anything else. A wrong
answer either spends the owner's model server on nothing or lets a skill
change go unmeasured, so these feed it changes shaped like a diff, on a small
tree of skills, and check the real tree's core skills too.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scope = _load("ci_skill_eval_scope")
Change = scope.Change


def _skill(root: Path, folder: str, *, description: str = "Use this skill when counting trees.",
           queries: list | None = None) -> None:
    path = root / folder
    (path / "evals").mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {path.name}\ndescription: >-\n  {description}\nlicense: MIT\n---\n## Body\n", encoding="utf-8")
    (path / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": path.name, "evals": [{"id": 1}],
        "trigger_queries": queries if queries is not None else [{"query": "q", "should_trigger": True}],
    }), encoding="utf-8")


@pytest.fixture()
def tree(tmp_path):
    """Three skills of skills/ (one of them core, placed by the preamble), one
    of a package, one without evaluations, and the base entry of agents/."""
    for name in ("trees", "birds", "nodes"):
        _skill(tmp_path, f"skills/{name}")
    _skill(tmp_path, "packages/curio.parks@1/skills/parks")
    (tmp_path / "skills" / "drafts").mkdir()
    (tmp_path / "skills" / "drafts" / "SKILL.md").write_text("---\nname: drafts\n---\n", encoding="utf-8")
    base = tmp_path / "agents" / "agent.curio.builtin@1"
    base.mkdir(parents=True)
    (base / "manifest.json").write_text(json.dumps({"kind": "base"}), encoding="utf-8")
    (base / "default_preamble.md").write_text("You are Curio.\n{{skill:nodes}}\n", encoding="utf-8")
    (base / "tools.md").write_text("## tools\nNo skill here.\n", encoding="utf-8")
    # A README that shows the placeholder as an example places nothing.
    (base / "README.md").write_text("Write {{skill:trees}} to place a skill.\n", encoding="utf-8")
    return tmp_path


def _old(tree: Path, edits: dict | None = None):
    """A reader of main's text: the tree as it is, with *edits* (path to old text, None if absent)."""
    edits = edits or {}

    def old_text(path: str):
        if path in edits:
            return edits[path]
        file = tree / path
        return file.read_text(encoding="utf-8") if file.is_file() else None

    return old_text


def _measures(found: dict) -> dict:
    return {name: (m["kinds"], m["runs"], tuple(m["conditions"]), m["cases"])
            for name, m in found["measures"].items()}


WHOLE = (["trigger", "task"], 3, ("with_skill", "without_skill"), None)
CASES = (["task"], 3, ("with_skill", "without_skill"), None)
SMOKE = (["task"], 1, ("with_skill",), 1)


def test_the_core_skills_are_those_the_base_entry_s_pages_place(tree):
    assert scope.core(tree) == ({"agents/agent.curio.builtin@1/default_preamble.md"}, {"nodes"})
    assert sorted(scope.skills_with_evals(tree)) == ["birds", "nodes", "parks", "trees"]


def test_a_changed_skill_s_body_measures_its_test_cases_both_ways(tree):
    found = scope.from_changes([Change("M", "skills/trees/SKILL.md")], root=tree, old_text=_old(tree))
    assert _measures(found) == {"trees": CASES}
    assert found["measure"] == "changed"


def test_a_new_skill_or_a_new_description_or_new_trigger_queries_measures_its_triggers_too(tree):
    new = scope.from_changes([Change("A", "skills/trees/SKILL.md"), Change("A", "skills/trees/evals/evals.json")],
                             root=tree, old_text=_old(tree, {"skills/trees/SKILL.md": None}))
    assert _measures(new) == {"trees": WHOLE}
    old_skill = (tree / "skills/trees/SKILL.md").read_text(encoding="utf-8").replace("counting", "naming")
    described = scope.from_changes([Change("M", "skills/trees/SKILL.md")], root=tree,
                                   old_text=_old(tree, {"skills/trees/SKILL.md": old_skill}))
    assert _measures(described) == {"trees": WHOLE}
    asked = scope.from_changes([Change("M", "skills/trees/evals/evals.json")], root=tree,
                               old_text=_old(tree, {"skills/trees/evals/evals.json": json.dumps(
                                   {"skill_name": "trees", "trigger_queries": []})}))
    assert _measures(asked) == {"trees": WHOLE}
    # A test case's change alone keeps the triggers out.
    cases = scope.from_changes([Change("M", "skills/trees/evals/evals.json")], root=tree,
                               old_text=_old(tree, {"skills/trees/evals/evals.json": json.dumps({
                                   "skill_name": "trees", "evals": [],
                                   "trigger_queries": [{"query": "q", "should_trigger": True}]})}))
    assert _measures(cases) == {"trees": CASES}


def test_a_package_s_skill_is_a_skill_too(tree):
    found = scope.from_changes([Change("M", "packages/curio.parks@1/skills/parks/SKILL.md")], root=tree,
                               old_text=_old(tree))
    assert _measures(found) == {"parks": CASES}


def test_a_core_skill_or_its_page_measures_every_skill_s_test_cases(tree):
    for path in ("skills/nodes/SKILL.md", "agents/agent.curio.builtin@1/default_preamble.md"):
        found = scope.from_changes([Change("M", path)], root=tree, old_text=_old(tree))
        assert found["measure"] == "core", path
        assert _measures(found) == {name: CASES for name in ("birds", "nodes", "parks", "trees")}, path
    # A core skill's own evaluations are in no prompt: they measure it alone.
    own = scope.from_changes([Change("M", "skills/nodes/evals/evals.json")], root=tree, old_text=_old(tree))
    assert own["measure"] == "changed" and _measures(own) == {"nodes": CASES}
    # A changed skill keeps its triggers beside a core change.
    old_skill = (tree / "skills/trees/SKILL.md").read_text(encoding="utf-8").replace("counting", "naming")
    both = scope.from_changes([Change("M", "skills/nodes/SKILL.md"), Change("M", "skills/trees/SKILL.md")],
                              root=tree, old_text=_old(tree, {"skills/trees/SKILL.md": old_skill}))
    assert _measures(both)["trees"] == WHOLE and _measures(both)["birds"] == CASES


def test_agent_text_or_code_measures_one_smoke_case_of_every_other_skill(tree):
    for path in ("agents/agent.curio.builtin@1/tools.md", "utk_curio/backend/app/agents/application/tools.py",
                 "utk_curio/tools/skill_eval_worker.py", "packages/curio.parks@1/manifest.json",
                 "docs/schemas/trill.v1.json", ".github/workflows/skill-evals.yml",
                 "scripts/ci_skill_evals.py", "scripts/skill_eval_floors.json"):
        found = scope.from_changes([Change("M", path)], root=tree, old_text=_old(tree))
        assert found["measure"] == "smoke", path
        assert _measures(found) == {name: SMOKE for name in ("birds", "nodes", "parks", "trees")}, path
    mixed = scope.from_changes([Change("M", "agents/agent.curio.builtin@1/tools.md"),
                                Change("M", "skills/trees/SKILL.md")], root=tree, old_text=_old(tree))
    assert mixed["measure"] == "changed"
    assert _measures(mixed) == {"trees": CASES, "birds": SMOKE, "nodes": SMOKE, "parks": SMOKE}


def test_anything_else_measures_nothing(tree):
    for path in ("docs/USAGE.md", "utk_curio/frontend/urban-workflows/src/App.tsx",
                 "packages/curio.parks@1/sources/index.tsx", ".github/workflows/docker-compose.yml"):
        found = scope.from_changes([Change("M", path)], root=tree, old_text=_old(tree))
        assert found["measures"] == {} and found["measure"] == "none", path
    gone = scope.from_changes([Change("D", "skills/gone/SKILL.md")], root=tree, old_text=_old(tree))
    assert gone["measures"] == {} and any("is gone" in line for line in gone["why"])
    unevaluated = scope.from_changes([Change("M", "skills/drafts/SKILL.md")], root=tree, old_text=_old(tree))
    assert unevaluated["measures"] == {} and any("no evals/evals.json" in line for line in unevaluated["why"])


def _event(tree, event, *, value="auto", ref="feat/x"):
    called = []

    def changes():
        called.append(True)
        return [Change("M", "skills/trees/SKILL.md")], _old(tree)

    found = scope.for_event(event=event, ref=ref, value=value, root=tree, changes=changes)
    return found, bool(called)


def test_only_a_run_started_by_hand_measures_and_a_before_run_s_auto_measures_nothing(tree):
    for kwargs in ({"event": "push"}, {"event": "schedule"}, {"event": "pull_request", "value": "full"},
                   {"event": "workflow_dispatch", "ref": "tmp/skill-evals-before"}):
        found, read = _event(tree, **kwargs)
        assert found["measures"] == {} and not read, kwargs
    # A before-run asked for a measure gets it.
    found, read = _event(tree, "workflow_dispatch", value="smoke", ref="tmp/skill-evals-before")
    assert found["measure"] == "smoke" and not read
    found, read = _event(tree, "workflow_dispatch")
    assert _measures(found) == {"trees": CASES} and read


def test_a_dispatch_measures_what_its_input_says(tree):
    found, read = _event(tree, "workflow_dispatch", value="full")
    assert _measures(found) == {name: WHOLE for name in ("birds", "nodes", "parks", "trees")} and not read
    assert _measures(_event(tree, "workflow_dispatch", value="core")[0])["parks"] == CASES
    assert _measures(_event(tree, "workflow_dispatch", value="smoke")[0])["birds"] == SMOKE
    assert _measures(_event(tree, "workflow_dispatch", value="trees, parks")[0]) == {"trees": WHOLE, "parks": WHOLE}
    assert _event(tree, "workflow_dispatch", value="none")[0]["measures"] == {}
    found, read = _event(tree, "workflow_dispatch")
    assert _measures(found) == {"trees": CASES} and read
    with pytest.raises(ValueError, match="no skill holds evals/evals.json named nowhere"):
        _event(tree, "workflow_dispatch", value="trees,nowhere")


def test_each_measure_is_one_the_evaluations_read(tree):
    from utk_curio.backend.app.agents.evaluation import skill_evals

    found = scope.from_changes([Change("M", "skills/nodes/SKILL.md"), Change("M", "agents/x.md")], root=tree,
                               old_text=_old(tree))
    read = skill_evals.measures(json.loads(json.dumps(found)))
    assert all(measure.whole for measure in read.values())
    assert skill_evals.Measure.from_dict(scope.WHOLE).whole and skill_evals.Measure.from_dict(scope.CASES).whole
    assert not skill_evals.Measure.from_dict(scope.SMOKE).whole
    assert scope.RUNS == skill_evals.RUNS


def test_on_github_a_scope_goes_to_the_step_s_output_or_nothing_and_a_failure_is_written_down(tmp_path, monkeypatch):
    output, summary = tmp_path / "output", tmp_path / "summary"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert scope.main(["--github"]) == 0
    assert output.read_text(encoding="utf-8") == "skill_evals=\n"
    assert "- a push event measures nothing: the workflow measures when it is started" in summary.read_text(
        encoding="utf-8")

    output.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("SKILL_EVALS", "smoke")
    assert scope.main(["--github"]) == 0
    written = output.read_text(encoding="utf-8")
    assert written.startswith("skill_evals={") and "\n" not in written.rstrip("\n")
    assert json.loads(written.split("=", 1)[1])["measure"] == "smoke"

    # A failure while reading the run is written down for the run to fail on.
    output.write_text("", encoding="utf-8")
    monkeypatch.setenv("SKILL_EVALS", "auto")
    monkeypatch.setenv("HEAD_REF", "feat/x")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    assert scope.main(["--github"]) == 0
    assert "error" in json.loads(output.read_text(encoding="utf-8").split("=", 1)[1])


def test_main_s_core_skills_are_the_preamble_s():
    pages, placed = scope.core(REPO_ROOT)
    assert placed == {"nodes", "node-control", "compatibility"}
    assert pages == {"agents/agent.curio.builtin@1/default_preamble.md"}
    shipped = scope.skills_with_evals(REPO_ROOT)
    assert placed <= set(shipped) and {"vega-lite-charts", "rasterization"} <= set(shipped)
