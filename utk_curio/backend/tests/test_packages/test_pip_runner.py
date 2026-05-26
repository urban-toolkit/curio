"""Tests for the per-package pip_runner.

The runner shells out to ``pip``; tests stub the subprocess to keep them
fast (and to not actually mutate the test env). What we care about:

- Idempotency: deps that are already installed get skipped.
- Spec formatting: ``>=2.0`` stays as-is, bare ``1.2.3`` becomes ``==1.2.3``.
- Failure surfaces a useful error (tail of pip's stderr).
- Uninstall propagates names correctly.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from utk_curio.backend.app.packages.pip_runner import (
    PipInstallError,
    _spec_argv,
    install_python_deps,
    uninstall_python_deps,
)


def _fake_proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    p = subprocess.CompletedProcess(args=[], returncode=returncode)
    p.stdout = stdout
    p.stderr = stderr
    return p


def test_spec_argv_keeps_comparators_intact():
    assert _spec_argv("torch", ">=2.0") == "torch>=2.0"
    assert _spec_argv("foo", "~=1.4") == "foo~=1.4"
    assert _spec_argv("bar", "==3.0.0") == "bar==3.0.0"


def test_spec_argv_bare_version_becomes_exact_match():
    assert _spec_argv("torch", "2.0") == "torch==2.0"


def test_spec_argv_empty_spec_is_bare_name():
    assert _spec_argv("ultralytics", "") == "ultralytics"
    assert _spec_argv("ultralytics", "   ") == "ultralytics"


def test_install_empty_deps_is_noop():
    report = install_python_deps({})
    assert report.installed == [] and report.skipped == []


def test_install_skips_already_satisfied():
    """A package the runner can resolve via ``importlib.metadata`` is
    skipped — pip is never invoked."""
    with patch("utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=True), \
         patch("subprocess.run") as run:
        report = install_python_deps({"torch": ">=2.0", "transformers": ">=4.30"})
    run.assert_not_called()
    assert sorted(report.skipped) == ["torch", "transformers"]
    assert report.installed == []


def test_install_invokes_pip_for_missing_deps():
    with patch("utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=False), \
         patch("subprocess.run", return_value=_fake_proc(0, "ok", "")) as run:
        report = install_python_deps({"torch": ">=2.0"})
    assert run.call_count == 1
    argv = run.call_args[0][0]
    # The argv ends in the pip-formatted spec; preceding entries are the
    # interpreter, ``-m pip install --no-input``.
    assert argv[-1] == "torch>=2.0"
    assert "install" in argv and "--no-input" in argv
    assert report.installed == ["torch>=2.0"] and report.skipped == []


def test_install_raises_with_pip_stderr_tail_on_failure():
    big_stderr = "x" * 5000 + "FATAL ERROR HERE"
    with patch("utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=False), \
         patch("subprocess.run", return_value=_fake_proc(1, "", big_stderr)):
        with pytest.raises(PipInstallError) as exc_info:
            install_python_deps({"torch": ">=2.0"})
    # We surface the *tail* (last 2000 chars) — long enough to include the
    # error, short enough to fit in a JSON response.
    msg = str(exc_info.value)
    assert "FATAL ERROR HERE" in msg
    assert "exit 1" in msg


def test_uninstall_empty_list_is_noop():
    report = uninstall_python_deps([])
    assert report.removed == [] and report.kept == []


def test_uninstall_invokes_pip_with_names():
    with patch("subprocess.run", return_value=_fake_proc(0, "ok", "")) as run:
        report = uninstall_python_deps(["torch", "transformers"])
    argv = run.call_args[0][0]
    assert "uninstall" in argv and "-y" in argv
    assert "torch" in argv and "transformers" in argv
    assert report.removed == ["torch", "transformers"]
