"""``scripts/ci_selected_tests.py``: what a filtered Full stack build selects, and that it ran.

A filtered run (a re-mint with a ``remint_filter``, or the ``tests`` input)
starts only the jobs and parts that hold a selected test, and ci-report checks
the selected tests instead of the whole suite. These build its inputs by hand:
the words of ``tests``, the listings a CURIO_LIST_PARTS collection writes, and
the jobs' JUnit and Jest results.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load():
    path = REPO_ROOT / "scripts" / "ci_selected_tests.py"
    spec = importlib.util.spec_from_file_location("_scripts_ci_selected_tests", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


selected = _load()

UNIT = "utk_curio/backend/tests/test_suite_parts.py::PartsTest::test_a_part_is_k_of_n"
E2E = "utk_curio/backend/tests/test_frontend/test_spa_deep_link_e2e.py"
SANDBOX = "utk_curio/sandbox/tests"
JEST = "utk_curio/frontend/urban-workflows/src/tests/ciParts.test.ts"


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


def _jest(root, *titles):
    folder = root / "ci-inputs-jest"
    folder.mkdir(parents=True, exist_ok=True)
    results = [{"name": "/home/runner/work/curio/curio/utk_curio/frontend/urban-workflows/src/tests/ciParts.test.ts",
                "assertionResults": [{"ancestorTitles": [], "title": title, "status": "passed"}
                                     for title in titles]}]
    (folder / "jest.json").write_text(json.dumps({"testResults": results}), encoding="utf-8")


def _listing(folder, jobs):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"listed-{len(list(folder.iterdir()))}.json").write_text(json.dumps(jobs), encoding="utf-8")
    return folder


def test_each_word_goes_to_the_suite_whose_folder_holds_it():
    found = selected.by_suite([UNIT, E2E, SANDBOX, JEST, "utk_curio/backend/tests"])
    assert found == {"e2e": [E2E], "backend": [UNIT, "utk_curio/backend/tests"],
                     "sandbox": [SANDBOX], "jest": [JEST]}
    assert selected.targets("jest", [UNIT, JEST]) == ["src/tests/ciParts.test.ts"]
    assert selected.targets("e2e", [UNIT, JEST]) == []


@pytest.mark.parametrize("word", [
    "utk_curio/backend/app/agents/service.py",       # not a test folder
    "/abs/utk_curio/backend/tests/test_suite_parts.py",
    "utk_curio/backend/tests/../tests/test_suite_parts.py",
    "utk_curio/backend/tests/test_not_there.py",      # a typo
    "utk_curio/backend/tests/test_suite_parts.py::",  # no test after ::
    "utk_curio/backend/tests::test_x",                # an id must name a file
    f"{JEST}::the parts",                              # Jest takes files only
    "utk_curio/frontend/urban-workflows/src",          # nor a folder
])
def test_a_word_no_suite_holds_is_refused(word):
    with pytest.raises(selected.Refused):
        selected.by_suite([UNIT, word])


def test_a_word_selects_its_tests_by_the_keys_the_results_use():
    assert selected.selects(UNIT, "tests.test_suite_parts.PartsTest::test_a_part_is_k_of_n")
    assert not selected.selects(UNIT, "tests.test_suite_parts.PartsTest::test_a_part_is_k_of_n_too")
    e2e_key = "tests.test_frontend.test_spa_deep_link_e2e::test_deep_link[chromium]"
    assert selected.selects(E2E, e2e_key)
    assert selected.selects(f"{E2E}::test_deep_link", e2e_key)
    assert not selected.selects(f"{E2E}::test_deep", e2e_key)
    assert not selected.selects("utk_curio/backend/tests/test_frontend/test_spa", e2e_key)
    assert selected.selects(SANDBOX, "utk_curio.sandbox.tests.test_codec.TestCodec::test_round_trip")
    assert selected.selects(JEST, "src/tests/ciParts.test.ts::the parts > split")
    assert not selected.selects(JEST, "src/tests/ciPartsOther.test.ts::x")


def test_the_jobs_that_hold_a_selected_test(tmp_path):
    listing = _listing(tmp_path / "listed", {"test-gpu": [], "e2e-desktop-1": ["tests.test_frontend.t::a"],
                                             "e2e-desktop-2": []})
    _listing(listing, {"unit-backend-3": ["tests.test_x::b"], "unit-backend-1": []})
    listed = selected.read_listings([listing])
    assert selected.holding(listed, [UNIT, SANDBOX, JEST]) == [
        "e2e-desktop-1", "jest", "unit-backend-3", "unit-sandbox"]
    assert selected.holding(None, [JEST]) == ["jest"]
    assert selected.read_listings([tmp_path / "missing"]) is None


def test_a_failed_collection_starts_every_part_of_the_selected_suites_and_no_other():
    """A misspelled test name fails the collection: its suite's parts run, no other suite's."""
    assert selected.whole_suites([UNIT]) == [f"unit-backend-{k}" for k in range(1, 5)]
    e2e_parts = sorted(f"e2e-desktop-{k}" for k in range(1, 15))
    assert selected.whole_suites([], remint_filter="test_x") == e2e_parts
    assert selected.whole_suites([E2E, SANDBOX, JEST]) == sorted([*e2e_parts, "jest", "unit-sandbox"])


def test_holding_prints_the_output_and_one_jobs_answer(tmp_path, capsys, monkeypatch):
    listing = _listing(tmp_path / "listed", {"test-gpu": ["tests.test_frontend.t::a"], "e2e-desktop-1": []})
    monkeypatch.setenv("CURIO_TESTS", "")
    assert selected.main(["holding", str(listing)]) == 0
    assert capsys.readouterr().out == "holding=,test-gpu,\n"
    assert selected.main(["holding", str(listing / "listed-0.json"), "--job", "test-gpu"]) == 0
    assert capsys.readouterr().out == "CURIO_CI_HOLDS=true\n"
    assert selected.main(["holding", str(listing), "--job", "e2e-desktop-1"]) == 0
    assert capsys.readouterr().out == "CURIO_CI_HOLDS=false\n"


def test_split_says_which_suites_hold_a_word_and_a_remint_takes_none(capsys, monkeypatch):
    monkeypatch.setenv("CURIO_TESTS", f"{UNIT} {JEST}")
    assert selected.main(["split"]) == 0
    assert capsys.readouterr().out == "e2e=false\nbackend=true\nsandbox=false\njest=true\n"
    assert selected.main(["split", "--remint"]) == 1
    assert "::error::" in capsys.readouterr().out
    monkeypatch.setenv("CURIO_TESTS", "")
    assert selected.main(["split", "--remint", "--remint-filter", "test_spa"]) == 0
    assert capsys.readouterr().out.startswith("e2e=true\n")
    monkeypatch.setenv("CURIO_TESTS", "utk_curio/backend/tests/test_not_there.py")
    assert selected.main(["split"]) == 1


UNIT_KEY = "tests.test_suite_parts.PartsTest::test_a_part_is_k_of_n"


def test_a_filtered_run_whose_selected_tests_ran_passes(tmp_path):
    inputs = tmp_path / "inputs"
    _job(inputs, "unit-backend-2", _case("tests.test_suite_parts.PartsTest", "test_a_part_is_k_of_n"))
    _job(inputs, "unit-sandbox", _case("utk_curio.sandbox.tests.test_codec.TestCodec", "test_round_trip"))
    _jest(inputs, "split")
    listed = {**{f"unit-backend-{k}": [] for k in (1, 3, 4)}, "unit-backend-2": [UNIT_KEY]}
    errors, notes = selected.check(inputs, listed, [UNIT, SANDBOX, JEST])
    assert errors == []
    assert "3 test(s) ran, in jest, unit-backend-2, unit-sandbox" in notes


def test_a_holding_job_without_results_and_a_listed_test_that_skipped_fail(tmp_path):
    inputs = tmp_path / "inputs"
    _job(inputs, "e2e-desktop-3", _case("tests.test_frontend.test_a", "test_b[chromium]", skipped="no WebGPU"))
    listed = {"test-gpu": ["tests.test_frontend.test_c::test_d[chromium]"],
              "e2e-desktop-3": ["tests.test_frontend.test_a::test_b[chromium]"]}
    errors, _ = selected.check(inputs, listed, [], remint_filter="test_b or test_d")
    assert "test-gpu holds a selected test and sent no results" in errors
    assert any("test_a::test_b[chromium], selected in e2e-desktop-3, did not run (skipped: no WebGPU)" in e
               for e in errors)
    assert any("test_c::test_d[chromium], selected in test-gpu, did not run (no result)" in e for e in errors)


def test_a_word_that_selects_nothing_that_ran_fails(tmp_path):
    inputs = tmp_path / "inputs"
    _job(inputs, "unit-sandbox", _case("utk_curio.sandbox.tests.test_codec.TestCodec", "test_round_trip"))
    word = "utk_curio/sandbox/tests/test_codec.py::TestCodec::test_other"
    errors, _ = selected.check(inputs, {}, [word])
    assert errors == [f"{word} selects no test that ran"]


def test_a_remint_filter_that_selects_nothing_fails(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    listed = {"test-gpu": [], **{f"e2e-desktop-{k}": [] for k in range(1, 15)}}
    errors, _ = selected.check(inputs, listed, [], remint_filter="test_no_such_name")
    assert errors == ["the remint_filter 'test_no_such_name' selects no test"]


def test_a_known_test_or_a_runtime_skip_is_excused(tmp_path):
    inputs = tmp_path / "inputs"
    known = "tests.test_frontend.test_no_project_menu::test_file_menu_has_no_orphan_divider_in_no_project_mode[chromium]"
    _job(inputs, "e2e-desktop-1",
         _case("tests.test_frontend.test_no_project_menu",
               "test_file_menu_has_no_orphan_divider_in_no_project_mode[chromium]", skipped="CURIO_NO_PROJECT"),
         _case("tests.test_frontend.test_portal", "test_search[chromium]", skipped="the portal is unreachable"),
         _case("tests.test_frontend.test_portal", "test_list[chromium]"))
    listed = {"test-gpu": [], "e2e-desktop-1": [known, "tests.test_frontend.test_portal::test_search[chromium]",
                                                "tests.test_frontend.test_portal::test_list[chromium]"]}
    errors, _ = selected.check(inputs, listed, [], remint_filter="test_portal or no_project")
    assert errors == []


def test_without_a_listing_it_checks_what_ran_and_says_so(tmp_path):
    """build-image's collection failed, so every part ran with the filter."""
    inputs = tmp_path / "inputs"
    _job(inputs, "e2e-desktop-4",
         _case("tests.test_frontend.test_spa_deep_link_e2e", "test_deep_link[chromium]"),
         _case("tests.test_frontend.test_spa_deep_link_e2e", "test_other[chromium]", skipped="no reason"))
    errors, notes = selected.check(inputs, None, [E2E])
    assert any("no list of the selected tests" in note for note in notes)
    assert errors == ["tests.test_frontend.test_spa_deep_link_e2e::test_other[chromium] only skipped (no reason)"]


def test_check_reads_the_downloaded_listing_and_fails_the_run(tmp_path, capsys, monkeypatch):
    inputs = tmp_path / "inputs"
    _job(inputs, "unit-backend-1", _case("tests.test_suite_parts.PartsTest", "test_a_part_is_k_of_n"))
    listing = _listing(tmp_path / "selected", {f"unit-backend-{k}": [UNIT_KEY] if k == 1 else [] for k in range(1, 5)})
    monkeypatch.setenv("CURIO_TESTS", UNIT)
    assert selected.main(["check", str(inputs), str(listing)]) == 0
    assert "OK: every selected test ran" in capsys.readouterr().out
    monkeypatch.setenv("CURIO_TESTS", f"{UNIT} {JEST}")
    assert selected.main(["check", str(inputs), str(listing)]) == 1
    out = capsys.readouterr().out
    assert "::error::jest holds a selected test and sent no results" in out
    assert f"::error::{JEST} selects no test that ran" in out
