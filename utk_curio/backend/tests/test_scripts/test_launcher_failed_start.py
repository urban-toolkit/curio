"""A start that fails exits non-zero.

Each check the launcher makes before a server runs (``check_install_build``
in ``utk_curio/cli/frontend_build.py``, ``start_frontend`` and
``prepare_backend_database`` in ``utk_curio/cli/services.py``) logs its error
and stops the launcher through ``clean_shutdown``. They run on the main
thread, so ``clean_shutdown``'s ``sys.exit`` is the launcher's exit, and its
default status is 0: ``python curio.py start`` with no npm on ``PATH``, a
failed ``npm run build`` or a failed migration told a script, a CI step or a
service manager that Curio came up. ``_require_supported_node`` and the
backend group's ``_stop`` already exit 1 (``test_launcher_dev_flag.py``,
``test_backend_group.py``); each test here is one of the other failures.
"""
from __future__ import annotations

import io
import subprocess
import threading
from types import SimpleNamespace

import pytest

from utk_curio.cli import frontend_build, lifecycle, services
from utk_curio.cli.frontend_build import NODE_MAJOR


@pytest.fixture(autouse=True)
def launcher_state(monkeypatch):
    """What ``clean_shutdown`` changes, each put back after the test."""
    monkeypatch.setattr(lifecycle, "processes", [])
    monkeypatch.setattr(lifecycle, "shutdown_flag", threading.Event())
    monkeypatch.setattr(lifecycle, "servers_stopped", threading.Event())
    monkeypatch.setattr(lifecycle, "exit_status", 0)


def _exit_status(call, *args, **kwargs):
    with pytest.raises(SystemExit) as exited:
        call(*args, **kwargs)
    return exited.value.code


# --- check_install_build: the tools, npm install and npm run build -----------


def _tools(monkeypatch, *, npm=True, node=True, version=(f"v{NODE_MAJOR}.0.0", NODE_MAJOR)):
    monkeypatch.setattr(
        frontend_build.shutil, "which",
        lambda name: f"/usr/bin/{name}" if {"npm": npm, "node": node}.get(name) else None,
    )
    monkeypatch.setattr(frontend_build, "_read_node_version", lambda: version)
    monkeypatch.setattr(frontend_build, "_node_tree_is_stale", lambda root, major: False)


def _npm(monkeypatch, failing, error):
    """npm, whose ``failing`` command (``install`` or ``run``) raises ``error``."""

    def run(cmd, **kwargs):
        if cmd[1] == failing:
            raise error
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(frontend_build, "subprocess", SimpleNamespace(
        run=run, CalledProcessError=subprocess.CalledProcessError,
    ))


@pytest.mark.parametrize("tools", [
    pytest.param({"npm": False}, id="no npm"),
    pytest.param({"node": False}, id="no node"),
    pytest.param({"version": (None, 0)}, id="node version unreadable"),
    pytest.param({"version": ("v24.9.0", 24)}, id="node too old"),
])
def test_a_build_without_the_tools_it_needs_exits_non_zero(tools, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _tools(monkeypatch, **tools)
    assert _exit_status(frontend_build.check_install_build, str(tmp_path)) == 1


@pytest.mark.parametrize("failing", ["install", "run"], ids=["npm install", "npm run build"])
@pytest.mark.parametrize("error", [
    pytest.param(subprocess.CalledProcessError(1, "npm"), id="npm fails"),
    pytest.param(OSError("npm cannot run"), id="npm does not run"),
])
def test_a_failed_npm_step_exits_non_zero(failing, error, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _tools(monkeypatch)
    _npm(monkeypatch, failing, error)
    assert _exit_status(frontend_build.check_install_build, str(tmp_path)) == 1


# --- start_frontend and prepare_backend_database -----------------------------


def _services_subprocess(monkeypatch, **calls):
    """``subprocess`` as ``services`` sees it, with ``calls`` in place of its
    own, so no other code in the process gets the stand-ins."""
    monkeypatch.setattr(services, "subprocess", SimpleNamespace(
        PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT,
        CalledProcessError=subprocess.CalledProcessError,
        TimeoutExpired=subprocess.TimeoutExpired, **calls,
    ))



class _ExitedServer:
    """The dev server, exited before the launcher first looked at it. Its
    output goes to stdout (``stderr=subprocess.STDOUT``), so it has no stderr."""

    args = ["npm"]
    returncode = 1
    stdout = io.StringIO("")
    stderr = None

    def poll(self):
        return self.returncode


@pytest.fixture
def frontend(monkeypatch, tmp_path):
    """start_frontend with nothing to build, no port to free and no thread to
    stream a server's output; its errors as it logged them."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(services, "_kill_port", lambda port: None)
    monkeypatch.setattr(services, "_frontend_must_build", lambda force_rebuild: False)
    monkeypatch.setattr(services, "threading", SimpleNamespace(
        Thread=lambda **kwargs: SimpleNamespace(start=lambda: None),
    ))
    errors = []
    monkeypatch.setattr(services, "log_error", errors.append)
    return errors


def test_a_dev_server_that_exits_at_once_exits_non_zero(frontend, monkeypatch):
    monkeypatch.setenv("CURIO_DEV", "1")
    _services_subprocess(monkeypatch, Popen=lambda *args, **kwargs: _ExitedServer())

    assert _exit_status(services.start_frontend) == 1
    assert frontend == ["[Frontend] Error: Server exited with code 1"]


def test_nothing_built_to_serve_exits_non_zero(frontend, monkeypatch):
    monkeypatch.setenv("CURIO_DEV", "0")
    monkeypatch.setattr(services, "_frontend_is_built", lambda: False)

    assert _exit_status(services.start_frontend) == 1


def test_a_page_server_that_cannot_start_exits_non_zero(frontend, monkeypatch):
    monkeypatch.setenv("CURIO_DEV", "0")
    monkeypatch.setattr(services, "_frontend_is_built", lambda: True)

    def cannot_start(*args, **kwargs):
        raise OSError("no such interpreter")

    _services_subprocess(monkeypatch, Popen=cannot_start)

    assert _exit_status(services.start_frontend) == 1


@pytest.mark.parametrize("error", [
    pytest.param(
        subprocess.CalledProcessError(1, "flask db upgrade", output="", stderr="no such table"),
        id="the migration fails",
    ),
    pytest.param(OSError("flask cannot run"), id="the migration does not run"),
])
def test_a_failed_migration_exits_non_zero(error, monkeypatch, tmp_path):
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(services, "_is_testing", lambda: False)

    def migrate(*args, **kwargs):
        raise error

    _services_subprocess(monkeypatch, run=migrate)

    assert _exit_status(services.prepare_backend_database) == 1
