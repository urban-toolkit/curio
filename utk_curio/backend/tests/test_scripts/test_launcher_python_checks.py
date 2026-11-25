"""The launcher refuses a Python it cannot run on, and says when it has no pip.

Curio runs on the Python ``pyproject.toml``'s ``requires-python`` names, 3.12
alone. ``pip install utk-curio`` refuses another, but a clone does not: on
3.11, ``curio.py setup`` installs every library, and the start then fails in
its database migration with a ``SyntaxError`` in the backend's code, which
reads as a bug in Curio. The launcher now says which Python it needs before
it installs or starts anything.

A venv that ``uv venv`` makes has no pip, and the launcher installs Curio's
libraries with ``python -m pip``. Its failure said only ``pip install -r
requirements.txt failed (exit 1)``; it now says that this Python has no pip,
and how to add it.
"""
from __future__ import annotations

import re
import signal
import subprocess
import sys
import venv
from pathlib import Path
from types import SimpleNamespace

import pytest

import utk_curio.main as launcher
from utk_curio.cli import dependencies, logs

REPO_ROOT = Path(__file__).resolve().parents[4]


def _supported_python():
    """``(major, minor)`` of the one Python ``requires-python`` allows."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    spec = re.search(r'^requires-python\s*=\s*"([^"]+)"', text, re.M).group(1)
    assert re.fullmatch(r">=3\.(\d+),<3\.(\d+)", spec), spec
    low, high = (int(minor) for minor in re.findall(r"3\.(\d+)", spec))
    assert high == low + 1, f"{spec} allows more than one Python"
    return 3, low


SUPPORTED = _supported_python()
BELOW = (SUPPORTED[0], SUPPORTED[1] - 1)
ABOVE = (SUPPORTED[0], SUPPORTED[1] + 1)


def _setup(monkeypatch, version):
    """Run ``curio.py setup`` on Python *version*, with each install recorded
    instead of done. The installs it ran, its errors, and its exit code."""
    steps, errors = [], []
    monkeypatch.setattr("sys.argv", ["curio.py", "setup"])
    monkeypatch.setattr(sys, "version_info", (*version, 0, "final", 0))
    monkeypatch.setattr(logs, "verbosity", logs.verbosity)
    # What main() changes outside itself: its signal handlers and CURIO_DEV.
    monkeypatch.setattr(launcher, "signal", SimpleNamespace(
        SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM, signal=lambda *args: None,
    ))
    # Its own value, as main() would set it, so that monkeypatch takes it out after.
    monkeypatch.setenv("CURIO_DEV", "0")
    monkeypatch.setattr(launcher, "set_state_dir", lambda state_dir: None)
    monkeypatch.setattr(launcher, "setup_logging", lambda server: None)
    monkeypatch.setattr(launcher, "set_environment_variables", lambda **kwargs: None)
    monkeypatch.setattr(launcher, "install_framework_requirements", lambda: steps.append("framework"))
    monkeypatch.setattr(launcher, "install_manifest_dependencies", lambda **kwargs: steps.append("manifests"))
    monkeypatch.setattr(dependencies, "log_error", errors.append)
    monkeypatch.setattr(launcher, "log_error", errors.append, raising=False)
    with pytest.raises(SystemExit) as exited:
        launcher.main()
    return steps, errors, exited.value.code


@pytest.mark.parametrize("version", [BELOW, ABOVE], ids=lambda v: "Python %d.%d" % v)
def test_a_setup_on_another_python_stops_before_it_installs_anything(version, monkeypatch):
    steps, errors, code = _setup(monkeypatch, version)

    assert code == 1
    assert steps == []
    assert len(errors) == 1
    assert "Python %d.%d" % version in errors[0]
    assert "Python %d.%d" % SUPPORTED in errors[0]


def test_a_setup_on_the_supported_python_installs_as_before(monkeypatch):
    steps, errors, code = _setup(monkeypatch, SUPPORTED)

    assert code == 0
    assert steps == ["framework", "manifests"]
    assert errors == []


# --- pip --------------------------------------------------------------------


@pytest.fixture
def errors(monkeypatch):
    logged = []
    monkeypatch.setattr(dependencies, "log_error", logged.append)
    return logged


def test_a_python_without_pip_is_named_with_how_to_add_pip(tmp_path, monkeypatch, errors):
    # A venv as `uv venv` makes it: no pip.
    venv.create(tmp_path / "venv", with_pip=False, symlinks=sys.platform != "win32")
    python = next(path for path in [
        tmp_path / "venv" / "bin" / "python",
        tmp_path / "venv" / "Scripts" / "python.exe",
    ] if path.exists())
    assert subprocess.run([python, "-c", "import pip"], capture_output=True).returncode != 0
    monkeypatch.setattr(sys, "executable", str(python))

    with pytest.raises(SystemExit) as exited:
        dependencies.install_framework_requirements()

    assert exited.value.code == 1
    assert len(errors) == 1
    assert "has no pip" in errors[0]
    assert "python -m ensurepip" in errors[0]
    assert "uv venv --seed" in errors[0]


def test_a_pip_that_fails_keeps_its_own_message(errors):
    with pytest.raises(SystemExit) as exited:
        dependencies._run_pip([sys.executable, "-m", "pip", "--no-such-option"], "pip failed")

    assert exited.value.code == 1
    assert errors == ["pip failed (exit 2). Re-run with --verbose 2 to see pip's output."]
