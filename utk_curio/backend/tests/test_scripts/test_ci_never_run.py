"""``scripts/ci_never_run.py``: a test every job skipped fails the run.

The ci-report job runs it over every job's JUnit results. These build those
results by hand.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load():
    path = REPO_ROOT / "scripts" / "ci_never_run.py"
    spec = importlib.util.spec_from_file_location("_scripts_ci_never_run", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ci_never_run = _load()


def _case(classname, name, skipped=None):
    if skipped is None:
        return f'<testcase classname="{classname}" name="{name}" time="0.1"/>'
    return (f'<testcase classname="{classname}" name="{name}" time="0">'
            f'<skipped type="pytest.skip" message="{skipped}"/></testcase>')


def _job(root, job, *cases):
    folder = root / f"ci-inputs-{job}"
    folder.mkdir(parents=True)
    (folder / "results.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">'
        + "".join(cases) + "</testsuite></testsuites>",
        encoding="utf-8",
    )


def _check(root, capsys, *jobs):
    code = ci_never_run.main([str(root), *jobs])
    return code, capsys.readouterr().out


def test_a_test_another_job_ran_passes(tmp_path, capsys):
    _job(tmp_path, "unit", _case("tests.test_a", "test_x", skipped="needs auth"))
    _job(tmp_path, "gpu", _case("tests.test_a", "test_x"))
    code, out = _check(tmp_path, capsys, "unit", "gpu")
    assert code == 0, out


def test_a_test_every_job_skipped_fails_and_is_named(tmp_path, capsys):
    _job(tmp_path, "unit", _case("tests.test_a", "test_x", skipped="needs a checkout"))
    _job(tmp_path, "gpu", _case("tests.test_a", "test_x", skipped="needs a checkout"),
         _case("tests.test_a", "test_y"))
    code, out = _check(tmp_path, capsys, "unit", "gpu")
    assert code == 1
    assert "::error::ran in no job: tests.test_a::test_x (needs a checkout)" in out
    assert "test_y" not in out


def test_ids_match_across_the_gpu_suffix_and_the_long_class_name(tmp_path, capsys):
    """The GPU runner appends ``@<module>``; a run from the repository root
    names the class from ``utk_curio.backend``."""
    _job(tmp_path, "unit", _case("tests.test_a", "test_x[chromium]", skipped="no GPU"),
         _case("tests.test_b", "test_z", skipped="no checkout"))
    _job(tmp_path, "gpu", _case("tests.test_a", "test_x[chromium]@test_a"))
    _job(tmp_path, "host", _case("utk_curio.backend.tests.test_b", "test_z"))
    code, out = _check(tmp_path, capsys, "unit", "gpu", "host")
    assert code == 0, out


def test_a_known_test_is_a_notice(tmp_path, capsys):
    known = sorted(ci_never_run.KNOWN)[0]
    classname, name = known.split("::")
    _job(tmp_path, "unit", _case(classname, name, skipped="opt-in"))
    code, out = _check(tmp_path, capsys, "unit")
    assert code == 0, out
    assert f"::notice::ran in no job: {known}" in out


def test_a_skip_for_a_runtime_reason_is_a_notice(tmp_path, capsys):
    """A portal being down is not the test's fault, and it skips for that."""
    _job(tmp_path, "unit", _case("tests.test_discovery.test_provider_contracts", "test_p",
                                 skipped="https://example.org unreachable: TimeoutError"))
    code, out = _check(tmp_path, capsys, "unit")
    assert code == 0, out
    assert "::notice::ran in no job: tests.test_discovery.test_provider_contracts::test_p" in out


def test_nothing_is_checked_without_every_jobs_results(tmp_path, capsys):
    _job(tmp_path, "unit", _case("tests.test_a", "test_x", skipped="needs a checkout"))
    code, out = _check(tmp_path, capsys, "unit", "gpu")
    assert code == 0
    assert "not checked: no results from gpu" in out
