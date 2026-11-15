"""Which backend process this is, the start's boot id and the process a
dataflow belongs to (``utk_curio/common/backend_processes.py``), and what the
launcher gives the backend it starts (``cli/services.py``).

The module is imported inside each test, so a checkout without it fails each
test on its own.
"""
from __future__ import annotations

import importlib
import subprocess
import uuid
from types import SimpleNamespace

import pytest


def _processes():
    return importlib.import_module("utk_curio.common.backend_processes")


# Which process this is.


def test_a_backend_started_without_the_launchers_variables_is_process_0_of_1_home():
    processes = _processes()
    assert processes.this_process({}) == 0
    assert processes.process_count({}) == 1
    assert processes.is_home({}) is True


def test_the_launchers_variables_say_which_process_this_is():
    processes = _processes()
    third = {"CURIO_BACKEND_PROCESS": "2", "CURIO_BACKEND_PROCESSES": "4"}
    assert (processes.this_process(third), processes.process_count(third)) == (2, 4)
    assert processes.is_home(third) is False
    assert processes.is_home({"CURIO_BACKEND_PROCESS": "0", "CURIO_BACKEND_PROCESSES": "4"}) is True


def test_the_launcher_writes_what_the_backend_reads():
    processes = _processes()
    given = processes.environment(process=1, processes=3, boot_id="start-1")
    assert given == {"CURIO_BACKEND_PROCESS": "1", "CURIO_BACKEND_PROCESSES": "3", "CURIO_BOOT_ID": "start-1"}
    assert (processes.this_process(given), processes.process_count(given)) == (1, 3)
    assert processes.boot_id(given) == "start-1"


@pytest.mark.parametrize("environ", [
    {"CURIO_BACKEND_PROCESS": "one"},
    {"CURIO_BACKEND_PROCESS": "-1"},
    {"CURIO_BACKEND_PROCESS": "2", "CURIO_BACKEND_PROCESSES": "2"},
    {"CURIO_BACKEND_PROCESSES": "0"},
    {"CURIO_BACKEND_PROCESSES": "many"},
], ids=["not-a-number", "negative", "past-the-count", "no-processes", "count-not-a-number"])
def test_a_process_number_no_launcher_gives_stops_the_backend(environ):
    """A backend that cannot tell whether it is home refuses to start, rather
    than doing the startup work a second time or never."""
    with pytest.raises(ValueError):
        _processes().is_home(environ)


# The start's boot id.


def test_every_backend_of_a_start_takes_the_starts_boot_id():
    processes = _processes()
    assert processes.boot_id({"CURIO_BOOT_ID": "start-1"}) == "start-1"
    # Started without one, a backend makes its own.
    made = {processes.boot_id({}), processes.boot_id({}), processes.boot_id({"CURIO_BOOT_ID": " "})}
    assert len(made) == 3
    for one in made:
        uuid.UUID(one)


def test_a_backend_werkzeugs_reloader_started_makes_its_own_boot_id():
    """The reloader starts its child again after each code change with the
    environment it started the first one with. Each of those is a restart: the
    runs the last child left going were cut off, and the next must find them
    so (``runs/service.py``)."""
    processes = _processes()
    given = {"CURIO_BOOT_ID": "start-1", "WERKZEUG_RUN_MAIN": "true"}
    first, second = processes.boot_id(given), processes.boot_id(given)
    assert "start-1" not in (first, second)
    assert first != second


# The process a dataflow belongs to.


@pytest.mark.parametrize("dataflow_id, count, owner", [
    # The id's first two hex digits, as a number, modulo the processes.
    ("3f2a9c1e-0b4d-4c8e-9a7f-2d6b8e1c5a90", 8, 0x3F % 8),
    ("3F2A9C1E-0B4D-4C8E-9A7F-2D6B8E1C5A90", 8, 0x3F % 8),
    ("a0e1b2c3-d4e5-46f7-8a9b-0c1d2e3f4a5b", 3, 0xA0 % 3),
    ("ff000000-0000-4000-8000-000000000000", 8, 7),
    ("00ffffff-ffff-4fff-bfff-ffffffffffff", 8, 0),
    ("0a", 16, 10),
    # An id that does not start with two hex digits is the home process's.
    ("example-06-shadow-study", 8, 0),
    ("g3f2a9c1", 8, 0),
    ("3", 8, 0),
    ("", 8, 0),
    (None, 8, 0),
    # With one process, every dataflow is its.
    ("3f2a9c1e-0b4d-4c8e-9a7f-2d6b8e1c5a90", 1, 0),
    ("ff000000-0000-4000-8000-000000000000", 1, 0),
])
def test_a_dataflow_belongs_to_the_process_its_ids_first_two_hex_digits_name(dataflow_id, count, owner):
    assert _processes().shard_of(dataflow_id, count) == owner


def test_every_process_owns_a_share_of_the_dataflows():
    shard_of = _processes().shard_of
    owners = {shard_of(f"{lead:02x}000000-0000-4000-8000-000000000000", 8) for lead in range(256)}
    assert owners == set(range(8))


# What the launcher gives the backend.


class _Started:
    stdout = None

    def poll(self):
        return None


def _backend_environment(monkeypatch, **given) -> dict:
    """The environment ``start_backend`` would start the backend with; no
    process is started and no database migrated."""
    import utk_curio.cli.services as services

    started = []
    monkeypatch.setattr(services, "subprocess", SimpleNamespace(
        Popen=lambda args, **kwargs: started.append(kwargs.get("env")) or _Started(),
        PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT))
    monkeypatch.setattr(services, "threading", SimpleNamespace(
        Thread=lambda *args, **kwargs: SimpleNamespace(start=lambda: None)))
    monkeypatch.setattr(services, "_kill_port", lambda port: None)
    monkeypatch.setattr(services, "prepare_backend_database", lambda: None)
    services.start_backend("127.0.0.1", 2998, **given)
    (env,) = started
    return env


NAMES = ("CURIO_BACKEND_PROCESS", "CURIO_BACKEND_PROCESSES", "CURIO_BOOT_ID")


def test_each_start_gives_its_backend_a_new_boot_id_and_makes_it_home(monkeypatch):
    # What the launcher's own environment holds never reaches the backend: a
    # start takes no other start's boot id.
    monkeypatch.setenv("CURIO_BOOT_ID", "an-earlier-start")
    monkeypatch.setenv("CURIO_BACKEND_PROCESS", "3")
    monkeypatch.setenv("CURIO_BACKEND_PROCESSES", "4")

    first = _backend_environment(monkeypatch)
    second = _backend_environment(monkeypatch)

    for env in (first, second):
        given = {name: env.get(name) for name in NAMES}
        assert given["CURIO_BACKEND_PROCESS"] == "0" and given["CURIO_BACKEND_PROCESSES"] == "1", given
        assert given["CURIO_BOOT_ID"] not in (None, "", "an-earlier-start"), given
    assert first["CURIO_BOOT_ID"] != second["CURIO_BOOT_ID"], "two starts gave their backends one boot id"


def test_the_backends_of_one_start_share_its_boot_id(monkeypatch):
    envs = [_backend_environment(monkeypatch, process=n, processes=2, boot_id="start-1") for n in (0, 1)]
    assert [{name: env.get(name) for name in NAMES} for env in envs] == [
        {"CURIO_BACKEND_PROCESS": "0", "CURIO_BACKEND_PROCESSES": "2", "CURIO_BOOT_ID": "start-1"},
        {"CURIO_BACKEND_PROCESS": "1", "CURIO_BACKEND_PROCESSES": "2", "CURIO_BOOT_ID": "start-1"},
    ]


def test_the_migration_before_the_backend_starts_does_none_of_the_startup_work(monkeypatch, tmp_path):
    """``flask db upgrade`` builds the app as the backend does; it builds it
    without the startup work, which is the home process's alone. Its
    ``FLASK_APP`` is resolved here as Flask resolves it."""
    import flask
    import flask.cli

    import utk_curio.backend.app as backend_app
    import utk_curio.cli.services as services

    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(services, "_is_testing", lambda: False)
    ran = []
    monkeypatch.setattr(services, "subprocess", SimpleNamespace(
        run=lambda args, **kwargs: ran.append((args, kwargs["env"])) or SimpleNamespace(stdout="", stderr=""),
        CalledProcessError=subprocess.CalledProcessError))
    services.prepare_backend_database()
    ((args, env),) = ran
    assert args[:3] == ["flask", "db", "upgrade"]

    module_name, _, factory = env["FLASK_APP"].partition(":")
    asked = []
    monkeypatch.setattr(backend_app, "create_app",
                        lambda *args, **kwargs: asked.append(kwargs) or flask.Flask("migration"))
    flask.cli.locate_app(module_name, factory)
    assert asked == [{"startup_work": False}], (
        f"the migration builds the app as {env['FLASK_APP']!r}, which does the startup work"
    )
