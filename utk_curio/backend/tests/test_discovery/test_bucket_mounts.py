"""The bucket mount service's control channel and self-test
(``discovery/infrastructure/bucket_mounts.py``), and the check the backend runs
with them as it starts (``discovery/application/bucket_mount_check.py``).

The rc client is tested against a fake rc server on a Unix socket, in a short
folder of its own (an AF_UNIX path holds about 100 bytes; netguard lets AF_UNIX
through). The self-test runs against a fake service whose "mount" copies the
test file where the mount would show it, and unmount takes it away.
"""

from __future__ import annotations

import errno
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

from utk_curio.backend.app.discovery.application import bucket_mount_check
from utk_curio.backend.app.discovery.infrastructure import bucket_mounts as bm

MOUNT_POINT = "/mounts/.selftest"


# ── A fake rc server on a Unix socket ───────────────────────────────────────


class _RcServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # A handler the timeout test held answers a client that is gone;
        # nothing to report.
        return


class _Handler(http.server.BaseHTTPRequestHandler):
    """Records each call, then answers from the server's ``answers``: a
    ``(status, JSON or bytes)`` per method, ``"hang"`` to answer only once the
    test is over, and ``{}`` otherwise."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        method = self.path.lstrip("/")
        self.server.calls.append((self.command, self.path, self.headers.get("Content-Type"), json.loads(body or b"{}")))
        answer = self.server.answers.get(method, (200, {}))
        if answer == "hang":
            self.server.release.wait(10)
            answer = (200, {})
        status, payload = answer
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        # A Unix socket has no client address to log, and the tests read the calls.
        return


@pytest.fixture
def rc_server():
    folder = tempfile.mkdtemp(prefix="rc")
    path = os.path.join(folder, "rc.sock")
    server = _RcServer(path, _Handler)
    server.calls, server.answers, server.release = [], {}, threading.Event()
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server, path
    finally:
        server.release.set()
        server.shutdown()
        server.server_close()
        thread.join(5)
        shutil.rmtree(folder, ignore_errors=True)


class TestTheRcClient:
    def test_each_call_is_one_post_of_its_json_to_its_path(self, rc_server):
        server, path = rc_server
        server.answers["mount/listmounts"] = (200, {"mountPoints": []})
        client = bm.RcClient(path, timeout=5)

        assert client.call("mount/mount", {"fs": "/selftest", "mountPoint": MOUNT_POINT}) == {}
        assert client.call("mount/listmounts") == {"mountPoints": []}
        assert server.calls == [
            ("POST", "/mount/mount", "application/json", {"fs": "/selftest", "mountPoint": MOUNT_POINT}),
            ("POST", "/mount/listmounts", "application/json", {}),
        ]

    def test_rclones_error_answer_becomes_its_reason(self, rc_server):
        server, path = rc_server
        server.answers["mount/unmount"] = (500, {
            "error": "mount not found", "input": {"mountPoint": MOUNT_POINT},
            "path": "mount/unmount", "status": 500,
        })

        with pytest.raises(bm.RcError) as refused:
            bm.RcClient(path, timeout=5).call("mount/unmount", {"mountPoint": MOUNT_POINT})
        assert refused.value.kind == "refused"
        assert str(refused.value) == "the mount service refused mount/unmount: mount not found"

    def test_an_answer_that_is_not_json_is_named(self, rc_server):
        server, path = rc_server
        server.answers["rc/noop"] = (200, b"<html>not rclone</html>")

        with pytest.raises(bm.RcError) as malformed:
            bm.RcClient(path, timeout=5).call("rc/noop")
        assert malformed.value.kind == "malformed"
        assert "something other than JSON" in str(malformed.value)

    def test_a_call_with_no_answer_times_out(self, rc_server):
        server, path = rc_server
        server.answers["rc/noop"] = "hang"

        started = time.monotonic()
        with pytest.raises(bm.RcError) as late:
            bm.RcClient(path, timeout=0.3).call("rc/noop")
        assert late.value.kind == "timeout"
        assert str(late.value) == "the mount service did not answer rc/noop within 0.3 s"
        assert time.monotonic() - started < 5

    def test_a_missing_socket_is_unreachable_and_named(self):
        folder = tempfile.mkdtemp(prefix="rc")
        missing = os.path.join(folder, "rc.sock")
        try:
            with pytest.raises(bm.RcError) as gone:
                bm.RcClient(missing, timeout=5).call("rc/noop")
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        assert gone.value.kind == "unreachable"
        assert missing in str(gone.value)


# ── The self-test, against a fake service ───────────────────────────────────


class _FakeService:
    """The mount service as the self-test calls it. ``operations/mkdir``
    makes the test mount's folder in *mounts_dir*, ``mount/mount`` "mounts" by
    writing the test file there (unless *propagate* is off), and
    ``mount/unmount`` takes it away. *refuse* maps a method to rclone's error;
    *unreachable* makes the first calls find no service."""

    def __init__(self, mounts_dir: Path, *, refuse=None, propagate=True,
                 line=bm.SELFTEST_LINE, leftover=False, unreachable=0):
        self.mounts_dir = mounts_dir
        self.refuse = dict(refuse or {})
        self.propagate = propagate
        self.line = line
        self.mounted = leftover
        self.unreachable = unreachable
        self.calls = []

    def call(self, method, params=None, *, timeout=None):
        self.calls.append((method, dict(params or {})))
        if self.unreachable:
            self.unreachable -= 1
            raise bm.RcError("unreachable", "nothing answers on the mount service's socket /run/x/rc.sock")
        if method in self.refuse:
            raise bm.RcError("refused", f"the mount service refused {method}: {self.refuse[method]}")
        folder = self.mounts_dir / bm.SELFTEST_MOUNT
        if method == "operations/mkdir":
            folder.mkdir(parents=True, exist_ok=True)
        elif method == "mount/mount":
            if self.propagate:
                (folder / bm.SELFTEST_FILE).write_text(self.line + "\n")
            self.mounted = True
        elif method == "mount/unmount":
            (folder / bm.SELFTEST_FILE).unlink(missing_ok=True)
            self.mounted = False
        elif method == "mount/listmounts":
            return {"mountPoints": [{"Fs": bm.SELFTEST_FOLDER, "MountPoint": MOUNT_POINT}] if self.mounted else []}
        return {}

    def methods(self):
        return [method for method, _ in self.calls]


class TestTheSelfTest:
    def test_it_mounts_the_test_folder_reads_it_and_unmounts_it(self, tmp_path):
        service = _FakeService(tmp_path)

        outcome = bm.self_test(service, tmp_path, wait_seconds=0)

        assert (outcome.passed, outcome.problem) == (True, None)
        assert service.methods() == [
            "rc/noop", "mount/listmounts", "operations/mkdir", "mount/mount", "mount/unmount",
        ]
        assert service.calls[2][1] == {"fs": "/mounts", "remote": ".selftest"}
        # Read-only, with allow_other, no cache, files 0444 and folders 0555,
        # as flat parameters, which rclone refuses by name when it does not know one.
        assert service.calls[3][1] == {
            "fs": "/selftest", "mountPoint": MOUNT_POINT, "mountType": "mount",
            "allow_other": True, "read_only": True, "vfs_cache_mode": "off",
            "file_perms": "0444", "dir_perms": "0555",
        }
        assert service.calls[4][1] == {"mountPoint": MOUNT_POINT}
        assert not service.mounted

    def test_it_reads_as_the_execution_account_with_its_ids(self, tmp_path, monkeypatch):
        service = _FakeService(tmp_path)
        runs = []

        def run(argv, **kwargs):
            runs.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, (bm.SELFTEST_LINE + "\n").encode(), b"")

        monkeypatch.setattr(bm.subprocess, "run", run)
        outcome = bm.self_test(service, tmp_path, account=bm.Account("curio-exec", 999, 998), wait_seconds=0)

        assert outcome.passed, outcome.detail
        assert "as curio-exec (uid 999)" in outcome.detail
        [(argv, kwargs)] = runs
        assert (kwargs["user"], kwargs["group"], kwargs["extra_groups"]) == (999, 998, [])
        # Nothing of the backend's environment reaches the reader.
        assert (kwargs["env"], kwargs["cwd"]) == ({}, "/")
        assert argv[-1] == str(tmp_path / ".selftest" / "ok")

    def test_a_read_the_execution_account_cannot_make_fails_and_still_unmounts(self, tmp_path, monkeypatch):
        service = _FakeService(tmp_path)
        monkeypatch.setattr(
            bm.subprocess, "run",
            lambda argv, **kwargs: subprocess.CompletedProcess(argv, 100 + errno.EACCES, b"", b""),
        )

        outcome = bm.self_test(service, tmp_path, account=bm.Account("curio-exec", 999, 998), wait_seconds=0)

        assert (outcome.passed, outcome.problem) == (False, "not-readable")
        assert "curio-exec (uid 999)" in outcome.detail
        assert os.strerror(errno.EACCES) in outcome.detail
        assert service.calls[-1] == ("mount/unmount", {"mountPoint": MOUNT_POINT})
        assert not service.mounted

    def test_a_refused_mount_fails_with_rclones_reason(self, tmp_path):
        service = _FakeService(tmp_path, refuse={
            "mount/mount": "failed to mount FUSE fs: fusermount3: mount failed: Permission denied",
        })

        outcome = bm.self_test(service, tmp_path, wait_seconds=0)

        assert (outcome.passed, outcome.problem) == (False, "mount-refused")
        assert "fusermount3: mount failed: Permission denied" in outcome.detail
        assert "mount/unmount" not in service.methods()

    def test_a_service_that_is_gone_fails_as_no_service(self, tmp_path):
        outcome = bm.self_test(bm.RcClient(tmp_path / "rc.sock", timeout=5), tmp_path, wait_seconds=0)

        assert (outcome.passed, outcome.problem) == (False, "no-service")
        assert "rc/noop" in outcome.detail

    def test_it_waits_for_a_service_that_starts_after_the_backend(self, tmp_path):
        service = _FakeService(tmp_path, unreachable=2)
        now, sleeps = [0.0], []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        outcome = bm.self_test(service, tmp_path, wait_seconds=60, sleep=sleep, clock=lambda: now[0])

        assert outcome.passed, outcome.detail
        assert sleeps == [bm.SERVICE_RETRY_SECONDS] * 2

    def test_it_stops_waiting_for_a_service_that_never_answers(self, tmp_path):
        service = _FakeService(tmp_path, unreachable=1000)
        now = [0.0]

        def sleep(seconds):
            now[0] += seconds

        outcome = bm.self_test(service, tmp_path, wait_seconds=5, sleep=sleep, clock=lambda: now[0])

        assert (outcome.passed, outcome.problem) == (False, "no-service")
        assert service.methods() == ["rc/noop"] * 4

    def test_a_mount_that_did_not_reach_this_container_fails_as_not_propagated(self, tmp_path):
        service = _FakeService(tmp_path, propagate=False)

        outcome = bm.self_test(service, tmp_path, wait_seconds=0)

        assert (outcome.passed, outcome.problem) == (False, "not-propagated")
        assert f"errno {errno.ENOENT}" in outcome.detail
        assert service.methods()[-1] == "mount/unmount"

    def test_another_file_fails_as_wrong_file(self, tmp_path):
        service = _FakeService(tmp_path, line="not the service's line")

        outcome = bm.self_test(service, tmp_path, wait_seconds=0)

        assert (outcome.passed, outcome.problem) == (False, "wrong-file")
        assert not service.mounted

    def test_a_test_mount_a_stopped_self_test_left_is_unmounted_first(self, tmp_path):
        service = _FakeService(tmp_path, leftover=True)

        outcome = bm.self_test(service, tmp_path, wait_seconds=0)

        assert outcome.passed, outcome.detail
        assert service.methods() == [
            "rc/noop", "mount/listmounts", "mount/unmount", "operations/mkdir", "mount/mount", "mount/unmount",
        ]

    def test_a_refused_unmount_fails_the_self_test(self, tmp_path):
        service = _FakeService(tmp_path, refuse={"mount/unmount": "mount not found"})

        outcome = bm.self_test(service, tmp_path, wait_seconds=0)

        assert (outcome.passed, outcome.problem) == (False, "unmount-refused")
        assert "mount not found" in outcome.detail


class TestTheRead:
    def test_the_childs_reader_gives_the_file_or_the_errno_that_stopped_it(self, tmp_path):
        """The child's own program, run as this account."""
        (tmp_path / "ok").write_text(bm.SELFTEST_LINE + "\n")
        assert bm._read_in_child(tmp_path / "ok", None) == bm.SELFTEST_LINE + "\n"

        with pytest.raises(bm.SelfTestFailed) as missing:
            bm._read_in_child(tmp_path / "missing", None)
        assert missing.value.problem == "not-propagated"
        assert f"errno {errno.ENOENT}" in missing.value.detail

    def test_the_execution_account_reads_only_where_this_process_is_root(self, monkeypatch):
        import pwd

        class _Entry:
            pw_uid, pw_gid = 999, 998

        def getpwnam(name):
            if name != "curio-exec":
                raise KeyError(name)
            return _Entry

        monkeypatch.setattr(pwd, "getpwnam", getpwnam)
        named = {bm.EXEC_USER_VARIABLE: "curio-exec"}

        monkeypatch.setattr(os, "geteuid", lambda: 0)
        assert bm.execution_account(named) == bm.Account("curio-exec", 999, 998)
        assert bm.execution_account({bm.EXEC_USER_VARIABLE: ""}) is None
        assert bm.execution_account({bm.EXEC_USER_VARIABLE: "nobody-here"}) is None

        monkeypatch.setattr(os, "geteuid", lambda: 1000)
        assert bm.execution_account(named) is None


# ── The check at backend start, and what /monitor reads of it ───────────────


@pytest.fixture
def check(monkeypatch):
    from utk_curio.backend.app.monitor import errors

    errors.reset()
    bucket_mount_check.reset()
    monkeypatch.setenv(bm.DIR_VARIABLE, "/bucket-mounts")
    monkeypatch.setenv(bm.SOCKET_VARIABLE, "/run/curio-bucket-mounts/rc.sock")
    yield bucket_mount_check
    bucket_mount_check.reset()
    errors.reset()


class TestTheCheck:
    def test_with_no_service_named_there_is_none(self, check, monkeypatch):
        monkeypatch.delenv(bm.SOCKET_VARIABLE)

        assert check.start() is False
        assert check.status() == {"state": "none", "problem": None}

    def test_it_is_pending_until_the_self_test_ends(self, check):
        assert check.status() == {"state": "pending", "problem": None}

    def test_a_passed_self_test_is_passed(self, check):
        check.record(bm.SelfTest(True, None, "mounted /selftest at /mounts/.selftest, read it, unmounted it"))

        assert check.status() == {"state": "passed", "problem": None}

    def test_a_failed_self_test_says_why_in_words_and_is_one_of_the_recent_errors(self, check):
        from utk_curio.backend.app.monitor import errors

        detail = "reading /bucket-mounts/.selftest/ok as curio-exec (uid 999): Permission denied (errno 13)"
        check.record(bm.SelfTest(False, "not-readable", detail))

        assert check.status() == {"state": "unavailable", "problem": bm.PROBLEMS["not-readable"]}
        [entry] = errors.snapshot()["errors"]
        assert entry["source"] == "backend"
        assert entry["summary"] == f"Bucket mounts are unavailable: {bm.PROBLEMS['not-readable']}"
        assert entry["detail"] == detail

    def test_it_runs_the_self_test_once_on_a_thread_of_its_own(self, check, monkeypatch):
        from utk_curio.backend.app.discovery.application import bucket_mount_sources

        runs = []

        def self_test_from_env():
            runs.append(("self-test", threading.current_thread().name))
            return bm.SelfTest(True, None, "passed")

        monkeypatch.setattr(bm, "self_test_from_env", self_test_from_env)
        # After a passed self-test, the same thread looks at the service's
        # mounts of sources (test_bucket_mount_sources.py tests what it does).
        monkeypatch.setattr(bucket_mount_sources, "reconcile_at_start",
                            lambda: runs.append(("mounts", threading.current_thread().name)))
        assert check.start() is True
        assert check.start() is True
        check._thread.join(5)

        assert runs == [("self-test", "bucket-mounts-self-test"), ("mounts", "bucket-mounts-self-test")]
        assert check.status() == {"state": "passed", "problem": None}

    def test_a_self_test_that_raises_still_reports(self, check, monkeypatch):
        def broken():
            raise RuntimeError("a bug")

        monkeypatch.setattr(bm, "self_test_from_env", broken)
        check.start()
        check._thread.join(5)

        assert check.status() == {"state": "unavailable", "problem": bm.PROBLEMS["error"]}
