"""``POST /api/analyzeNotebook``, which the Projects page's Import notebook asks.

The backend reads each cell's code and runs none of it. The Vega-Lite spec of
a cell that draws an Altair chart is made in the sandbox, where node code
runs, so these tests stand in for the sandbox and open no socket. The route
needs a sign-in, as a Play does.
"""
from __future__ import annotations

import ast
import sys
import textwrap
import types
from pathlib import Path

import pytest

from utk_curio.backend.app import notebooks
from utk_curio.backend.app.execution import sandbox_client

#: A module the test owns, which a chart cell marks when its code runs.
PROBE = "curio_notebook_import_probe"

#: A cell the import turns into a Vega-Lite node: it parses, assigns a
#: variable and calls ``alt.Chart(``. Its first lines mark the probe.
CHART_CELL = textwrap.dedent(f"""
    import {PROBE}
    {PROBE}.ran_in = "the backend"
    chart = alt.Chart(df).mark_bar().encode(x="city:N", y="population:Q")
""").strip()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def probe(monkeypatch):
    """The probe module, which the chart cell's import finds in sys.modules."""
    module = types.ModuleType(PROBE)
    monkeypatch.setitem(sys.modules, PROBE, module)
    return module


class _Reply:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def sandbox_calls(monkeypatch):
    """Stand in for the sandbox: each call is recorded and answered as a run
    that made no output, and none opens a socket."""
    calls = []

    def fake(method, path, *, label, timeout, **kwargs):
        calls.append({"method": method, "path": path, "timeout": timeout, **kwargs})
        return _Reply({"stdout": [], "stderr": "", "output": {"path": "", "dataType": "str"}})

    monkeypatch.setattr(sandbox_client, "sandbox_request", fake)
    return calls


class TestTheSignIn:
    def test_an_unsigned_request_is_refused(self, client):
        response = client.post("/api/analyzeNotebook", json={"cells": ["x = 1"]})
        assert response.status_code == 401, (
            f"the notebook analysis answered {response.status_code} to a request with no sign-in"
        )


class TestNoCellCodeRuns:
    def test_a_chart_cells_code_does_not_run_in_the_backend(self, client, user_and_token, probe, sandbox_calls):
        _, token = user_and_token
        response = client.post(
            "/api/analyzeNotebook", json={"cells": [CHART_CELL]}, headers=_auth(token),
        )
        assert not hasattr(probe, "ran_in"), "the backend ran the code of a notebook cell it analyzed"
        assert response.status_code == 200

    def test_the_notebook_package_calls_no_exec_eval_or_compile(self):
        """No module of the backend's notebook package runs text as code. The
        run the sandbox makes of the chart cells is a string the package
        sends, never a call of its own."""
        found = []
        for path in sorted(Path(notebooks.__file__).parent.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                builtin = (
                    func.id if isinstance(func, ast.Name)
                    else func.attr if (
                        isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "builtins"
                    )
                    else None
                )
                if builtin in {"exec", "eval", "compile"}:
                    found.append(f"{path.name}:{node.lineno}: {builtin}()")
        assert found == [], f"the notebook package runs text as code: {found}"
