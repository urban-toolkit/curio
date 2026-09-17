"""What ``test_frontend/diagnostics.py`` leaves behind when an e2e test fails.

The module runs inside the Playwright harness, but it only ever talks to a
page, a browser context and a pytest item, so a fake of each is enough to pin
what it writes and, above all, that it never raises.
"""

import os
import types

import pytest

from utk_curio.backend.tests.test_frontend import diagnostics


class _Tracing:
    def __init__(self):
        self.calls = []

    def start(self, **kwargs):
        self.calls.append(("start", kwargs))

    def start_chunk(self, **kwargs):
        self.calls.append(("start_chunk", kwargs))

    def stop_chunk(self, path=None):
        self.calls.append(("stop_chunk", path))
        if path:
            with open(path, "wb") as handle:
                handle.write(b"PK")

    def stop(self):
        self.calls.append(("stop", None))


class _Page:
    url = "http://localhost:8080/dataflow/abc"

    def __init__(self, *, nodes=(), log=None, screenshot_error=None, closed=False):
        self.context = types.SimpleNamespace(tracing=_Tracing())
        self._nodes = list(nodes)
        self._screenshot_error = screenshot_error
        self._closed = closed
        self.evaluated = False
        if log is not None:
            self._curio_browser_log = log

    def is_closed(self):
        return self._closed

    def screenshot(self, path, full_page, timeout):
        if self._screenshot_error:
            raise self._screenshot_error
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG")

    def evaluate(self, _js):
        self.evaluated = True
        return self._nodes


def _item(nodeid="tests/test_frontend/test_workflows.py::T::test_node_execution[06.json]",
          **funcargs):
    return types.SimpleNamespace(nodeid=nodeid, funcargs=funcargs)


@pytest.fixture(autouse=True)
def failure_root(tmp_path, monkeypatch):
    monkeypatch.setenv(diagnostics.DIR_ENV, str(tmp_path))
    monkeypatch.delenv(diagnostics.TRACE_ENV, raising=False)
    return tmp_path


POOL = {"id": "whatif-pool", "type": "react-flow__node-DATA_POOL",
        "status": None, "text": "Data Pool No data"}
DATA = {"id": "whatif-data", "type": "react-flow__node-AUTK_GRAMMAR",
        "status": "done", "text": "Autark Done"}


def test_a_failure_leaves_screenshot_node_states_and_browser_log():
    page = _Page(nodes=[DATA, POOL], log=[
        {"kind": "console", "type": "error", "text": "boom",
         "location": {"url": "bundle.js", "lineNumber": 7}},
        {"kind": "pageerror", "message": "TypeError: x is undefined"},
    ])
    written = diagnostics.finish(_item(workflow_page=page), failed=True)

    names = sorted(os.path.basename(p) for p in written)
    assert names == ["browser-log.txt", "nodes.txt", "screenshot.png"]
    nodes = open(next(p for p in written if p.endswith("nodes.txt"))).read()
    assert "whatif-pool  status=-" in nodes and "Data Pool No data" in nodes
    assert "whatif-data  status=done" in nodes
    log = open(next(p for p in written if p.endswith("browser-log.txt"))).read()
    assert "[error] boom  (bundle.js:7)" in log
    assert "[pageerror] TypeError: x is undefined" in log


def test_a_pass_leaves_nothing(failure_root):
    assert diagnostics.finish(_item(workflow_page=_Page(nodes=[POOL])), failed=False) == []
    assert list(failure_root.iterdir()) == []


def test_the_test_id_becomes_a_safe_directory(failure_root):
    path = diagnostics.failure_dir("tests/a.py::T::t[06 what-if.json-chromium]@wf-06")
    assert os.path.dirname(path) == str(failure_root)
    assert all(c.isalnum() or c in "_.-" for c in os.path.basename(path))


def test_the_workflow_page_is_preferred_and_closed_pages_are_skipped():
    workflow_page, page = _Page(), _Page()
    assert diagnostics.page_for(_item(workflow_page=workflow_page, page=page)) is workflow_page
    assert diagnostics.page_for(_item(workflow_page=_Page(closed=True), page=page)) is page
    assert diagnostics.page_for(_item()) is None


def test_a_hung_page_skips_the_node_query():
    """evaluate() has no timeout; asking a hung page would hang the run."""
    page = _Page(nodes=[POOL], screenshot_error=type("TimeoutError", (Exception,), {})("15s"))
    written = diagnostics.finish(_item(workflow_page=page), failed=True)
    assert not page.evaluated
    assert written == []
    errors_file = os.path.join(diagnostics.failure_dir(_item().nodeid),
                               "diagnostics-errors.txt")
    assert "did not respond" in open(errors_file).read()


def test_a_failing_diagnostic_never_raises():
    page = _Page(nodes=[POOL], screenshot_error=RuntimeError("target closed"))
    written = diagnostics.finish(_item(workflow_page=page), failed=True)
    assert [os.path.basename(p) for p in written] == ["nodes.txt"]


def test_tracing_is_off_unless_asked_for():
    context = types.SimpleNamespace(tracing=_Tracing())
    diagnostics.start_tracing(context)
    assert context.tracing.calls == []


def test_a_trace_records_snapshots_without_screenshots(monkeypatch):
    """What CI runs: the action log and DOM snapshots, but no per-action shots."""
    monkeypatch.setenv(diagnostics.TRACE_ENV, "1")
    context = types.SimpleNamespace(tracing=_Tracing())

    diagnostics.start_tracing(context)

    assert context.tracing.calls[0] == ("start", {"screenshots": False, "snapshots": True})


def test_full_adds_per_action_screenshots(monkeypatch):
    """What the manual repro job runs, where the extra cost is worth it."""
    monkeypatch.setenv(diagnostics.TRACE_ENV, "full")
    context = types.SimpleNamespace(tracing=_Tracing())

    diagnostics.start_tracing(context)

    assert context.tracing.calls[0] == ("start", {"screenshots": True, "snapshots": True})


def test_a_traced_failure_keeps_its_chunk(monkeypatch):
    monkeypatch.setenv(diagnostics.TRACE_ENV, "1")
    page = _Page(nodes=[POOL])
    diagnostics.start_tracing(page.context)
    item = _item(workflow_page=page)

    diagnostics.start_trace_chunk(item)
    written = diagnostics.finish(item, failed=True)

    assert [call[0] for call in page.context.tracing.calls] == [
        "start", "start_chunk", "stop_chunk"]
    assert page.context.tracing.calls[-1][1].endswith("trace.zip")
    assert "trace.zip" in [os.path.basename(p) for p in written]


def test_a_traced_pass_discards_its_chunk(monkeypatch):
    monkeypatch.setenv(diagnostics.TRACE_ENV, "1")
    page = _Page()
    diagnostics.start_tracing(page.context)
    item = _item(workflow_page=page)

    diagnostics.start_trace_chunk(item)
    assert diagnostics.finish(item, failed=False) == []
    assert page.context.tracing.calls[-1] == ("stop_chunk", None)
