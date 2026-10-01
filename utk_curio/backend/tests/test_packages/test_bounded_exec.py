"""A bounded child gets its limits after exec, never from a ``preexec_fn``.

``preexec_fn`` runs Python in the forked copy of a threaded process, and a lock
another thread held at the fork stays held in that copy, so the child can hang
before exec with the parent waiting on it for good. CI caught it in
``test_invocation_waits_out_the_replace_window``: the invocation's child was
still a copy of pytest, parked on a futex. ``bounded_exec`` execs a fresh
interpreter first, which sets the limits and then execs the real command.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.infrastructure import bounded_exec
from utk_curio.backend.app.packages.infrastructure import workspace as build_workspace
from utk_curio.backend.app.packages.infrastructure.workspace import WorkerLimits

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX rlimits")

# The whole packages tree: its modules sit in layer directories now.
PACKAGES = Path(build_workspace.__file__).resolve().parents[1]


def _run(argv, bounds):
    return subprocess.run(
        bounded_exec.bounded_argv(argv, bounds), capture_output=True, text=True, timeout=60,
    )


class TestTheCommandStartsBounded:
    def test_its_limits_are_set_before_it_runs(self):
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(64, soft)
        out = _run(
            [sys.executable, "-c",
             "import resource; print(resource.getrlimit(resource.RLIMIT_NOFILE))"],
            {"rlimits": [[resource.RLIMIT_NOFILE, target]]},
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == str((target, target))

    def test_it_is_the_command_itself_not_a_child_of_the_trampoline(self):
        # exec replaces the trampoline, so killing the pid Popen returned kills
        # the command, as it did before.
        proc = subprocess.Popen(
            bounded_exec.bounded_argv(
                [sys.executable, "-c", "import os, sys; sys.stdout.write(str(os.getpid()))"],
                {"rlimits": []},
            ),
            stdout=subprocess.PIPE, text=True,
        )
        out, _ = proc.communicate(timeout=60)
        assert out == str(proc.pid)

    def test_a_missing_command_says_so_and_exits_127(self):
        out = _run(["/nonexistent/curio-worker"], {"rlimits": []})
        assert out.returncode == 127
        assert "cannot start /nonexistent/curio-worker" in out.stderr

    def test_the_bounds_can_be_read_back(self):
        argv = bounded_exec.bounded_argv(["pip", "install"], {"rlimits": [[1, 2]], "drop": [5, 6]})
        assert bounded_exec.bounds_of(argv) == {"rlimits": [[1, 2]], "drop": [5, 6]}
        assert bounded_exec.command_of(argv) == ["pip", "install"]
        assert bounded_exec.bounds_of(["pip", "install"]) is None


class TestRunWorker:
    def test_it_passes_no_preexec_fn(self, tmp_path, monkeypatch):
        seen: dict = {}

        class _Stop(Exception):
            pass

        def _popen(argv, **kwargs):
            seen["argv"], seen["kwargs"] = argv, kwargs
            raise _Stop

        monkeypatch.setattr(build_workspace.subprocess, "Popen", _popen)
        ws = build_workspace.create_workspace("bounded-exec-test")
        try:
            with pytest.raises(_Stop):
                build_workspace.run_worker(
                    ws, [sys.executable, "-c", "pass"], limits=WorkerLimits(wall_time_seconds=5.0),
                )
        finally:
            build_workspace.destroy_workspace(ws)
        assert "preexec_fn" not in seen["kwargs"]
        bounds = bounded_exec.bounds_of(seen["argv"])
        assert bounds is not None and bounds["rlimits"]
        assert bounded_exec.command_of(seen["argv"]) == [sys.executable, "-c", "pass"]


def test_nothing_in_the_package_runtime_forks_with_a_preexec_fn():
    # A new subprocess call reaching for preexec_fn would bring the hang back.
    offenders = [
        f"{path.name}:{number}"
        for path in sorted(PACKAGES.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bpreexec_fn\s*=", line)
    ]
    assert offenders == []
