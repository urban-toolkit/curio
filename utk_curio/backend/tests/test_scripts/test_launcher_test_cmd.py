"""``curio test`` flag mapping onto ``scripts/test.sh``.

The launcher's ``test`` command is a thin translator: a suite name and a few
options in, test.sh flags out. If a spelling drifts on either side, test.sh
exits 1 on "Unknown option" -- which reads like a failing test suite rather
than a launcher bug -- or, worse, a suite silently does not run. So every
flag the launcher can emit is asserted against the script's own source.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.main import TEST_SUITES, _parse_test_args, _test_script_flags

TEST_SH = Path(__file__).resolve().parents[4] / "scripts" / "test.sh"


def flags(*argv):
    return _test_script_flags(_parse_test_args(list(argv)))


@pytest.fixture(scope="module")
def test_sh_source():
    assert TEST_SH.is_file(), f"{TEST_SH} is missing; curio test has nothing to call"
    return TEST_SH.read_text(encoding="utf-8")


def test_bare_test_runs_the_whole_script_with_no_flags():
    assert flags() == []


@pytest.mark.parametrize("suite", [s for s in TEST_SUITES if s != "all"])
def test_every_suite_maps_to_a_flag_test_sh_parses(suite, test_sh_source):
    only = f"--{suite}-only"
    assert flags(suite) == [only]
    assert only in test_sh_source


def test_options_map_and_compose():
    assert flags("e2e", "--use-existing", "--headed") == [
        "--e2e-only",
        "--use-existing",
        "--headed",
    ]
    assert flags("-e") == ["--use-existing"]
    assert flags("--workflows", "Vega.json,Regression.json") == [
        "--workflows",
        "Vega.json,Regression.json",
    ]
    assert flags("e2e", "--allure-dir", "out") == [
        "--e2e-only",
        "--allure-dir",
        "out",
    ]


def test_every_option_flag_is_one_test_sh_accepts(test_sh_source):
    emitted = flags(
        "e2e", "--use-existing", "--headed", "--workflows", "A.json",
        "--allure-dir", "out",
    )
    for flag in [f for f in emitted if f.startswith("--")]:
        assert flag in test_sh_source, f"curio test emits {flag}, test.sh does not parse it"


def test_a_server_name_is_not_a_suite():
    # 'frontend' is a curio start target; the suite is called 'jest'.
    with pytest.raises(SystemExit):
        _parse_test_args(["frontend"])
