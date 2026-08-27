"""Does ``scripts/validate_trill.py`` behave like a CLI people can rely on?

The script is the half of trill validation CI cannot do. CI sees the 31 specs
committed under ``docs/examples/``; ``.curio/`` is gitignored, so a developer's
own projects are reachable only from here. That makes two properties worth
pinning: the exit code has to be trustworthy enough to use in a shell, and a
directory scan has to not drown the real findings in noise.

The noise point is not hypothetical. The first version of the directory walk
collected every ``*.json`` it found, so pointing it at ``.curio/`` reported every
package, agent, and dataset ``manifest.json`` as "missing 'dataflow'" - twenty-odd
false failures around the handful of true ones. ``test_a_directory_scan_ignores_
non_dataflow_json`` is that bug's regression test.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from utk_curio.backend.app.projects.seed import _repo_root

REPO_ROOT = str(_repo_root())
SCRIPT = os.path.join(REPO_ROOT, "scripts", "validate_trill.py")
EXAMPLES = os.path.join(REPO_ROOT, "docs", "examples")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


VALID_SPEC = {
    "dataflow": {
        "nodes": [
            {
                "id": "n1",
                "type": "curio.builtin/data-loading",
                "x": 0,
                "y": 0,
                "in": "DEFAULT",
                "out": "DEFAULT",
                "goal": "",
                "content": "print(1)",
                "metadata": {"keywords": []},
            }
        ],
        "edges": [],
        "name": "Fixture",
        "task": "",
        "timestamp": 1748990000000,
        "provenance_id": "Fixture",
    }
}


def _write(path, doc) -> str:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def test_the_script_exists_and_is_runnable():
    assert os.path.isfile(SCRIPT), f"expected the validator at {SCRIPT}"
    result = _run("--help")
    assert result.returncode == 0, result.stderr
    assert "trill" in result.stdout.lower()


class TestExitCodes:
    def test_a_valid_file_exits_zero(self, tmp_path):
        target = _write(tmp_path / "good.trill.json", VALID_SPEC)
        result = _run(target)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_an_invalid_file_exits_one(self, tmp_path):
        broken = json.loads(json.dumps(VALID_SPEC))
        broken["dataflow"]["nodes"][0]["type"] = "DATA_LOADING"
        target = _write(tmp_path / "bad.trill.json", broken)
        result = _run(target)
        assert result.returncode == 1
        assert "nodes.0.type" in result.stderr, result.stderr

    def test_the_committed_examples_all_validate(self):
        # The same corpus CI gates, exercised through the CLI rather than pytest,
        # so a schema edit that breaks one is caught from either direction.
        result = _run(EXAMPLES, "--resolve")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_malformed_json_is_reported_not_raised(self, tmp_path):
        target = tmp_path / "truncated.trill.json"
        target.write_text('{"dataflow": {', encoding="utf-8")
        result = _run(str(target))
        assert result.returncode == 1
        assert "not valid JSON" in result.stderr
        assert "Traceback" not in result.stderr

    def test_a_missing_path_is_a_usage_error(self):
        result = _run(os.path.join(REPO_ROOT, "does", "not", "exist.json"))
        assert result.returncode == 2
        assert "No such path" in result.stderr

    def test_no_arguments_is_a_usage_error(self):
        result = _run()
        assert result.returncode == 2

    def test_all_and_explicit_paths_are_mutually_exclusive(self):
        result = _run("--all", EXAMPLES)
        assert result.returncode == 2


class TestTargets:
    def test_a_directory_is_searched_recursively(self, tmp_path):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        _write(nested / "deep.trill.json", VALID_SPEC)
        result = _run(str(tmp_path))
        assert result.returncode == 0
        assert "deep.trill.json" in result.stdout

    def test_a_directory_scan_ignores_non_dataflow_json(self, tmp_path):
        """Regression: manifests are JSON but are not dataflows.

        A package/agent/dataset store is full of ``manifest.json`` and
        ``integrity.json``. Reporting each as "missing 'dataflow'" made a scan of
        .curio/ useless.
        """
        _write(tmp_path / "spec.trill.json", VALID_SPEC)
        _write(tmp_path / "manifest.json", {"id": "curio.builtin", "templates": []})
        _write(tmp_path / "integrity.json", {"files": {}})
        _write(tmp_path / "default-packages.json", ["curio.builtin@1"])
        result = _run(str(tmp_path))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "spec.trill.json" in result.stdout
        for ignored in ("manifest.json", "integrity.json", "default-packages.json"):
            assert ignored not in result.stdout + result.stderr

    def test_a_named_file_is_validated_even_without_a_dataflow_key(self, tmp_path):
        # Naming a path deserves a verdict, including "this is not a dataflow".
        target = _write(tmp_path / "manifest.json", {"id": "curio.builtin"})
        result = _run(target)
        assert result.returncode == 1
        assert "'dataflow' is a required property" in result.stderr

    def test_dataset_fixture_directories_are_skipped(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        # docs/examples/data holds dataset fixtures; a .json in there is not a spec.
        _write(data / "cities.json", {"type": "FeatureCollection"})
        _write(tmp_path / "spec.trill.json", VALID_SPEC)
        result = _run(str(tmp_path))
        assert result.returncode == 0
        assert "cities.json" not in result.stdout + result.stderr

    def test_all_reports_each_corpus_separately(self):
        # --all deliberately exits non-zero when .curio projects predate the
        # schema, so assert on the report rather than the status.
        result = _run("--all")
        combined = result.stdout + result.stderr
        assert "docs/examples" in combined
        assert "docs/examples/dataflows" in combined
        assert ".curio user projects" in combined


class TestOutputControls:
    def test_quiet_prints_nothing_on_success(self, tmp_path):
        target = _write(tmp_path / "good.trill.json", VALID_SPEC)
        result = _run(target, "--quiet")
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_quiet_still_signals_failure_through_the_exit_code(self, tmp_path):
        broken = json.loads(json.dumps(VALID_SPEC))
        broken["dataflow"].pop("name")
        target = _write(tmp_path / "bad.trill.json", broken)
        result = _run(target, "--quiet")
        assert result.returncode == 1
        assert result.stdout == ""

    def test_max_errors_caps_the_report_and_says_so(self, tmp_path):
        broken = json.loads(json.dumps(VALID_SPEC))
        for field in ("name", "task", "timestamp", "provenance_id"):
            broken["dataflow"].pop(field)
        target = _write(tmp_path / "bad.trill.json", broken)
        capped = _run(target, "--max-errors", "2")
        assert capped.returncode == 1
        assert "and 2 more" in capped.stderr, capped.stderr
        full = _run(target, "--max-errors", "10")
        assert "more" not in full.stderr.split("problem(s)")[-1]


class TestResolve:
    def test_resolve_rejects_a_type_with_no_template(self, tmp_path):
        """The boundary between the two schemas.

        A grammatically valid coordinate that resolves to nothing must pass the
        schema (resolution is a manifest question) and fail --resolve.
        """
        doc = json.loads(json.dumps(VALID_SPEC))
        doc["dataflow"]["nodes"][0]["type"] = "curio.builtin/not-a-real-template"
        target = _write(tmp_path / "ghost.trill.json", doc)

        assert _run(target).returncode == 0, "the schema should accept the shape"

        resolved = _run(target, "--resolve")
        assert resolved.returncode == 1
        assert "no template under packages/" in resolved.stderr, resolved.stderr

    def test_resolve_accepts_a_versioned_type(self, tmp_path):
        # Palette-dragged nodes persist the versioned form; --resolve has to
        # normalize before looking the template up.
        doc = json.loads(json.dumps(VALID_SPEC))
        doc["dataflow"]["nodes"][0]["type"] = "curio.builtin/data-loading@1"
        target = _write(tmp_path / "versioned.trill.json", doc)
        result = _run(target, "--resolve")
        assert result.returncode == 0, result.stdout + result.stderr
