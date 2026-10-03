"""Widget references in the headless runner (#662).

A node's widgets live at ``metadata.widgets`` and its code places each one as a
``[!! name !!]`` reference. The browser resolves them in
``src/utils/widgets/widgetSubstitution.ts``; the runner resolves them in
``execution/widget_substitution.py``. Both read the same table of cases, so a
node validated headless runs the code the canvas would run.

Before, the runner read the old ``[!! name$TYPE$default !!]`` marker and always
used its default, while the browser used the value the user set.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.execution import runner
from utk_curio.backend.app.execution.widget_substitution import (
    REFERENCE_RE,
    WIDGET_NAME_RE,
    WidgetReferenceError,
    js_number,
    normalize_widgets,
    resolve_widget_references,
)
from utk_curio.backend.app.execution.workflow_spec import (
    parse_workflow_dict,
    resolve_widget_placeholders,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
WIDGETS_DIR = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "widgets"
CASES = json.loads((WIDGETS_DIR / "widgetSubstitution.cases.json").read_text(encoding="utf-8"))["cases"]

KEY = "4242"
PID = "p-widgets"


class TestTheSharedCases:
    """The table Jest reads too (``src/tests/utils/widgetSubstitution.test.ts``)."""

    @pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
    def test_the_runner_writes_what_the_browser_writes(self, case):
        code, problems = resolve_widget_references(case["code"], case["widgets"], case["language"])
        assert code == case["expected"]
        assert [p["message"] for p in problems] == case.get("problems", [])

    def test_the_table_covers_every_language_and_every_problem(self):
        assert {c["language"] for c in CASES} == {"python", "javascript", "json"}
        messages = " ".join(m for c in CASES for m in c.get("problems", []))
        for kind in ("is an old widget marker", "does not name a widget", "has no widget named"):
            assert kind in messages, kind


class TestNumbersMatchJavaScript:
    """Numbers are written the way JavaScript's ``String()`` writes them."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            (0, "0"),
            (-0.0, "0"),
            (2.0, "2"),
            (10, "10"),
            (1.5, "1.5"),
            (-1.5, "-1.5"),
            (1 / 3, "0.3333333333333333"),
            (0.1 + 0.2, "0.30000000000000004"),
            (0.000001, "0.000001"),
            (1e-7, "1e-7"),
            (1.23e-18, "1.23e-18"),
            (123456789012345680000.0, "123456789012345680000"),
            (1e21, "1e+21"),
            (10 ** 21, "1e+21"),
            (1.5e300, "1.5e+300"),
        ],
    )
    def test_js_number(self, value, expected):
        assert js_number(value) == expected


class TestThePatternsAreShared:
    """The frontend has no Python-importable constant, so its source is read."""

    def _ts(self, name: str) -> str:
        return (WIDGETS_DIR / name).read_text(encoding="utf-8")

    def _schemas(self):
        trill = json.loads((REPO_ROOT / "docs/schemas/trill.v1.json").read_text(encoding="utf-8"))
        package = json.loads((REPO_ROOT / "docs/schemas/node-package.v4.json").read_text(encoding="utf-8"))
        return trill["$defs"]["widget"], package["$defs"]["widget"]

    def test_the_reference_pattern(self):
        written = re.search(r"WIDGET_REFERENCE_PATTERN = String\.raw`(.*?)`", self._ts("widgetSubstitution.ts"))
        assert written and written.group(1) == REFERENCE_RE.pattern

    def test_the_name_pattern(self):
        written = re.search(r"WIDGET_NAME_PATTERN = String\.raw`(.*?)`", self._ts("widgetModel.ts"))
        assert written and written.group(1) == WIDGET_NAME_RE.pattern
        for schema in self._schemas():
            assert schema["properties"]["name"]["pattern"] == WIDGET_NAME_RE.pattern

    def test_the_widget_types(self):
        block = re.search(r"WIDGET_KINDS = \[(.*?)\]", self._ts("widgetModel.ts"), re.S)
        kinds = re.findall(r'"([a-z-]+)"', block.group(1))
        assert kinds
        for schema in self._schemas():
            assert schema["properties"]["type"]["enum"] == kinds


class TestResolveWidgetPlaceholders:
    def test_a_reference_takes_the_set_value(self):
        widgets = [{"name": "factor", "type": "number", "default": 1, "value": 3}]
        assert resolve_widget_placeholders("x = [!! factor !!]", widgets) == "x = 3"

    def test_without_a_set_value_the_default(self):
        widgets = [{"name": "factor", "type": "number", "default": 1}]
        assert resolve_widget_placeholders("x = [!! factor !!]", widgets) == "x = 1"

    def test_code_without_references_is_unchanged(self):
        assert resolve_widget_placeholders("return arg") == "return arg"

    def test_an_old_marker_is_refused_naming_the_new_way(self):
        with pytest.raises(WidgetReferenceError) as exc:
            resolve_widget_placeholders("x = [!! factor$INPUT_VALUE$1 !!]")
        assert "is an old widget marker" in str(exc.value)
        assert "Widgets tab" in str(exc.value)

    def test_every_problem_is_named(self):
        widgets = [{"name": "factor", "type": "number", "default": 1}]
        with pytest.raises(WidgetReferenceError) as exc:
            resolve_widget_placeholders("a = [!! missing !!]\nb = [!! 9lives !!]", widgets)
        lines = str(exc.value).split("\n")
        assert len(lines) == 2
        assert "no widget named missing" in lines[0]
        assert "does not name a widget" in lines[1]

    def test_javascript_spells_booleans_its_own_way(self):
        widgets = [{"name": "on", "type": "checkbox", "default": False, "value": True}]
        assert resolve_widget_placeholders("[!! on !!]", widgets, "python") == "True"
        assert resolve_widget_placeholders("[!! on !!]", widgets, "javascript") == "true"


class TestTheSpecCarriesWidgets:
    def test_metadata_widgets_reach_the_node(self):
        widgets = [{"name": "factor", "type": "number", "default": 1, "value": 2}]
        spec = parse_workflow_dict({"dataflow": {"nodes": [
            {"id": "a", "type": "curio.builtin/data-loading", "content": "x", "metadata": {"widgets": widgets}},
            {"id": "b", "type": "curio.builtin/data-loading", "content": "x"},
        ], "edges": []}})
        by_id = {n.id: n for n in spec.nodes}
        assert by_id["a"].widgets == widgets
        assert by_id["b"].widgets == []

    def test_malformed_entries_are_dropped(self):
        raw = [
            {"name": "ok", "type": "number", "default": 1},
            {"name": "ok", "type": "text", "default": "duplicate"},
            {"name": "has space", "type": "number", "default": 1},
            "not an object",
        ]
        assert normalize_widgets(raw) == [raw[0]]
        assert normalize_widgets({"name": "ok"}) == []


def _spec(nodes, edges=()):
    return {"dataflow": {"nodes": list(nodes), "edges": list(edges)}}


def _node(node_id, content, widgets=None, node_type="curio.builtin/computation-analysis"):
    node = {"id": node_id, "type": node_type, "content": content, "goal": ""}
    if widgets is not None:
        node["metadata"] = {"widgets": widgets}
    return node


class _RecordingExec:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, endpoint, payload):
        self.calls.append((endpoint, payload))
        return {"stdout": [], "stderr": "", "output": {"path": f"art-{len(self.calls)}", "dataType": "int"}}


FACTOR = [{"name": "factor", "type": "number", "default": 1, "value": 3}]


class TestTheRunner:
    def test_the_sandbox_gets_the_set_value(self, tmp_curio):
        rec = _RecordingExec()
        report = runner.run_through_node(KEY, PID, _spec([_node("a", "return [!! factor !!] * 2", FACTOR)]), "a", exec_fn=rec)
        assert report["ok"] is True
        assert "return 3 * 2" in rec.calls[0][1]["code"]
        assert "[!!" not in rec.calls[0][1]["code"]

    def test_a_javascript_node_gets_a_javascript_literal(self, tmp_curio):
        rec = _RecordingExec()
        widgets = [{"name": "on", "type": "checkbox", "default": False, "value": True}]
        spec = _spec([_node("j", "return [!! on !!];", widgets, "curio.builtin/js-computation")])
        report = runner.run_through_node(KEY, PID, spec, "j", exec_fn=rec)
        assert report["ok"] is True
        endpoint, payload = rec.calls[0]
        assert endpoint == "/execJs"
        assert "return true;" in payload["code"]

    def test_an_old_marker_fails_the_node_without_the_sandbox(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec([_node("a", "x = [!! factor$INPUT_VALUE$1 !!]")])
        report = runner.run_through_node(KEY, PID, spec, "a", exec_fn=rec)
        assert rec.calls == []
        assert report["ok"] is False
        assert report["blocker"] == "a"
        assert report["infrastructure"] is None
        assert report["nodes"]["a"]["status"] == "error"
        assert "is an old widget marker" in report["nodes"]["a"]["stderrTail"]

    def test_an_unknown_name_upstream_blocks_the_target(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec(
            [_node("a", "return [!! missing !!]", FACTOR), _node("b", "return arg")],
            [{"id": "e1", "source": "a", "target": "b"}],
        )
        report = runner.run_through_node(KEY, PID, spec, "b", exec_fn=rec)
        assert rec.calls == []
        assert report["ok"] is False and report["blocker"] == "a"
        assert "upstream" in report["error"]
        assert "no widget named missing" in report["nodes"]["a"]["stderrTail"]
