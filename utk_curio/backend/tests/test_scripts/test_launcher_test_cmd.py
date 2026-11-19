"""``curio test`` flag mapping onto ``scripts/test.sh``.

The launcher's ``test`` command is a thin translator: a suite name and a few
options in, test.sh flags out. If a spelling drifts on either side, test.sh
exits 1 on "Unknown option" -- which reads like a failing test suite rather
than a launcher bug -- or, worse, a suite silently does not run. So every
flag the launcher can emit is asserted against the script's own source.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.cli import test_runner
from utk_curio.cli.test_runner import TEST_SUITES, _parse_test_args, _test_script_flags

TEST_SH = Path(__file__).resolve().parents[4] / "scripts" / "test.sh"

# python or pip as a command's name: not a part of a longer word, a path or a
# variable, and not pip run as a module (-m pip), so PYTHONPATH, pipefail,
# 'python.exe', "$PYTHON" -m pip and the fallback in
# "${CURIO_TEST_PYTHON:-python}" are not calls.
BARE_INTERPRETER = re.compile(r"(?<![\w.$/-])(?<!-m )(?:python|pip)[0-9.]*(?![\w.-])")


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
    assert flags("--workflows", "vega.json,regression.json") == [
        "--workflows",
        "vega.json,regression.json",
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


def test_curio_test_hands_test_sh_its_own_interpreter(monkeypatch):
    """A virtual environment's interpreter, started by its path with the
    environment not active, has that environment's ``python`` and ``pip``
    nowhere on ``PATH``. ``curio test`` hands test.sh the interpreter it runs
    on, in the launcher's own environment, as the launcher starts the backend
    and the sandbox on it."""
    # A run of this test under curio test inherits the variable; start without it.
    monkeypatch.delenv("CURIO_TEST_PYTHON", raising=False)
    seen = {}

    def _call(cmd, **kwargs):
        seen.update(kwargs, cmd=cmd)
        return 0

    monkeypatch.setattr(test_runner, "subprocess", SimpleNamespace(call=_call))
    with pytest.raises(SystemExit) as exited:
        test_runner.run_tests(["unit"])

    assert exited.value.code == 0
    assert Path(seen["cmd"][1]).resolve() == TEST_SH and seen["cmd"][2:] == ["--unit-only"], seen["cmd"]
    env = seen.get("env")
    assert env is not None, "curio test starts test.sh with no word of the interpreter it runs on"
    assert env.get("CURIO_TEST_PYTHON") == sys.executable, (
        f"test.sh is told to run {env.get('CURIO_TEST_PYTHON')!r}, not {sys.executable!r}"
    )
    assert {name: value for name, value in env.items() if name != "CURIO_TEST_PYTHON"} == dict(os.environ)


def test_test_sh_runs_every_python_and_pip_on_the_interpreter_it_is_given(test_sh_source):
    """test.sh runs python, and pip through it, as ``$PYTHON``: the interpreter
    ``curio test`` hands it, else the python on ``PATH``, which CI, calling
    test.sh directly, keeps. An echo's text is read only for the commands it
    runs inside ``$(...)``."""
    assert 'PYTHON="${CURIO_TEST_PYTHON:-python}"' in test_sh_source
    bare = []
    for number, line in enumerate(test_sh_source.splitlines(), start=1):
        code = line.strip()
        if code.startswith("#"):
            continue
        if code.startswith("echo "):
            code = " ".join(re.findall(r"\$\(([^()]*)\)", code))
        if BARE_INTERPRETER.search(code):
            bare.append(f"  {number}: {line.strip()}")
    assert bare == [], "test.sh runs python or pip by name, not as $PYTHON:\n" + "\n".join(bare)
