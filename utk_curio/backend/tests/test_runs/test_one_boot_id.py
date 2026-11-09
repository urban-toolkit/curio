"""Every backend process of one start shares the start's boot id, so a run read
in one of them leaves alone a run another of them has going.

A run left queued or running under another boot id was cut off by a restart:
a backend's start and every run read mark it interrupted
(``runs/service.py`` ``interrupt_runs_of_other_processes``). Here this test's
process is the backend whose run is going, held before its node by the test
rig's hold. The other backend is a fresh interpreter given this process's boot
id, as the launcher gives every backend of a start its one id: it starts on
the same database, reads the run as a tab does (``GET /api/runs/<id>``), and
says what it saw. Never forked: a forked child keeps the boot id this process
made when it imported the runs, whatever it is given.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import utk_curio
from utk_curio.backend.tests.test_runs.test_run_routes import (  # noqa: F401
    _create,
    _get,
    _node,
    _start,
    _until,
    _wait,
    sandbox,
)

#: The other backend: it builds the app on the database it is given, as a
#: backend starts, reads the run, and writes what it saw.
_OTHER_BACKEND = """
import json
import sys

from utk_curio.backend.app import create_app

database, run_id, token, out = sys.argv[1:5]


class Config:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = database
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret"


app = create_app(Config)

from utk_curio.backend.app.runs import jobs

reply = app.test_client().get(f"/api/runs/{run_id}", headers={"Authorization": f"Bearer {token}"})
body = reply.get_json(silent=True) or {}
with open(out, "w", encoding="utf-8") as handle:
    json.dump({"code": reply.status_code, "id": body.get("id"), "status": body.get("status"),
               "bootId": jobs.BOOT_ID}, handle)
"""


def _another_backend_reads(app, tmp_path, run_id, token, boot_id) -> dict:
    """What a fresh backend process, given *boot_id* as the launcher gives it
    and started as the second of two, saw when it read *run_id*."""
    out = tmp_path / "other-backend.json"
    env = {name: value for name, value in os.environ.items() if name != "WERKZEUG_RUN_MAIN"}
    root = str(Path(utk_curio.__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join(part for part in (root, env.get("PYTHONPATH")) if part)
    env.update({
        "CURIO_BOOT_ID": boot_id,
        "CURIO_BACKEND_PROCESS": "1",
        "CURIO_BACKEND_PROCESSES": "2",
    })
    done = subprocess.run(
        [sys.executable, "-c", _OTHER_BACKEND,
         app.config["SQLALCHEMY_DATABASE_URI"], run_id, token, str(out)],
        env=env, capture_output=True, text=True, timeout=300,
    )
    assert done.returncode == 0, f"the other backend failed:\n{done.stderr[-4000:]}"
    return json.loads(out.read_text(encoding="utf-8"))


def test_a_run_one_backend_has_going_survives_another_backends_read(
    app, client, user_and_token, sandbox, tmp_path, monkeypatch,
):
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs

    # The test rig's hold holds only under --testing.
    monkeypatch.setattr(config, "_is_testing", lambda: True)
    user, token = user_and_token
    project_id, _ = _create(client, token, [_node("a")])
    jobs.set_hold(True)
    try:
        run_id = _start(client, token, project_id).get_json()["id"]
        _until(lambda: jobs.hold_state()["waiting"] == 1)
        assert _get(client, token, run_id)["status"] == "running"

        seen = _another_backend_reads(app, tmp_path, run_id, token, jobs.BOOT_ID)
    finally:
        jobs.set_hold(False)

    assert seen["code"] == 200 and seen["id"] == run_id, f"the other backend did not find the run: {seen}"
    assert seen["status"] == "running", (
        f"the other backend of this start marked this backend's live run {seen['status']}: "
        f"its boot id is {seen['bootId']!r}, this backend's {jobs.BOOT_ID!r}"
    )
    _wait(run_id)
    assert _get(client, token, run_id)["status"] == "succeeded"
