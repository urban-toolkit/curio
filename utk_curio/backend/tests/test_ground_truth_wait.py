"""The ground-truth run waits for the sandbox to end each node itself.

``test_node_execution`` (test_frontend/test_workflows.py) first runs an
example's Python nodes through the sandbox's ``/exec``
(``execute_workflow_programmatically``). The sandbox sends nothing while a node
runs and stops one at its own limit (``CURIO_EXEC_TIMEOUT``, 300 s unless set),
but the call gave up after 120 s. On run 42230248452, example 28's training ran
past 120 s on a loaded arcade runner: the test failed on a ConnectionError, and
the run it left went on to the sandbox's limit, beside example 29's nodes. A
call that waits out the sandbox's limit leaves no run behind it.

Browser-free, so it lives in the unit sweep, as test_artifact_snapshots.py
does.
"""
from __future__ import annotations

import os

import requests

from utk_curio.backend.tests.test_frontend.utils import REPO_ROOT
from utk_curio.backend.tests.test_frontend.utils import sandbox as sandbox_utils

EXAMPLE = os.path.join(REPO_ROOT, "docs", "examples", "28-pytorch-training-on-the-gpu.json")


class _Answer:
    """What ``/exec`` answers for a node that ran."""

    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"stdout": [], "stderr": "", "output": {"path": "1700000000000_ran", "dataType": "str"}}


def test_the_ground_truth_call_waits_out_the_sandboxs_node_limit(monkeypatch):
    from utk_curio.backend.tests.test_frontend.workflow_spec import parse_workflow
    from utk_curio.sandbox.isolation.supervisor import DEFAULT_WALL_TIMEOUT_SECONDS

    waits = []

    def post(url, **kwargs):
        waits.append(kwargs.get("timeout"))
        return _Answer()

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(sandbox_utils, "_catalog_resolution", lambda *args, **kwargs: {
        "paths": {}, "formats": {}, "collections": {}, "mediaDir": None, "models": {}, "packageModules": None,
    })
    monkeypatch.setattr(sandbox_utils, "snapshot_artifact", lambda path: {"path": path})

    sandbox_utils.execute_workflow_programmatically(parse_workflow(EXAMPLE))

    limit = int(os.environ.get("CURIO_EXEC_TIMEOUT") or DEFAULT_WALL_TIMEOUT_SECONDS)
    assert waits, "the ground-truth run sent no node to /exec"
    assert all(wait > limit for wait in waits), (
        f"the ground-truth call gave /exec {waits} s, but the sandbox lets a node run {limit} s"
    )
