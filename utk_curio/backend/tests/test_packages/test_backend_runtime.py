"""memo dev/91 commit 2 — the backend sandbox runtime + harness, exercised
with REAL worker subprocesses (the A9 lesson: fakes never catch what the
real toolchain refuses).

The suite installs a tiny backend-bearing package into a temp user store and
drives ``invoke_handler`` end-to-end: success, probe-without-execution,
handler failure, env scrub (a poisoned parent secret never reaches the
worker), the advisory network guard, persistent data dir + cap, timeout
kill, missing-reply contract error, digest drift, undeclared handlers,
payload bounds, and the audit ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from utk_curio.backend.app.common.user_storage import users_base
from utk_curio.backend.app.packages import backend_contract as bc
from utk_curio.backend.app.packages import backend_runtime as rt
from utk_curio.backend.app.packages.build_workspace import WorkerLimits

USER = "42"  # user keys are guest-or-numeric (storage._user_key_segment)
PKG = "curio.counter@1"

#: Tight limits keep the real-subprocess suite fast; the wall clock only has
#: to outlive interpreter startup.
FAST = WorkerLimits(wall_time_seconds=20.0, cpu_seconds=10)
KILL_FAST = WorkerLimits(wall_time_seconds=1.5, cpu_seconds=10)

_HANDLER_SRC = '''\
import json
import os


def _count(payload):
    return {"words": len(str(payload.get("text", "")).split())}


def _env_probe(payload):
    return {"present": [k for k in payload["names"] if k in os.environ]}


def _net(payload):
    import socket
    socket.socket()
    return {"reached": True}


def _remember(payload):
    data_dir = os.environ["CURIO_PKG_DATA_DIR"]
    path = os.path.join(data_dir, "note.txt")
    if "write" in payload:
        with open(path, "w") as fh:
            fh.write(payload["write"])
        return {"wrote": True}
    with open(path) as fh:
        return {"read": fh.read()}


def _boom(payload):
    raise RuntimeError("the handler exploded")


def _spin(payload):
    while True:
        pass


def _unserializable(payload):
    return {"x": object()}


HANDLERS = {
    "word-count": _count,
    "env-probe": _env_probe,
    "net": _net,
    "remember": _remember,
    "boom": _boom,
    "spin": _spin,
    "unserializable": _unserializable,
}
'''

_ALL_HANDLERS = ["word-count", "env-probe", "net", "remember", "boom", "spin",
                 "unserializable"]


def _user_store(tmp_path: Path) -> Path:
    """The per-user root the app will use once ``CURIO_LAUNCH_CWD`` is *tmp_path*.

    Asked of the code rather than spelled out here. Under ``CURIO_TESTING`` —
    which the root conftest sets for the whole suite — that root is
    ``.curio/test/users/`` (see ``common/user_storage``), so a literal
    ``tmp_path / ".curio" / "users"`` builds a tree the app never looks at and
    every assertion below fails on an empty store.
    """
    base = users_base()
    assert base.is_relative_to(tmp_path.resolve()), (
        f"store root {base} escaped the tmp workspace {tmp_path}; "
        "CURIO_LAUNCH_CWD was probably not patched before this call"
    )
    return base


def _install_pkg(monkeypatch, tmp_path: Path, *, permissions=None,
                 handler_src: str = _HANDLER_SRC) -> Path:
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    pkg = _user_store(tmp_path) / USER / "packages" / PKG
    (pkg / "backend").mkdir(parents=True)
    perms = [bc.PERMISSION_SERVER_CODE] + list(permissions or [])
    manifest = {
        "id": "curio.counter", "version": "1.0.0", "name": "Counter",
        "publisher": "t", "description": "d", "compatibility": {"major": 1},
        "permissions": perms,
        "templates": [{
            "id": "counter", "label": "Counter", "category": "computation",
            "engine": "python", "editor": "none", "hasCode": False,
            "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "backendHandler": "word-count",
        }],
        "backend": {
            "entry": "backend/handler.py",
            "handlers": [{"name": n, "timeoutClass": "quick"} for n in _ALL_HANDLERS],
        },
    }
    (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pkg / "backend" / "handler.py").write_text(handler_src, encoding="utf-8")
    return pkg


@pytest.fixture(autouse=True)
def _fresh_breakers_everywhere():
    # dev/92 B-3: breaker state is module-global in backend_runtime — every
    # test in THIS file starts clean, whatever the execution order.
    rt.reset_breakers()
    yield
    rt.reset_breakers()


def _ledger_rows(tmp_path: Path) -> list[dict]:
    root = _user_store(tmp_path) / USER / "package-backend-ledger" / PKG
    rows: list[dict] = []
    if root.is_dir():
        for day_file in sorted(root.glob("*.jsonl")):
            rows.extend(json.loads(line) for line in day_file.read_text().splitlines())
    return rows


class TestInvokeHandler:
    def test_success_end_to_end(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        out = rt.invoke_handler(USER, PKG, "word-count", {"text": "a b c"}, limits=FAST)
        assert out["reply"] == {"contract": bc.PKGBACKEND_CONTRACT_VERSION,
                                "ok": True, "result": {"words": 3}}
        assert out["workerStatus"] == "ok"
        assert out["invocationId"] and out["entryDigest"]
        rows = _ledger_rows(tmp_path)
        assert len(rows) == 1 and rows[0]["status"] == "ok"
        assert rows[0]["handler"] == "word-count"
        # The audit row records sizes and outcomes, never payload contents.
        assert "a b c" not in json.dumps(rows[0])

    def test_probe_answers_ok_without_running_the_handler(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        # "boom" raises on ANY execution — a probe must succeed anyway,
        # because load + resolution IS the health check (memo dev/91 §3).
        out = rt.invoke_handler(USER, PKG, "boom", bc.probe_payload(), limits=FAST)
        assert out["reply"]["ok"] is True
        assert out["reply"]["result"]["probe"] == "ok"

    def test_handler_exception_is_an_honest_handler_error(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        out = rt.invoke_handler(USER, PKG, "boom", {}, limits=FAST)
        assert out["reply"]["ok"] is False
        assert out["reply"]["kind"] == "handler-error"
        assert "the handler exploded" in out["reply"]["error"]
        assert _ledger_rows(tmp_path)[0]["status"] == "reply-handler-error"

    def test_unserializable_result_is_a_handler_error(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        out = rt.invoke_handler(USER, PKG, "unserializable", {}, limits=FAST)
        assert out["reply"]["ok"] is False and out["reply"]["kind"] == "handler-error"
        assert "non-JSON" in out["reply"]["error"]

    def test_worker_env_is_scrubbed_of_host_secrets(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        monkeypatch.setenv("CURIO_SEARCH_URL", "https://example.test/?api_key=SECRET")
        monkeypatch.setenv("AICONN_API_KEY", "hostsecret")
        out = rt.invoke_handler(
            USER, PKG, "env-probe",
            {"names": ["CURIO_SEARCH_URL", "AICONN_API_KEY", "CURIO_PKG_DATA_DIR"]},
            limits=FAST,
        )
        # The from-scratch env carries ONLY the sandbox's own vars.
        assert out["reply"]["result"]["present"] == ["CURIO_PKG_DATA_DIR"]

    def test_network_guard_blocks_undeclared_and_opens_declared(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        out = rt.invoke_handler(USER, PKG, "net", {}, limits=FAST)
        assert out["reply"]["ok"] is False
        assert "server-network" in out["reply"]["error"]

    def test_declared_network_permission_lifts_the_guard(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path,
                     permissions=[bc.PERMISSION_SERVER_NETWORK])
        out = rt.invoke_handler(USER, PKG, "net", {}, limits=FAST)
        # socket.socket() constructs without touching any real network.
        assert out["reply"] == {"contract": bc.PKGBACKEND_CONTRACT_VERSION,
                                "ok": True, "result": {"reached": True}}

    def test_data_dir_persists_across_invocations_and_caps(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        assert rt.invoke_handler(USER, PKG, "remember", {"write": "kept"},
                                 limits=FAST)["reply"]["result"] == {"wrote": True}
        assert rt.invoke_handler(USER, PKG, "remember", {},
                                 limits=FAST)["reply"]["result"] == {"read": "kept"}
        # Over-cap refuses the NEXT invocation with the stated 507 (§6.7).
        monkeypatch.setattr(rt, "DATA_DIR_MAX_BYTES", 1)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "remember", {}, limits=FAST)
        assert exc.value.status == 507 and "clear it" in str(exc.value)

    def test_timeout_kills_the_worker_and_reports_502(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "spin", {}, limits=KILL_FAST)
        assert exc.value.status == 502 and "timeout" in str(exc.value)
        assert _ledger_rows(tmp_path)[0]["status"] == "worker-timeout"

    def test_worker_exit_zero_without_reply_is_a_502(self, monkeypatch, tmp_path):
        # os._exit(0) at entry import: the harness dies "successfully"
        # without writing a reply — the no-reply contract branch.
        _install_pkg(monkeypatch, tmp_path,
                     handler_src="import os\nos._exit(0)\n")
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc.value.status == 502
        assert "without a reply envelope" in str(exc.value)

    def test_worker_nonzero_exit_is_a_502(self, monkeypatch, tmp_path):
        # os._exit(3) bypasses even the harness's BaseException net — the
        # worker's own failure status is the diagnosis.
        _install_pkg(monkeypatch, tmp_path,
                     handler_src="import os\nos._exit(3)\n")
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc.value.status == 502
        assert "did not complete (failed)" in str(exc.value)
        assert _ledger_rows(tmp_path)[0]["status"] == "worker-failed"

    def test_entry_load_failure_is_a_handler_error(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path, handler_src="import not_a_real_module\n")
        out = rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert out["reply"]["ok"] is False and out["reply"]["kind"] == "handler-error"
        assert "not_a_real_module" in out["reply"]["error"]  # §6.9: names the module


class TestRefusals:
    def test_unknown_package_and_handler_404(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, "curio.ghost@1", "h", {}, limits=FAST)
        assert exc.value.status == 404
        with pytest.raises(rt.BackendRuntimeError) as exc2:
            rt.invoke_handler(USER, PKG, "ghost", {}, limits=FAST)
        assert exc2.value.status == 404
        assert "word-count" in str(exc2.value)  # the refusal names the declared set

    def test_digest_drift_refuses_with_reinstall_guidance(self, monkeypatch, tmp_path):
        pkg = _install_pkg(monkeypatch, tmp_path)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {},
                              expected_entry_digest="0" * 64, limits=FAST)
        assert exc.value.status == 409 and "reinstall" in str(exc.value)
        # The pinned digest matches what's on disk → runs.
        good = rt.entry_digest((pkg / "backend" / "handler.py").read_bytes())
        out = rt.invoke_handler(USER, PKG, "word-count", {"text": "x"},
                                expected_entry_digest=good, limits=FAST)
        assert out["reply"]["ok"] is True

    def test_payload_bounds_refuse_before_any_worker(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count",
                              {"blob": "x" * (bc.PAYLOAD_MAX_BYTES + 1)}, limits=FAST)
        assert exc.value.status == 413
        deep: object = 1
        for _ in range(bc.PAYLOAD_MAX_DEPTH + 1):
            deep = [deep]
        with pytest.raises(rt.BackendRuntimeError) as exc2:
            rt.invoke_handler(USER, PKG, "word-count", deep, limits=FAST)
        assert exc2.value.status == 422

    def test_no_worker_slot_is_a_503(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)

        class NoSlot:
            def acquire(self, timeout=None):
                return False

            def release(self):  # pragma: no cover — never reached
                raise AssertionError("release without acquire")

        monkeypatch.setattr(rt, "_worker_slots", NoSlot())
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc.value.status == 503

    def test_backend_less_package_404s(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
        pkg = _user_store(tmp_path) / USER / "packages" / "curio.plain@1"
        pkg.mkdir(parents=True)
        (pkg / "manifest.json").write_text(json.dumps({
            "id": "curio.plain", "version": "1.0.0", "name": "P", "publisher": "t",
            "description": "d", "compatibility": {"major": 1},
            "templates": [{
                "id": "t", "label": "T", "category": "computation",
                "engine": "python", "editor": "none",
                "inputPorts": [], "outputPorts": [],
            }],
        }), encoding="utf-8")
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, "curio.plain@1", "h", {}, limits=FAST)
        assert exc.value.status == 404 and "no backend" in str(exc.value)


class TestOptionThreeSeam:
    def test_interpreter_is_operator_pinnable(self, monkeypatch):
        monkeypatch.delenv("CURIO_BACKEND_SANDBOX_PYTHON", raising=False)
        import sys
        assert rt.sandbox_interpreter() == sys.executable
        monkeypatch.setenv("CURIO_BACKEND_SANDBOX_PYTHON", "/opt/pinned/python")
        assert rt.sandbox_interpreter() == "/opt/pinned/python"

    def test_overlay_dir_rides_pythonpath(self, monkeypatch, tmp_path):
        # The reserved §0.1 Option-2 slot: an overlay module resolves from
        # PYTHONPATH inside the worker — dependency isolation as parameter
        # values, no contract change.
        _install_pkg(monkeypatch, tmp_path,
                     handler_src="import overlay_mod\n"
                                 "def handle(payload):\n"
                                 "    return {'from': overlay_mod.WHERE}\n")
        overlay = tmp_path / "overlay"
        overlay.mkdir()
        (overlay / "overlay_mod.py").write_text("WHERE = 'overlay'\n", encoding="utf-8")
        out = rt.invoke_handler(USER, PKG, "word-count", {},
                                overlay_dir=overlay, limits=FAST)
        assert out["reply"] == {"contract": bc.PKGBACKEND_CONTRACT_VERSION,
                                "ok": True, "result": {"from": "overlay"}}


class TestPromoteInvokeConsistency:
    """dev/92 B-1: invocations serialize against promotes on the SAME lock —
    an invocation can no longer observe the installer's non-atomic
    rmtree+move window or a files-vs-pin mismatch."""

    def test_one_lock_object_shared_by_all_three_consumers(self):
        from utk_curio.backend.app.packages import build_promotion
        from utk_curio.backend.app.packages import backend_runtime as rt_mod
        from utk_curio.backend.app.packages.target_locks import target_lock

        lock = target_lock("42", "curio.demo@1")
        assert build_promotion._target_lock("42", "curio.demo@1") is lock
        assert rt_mod.target_lock("42", "curio.demo@1") is lock
        # And it IS dev/93's shared implementation — never a second dance.
        from utk_curio.backend.app.common.file_locks import keyed_thread_lock

        assert keyed_thread_lock("package-target", "42/curio.demo@1") is lock

    def test_invocation_waits_out_the_replace_window(self, monkeypatch, tmp_path):
        import shutil
        import threading as th

        from utk_curio.backend.app.packages.target_locks import target_lock

        _install_pkg(monkeypatch, tmp_path)
        lock = target_lock(USER, PKG)
        results: dict = {}

        def _invoke():
            try:
                results["out"] = rt.invoke_handler(
                    USER, PKG, "word-count", {"text": "a b"}, limits=FAST)
            except rt.BackendRuntimeError as exc:  # pragma: no cover — the bug
                results["err"] = exc

        lock.acquire()
        try:
            worker = th.Thread(target=_invoke)
            worker.start()
            worker.join(timeout=0.4)
            # The invocation is parked on the lock — it never reads the store
            # while the "promote" below has it torn open.
            assert worker.is_alive()
            # Simulate the installer's non-atomic replace: dir GONE, then new.
            pkg_dir = _user_store(tmp_path) / USER / "packages" / PKG
            shutil.rmtree(pkg_dir)
            assert not pkg_dir.exists()  # the pre-dev/92 404 window, held open
            _install_pkg(monkeypatch, tmp_path)
        finally:
            lock.release()
        worker.join(timeout=30)
        assert not worker.is_alive()
        # No transient 404/409 — the invocation read the NEW consistent state.
        assert "err" not in results, results.get("err")
        assert results["out"]["reply"]["ok"] is True


class TestQuarantineBreaker:
    """dev/92 B-3: three consecutive INFRASTRUCTURE failures quarantine the
    handler (503, self-expiring, reinstall clears); a well-formed
    handler-error reply is the handler working as designed and never counts;
    isolation is per handler."""

    def _fail_n(self, n: int, *, handler="word-count", limits=FAST):
        for _ in range(n):
            with pytest.raises(rt.BackendRuntimeError) as exc:
                rt.invoke_handler(USER, PKG, handler, {}, limits=limits)
            yield exc

    def test_three_infra_failures_quarantine_with_the_way_out(
            self, monkeypatch, tmp_path):
        # os._exit(0) at import: every invocation is a no-reply infra failure.
        _install_pkg(monkeypatch, tmp_path, handler_src="import os\nos._exit(0)\n")
        for exc in self._fail_n(3):
            assert exc.value.status == 502  # the failures themselves
        with pytest.raises(rt.BackendRuntimeError) as exc4:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc4.value.status == 503
        assert "quarantined" in str(exc4.value)
        assert "reinstall clears it immediately" in str(exc4.value)
        rows = _ledger_rows(tmp_path)
        assert rows[-1]["status"] == "quarantined"
        assert rows[-1]["cooldownRemainingSeconds"] >= 1
        # The refusal spent NO worker: three no-reply rows + one quarantine row.
        assert [r["status"] for r in rows] == ["no-reply"] * 3 + ["quarantined"]

    def test_handler_errors_never_count(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        for _ in range(4):
            out = rt.invoke_handler(USER, PKG, "boom", {}, limits=FAST)
            assert out["reply"]["kind"] == "handler-error"
        # Still invocable — a correctly-failing handler is not a crash loop.
        ok = rt.invoke_handler(USER, PKG, "word-count", {"text": "x"}, limits=FAST)
        assert ok["reply"]["ok"] is True

    def test_quarantine_is_per_handler(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        # Quarantine "spin" via three timeout kills (KILL_FAST wall = 1.5s).
        for exc in self._fail_n(3, handler="spin", limits=KILL_FAST):
            assert "timeout" in str(exc.value)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "spin", {}, limits=KILL_FAST)
        assert exc.value.status == 503
        # The healthy sibling is untouched.
        ok = rt.invoke_handler(USER, PKG, "word-count", {"text": "a b"}, limits=FAST)
        assert ok["reply"]["result"] == {"words": 2}

    def test_reinstall_resets_the_breaker(self, monkeypatch, tmp_path):
        pkg = _install_pkg(monkeypatch, tmp_path, handler_src="import os\nos._exit(0)\n")
        list(self._fail_n(3))
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc.value.status == 503
        # "Reinstall": the entry changes on disk → new digest → fresh start.
        entry = pkg / "backend" / "handler.py"
        entry.chmod(0o644)
        entry.write_text(_HANDLER_SRC, encoding="utf-8")
        out = rt.invoke_handler(USER, PKG, "word-count", {"text": "a"}, limits=FAST)
        assert out["reply"]["ok"] is True

    def test_cooldown_half_open_requarantines_at_once(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path, handler_src="import os\nos._exit(0)\n")
        clock = {"t": 1000.0}
        monkeypatch.setattr(rt, "_now", lambda: clock["t"])
        list(self._fail_n(3))
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc.value.status == 503
        # Cooldown expires → HALF-OPEN: the next call runs (and fails again)…
        clock["t"] += rt.QUARANTINE_SECONDS + 1
        with pytest.raises(rt.BackendRuntimeError) as exc_half:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc_half.value.status == 502  # a real worker ran
        # …and ONE failure re-quarantines immediately (counter was kept).
        with pytest.raises(rt.BackendRuntimeError) as exc_again:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc_again.value.status == 503


class TestDependencyOverlay:
    """dev/97 (§0.1 Option 2 delivered): handler deps live in a per-package
    overlay built by REAL pip --target (the A9 real-toolchain rule — a
    hand-built minimal wheel, installed offline via pip's env knobs), handed
    to workers on PYTHONPATH by AUTO-resolution, and swept at uninstall."""

    def _build_wheel(self, tmp_path) -> "Path":
        # A minimal valid wheel: one module + dist-info (METADATA/WHEEL/RECORD).
        import zipfile

        wheel = tmp_path / "wheelhouse" / "tinylib-1.0.0-py3-none-any.whl"
        wheel.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(wheel, "w") as zf:
            zf.writestr("tinylib.py", "VALUE = 'from-the-overlay'\n")
            zf.writestr("tinylib-1.0.0.dist-info/METADATA",
                        "Metadata-Version: 2.1\nName: tinylib\nVersion: 1.0.0\n")
            zf.writestr("tinylib-1.0.0.dist-info/WHEEL",
                        "Wheel-Version: 1.0\nGenerator: test\n"
                        "Root-Is-Purelib: true\nTag: py3-none-any\n")
            zf.writestr("tinylib-1.0.0.dist-info/RECORD",
                        "tinylib.py,,\ntinylib-1.0.0.dist-info/METADATA,,\n"
                        "tinylib-1.0.0.dist-info/WHEEL,,\n"
                        "tinylib-1.0.0.dist-info/RECORD,,\n")
        return wheel.parent

    def test_real_pip_target_overlay_end_to_end(self, monkeypatch, tmp_path):
        from utk_curio.backend.app.packages import pip_runner

        _install_pkg(
            monkeypatch, tmp_path,
            handler_src=(
                "def handle(payload):\n"
                "    import tinylib  # lazy per the dev/97 contract\n"
                "    return {'value': tinylib.VALUE}\n"
            ),
        )
        # Offline discipline: pip resolves ONLY from the local wheelhouse.
        monkeypatch.setenv("PIP_NO_INDEX", "1")
        monkeypatch.setenv("PIP_FIND_LINKS", str(self._build_wheel(tmp_path)))
        overlay = rt.overlay_dir_for(USER, PKG)
        overlay.mkdir(parents=True, exist_ok=True)
        report = pip_runner.install_python_deps_to_target(
            {"tinylib": "1.0.0"}, str(overlay))
        assert report.installed == ["tinylib==1.0.0"] and report.skipped == []
        assert (overlay / "tinylib.py").is_file()
        # The host interpreter is untouched.
        with pytest.raises(ImportError):
            import tinylib  # noqa: F401
        # AUTO-resolution: no overlay parameter — the worker still sees it.
        out = rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert out["reply"] == {"contract": "curio.pkgbackend.v1", "ok": True,
                                "result": {"value": "from-the-overlay"}}

    def test_explicit_overlay_parameter_wins_over_auto(self, monkeypatch, tmp_path):
        _install_pkg(
            monkeypatch, tmp_path,
            handler_src="import overlay_probe\n"
                        "def handle(payload):\n"
                        "    return {'which': overlay_probe.WHICH}\n")
        auto = rt.overlay_dir_for(USER, PKG)
        auto.mkdir(parents=True)
        (auto / "overlay_probe.py").write_text("WHICH = 'auto'\n", encoding="utf-8")
        explicit = tmp_path / "explicit-overlay"
        explicit.mkdir()
        (explicit / "overlay_probe.py").write_text("WHICH = 'explicit'\n",
                                                   encoding="utf-8")
        out = rt.invoke_handler(USER, PKG, "word-count", {},
                                overlay_dir=explicit, limits=FAST)
        assert out["reply"]["result"] == {"which": "explicit"}

    def test_residue_sweep_removes_overlay_data_and_pin_keeps_ledger(
            self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        # Populate all four backend homes.
        rt.invoke_handler(USER, PKG, "remember", {"write": "kept"}, limits=FAST)
        rt.record_entry_pin(USER, PKG)
        overlay = rt.overlay_dir_for(USER, PKG)
        overlay.mkdir(parents=True)
        (overlay / "dep.py").write_text("X = 1\n", encoding="utf-8")
        assert rt.pinned_entry_digest(USER, PKG)
        assert _ledger_rows(tmp_path)

        removed = rt.remove_backend_residue(USER, PKG)

        assert removed == {"overlay": True, "dataDir": True, "pin": True}
        assert not overlay.exists()
        assert not (_user_store(tmp_path) / USER
                    / "package-backend-data" / PKG).exists()
        assert rt.pinned_entry_digest(USER, PKG) is None
        # The append-only audit history SURVIVES uninstall (retention owns it).
        assert _ledger_rows(tmp_path)

    def test_sweep_on_a_clean_slate_is_a_quiet_noop(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
        assert rt.remove_backend_residue(USER, "curio.ghost@1") == {
            "overlay": False, "dataDir": False, "pin": False}
