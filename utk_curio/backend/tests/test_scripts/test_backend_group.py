"""``curio.py start --backend-processes N``: N backend processes behind nginx
(``utk_curio/cli/backend_group.py``).

With N above 1 the launcher starts the home process first, on a port of
127.0.0.1 of its own, and waits until it answers, since it alone does the
startup work; then the others, each told its number, the count, the start's
one boot id, every process's port and a secret made at this start; then nginx
on the backend's host and port, with the config it writes at each start. If
any of them exits, it stops them all. N of 1, the default, is today's one
backend on the backend's port, with no nginx.

The group runs here with every process faked
(``tests/_support/backend_group_fakes.py``); the config and nginx itself are
``test_backend_router_config.py`` and ``test_backend_router_nginx.py``. The
launcher's modules are imported inside each test, so a checkout without them
fails each test on its own.
"""
from __future__ import annotations

import importlib
import logging
import os
import signal
import stat
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests._support.backend_group_fakes import boot

#: The variables the launcher gives each backend of a start of several.
_NAMES = ("CURIO_BACKEND_PROCESS", "CURIO_BACKEND_PROCESSES", "CURIO_BOOT_ID",
          "CURIO_BACKEND_PORTS", "CURIO_BACKEND_TOKEN")


@pytest.fixture(autouse=True)
def _a_start_of_its_own(monkeypatch, tmp_path):
    """Each test's start keeps its state in its own folder, with none of the
    variables an earlier start left in this process."""
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
    for name in (*_NAMES, "CURIO_PROXY_HOPS"):
        monkeypatch.delenv(name, raising=False)


def _ports(env: dict) -> list[int]:
    return [int(part) for part in env["CURIO_BACKEND_PORTS"].split(",")]


# ---------------------------------------------------------------------------
# The start
# ---------------------------------------------------------------------------

def test_home_answers_before_the_others_start_and_nginx_starts_last(monkeypatch):
    booted = boot(monkeypatch, processes=4)

    assert booted.events == [
        ("start", "Backend 0"), ("answers", "Backend 0"),
        ("start", "Backend 1"), ("start", "Backend 2"), ("start", "Backend 3"),
        ("answers", "Backend 1"), ("answers", "Backend 2"), ("answers", "Backend 3"),
        ("check", "nginx -t"), ("start", "nginx"), ("answers", "nginx"),
    ], "the home process must finish the startup work, which answering /health follows, before any other starts"
    assert [name for name, _process in booted.started] == [
        "Backend 0", "Backend 1", "Backend 2", "Backend 3", "nginx",
    ]
    assert booted.stopped == []


def test_each_backend_is_told_its_number_the_count_one_boot_id_every_port_and_the_starts_secret(monkeypatch):
    # What the launcher's own environment holds from an earlier start never
    # reaches a backend: a start takes no other start's boot id or secret.
    monkeypatch.setenv("CURIO_BOOT_ID", "an-earlier-start")
    monkeypatch.setenv("CURIO_BACKEND_TOKEN", "an-earlier-starts-secret")
    # --proxy-hops 1, as the hosted stacks pass for their Caddy.
    monkeypatch.setenv("CURIO_PROXY_HOPS", "1")
    # No arena cap of this process's own, so each backend's is the launcher's.
    monkeypatch.delenv("MALLOC_ARENA_MAX", raising=False)

    booted = boot(monkeypatch, processes=4, host="0.0.0.0", port=5999)

    envs = [booted.env(number) for number in range(4)]
    ports = _ports(envs[0])
    assert len(ports) == 4 and len(set(ports)) == 4, f"each process needs a port of its own: {ports}"
    assert 5999 not in ports, "a backend took the public port, which is nginx's"
    boot_ids = {env["CURIO_BOOT_ID"] for env in envs}
    secrets = {env["CURIO_BACKEND_TOKEN"] for env in envs}
    assert len(boot_ids) == 1 and boot_ids != {"an-earlier-start"} and "" not in boot_ids, boot_ids
    assert len(secrets) == 1 and secrets != {"an-earlier-starts-secret"}, "the backends of a start share a secret of its own"
    assert len(next(iter(secrets))) >= 32, "the start's secret is too short to be one"
    for number, env in enumerate(envs):
        assert env["CURIO_BACKEND_PROCESS"] == str(number)
        assert env["CURIO_BACKEND_PROCESSES"] == "4"
        assert _ports(env) == ports, "every backend lists every process's port, by number"
        assert env["FLASK_BACKEND_HOST"] == "127.0.0.1", "a backend of several serves on 127.0.0.1 alone, behind nginx"
        assert env["FLASK_BACKEND_PORT"] == str(ports[number])
        assert env["FLASK_USE_RELOADER"] == "0", "under Werkzeug's reloader each backend would make a boot id of its own"
        assert env["CURIO_PROXY_HOPS"] == "2", "nginx adds the address it was reached from: one more proxy hop"
        assert env["MALLOC_ARENA_MAX"] == "16", "each backend of several starts with the backend's 16 malloc arenas"
    # Each process is waited for where it serves; nginx, which listens on every
    # address, where this host reaches it.
    assert booted.asked == [
        ("Backend 0", "127.0.0.1", ports[0]),
        ("Backend 1", "127.0.0.1", ports[1]), ("Backend 2", "127.0.0.1", ports[2]),
        ("Backend 3", "127.0.0.1", ports[3]),
        ("nginx", "127.0.0.1", 5999),
    ]

    again = boot(monkeypatch, processes=4, host="0.0.0.0", port=5999)
    assert again.env(0)["CURIO_BOOT_ID"] not in boot_ids, "two starts gave their backends one boot id"
    assert again.env(0)["CURIO_BACKEND_TOKEN"] not in secrets, "two starts made one secret"


def test_without_proxy_hops_nginx_is_the_one_hop(monkeypatch):
    booted = boot(monkeypatch, processes=2)
    assert {booted.env(n)["CURIO_PROXY_HOPS"] for n in range(2)} == {"1"}


def test_the_starts_secret_is_in_the_backends_environments_alone(monkeypatch, tmp_path, caplog, capfd):
    """The secret opens every backend's internal route (owner_calls.py). It is
    never in the launcher's own environment, which the sandbox and the page
    server start from, nor in nginx's, its command or its config, nor in any
    line the launcher logs."""
    caplog.set_level(logging.DEBUG)
    # A secret an outer shell left in the launcher's environment does not
    # reach nginx either.
    monkeypatch.setenv("CURIO_BACKEND_TOKEN", "an-outer-shells-secret")

    booted = boot(monkeypatch, processes=3)

    secret = booted.env(0)["CURIO_BACKEND_TOKEN"]
    assert secret not in os.environ.values(), "the start's secret is in the launcher's environment, which the sandbox starts from"
    for args, env in [*booted.checks, (booted.nginx.args, booted.nginx.env)]:
        assert env is not None, f"{args} started with the launcher's own environment, the outer shell's secret in it"
        assert "CURIO_BACKEND_TOKEN" not in env, "nginx holds a backend's secret"
        assert secret not in " ".join(args) and secret not in env.values()
    for path in (tmp_path / "state").rglob("*"):
        if path.is_file():
            assert secret not in path.read_text(encoding="utf-8", errors="replace"), f"the secret was written to {path}"
    printed = capfd.readouterr()
    assert secret not in caplog.text and secret not in printed.out and secret not in printed.err, "the launcher logged the secret"


def test_each_server_writes_its_own_lines_under_its_own_name(monkeypatch):
    booted = boot(monkeypatch, processes=3)
    assert booted.streams == ["Backend 0", "Backend 1", "Backend 2", "nginx"]


def test_the_config_is_written_at_each_start_in_the_state_folder_and_checked_before_nginx_starts(monkeypatch, tmp_path):
    backend_group = importlib.import_module("utk_curio.cli.backend_group")

    booted = boot(monkeypatch, processes=2, port=5999)

    folder = tmp_path / "state" / "backend-router"
    config = folder / "nginx.conf"
    assert backend_group.router_folder() == folder
    assert config.is_file(), "the launcher wrote no nginx config"
    text = config.read_text(encoding="utf-8")
    assert "listen 127.0.0.1:5999" in text
    for port in _ports(booted.env(0)):
        assert f"server 127.0.0.1:{port};" in text, f"no upstream for the backend on port {port}"
    assert [args for args, _env in booted.checks] == [["/usr/sbin/nginx", "-t", "-c", str(config), "-e", "stderr"]]
    assert booted.nginx.args == ["/usr/sbin/nginx", "-c", str(config), "-e", "stderr"]
    # nginx's workers reach their folders in it without listing it.
    assert stat.S_IMODE(folder.stat().st_mode) == 0o711


# ---------------------------------------------------------------------------
# One server that stops stops them all
# ---------------------------------------------------------------------------

def test_a_home_that_never_answers_stops_every_server_and_starts_no_other(monkeypatch):
    booted = boot(monkeypatch, processes=3, answers=lambda name: name != "Backend 0")
    assert booted.started is None
    assert booted.events == [("start", "Backend 0"), ("answers", "Backend 0")]
    assert booted.stopped == [1], "a start that cannot serve must end with an error, so Docker restarts it"


def test_a_config_nginx_refuses_stops_every_server(monkeypatch):
    booted = boot(monkeypatch, processes=2, check_status=1)
    assert booted.started is None
    assert ("start", "nginx") not in booted.events
    assert booted.stopped == [1]


@pytest.mark.parametrize("which", ["Backend 2", "nginx"])
def test_any_server_that_exits_stops_them_all_with_an_error(monkeypatch, caplog, which):
    backend_group = importlib.import_module("utk_curio.cli.backend_group")
    caplog.set_level(logging.DEBUG)
    booted = boot(monkeypatch, processes=3)
    process = dict(booted.started)[which]
    process.exit_code = 9
    caplog.clear()

    backend_group.watch(booted.started)

    assert booted.stopped == [1]
    assert any(which in record.getMessage() and "exited with code 9" in record.getMessage()
               for record in caplog.records), (
        f"the launcher did not say that {which} exited, and with which code: {caplog.text}"
    )


def test_the_database_is_prepared_once_before_any_backend_starts(monkeypatch):
    backend_group = importlib.import_module("utk_curio.cli.backend_group")
    services = importlib.import_module("utk_curio.cli.services")
    done = []
    monkeypatch.setattr(backend_group, "nginx_path", lambda: "/usr/sbin/nginx")
    monkeypatch.setattr(services, "prepare_backend_database", lambda: done.append("prepare"))
    monkeypatch.setattr(services, "_kill_port", lambda port: done.append(f"free {port}"))
    monkeypatch.setattr(backend_group, "boot", lambda host, port, processes, nginx: done.append(
        f"boot {host}:{port} x{processes} with {nginx}") or [("Backend 0", None)])
    monkeypatch.setattr(backend_group, "watch", lambda started: done.append("watch"))
    monkeypatch.setattr(backend_group, "threading", SimpleNamespace(
        Thread=lambda target=None, args=(), **kwargs: SimpleNamespace(start=lambda: target(*args))))

    backend_group.start_backend_group("0.0.0.0", "5999", 3)

    assert done == ["free 5999", "prepare", "boot 0.0.0.0:5999 x3 with /usr/sbin/nginx", "watch"]


# ---------------------------------------------------------------------------
# curio.py's flag
# ---------------------------------------------------------------------------

@pytest.fixture
def launcher(monkeypatch):
    """``main()`` as ``curio.py`` runs it, with *argv*, starting nothing: the
    signal handlers it installs go back after the test."""
    import utk_curio.main as main

    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    def refuse(*args, **kwargs):
        raise AssertionError("a server was started")

    for name in ("start_backend", "start_sandbox", "start_frontend"):
        monkeypatch.setattr(main, name, refuse)

    def run(*argv):
        monkeypatch.setattr("sys.argv", ["curio.py", *argv])
        try:
            main.main()
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)

    yield run


def test_more_than_one_process_without_nginx_is_refused_before_anything_starts(launcher, monkeypatch):
    backend_group = importlib.import_module("utk_curio.cli.backend_group")
    monkeypatch.setattr("shutil.which", lambda name, *args, **kwargs: None)
    monkeypatch.setattr(backend_group, "start_backend_group",
                        lambda *args, **kwargs: pytest.fail("the group started without nginx"))

    with pytest.raises(SystemExit) as refused:
        launcher("start", "--backend-processes", "3")

    message = str(refused.value.code)
    assert "--backend-processes" in message and "nginx" in message and "PATH" in message, message


def _error_line(err: str) -> str:
    """The parser's own error, not its usage line, which names every flag."""
    lines = [line for line in err.splitlines() if ": error: " in line]
    assert lines, f"the parser printed no error: {err!r}"
    return lines[-1]


def test_dev_runs_one_backend(launcher, capsys):
    with pytest.raises(SystemExit) as refused:
        launcher("start", "--dev", "--backend-processes", "2")
    assert refused.value.code == 2
    error = _error_line(capsys.readouterr().err)
    assert "--dev" in error and "--backend-processes" in error and "unrecognized" not in error, error


@pytest.mark.parametrize("count, said", [("0", "at least 1"), ("-1", "at least 1"), ("257", "at most 256")])
def test_the_process_count_is_from_1_to_256(launcher, capsys, count, said):
    with pytest.raises(SystemExit) as refused:
        launcher("start", "--backend-processes", count)
    assert refused.value.code == 2
    error = _error_line(capsys.readouterr().err)
    assert "--backend-processes" in error and said in error, error


def test_one_process_is_todays_one_backend_and_several_are_the_group(monkeypatch):
    import utk_curio.main as main
    from utk_curio.cli import lifecycle

    backend_group = importlib.import_module("utk_curio.cli.backend_group")
    started = []
    monkeypatch.setattr(lifecycle, "processes", [])
    monkeypatch.setattr(main, "start_backend", lambda host, port: started.append(("one", host, port)) or "backend")
    monkeypatch.setattr(backend_group, "start_backend_group",
                        lambda host, port, processes: started.append(("group", host, port, processes)))

    main._start_backends(SimpleNamespace(backend_processes=1, backend_host="127.0.0.1", backend_port="5002"))
    main._start_backends(SimpleNamespace(backend_processes=3, backend_host="0.0.0.0", backend_port="5002"))

    assert started == [("one", "127.0.0.1", "5002"), ("group", "0.0.0.0", "5002", 3)]
    assert lifecycle.processes == ["backend"], "the one backend is not among the servers the launcher stops"
