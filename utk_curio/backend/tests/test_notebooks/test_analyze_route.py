"""``POST /api/analyzeNotebook``, which the Projects page's Import notebook asks.

The backend reads each cell's code and runs none of it. The Vega-Lite spec of
a cell that draws an Altair chart is made in the sandbox, where node code
runs, so these tests stand in for the sandbox and open no socket. The route
needs a sign-in, as a Play does.
"""
from __future__ import annotations

import ast
import json
import sys
import textwrap
import types
from pathlib import Path

import pytest

from utk_curio.backend.app import notebooks
from utk_curio.backend.app.execution import sandbox_client
from utk_curio.backend.app.notebooks import charts

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

    def test_a_hosted_guest_still_gets_the_analysis(self, client, guest_user_and_token):
        token = guest_user_and_token[1]
        response = client.post(
            "/api/analyzeNotebook", json={"cells": ["df = load()", "out = df.head()"]},
            headers=_auth(token),
        )
        assert response.status_code == 200
        assert response.get_json()["edges"] == [{"source": 0, "target": 1}]


class TestTheChartRun:
    """The cells that draw an Altair chart go to the sandbox's ``/exec`` as one
    node's run, under the caller's sign-in, and its output is read back with
    ``/get``. Anything else the sandbox answers leaves every chart cell with
    no spec, and the rest of the analysis whole."""

    CELLS = [
        "import altair as alt",
        "df = load()",
        'chart = alt.Chart(df).mark_bar().encode(x="city:N", y="population:Q")',
        "out = df.head()",
        'line = alt.Chart(df).mark_line().encode(x="day:T")',
    ]
    SPEC = {"mark": {"type": "bar"}, "encoding": {"x": {"field": "city", "type": "nominal"}}}
    RAN = {"stdout": [], "stderr": "", "output": {"path": "art-7", "dataType": "dict"}}

    def _sandbox(self, monkeypatch, exec_reply=None, stored=None, unreachable=False):
        calls = []

        def fake(method, path, *, label, timeout, **kwargs):
            calls.append({"method": method, "path": path, "timeout": timeout, **kwargs})
            if unreachable:
                raise sandbox_client.SandboxTransportError(
                    {"error": "sandbox_unreachable", "message": "Could not reach the sandbox on /exec."}, 502,
                )
            return _Reply(exec_reply if path == "/exec" else stored)

        monkeypatch.setattr(sandbox_client, "sandbox_request", fake)
        return calls

    def _analysis(self, client, token, cells=None):
        response = client.post(
            "/api/analyzeNotebook", json={"cells": cells or self.CELLS}, headers=_auth(token),
        )
        assert response.status_code == 200
        return response.get_json()

    def test_the_chart_cells_go_to_the_sandbox_as_one_run_under_the_sign_in(
        self, client, user_and_token, monkeypatch,
    ):
        from utk_curio.backend.app.execution.node_exec import SANDBOX_EXEC_TIMEOUT
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        calls = self._sandbox(
            monkeypatch, self.RAN, {"data": {"specs": [self.SPEC, None]}, "dataType": "dict"},
        )
        analysis = self._analysis(client, token)

        assert [call["path"] for call in calls] == ["/exec", "/get"]
        run = json.loads(calls[0]["data"])
        # A Play's run: the caller's session, the work directory of their
        # account, a Play's time limit, and no dataset saved.
        assert run["session_id"] == token
        assert run["user_key"] == _user_dir_key(user)
        assert calls[0]["timeout"] == SANDBOX_EXEC_TIMEOUT
        assert run["save_dataset"] is False
        assert (run["nodeType"], run["file_path"], run["dataType"]) == (charts.RUN_LABEL, "", "")
        # The two chart cells, and no other cell, are the run's.
        assert repr(self.CELLS[2]) in run["code"] and repr(self.CELLS[4]) in run["code"]
        assert self.CELLS[1] not in run["code"] and self.CELLS[3] not in run["code"]
        assert calls[1]["params"] == {"fileName": "art-7", "sessionId": token}
        assert [cell["altair_spec"] for cell in analysis["analysis"]] == [None, None, self.SPEC, None, None]

    def test_a_notebook_with_no_chart_cell_asks_the_sandbox_nothing(self, client, user_and_token, monkeypatch):
        token = user_and_token[1]
        calls = self._sandbox(monkeypatch)
        self._analysis(client, token, ["df = load()", "out = df.head()"])
        assert calls == []

    def test_an_unreachable_sandbox_gives_no_chart_cell_a_spec(self, client, user_and_token, monkeypatch):
        token = user_and_token[1]
        self._sandbox(monkeypatch, unreachable=True)
        analysis = self._analysis(client, token)
        assert [cell["altair_spec"] for cell in analysis["analysis"]] == [None] * 5
        assert {"source": 1, "target": 2} in analysis["edges"]
        assert analysis["analysis"][0]["is_import_only"] is True

    def test_a_run_the_sandbox_failed_gives_no_chart_cell_a_spec(self, client, user_and_token, monkeypatch):
        token = user_and_token[1]
        calls = self._sandbox(monkeypatch, {"error": "run_failed", "message": "The run's place went away."})
        analysis = self._analysis(client, token)
        assert [call["path"] for call in calls] == ["/exec"]
        assert [cell["altair_spec"] for cell in analysis["analysis"]] == [None] * 5

    def test_a_run_that_made_no_output_gives_no_chart_cell_a_spec(self, client, user_and_token, monkeypatch):
        # As a run stopped at its time limit or its memory budget answers.
        token = user_and_token[1]
        calls = self._sandbox(monkeypatch, {
            "stdout": [], "stderr": "This node was stopped after 300s.",
            "output": {"path": "", "dataType": "str"},
        })
        analysis = self._analysis(client, token)
        assert [call["path"] for call in calls] == ["/exec"]
        assert [cell["altair_spec"] for cell in analysis["analysis"]] == [None] * 5

    def test_an_output_without_a_spec_for_each_chart_cell_gives_none(self, client, user_and_token, monkeypatch):
        token = user_and_token[1]
        self._sandbox(monkeypatch, self.RAN, {"data": {"specs": [self.SPEC]}, "dataType": "dict"})
        analysis = self._analysis(client, token)
        assert [cell["altair_spec"] for cell in analysis["analysis"]] == [None] * 5


class TestNoCellCodeRuns:
    def test_a_chart_cells_code_does_not_run_in_the_backend(self, client, user_and_token, probe, sandbox_calls):
        token = user_and_token[1]
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
