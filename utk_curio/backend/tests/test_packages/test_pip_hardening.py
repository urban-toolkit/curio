"""What pip runs as, and whether it is allowed to build (#309 residual 2).

Gating decides *who* may trigger an install. It says nothing about what the
install then executes. ``pip install --target`` is a plain subprocess of the
backend process, so an sdist's ``setup.py`` runs as the backend user with the
backend's privileges and no limits, whatever ``CURIO_ISOLATION`` says. Node code
is confined; the install that precedes it was not.

Two mitigations, cheapest first:

* **Prefer wheels.** A wheel is unpacked, not executed, so ``setup.py`` never
  runs. This removes the exposure for the common case rather than containing it,
  and costs one flag. The fallback stays, because a dependency with no wheel for
  the platform must still install.
* **Drop privileges for the build that remains.** When an execution user is
  configured, the sdist build runs as that account under resource limits rather
  than as the backend.

No seccomp: pip legitimately needs network and fork. This is a uid and rlimit
boundary, not a syscall one, and it is worth being precise about that.
"""
from __future__ import annotations

import sys

import pytest

from utk_curio.backend.app.packages import pip_runner


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def runs(monkeypatch):
    """Every subprocess.run pip_runner makes: (cmd, kwargs)."""
    calls: list[tuple[list[str], dict]] = []

    def _run(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        return _Result(returncode=0)

    monkeypatch.setattr(pip_runner.subprocess, "run", _run)
    return calls


class TestWheelsArePreferred:
    def test_the_first_attempt_forbids_sdists(self, runs, tmp_path):
        pip_runner.install_python_deps_to_target({"humanize": ""}, str(tmp_path))
        assert runs, "pip was never invoked"
        assert "--only-binary=:all:" in runs[0][0]

    def test_a_wheel_only_failure_retries_allowing_a_build(self, monkeypatch, tmp_path):
        calls: list[list[str]] = []

        def _run(cmd, **kwargs):
            calls.append(list(cmd))
            if "--only-binary=:all:" in cmd:
                return _Result(
                    returncode=1,
                    stdout="ERROR: Could not find a version that satisfies "
                           "the requirement obscure-lib (from versions: none)",
                )
            return _Result(returncode=0)

        monkeypatch.setattr(pip_runner.subprocess, "run", _run)
        pip_runner.install_python_deps_to_target({"obscure-lib": ""}, str(tmp_path))

        assert len(calls) == 2, "expected a wheel-only attempt then a fallback"
        assert "--only-binary=:all:" in calls[0]
        assert "--only-binary=:all:" not in calls[1]

    def test_a_real_failure_is_not_retried_forever(self, monkeypatch, tmp_path):
        calls: list[list[str]] = []

        def _run(cmd, **kwargs):
            calls.append(list(cmd))
            return _Result(returncode=1, stdout="ERROR: invalid requirement")

        monkeypatch.setattr(pip_runner.subprocess, "run", _run)
        with pytest.raises(pip_runner.PipInstallError):
            pip_runner.install_python_deps_to_target({"bad": ""}, str(tmp_path))
        assert len(calls) <= 2


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX privilege model")
class TestTheBuildDropsPrivileges:
    def test_it_runs_as_the_execution_user_when_one_is_configured(
        self, runs, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("CURIO_EXEC_USER", "curio-exec")
        monkeypatch.setattr(pip_runner, "_resolve_exec_uid", lambda user: 4242)
        monkeypatch.setattr(pip_runner, "_resolve_exec_gid", lambda user: 4242)

        pip_runner.install_python_deps_to_target({"humanize": ""}, str(tmp_path))

        _cmd, kwargs = runs[0]
        assert kwargs.get("preexec_fn") is not None

    def test_a_local_run_drops_nothing(self, runs, tmp_path, monkeypatch):
        # No execution user is the local case. There is no lesser account to
        # drop to, and refusing to install because of that would break every
        # local run; the preexec still applies limits.
        monkeypatch.delenv("CURIO_EXEC_USER", raising=False)

        pip_runner.install_python_deps_to_target({"humanize": ""}, str(tmp_path))

        _cmd, kwargs = runs[0]
        preexec = kwargs.get("preexec_fn")
        assert preexec is None or pip_runner._drops_privileges(preexec) is False
