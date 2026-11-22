"""The Vega-Lite specs a notebook import gets of its Altair cells, made in the
sandbox as node code runs there.

The backend's analysis runs no cell (``backend/app/notebooks/analyzer.py``).
``backend/app/notebooks/charts.py`` sends the cells that draw a chart to
``/exec`` as one node's code and reads the run's output with ``/get``. These
tests take that path through this app's routes, with no socket: in process,
and under fork isolation, where the cells run in a confined child.
"""
from __future__ import annotations

import json
import os
import textwrap

import pytest

from utk_curio.backend.app.execution import sandbox_client
from utk_curio.backend.app.notebooks import charts
from utk_curio.backend.app.notebooks.analyzer import analyze_cells, chart_cells
from utk_curio.sandbox.tests.test_isolation_linux import (  # noqa: F401
    isolated,
    linux_only,
    needs_seccomp,
    workspace,
)

#: The sign-in the import's run is made under.
SESSION = "notebook-import-session"


class _Reply:
    """This app's answer, read as the backend reads the sandbox's."""

    def __init__(self, response):
        self.status_code = response.status_code
        self._body = response.get_data(as_text=True)
        response.close()

    def json(self):
        return json.loads(self._body)


@pytest.fixture
def sandbox(workspace, monkeypatch):
    """The backend's calls to the sandbox, answered by this app's routes on
    the in-process path. Yields the paths asked, in order."""
    from utk_curio.sandbox.app import api, app
    from utk_curio.sandbox.app.worker import _worker_init

    _worker_init()
    client = app.test_client()
    asked = []

    def ask(method, path, *, label, timeout, **kwargs):
        asked.append(path)
        if method == "post":
            return _Reply(client.post(path, data=kwargs["data"], headers=kwargs["headers"]))
        return _Reply(client.get(path, query_string=kwargs["params"]))

    monkeypatch.setattr(sandbox_client, "sandbox_request", ask)
    monkeypatch.setattr(api, "_isolation_state", False)
    return asked


@pytest.fixture
def isolated_sandbox(sandbox, isolated, monkeypatch):
    """:func:`sandbox`, with ``/exec`` running each node in a child of a live
    zygote, as a deployment's sandbox does."""
    from utk_curio.sandbox.app import api
    from utk_curio.sandbox.isolation import runner

    monkeypatch.setattr(api, "_isolation_state", (runner.execute_isolated, isolated))
    return sandbox


def _specs(*sources):
    """The specs the import gets of the notebook of *sources*, by cell."""
    cells = [textwrap.dedent(source).strip("\n") for source in sources]
    found = chart_cells(cells, analyze_cells(cells)["analysis"])
    return charts.altair_specs(found, user=None, session_token=SESSION)


class TestTheSpecs:
    def test_a_bar_charts_spec(self, sandbox):
        specs = _specs(
            "import altair as alt",
            'chart = alt.Chart(df).mark_bar().encode(x="city:N", y="population:Q")',
        )
        assert set(specs) == {1}
        spec = specs[1]
        assert spec["mark"] == {"type": "bar"}
        assert spec["encoding"] == {
            "x": {"field": "city", "type": "nominal"},
            "y": {"field": "population", "type": "quantitative"},
        }
        assert spec["$schema"].startswith("https://vega.github.io/schema/vega-lite/")
        # One run for the notebook, read back once.
        assert sandbox == ["/exec", "/get"]

    def test_a_shorthand_fields_type_comes_from_the_stand_in_frame(self, sandbox):
        # Its columns are the fields the cell's strings name, holding numbers.
        spec = _specs('chart = alt.Chart(trips).mark_point().encode(x="distance", y="fare")')[0]
        assert spec["encoding"] == {
            "x": {"field": "distance", "type": "quantitative"},
            "y": {"field": "fare", "type": "quantitative"},
        }

    def test_the_spec_holds_no_data(self, sandbox):
        # The Vega-Lite node reads its data from the node wired into it.
        spec = _specs('chart = alt.Chart(pd.DataFrame({"a": [1, 2]})).mark_line().encode(x="a:Q")')[0]
        assert "data" not in spec and "datasets" not in spec
        assert spec["mark"] == {"type": "line"}
        assert spec["encoding"] == {"x": {"field": "a", "type": "quantitative"}}

    def test_each_cell_gets_its_spec_or_none_of_its_own(self, sandbox):
        specs = _specs(
            "broken = alt.Chart(df).mark_bar().encode(x=1 / 0)",
            "count = 3\nchart = alt.Chart(df).mark_area()\ntotal = 4",
            "import sys\nsys.exit(3)\nchart = alt.Chart(df).mark_bar()",
            'chart = alt.Chart(df).mark_tick().encode(x="a:Q")',
        )
        # A cell that raises, one whose last variable is no chart and one that
        # exits have none; the last keeps its own.
        assert set(specs) == {3}
        assert specs[3]["mark"] == {"type": "tick"}

    def test_the_run_keeps_no_import_for_the_sessions_later_nodes(self, sandbox):
        from utk_curio.sandbox.app import worker

        _specs("import os\nchart = alt.Chart(df).mark_bar().properties(title=os.sep)")
        assert worker._import_bindings_for(SESSION) == {}


@linux_only
class TestInAnIsolatedChild:
    def test_the_cells_run_in_a_child_and_their_spec_comes_back(self, isolated_sandbox):
        spec = _specs(
            "import os\nchart = alt.Chart(df).mark_bar().properties(title=str(os.getpid()))",
        )[0]
        assert spec["mark"] == {"type": "bar"}
        assert spec["title"] != str(os.getpid()), "the cell ran in the sandbox's own process"
        assert isolated_sandbox == ["/exec", "/get"]

    @needs_seccomp
    def test_a_chart_cell_has_no_network(self, isolated_sandbox):
        spec = _specs(
            """
            import socket
            try:
                socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                reach = "a network socket"
            except OSError:
                reach = "no network socket"
            chart = alt.Chart(df).mark_bar().properties(title=reach)
            """,
        )[0]
        assert spec["title"] == "no network socket"
