"""``start all`` starts a frontend that has nothing to build before anything else.

A deploy stops the old container and starts the new one, and until a server
answers on the frontend's port the site is a blank page. The static server
needs none of the start-up checks (two pip runs, the DuckDB extension seeding)
nor the backend's database preparation, so when ``dist/`` is current it starts
first and the page, with its offline banner, is back within seconds. A start
that has to build the frontend keeps the old order, so a local build never
delays the backend.
"""
from __future__ import annotations

import signal
import threading
from types import SimpleNamespace

import pytest

import utk_curio.main as launcher
from utk_curio.cli import frontend_build, lifecycle, logs


class _Server:
    """A started server, as clean_shutdown and a failed check handle it."""

    def __init__(self, name):
        self.args = [name]
        self.calls = []

    def terminate(self):
        self.calls.append("terminate")

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.calls.append("kill")


def _interrupted(seconds):
    raise KeyboardInterrupt


def _start(monkeypatch, *, must_build, failing_check=None):
    """Run ``curio.py start`` with every step recorded instead of done.

    Returns the order of the steps, the servers, and how main() exited.
    """
    steps = []
    servers = {name: _Server(name) for name in ("backend", "sandbox", "frontend")}
    flag = threading.Event()

    def step(name, result=None):
        def run(*args, **kwargs):
            steps.append(name)
            if name == failing_check:
                raise SystemExit(1)
            return result
        return run

    # What main() changes outside itself, each put back after the test.
    monkeypatch.setattr("sys.argv", ["curio.py", "start"])
    monkeypatch.setattr(logs, "verbosity", logs.verbosity)
    monkeypatch.setattr(lifecycle, "processes", [])
    monkeypatch.setattr(lifecycle, "shutdown_flag", flag)
    monkeypatch.setattr(launcher, "shutdown_flag", flag)
    monkeypatch.setattr(launcher, "signal", SimpleNamespace(
        SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM, signal=lambda *args: None,
    ))
    monkeypatch.setattr(launcher, "setup_logging", lambda server: None)
    monkeypatch.setattr(launcher, "set_environment_variables", lambda **kwargs: None)
    monkeypatch.setattr(launcher, "_require_supported_node", lambda: None)
    # Whether the frontend must build, as the launcher's gate reads it: no
    # --dev or --force-rebuild here, so the bundle's own state decides.
    monkeypatch.delenv("CURIO_DEV", raising=False)
    monkeypatch.setattr(frontend_build, "_frontend_needs_build", lambda: must_build)
    monkeypatch.setattr(frontend_build, "_frontend_tree_is_stale", lambda: False)
    monkeypatch.setattr(launcher, "_skip_dep_install", lambda: False)
    monkeypatch.setattr(launcher, "install_framework_requirements", step("framework requirements"))
    monkeypatch.setattr(launcher, "install_manifest_dependencies", step("manifest dependencies"))
    monkeypatch.setattr(launcher, "seed_duckdb_extensions", step("duckdb extensions"))
    monkeypatch.setattr(launcher, "start_backend", step("backend", servers["backend"]))
    monkeypatch.setattr(launcher, "start_sandbox", step("sandbox", servers["sandbox"]))
    monkeypatch.setattr(launcher, "start_frontend", step("frontend", servers["frontend"]))
    monkeypatch.setattr(launcher, "threading", SimpleNamespace(
        Thread=lambda **kwargs: SimpleNamespace(start=lambda: None),
    ))
    # The wait loop's first sleep ends the start through clean_shutdown.
    monkeypatch.setattr(launcher, "time", SimpleNamespace(sleep=_interrupted))

    with pytest.raises(SystemExit) as exited:
        launcher.main()
    return steps, servers, exited.value.code


CHECKS = ["framework requirements", "manifest dependencies", "duckdb extensions"]


def test_a_built_frontend_starts_before_the_checks_and_the_backend(monkeypatch):
    steps, servers, code = _start(monkeypatch, must_build=False)

    assert steps == ["frontend", *CHECKS, "backend", "sandbox"]
    assert code == 0
    for name, server in servers.items():
        assert server.calls[:1] == ["terminate"], (name, server.calls)


def test_a_frontend_that_must_build_starts_last(monkeypatch):
    steps, servers, code = _start(monkeypatch, must_build=True)

    assert steps == [*CHECKS, "backend", "sandbox", "frontend"]
    assert code == 0
    for name, server in servers.items():
        assert server.calls[:1] == ["terminate"], (name, server.calls)


def test_a_failed_check_stops_the_frontend_it_started_first(monkeypatch):
    steps, servers, code = _start(
        monkeypatch, must_build=False, failing_check="framework requirements",
    )

    assert steps == ["frontend", "framework requirements"]
    assert code == 1
    assert servers["frontend"].calls == ["terminate"]
    assert servers["backend"].calls == []
    assert servers["sandbox"].calls == []
