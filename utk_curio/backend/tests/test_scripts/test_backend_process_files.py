"""Each backend process of a start of several writes files of its own
(``common/backend_processes.own_file``).

Two processes appending to one file interleave their lines, and a rotating
log renamed by one is still written by the others. So each process of a start
of several names its thread-stack file (``backend/thread_stacks.py``, which
the stress probe finds from the process's environment) and, when it logs to a
file rather than to its output, its log file with its number. A start of one
process keeps today's names.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

#: Environments of a backend process, and the name of its thread-stack file.
_STACKS = (
    ({"CURIO_LAUNCH_CWD": "/app"}, "backend-thread-stacks.txt"),
    ({"CURIO_LAUNCH_CWD": "/app", "CURIO_BACKEND_PROCESS": "0", "CURIO_BACKEND_PROCESSES": "1"},
     "backend-thread-stacks.txt"),
    ({"CURIO_LAUNCH_CWD": "/app", "CURIO_BACKEND_PROCESS": "0", "CURIO_BACKEND_PROCESSES": "4"},
     "backend-thread-stacks-0.txt"),
    ({"CURIO_LAUNCH_CWD": "/app", "CURIO_BACKEND_PROCESS": "2", "CURIO_BACKEND_PROCESSES": "4"},
     "backend-thread-stacks-2.txt"),
    ({"CURIO_STATE_DIR": "/state", "CURIO_BACKEND_PROCESS": "7", "CURIO_BACKEND_PROCESSES": "8"},
     "backend-thread-stacks-7.txt"),
)


def test_each_process_of_several_writes_its_own_thread_stacks_where_the_probe_reads_them():
    from utk_curio.backend import thread_stacks
    from utk_curio.backend.tests.stress.backend_probe import stacks_file

    for environ, name in _STACKS:
        path = thread_stacks.stacks_path(environ, "/app/utk_curio")
        assert path.name == name, f"{environ}: the stacks go to {path.name}, not {name}"
        assert path == stacks_file(environ, "/app/utk_curio"), f"{environ}: the probe reads another file"


def test_each_process_of_several_names_its_own_files():
    from utk_curio.common.backend_processes import own_file

    one = {"CURIO_BACKEND_PROCESS": "0", "CURIO_BACKEND_PROCESSES": "1"}
    third = {"CURIO_BACKEND_PROCESS": "2", "CURIO_BACKEND_PROCESSES": "3"}
    assert own_file("backend.log", {}) == "backend.log"
    assert own_file("backend.log", one) == "backend.log"
    assert own_file("backend.log", third) == "backend-2.log"
    assert own_file("backend-thread-stacks.txt", third) == "backend-thread-stacks-2.txt"
    assert own_file("stacks", third) == "stacks-2"


_LOG_FILES = """
import json, logging
from logging.handlers import RotatingFileHandler
from utk_curio.backend.app import create_app

class Config:
    TESTING = False
    DEBUG = False
    LOG_TO_STDOUT = ""
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret"

app = create_app(Config, startup_work=False)
print("LOGS " + json.dumps([handler.baseFilename for handler in app.logger.handlers
                            if isinstance(handler, RotatingFileHandler)]))
"""


def _log_files(folder: Path, **given: str) -> list[str]:
    """The files the backend's app logs to, started in *folder* with
    *given*, as a process that logs to a file rather than to its output."""
    env = {name: value for name, value in os.environ.items()
           if name not in ("CURIO_BACKEND_PROCESS", "CURIO_BACKEND_PROCESSES", "LOG_TO_STDOUT")}
    env.update(PYTHONPATH=str(REPO_ROOT), CURIO_STATE_DIR=str(folder / "state"), **given)
    done = subprocess.run([sys.executable, "-c", _LOG_FILES], cwd=folder, env=env,
                          capture_output=True, text=True, timeout=300)
    lines = [line for line in done.stdout.splitlines() if line.startswith("LOGS ")]
    assert done.returncode == 0 and lines, f"exit {done.returncode}\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}"
    return [Path(path).name for path in json.loads(lines[-1][len("LOGS "):])]


def test_each_process_of_several_logs_to_a_file_of_its_own(tmp_path):
    one = tmp_path / "one"
    several = tmp_path / "several"
    one.mkdir()
    several.mkdir()
    alone = _log_files(one)
    third = _log_files(several, CURIO_BACKEND_PROCESS="3", CURIO_BACKEND_PROCESSES="4")
    assert alone == ["backend.log"], "a start of one process keeps its log file"
    assert third == ["backend-3.log"], f"process 3 of 4 logs to {third}"
