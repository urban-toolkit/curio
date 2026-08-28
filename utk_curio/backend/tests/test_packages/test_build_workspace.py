"""Isolation tests for :mod:`utk_curio.backend.app.packages.build_workspace`
(dev/89 commit 3): scrubbed env, read-only inputs, resource/wall/output
bounds, process-group cancellation, sanitized diagnostics, bounded output
collection, and workspace destruction.
"""

from __future__ import annotations

import os
import sys
import threading
import time

from unittest import mock

import pytest

from utk_curio.backend.app.packages import build_workspace
from utk_curio.backend.app.packages.build_workspace import (
    WorkerLimits,
    WorkspaceError,
    collect_outputs,
    create_workspace,
    destroy_workspace,
    populate_inputs,
    run_worker,
    sanitize_diagnostic,
)

_PY = sys.executable

#: Created by the Dockerfile; only exists inside the image. Same account the
#: sandbox's own drop fixture uses (sandbox/tests/test_isolation_linux.py).
EXEC_USER = "curio-exec"


@pytest.fixture()
def workspace():
    ws = create_workspace("deadbeefdeadbeef")
    yield ws
    destroy_workspace(ws)


@pytest.fixture()
def unprivileged_worker(workspace, monkeypatch):
    """Make ``run_worker``'s child run as an unprivileged user.

    A no-op when this process is already unprivileged — mode bits bite on
    their own there, which is the ordinary developer case. Inside the CI
    container pytest runs as root, and root reads and writes through any mode
    bit, so the read-only-input assertion below cannot hold: it observed
    ``status == "ok"`` and failed the whole backend suite. Skipping it there
    would leave the guarantee unexercised in the one environment that runs it
    on every push, so drop privileges instead.

    Wraps the ``preexec_fn`` ``run_worker`` already installs rather than
    adding a run-as parameter to ``build_workspace`` that no production caller
    would pass. Same account and the same 0711 traversal as ``isolated_dropped``
    in ``utk_curio/sandbox/tests/test_isolation_linux.py``.
    """
    if os.name != "posix" or os.geteuid() != 0:
        return  # already unprivileged; the chmod is the whole boundary

    import pwd

    try:
        account = pwd.getpwnam(EXEC_USER)
    except KeyError:
        pytest.skip(f"the {EXEC_USER} account does not exist on this host")

    # mkdtemp gives the root 0700 root-owned, so a dropped child could not
    # traverse into its own cwd/HOME/TMPDIR (_minimal_env points all three at
    # work/). 0711: reachable, still not listable. Only this one directory --
    # everything above it is the system temp tree, which is world-traversable
    # by construction (/tmp is 1777), and widening it here would strip that
    # sticky bit for every other process in the container. input/ is
    # deliberately left alone: populate_inputs leaves it 0555/0444 and that is
    # exactly the boundary under test.
    os.chmod(workspace.root, 0o711)
    for d in (workspace.work_dir, workspace.cache_dir, workspace.output_dir):
        os.chmod(d, 0o777)

    original = build_workspace._apply_rlimits

    def _dropping(limits):
        applied, preexec = original(limits)

        def _child() -> None:  # runs in the child, pre-exec
            preexec()  # rlimits first: after setuid they can only be lowered
            os.setgroups([])
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)  # last — nothing can be dropped after

        return applied, _child

    monkeypatch.setattr(build_workspace, "_apply_rlimits", _dropping)


def _run(ws, code: str, **kwargs) -> "WorkerResult":
    limits = kwargs.pop("limits", WorkerLimits(wall_time_seconds=20.0))
    return run_worker(ws, [_PY, "-c", code], limits=limits, **kwargs)


class TestLayoutAndInputs:
    def test_four_directories(self, workspace):
        for d in (workspace.input_dir, workspace.cache_dir, workspace.work_dir,
                  workspace.output_dir):
            assert d.is_dir()
        # In the system temp tree, never under the launch dir or repo.
        assert ".curio" not in str(workspace.root)

    def test_inputs_become_read_only(self, workspace, unprivileged_worker):
        populate_inputs(workspace, {"sources/a.py": b"return arg\n"})
        target = workspace.input_dir / "sources" / "a.py"
        assert target.read_bytes() == b"return arg\n"
        result = _run(
            workspace,
            "import os\n"
            "p = os.path.join(os.environ['CURIO_BUILD_INPUT_DIR'], 'sources', 'a.py')\n"
            "open(p, 'a').write('tamper')\n",
        )
        assert result.status == "failed"  # PermissionError inside the worker
        assert target.read_bytes() == b"return arg\n"

    def test_inputs_populate_only_once(self, workspace):
        populate_inputs(workspace, {"sources/a.py": b"x"})
        with pytest.raises(WorkspaceError, match="immutable"):
            populate_inputs(workspace, {"sources/b.py": b"y"})

    def test_input_escape_refused(self, workspace):
        with pytest.raises(WorkspaceError, match="escapes"):
            populate_inputs(workspace, {"../evil.py": b"x"})


class TestEnvironmentScrubbing:
    def test_host_env_never_reaches_the_worker(self, workspace, monkeypatch):
        monkeypatch.setenv("CURIO_TEST_SECRET", "hunter2")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
        result = _run(
            workspace,
            "import os, json; print(json.dumps(dict(os.environ)))",
        )
        assert result.status == "ok"
        assert "hunter2" not in result.stdout_tail
        assert "aws-secret" not in result.stdout_tail
        assert "CURIO_TEST_SECRET" not in result.stdout_tail

    def test_home_and_tmp_point_into_the_workspace(self, workspace):
        result = _run(workspace, "import os; print(os.environ['HOME'])")
        assert result.status == "ok"
        # The path is sanitized in the tail — the placeholder proves it
        # pointed inside the workspace.
        assert "<workspace>" in result.stdout_tail

    def test_explicit_extra_env_rides_along(self, workspace):
        result = _run(workspace, "import os; print(os.environ['CURIO_BUILD_MODE'])",
                      extra_env={"CURIO_BUILD_MODE": "create"})
        assert result.status == "ok" and "create" in result.stdout_tail

    def test_bad_extra_env_refused(self, workspace):
        with pytest.raises(WorkspaceError, match="extra_env"):
            _run(workspace, "print(1)", extra_env={"KEY": 5})


class TestBounds:
    def test_ok_and_failed_exit_codes(self, workspace):
        assert _run(workspace, "print('fine')").status == "ok"
        failed = _run(workspace, "raise SystemExit(3)")
        assert failed.status == "failed" and failed.exit_code == 3

    def test_wall_timeout_kills_the_group(self, workspace):
        started = time.monotonic()
        result = _run(workspace, "import time; time.sleep(30)",
                      limits=WorkerLimits(wall_time_seconds=1.0))
        assert result.status == "timeout"
        assert time.monotonic() - started < 10

    def test_output_cap_kills_the_worker(self, workspace):
        result = _run(
            workspace,
            "import sys\n"
            "while True: sys.stdout.write('x' * 8192); sys.stdout.flush()\n",
            limits=WorkerLimits(wall_time_seconds=20.0, max_output_bytes=64 * 1024),
        )
        assert result.status == "output-limit"
        # The stored tail stays bounded regardless of what the worker wrote.
        assert len(result.stdout_tail) <= 4_100

    def test_cpu_bound_is_applied_and_reported(self, workspace):
        """A CPU bound reaches the worker, on POSIX and on Windows alike.

        This asserted the *mechanism* - it read `resource.getrlimit` from
        inside the worker - so it could only ever pass on POSIX, and on Windows
        the payload's own `import resource` failed the run. The guarantee is
        that a cpu bound was applied; how it was applied is the platform's
        business (setrlimit, or a Job Object's PerJobUserTimeLimit).
        """
        result = _run(
            workspace,
            "print('worker ran')",
            limits=WorkerLimits(wall_time_seconds=20.0, cpu_seconds=7),
        )
        assert result.status == "ok"
        assert "worker ran" in result.stdout_tail
        assert "cpu" in result.limits_applied

    @pytest.mark.skipif(os.name == "nt", reason="reads POSIX setrlimit directly")
    def test_posix_rlimit_reaches_the_child_verbatim(self, workspace):
        # The mechanism check, kept where it can run: the child sees the exact
        # ceiling, not merely a claim that one was set.
        result = _run(
            workspace,
            "import resource; print(resource.getrlimit(resource.RLIMIT_CPU)[0])",
            limits=WorkerLimits(wall_time_seconds=20.0, cpu_seconds=7),
        )
        assert result.status == "ok"
        assert "7" in result.stdout_tail

    def test_cancellation_kills_promptly(self, workspace):
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        result = _run(workspace, "import time; time.sleep(30)",
                      limits=WorkerLimits(wall_time_seconds=30.0), cancel=cancel)
        assert result.status == "cancelled"
        assert time.monotonic() - started < 10


class TestOutputsAndCleanup:
    def test_collect_outputs(self, workspace):
        result = _run(
            workspace,
            "import os\n"
            "out = os.environ['CURIO_BUILD_OUTPUT_DIR']\n"
            "os.makedirs(os.path.join(out, 'scripts'), exist_ok=True)\n"
            "open(os.path.join(out, 'scripts', 'behaviors.js'), 'w').write('registered')\n",
        )
        assert result.status == "ok"
        outputs = collect_outputs(workspace)
        assert outputs == {"scripts/behaviors.js": b"registered"}

    def test_symlink_output_refused(self, workspace):
        """The guard runs on every platform; only the setup is privileged.

        Creating a real symlink on Windows needs SeCreateSymbolicLinkPrivilege
        (WinError 1314), so the fixture cannot be built there - but the guard
        being tested is `collect_outputs`, which is plain `is_symlink()` logic
        and identical on both. Where a real link is possible, use one; where it
        is not, present the same condition to the guard.
        """
        (workspace.output_dir / "real.txt").write_bytes(b"x")
        link = workspace.output_dir / "link.txt"
        try:
            link.symlink_to(workspace.output_dir / "real.txt")
        except OSError:
            link.write_bytes(b"x")
            import pathlib

            original = pathlib.Path.is_symlink

            def _fake_is_symlink(self):
                return self.name == "link.txt" or original(self)

            with mock.patch.object(pathlib.Path, "is_symlink", _fake_is_symlink):
                with pytest.raises(WorkspaceError, match="symlink"):
                    collect_outputs(workspace)
            return
        with pytest.raises(WorkspaceError, match="symlink"):
            collect_outputs(workspace)

    def test_output_caps(self, workspace):
        for i in range(3):
            (workspace.output_dir / f"f{i}.txt").write_bytes(b"x")
        with pytest.raises(WorkspaceError, match="file limit"):
            collect_outputs(workspace, max_files=2)
        with pytest.raises(WorkspaceError, match="total size"):
            collect_outputs(workspace, max_total_bytes=2)

    def test_destroy_removes_read_only_inputs(self):
        ws = create_workspace("cleanup-test")
        populate_inputs(ws, {"sources/a.py": b"x"})
        destroy_workspace(ws)
        assert not ws.root.exists()
        destroy_workspace(ws)  # idempotent


class TestSanitization:
    def test_workspace_and_home_paths_stripped(self, workspace):
        text = f"error at {workspace.root}/work/x.py and {os.path.expanduser('~')}/.ssh"
        cleaned = sanitize_diagnostic(text, workspace=workspace)
        assert str(workspace.root) not in cleaned
        assert "<workspace>/work/x.py" in cleaned
        assert "<home>/.ssh" in cleaned

    def test_worker_tails_are_sanitized(self, workspace):
        result = _run(workspace, "import os; print(os.getcwd())")
        assert result.status == "ok"
        assert str(workspace.root) not in result.stdout_tail
