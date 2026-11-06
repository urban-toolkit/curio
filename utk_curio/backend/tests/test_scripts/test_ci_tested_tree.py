"""Finding the green run of a git tree, so main's run of it can pass by link.

``scripts/ci_tested_tree.py`` runs in pick-runners on a push to main. A run it
names makes every test job of main's run skip, so a wrong answer would leave a
tree untested, and a crash would stop the run. These feed it answers shaped
like the GitHub artifacts API's.
"""
from __future__ import annotations

import importlib.util
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


tested = _load("ci_tested_tree")

TREE = "0123456789abcdef0123456789abcdef01234567"


def _artifact(run_id, expired=False):
    return {"name": f"tested-tree-{TREE}", "expired": expired,
            "workflow_run": {"id": run_id, "head_branch": "feat/x", "head_sha": "f" * 40}}


def _answer(*artifacts):
    asked = []

    def fetch(path):
        asked.append(path)
        return {"total_count": len(artifacts), "artifacts": list(artifacts)}
    return fetch, asked


def test_asks_for_the_artifact_named_after_the_tree():
    fetch, asked = _answer()
    assert tested.green_run(TREE, fetch) is None
    assert asked == [f"actions/artifacts?name=tested-tree-{TREE}&per_page=20"]


def test_names_the_newest_green_run_of_the_tree():
    fetch, _ = _answer(_artifact(41), _artifact(57), _artifact(49))
    assert tested.green_run(TREE, fetch)["id"] == 57


def test_an_expired_artifact_is_no_longer_proof():
    fetch, _ = _answer(_artifact(57, expired=True))
    assert tested.green_run(TREE, fetch) is None


def test_the_run_asking_is_never_its_own_proof():
    fetch, _ = _answer(_artifact(57))
    assert tested.green_run(TREE, fetch, this_run="57") is None


def test_only_a_tree_id_names_an_artifact():
    with pytest.raises(ValueError):
        tested.artifact_name("main")


def test_main_prints_the_run_for_github_output(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_RUN_ID", "99")
    monkeypatch.setattr(tested, "_get", lambda url, token: {"artifacts": [_artifact(57)]})
    assert tested.main(["lookup", TREE]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "run=57", "url=https://github.com/o/r/actions/runs/57"]


def test_an_api_error_prints_nothing_so_the_run_tests_everything(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")

    def fail(url, token):
        raise OSError("502 Bad Gateway")
    monkeypatch.setattr(tested, "_get", fail)
    assert tested.main(["lookup", TREE]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "could not look up a green run" in captured.err
