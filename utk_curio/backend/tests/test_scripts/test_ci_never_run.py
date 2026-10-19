"""``scripts/ci_never_run.py``: a test every job skipped fails the run.

The ci-report job runs it over every job's JUnit results. These build those
results by hand. Its ``--compare`` mode lists what differs between two runs'
results, test by test, and the tests at the end build two runs for it.
"""
from __future__ import annotations

import importlib.util
import json
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


def _job(root, job, *cases, file="results.xml"):
    folder = root / f"ci-inputs-{job}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_text(
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


def test_an_at_sign_inside_the_parameters_stays_in_the_id(tmp_path, capsys):
    """Only xdist's trailing ``@<group>`` goes: ``[curio.builtin@1]`` and
    ``[curio.builtin@2]`` are two tests, and the second one ran nowhere."""
    _job(tmp_path, "unit", _case("tests.test_a", "test_x[curio.builtin@1]"),
         _case("tests.test_a", "test_x[curio.builtin@2]", skipped="needs a checkout"))
    _job(tmp_path, "gpu", _case("tests.test_a", "test_x[curio.builtin@2]@test_a", skipped="needs a checkout"))
    code, out = _check(tmp_path, capsys, "unit", "gpu")
    assert code == 1
    assert "::error::ran in no job: tests.test_a::test_x[curio.builtin@2] (needs a checkout)" in out
    assert "curio.builtin@1" not in out


def _jest(root, job, *assertions, file="jest.json"):
    """Jest's --json output for one file, as a runner's checkout names it."""
    folder = root / f"ci-inputs-{job}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_text(json.dumps({"testResults": [{
        "name": "/home/runner/work/curio/curio/utk_curio/frontend/urban-workflows/src/tests/a.test.ts",
        "assertionResults": [{"ancestorTitles": ["the panel"], "title": title, "status": status}
                             for title, status in assertions],
    }]}), encoding="utf-8")


def test_a_jest_test_every_run_skipped_fails_the_run(tmp_path, capsys):
    _job(tmp_path, "unit", _case("tests.test_a", "test_x"))
    _jest(tmp_path, "jest", ("opens", "passed"), ("closes", "pending"))
    code, out = _check(tmp_path, capsys, "unit")
    assert code == 1
    assert "::error::ran in no job: src/tests/a.test.ts::the panel > closes (pending)" in out
    assert "opens" not in out


def _compare(capsys, before, after):
    code = ci_never_run.main(["--compare", str(before), str(after)])
    return code, capsys.readouterr().out


def _section(out, number):
    """The lines of one numbered list in the comparison."""
    start = out.index(f"\n{number}. ")
    end = out.find(f"\n{number + 1}. ", start + 1)
    return out[start:end if end > 0 else len(out)]


def test_the_same_tests_in_other_parts_compare_clean(tmp_path, capsys):
    """Ten e2e parts against fourteen, and two backend parts against four, with
    the same tests: no difference. A later run of a repeated suite is not read."""
    before, after = tmp_path / "before", tmp_path / "after"
    _job(before, "unit-backend-1", _case("tests.test_a", "test_x"), _case("tests.test_b", "test_y"))
    _job(before, "unit-backend-2", _case("tests.test_c", "test_z", skipped="needs auth"))
    _job(before, "e2e-desktop-10", _case("tests.test_frontend.test_e", "test_e[chromium]"))
    _job(before, "test-gpu", _case("tests.test_frontend.test_g", "test_g[chromium]@test_g"))
    _jest(before, "jest", ("opens", "passed"))
    _job(after, "unit-backend-4", _case("tests.test_a", "test_x"))
    _job(after, "unit-backend-3", _case("tests.test_b", "test_y"))
    _job(after, "unit-backend-1", _case("tests.test_c", "test_z", skipped="needs auth"))
    _job(after, "e2e-desktop-14", _case("tests.test_frontend.test_e", "test_e[chromium]"))
    _job(after, "e2e-desktop-14", _case("tests.test_frontend.test_e", "test_e[chromium]",
                                        skipped="a repeat's second run"), file="e2e.run2.xml")
    _job(after, "test-gpu", _case("tests.test_frontend.test_g", "test_g[chromium]@test_g"))
    _jest(after, "jest", ("opens", "passed"))
    _jest(after, "jest", ("opens", "failed"), file="jest.run2.json")
    code, out = _compare(capsys, before, after)
    assert code == 0, out
    assert "Same tests in both runs, with the same outcomes, skip reasons and runners." in out


def test_a_comparison_lists_the_four_differences(tmp_path, capsys):
    before, after = tmp_path / "before", tmp_path / "after"
    _job(before, "unit-backend-1",
         _case("tests.test_a", "test_gone"),
         _case("tests.test_a", "test_now_skips"),
         _case("tests.test_a", "test_reason", skipped="no checkout"),
         _case("tests.test_a", "test_x[curio.builtin@1]"),
         _case("tests.test_a", "test_x[curio.builtin@2]"))
    _job(before, "test-gpu", _case("tests.test_frontend.test_m", "test_m[chromium]@test_m"))
    _jest(before, "jest", ("opens", "passed"))
    _job(after, "unit-backend-2",
         _case("tests.test_a", "test_new"),
         _case("tests.test_a", "test_now_skips", skipped="already importable"),
         _case("tests.test_a", "test_reason", skipped="no auth"),
         _case("tests.test_a", "test_x[curio.builtin@1]"),
         _case("tests.test_a", "test_x[curio.builtin@2]", skipped="needs auth"))
    _job(after, "e2e-desktop-3", _case("tests.test_frontend.test_m", "test_m[chromium]"))
    _jest(after, "jest", ("opens", "pending"))
    code, out = _compare(capsys, before, after)
    assert code == 1
    only = _section(out, 1)
    assert "1. In one run only: 2" in only
    assert "only before [unit-backend] tests.test_a::test_gone (passed)" in only
    assert "only after  [unit-backend] tests.test_a::test_new (passed)" in only
    changed = _section(out, 2)
    assert "2. Outcome changed: 3" in changed
    # A runtime reason excuses nothing here.
    assert "[unit-backend] tests.test_a::test_now_skips: passed -> skipped (already importable)" in changed
    assert "[unit-backend] tests.test_a::test_x[curio.builtin@2]: passed -> skipped (needs auth)" in changed
    assert "[jest] src/tests/a.test.ts::the panel > opens: passed -> skipped (pending)" in changed
    assert "curio.builtin@1" not in out
    reasons = _section(out, 3)
    assert "3. Skip reason changed: 1" in reasons
    assert "[unit-backend] tests.test_a::test_reason\n      before: no checkout\n      after:  no auth" in reasons
    moved = _section(out, 4)
    assert "4. Moved between the GPU job and a CPU job: 1" in moved
    assert "tests.test_frontend.test_m::test_m[chromium]: GPU -> CPU" in moved


def test_a_comparison_names_a_job_with_no_results_and_a_test_run_twice(tmp_path, capsys):
    before, after = tmp_path / "before", tmp_path / "after"
    _job(before, "e2e-desktop-1", _case("tests.test_frontend.test_e", "test_e[chromium]"))
    _job(before, "test-isolated", _case("tests.test_frontend.test_e", "test_e[chromium]"))
    _job(after, "e2e-desktop-1", _case("tests.test_frontend.test_e", "test_e[chromium]"))
    _job(after, "e2e-desktop-2", _case("tests.test_frontend.test_e", "test_e[chromium]"))
    code, out = _compare(capsys, before, after)
    assert code == 1
    assert "::warning::no test-isolated results in the after run" in out
    assert "only before [test-isolated] tests.test_frontend.test_e::test_e[chromium] (passed)" in out
    assert ("after: [e2e] tests.test_frontend.test_e::test_e[chromium] in e2e-desktop-1, e2e-desktop-2"
            in out)
