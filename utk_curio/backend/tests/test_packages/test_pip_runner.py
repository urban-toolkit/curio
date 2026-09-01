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
    # `_format_range` round-trips an unbounded range to "*", so the
    # resolver hands `*` to `_spec_argv` whenever a manifest leaves a
    # version field empty. Treat it the same as the empty spec — pip
    # rejects bare "numpy==*" as invalid syntax.
    assert _spec_argv("numpy", "*") == "numpy"


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


# ---------------------------------------------------------------------------
# The streaming (on_line) path
# ---------------------------------------------------------------------------
#
# install_python_deps has two implementations picked by whether on_line is
# given. Only the buffered one was covered, yet the streaming one is what the
# launcher uses (main.py install_manifest_dependencies) - so a break there
# surfaces as a broken `curio start`, not a failing API call.


class _FakeProc:
    """Minimal Popen stand-in: iterable stdout plus a fixed exit code."""

    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self._rc = returncode

    def wait(self, timeout=None):
        # Mirrors ``Popen.wait``: the streaming branch bounds pip with
        # ``timeout=_PIP_TIMEOUT_SECONDS`` rather than waiting forever.
        return self._rc

    def kill(self):  # pragma: no cover - only on the timeout path
        pass


def test_streaming_path_reports_each_line_and_returns_installed():
    seen: list[str] = []
    with patch(
        "utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=False
    ), patch(
        "utk_curio.backend.app.packages.pip_runner.subprocess.Popen",
        return_value=_FakeProc(["Collecting inflection", "Successfully installed"]),
    ) as popen:
        report = install_python_deps({"inflection": ""}, on_line=seen.append)

    assert seen == ["Collecting inflection", "Successfully installed"]
    assert report.installed == ["inflection"]
    assert report.skipped == []
    # Popen itself takes no timeout; the deadline is applied at `proc.wait()`,
    # which is what bounds the branch. It previously called a bare `wait()` and
    # a wedged mirror hung the caller forever.
    assert "timeout" not in popen.call_args.kwargs


def test_streaming_path_raises_with_the_output_tail():
    with patch(
        "utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=False
    ), patch(
        "utk_curio.backend.app.packages.pip_runner.subprocess.Popen",
        return_value=_FakeProc(["ERROR: could not build wheel"], returncode=1),
    ):
        with pytest.raises(PipInstallError) as exc:
            install_python_deps({"inflection": ""}, on_line=lambda _l: None)

    assert "exit 1" in str(exc.value)
    assert "could not build wheel" in str(exc.value)


def test_streaming_path_keeps_only_the_last_40_lines():
    """The tail is capped, so a chatty failure stays a readable error."""
    lines = [f"line-{i}" for i in range(200)]
    with patch(
        "utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=False
    ), patch(
        "utk_curio.backend.app.packages.pip_runner.subprocess.Popen",
        return_value=_FakeProc(lines, returncode=2),
    ):
        with pytest.raises(PipInstallError) as exc:
            install_python_deps({"inflection": ""}, on_line=lambda _l: None)

    message = str(exc.value)
    assert "line-199" in message
    assert "line-160" in message      # 200 - 40 = the oldest line still kept
    assert "line-159" not in message  # ...and the one before it is dropped


def test_streaming_path_skips_pip_entirely_when_satisfied():
    """The satisfied short-circuit precedes the branch, so on_line is never called."""
    seen: list[str] = []
    with patch(
        "utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=True
    ), patch(
        "utk_curio.backend.app.packages.pip_runner.subprocess.Popen"
    ) as popen:
        report = install_python_deps({"inflection": ""}, on_line=seen.append)

    popen.assert_not_called()
    assert seen == []
    assert report.installed == []
    assert report.skipped == ["inflection"]



def test_streaming_path_kills_pip_when_it_overruns(monkeypatch):
    """The streaming branch is bounded, like the buffered one.

    It used to call a bare ``proc.wait()``. A mirror that accepts the
    connection and then never sends EOF pinned the calling thread forever, and
    this branch is reachable over HTTP: ``build_overlay`` streams, and it sits
    on the promotion and catalog-install paths.
    """
    import subprocess

    from utk_curio.backend.app.packages import pip_runner

    killed = {"count": 0}

    class _HangingProc:
        def __init__(self):
            self.stdout = iter(["Collecting slowpkg"])

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired(cmd="pip", timeout=timeout)
            return 0

        def kill(self):
            killed["count"] += 1

    monkeypatch.setattr(pip_runner, "_is_satisfied", lambda name, spec: False)
    monkeypatch.setattr(pip_runner.subprocess, "Popen", lambda *a, **k: _HangingProc())

    # The module-level import, not ``pip_runner.install_python_deps``: the
    # package conftest's autouse fixture replaces that attribute with a stub
    # that takes no ``on_line``. The other streaming tests bind it the same way.
    with pytest.raises(PipInstallError, match="timed out"):
        install_python_deps({"slowpkg": ""}, on_line=lambda line: None)

    assert killed["count"] == 1, "a pip that overruns must be killed, not leaked"
