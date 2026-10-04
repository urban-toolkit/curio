"""Code references in the headless runner (#662).

A node's widgets live at ``metadata.widgets`` and its code places each one as a
``[!! name !!]`` reference; its inputs are placed as ``[!! input 1 !!]`` and
their columns as ``[!! input 1.height !!]``. The browser resolves them in
``src/utils/references/codeReferences.ts``; the runner resolves them in
``execution/code_references.py``. Both read the same table of cases, so a
node validated headless runs the code the canvas would run.

Before, the runner read the old ``[!! name$TYPE$default !!]`` marker and always
used its default, while the browser used the value the user set.

The reference module is imported inside each test, as ``test_runner.py``
does, so one missing name fails its own tests and not the whole collection.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.execution import runner
from utk_curio.backend.app.execution.workflow_spec import (
    parse_workflow_dict,
    resolve_code_references,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src"
WIDGETS_DIR = SRC_DIR / "utils" / "widgets"
REFERENCES_DIR = SRC_DIR / "utils" / "references"

KEY = "4242"
PID = "p-widgets"


def _cases() -> list[dict]:
    return json.loads((REFERENCES_DIR / "codeReferences.cases.json").read_text(encoding="utf-8"))["cases"]


def _reference_error():
    from utk_curio.backend.app.execution.code_references import CodeReferenceError

    return CodeReferenceError


class TestTheSharedCases:
    """The table Jest reads too (``src/tests/utils/codeReferences.test.ts``)."""

    def test_the_runner_writes_what_the_browser_writes(self):
        from utk_curio.backend.app.execution.code_references import resolve_references

        cases = _cases()
        assert cases
        mismatches = []
        for case in cases:
            code, problems = resolve_references(
                case["code"], case["widgets"], case["language"], case.get("inputs", [])
            )
            got = (code, [p["message"] for p in problems])
            want = (case["expected"], case.get("problems", []))
            if got != want:
                mismatches.append(f"{case['name']}: wrote {got!r}, the table says {want!r}")
        assert not mismatches, "\n".join(mismatches)

    def test_the_table_covers_every_language_and_every_problem(self):
        cases = _cases()
        assert {c["language"] for c in cases} == {"python", "javascript", "json"}
        messages = " ".join(m for c in cases for m in c.get("problems", []))
        for kind in (
            "is an old widget marker",
            "does not name a widget",
            "has no widget named",
            "has no edge",
            "is an input, not text",
            "an input chip works in Python and JavaScript code",
            "the edge for this input was deleted",
            "has no column",
        ):
            assert kind in messages, kind

    def test_the_table_has_input_and_column_references_in_every_language(self):
        cases = _cases()
        for language in ("python", "javascript", "json"):
            codes = " ".join(c["code"] for c in cases if c["language"] == language)
            assert "[!! input 0" in codes or "[!! input 1" in codes, language


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
        from utk_curio.backend.app.execution.code_references import js_number

        assert js_number(value) == expected


class TestThePatternsAreShared:
    """The frontend has no Python-importable constant, so its source is read."""

    def _ts(self, name: str, folder: Path = WIDGETS_DIR) -> str:
        return (folder / name).read_text(encoding="utf-8")

    def _schemas(self):
        trill = json.loads((REPO_ROOT / "docs/schemas/trill.v1.json").read_text(encoding="utf-8"))
        package = json.loads((REPO_ROOT / "docs/schemas/node-package.v4.json").read_text(encoding="utf-8"))
        return trill["$defs"]["widget"], package["$defs"]["widget"]

    def test_the_reference_pattern(self):
        from utk_curio.backend.app.execution.code_references import REFERENCE_RE

        written = re.search(
            r"REFERENCE_PATTERN = String\.raw`(.*?)`", self._ts("codeReferences.ts", REFERENCES_DIR)
        )
        assert written and written.group(1) == REFERENCE_RE.pattern

    def test_the_input_reference_pattern(self):
        from utk_curio.backend.app.execution.code_references import INPUT_REFERENCE_RE

        written = re.search(
            r"INPUT_REFERENCE_PATTERN = String\.raw`(.*?)`", self._ts("codeReferences.ts", REFERENCES_DIR)
        )
        assert written and written.group(1) == INPUT_REFERENCE_RE.pattern

    def test_an_input_reference_is_never_a_widget_name(self):
        from utk_curio.backend.app.execution.code_references import INPUT_REFERENCE_RE, WIDGET_NAME_RE

        for inner in ("input 0", "input 12", "input 0.height", "input ?", "input ?.a"):
            assert INPUT_REFERENCE_RE.match(inner), inner
            assert not WIDGET_NAME_RE.match(inner), inner

    def test_the_name_pattern(self):
        from utk_curio.backend.app.execution.code_references import WIDGET_NAME_RE

        written = re.search(r"WIDGET_NAME_PATTERN = String\.raw`(.*?)`", self._ts("widgetModel.ts"))
        assert written and written.group(1) == WIDGET_NAME_RE.pattern
        for schema in self._schemas():
            assert schema["properties"]["name"]["pattern"] == WIDGET_NAME_RE.pattern

    def test_the_widget_types(self):
        from utk_curio.backend.app.execution.code_references import WIDGET_KINDS

        block = re.search(r"WIDGET_KINDS = \[(.*?)\]", self._ts("widgetModel.ts"), re.S)
        kinds = re.findall(r'"([a-z-]+)"', block.group(1))
        assert kinds
        assert list(WIDGET_KINDS) == kinds
        for schema in self._schemas():
            assert schema["properties"]["type"]["enum"] == kinds

    def test_the_datetime_fallback(self):
        from utk_curio.backend.app.execution.code_references import DATETIME_FALLBACK

        written = re.search(r'DATETIME_FALLBACK = "(.*?)"', self._ts("widgetModel.ts"))
        assert written and written.group(1) == DATETIME_FALLBACK

    def test_the_options_the_controls_read(self):
        options = re.search(r"export interface WidgetOptions \{(.*?)\n\}", self._ts("widgetModel.ts"), re.S)
        keys = re.findall(r"^\s*([a-z]+)\?:", options.group(1), re.M)
        assert keys == ["choices", "display", "min", "max", "step", "units"]
        for schema in self._schemas():
            assert list(schema["properties"]["options"]["properties"]) == keys


class TestResolveCodeReferences:
    def test_an_input_is_arg_alone_or_indexed(self):
        assert resolve_code_references("return [!! input 0 !!]", (), "python", [0]) == "return arg"
        assert resolve_code_references("return [!! input 1 !!]", (), "python", [0, 1]) == "return arg[1]"

    def test_an_input_with_no_edge_is_refused(self):
        with pytest.raises(_reference_error()) as exc:
            resolve_code_references("return [!! input 2 !!]", (), "python", [0, 1])
        assert "input 2 has no edge" in str(exc.value)

    def test_a_column_is_its_name_without_the_data(self):
        assert resolve_code_references("s = arg[[!! input 0.area !!]]", (), "python", [0]) == 's = arg["area"]'

    def test_a_reference_takes_the_set_value(self):
        widgets = [{"name": "factor", "type": "number", "default": 1, "value": 3}]
        assert resolve_code_references("x = [!! factor !!]", widgets) == "x = 3"

    def test_without_a_set_value_the_default(self):
        widgets = [{"name": "factor", "type": "number", "default": 1}]
        assert resolve_code_references("x = [!! factor !!]", widgets) == "x = 1"

    def test_code_without_references_is_unchanged(self):
        assert resolve_code_references("return arg") == "return arg"

    def test_an_old_marker_is_refused_naming_the_new_way(self):
        with pytest.raises(_reference_error()) as exc:
            resolve_code_references("x = [!! factor$INPUT_VALUE$1 !!]")
        assert "is an old widget marker" in str(exc.value)
        assert "Widgets tab" in str(exc.value)

    def test_every_problem_is_named(self):
        widgets = [{"name": "factor", "type": "number", "default": 1}]
        with pytest.raises(_reference_error()) as exc:
            resolve_code_references("a = [!! missing !!]\nb = [!! 9lives !!]", widgets)
        lines = str(exc.value).split("\n")
        assert len(lines) == 2
        assert "no widget named missing" in lines[0]
        assert "does not name a widget" in lines[1]

    def test_javascript_spells_booleans_its_own_way(self):
        widgets = [{"name": "on", "type": "checkbox", "default": False, "value": True}]
        assert resolve_code_references("[!! on !!]", widgets, "python") == "True"
        assert resolve_code_references("[!! on !!]", widgets, "javascript") == "true"


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
        from utk_curio.backend.app.execution.code_references import normalize_widgets

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


#: Two loaders into one Python node, on circles 0 and 1, listed in the
#: opposite order: the circle decides where each lands in ``arg``.
FAN_IN = _spec(
    [
        _node("a", "return 1", node_type="curio.builtin/data-loading"),
        _node("b", "return 2", node_type="curio.builtin/data-loading"),
        _node("t", "return [!! input 1 !!]"),
    ],
    [
        {"id": "e-b", "source": "b", "target": "t", "sourceHandle": "out", "targetHandle": "in_1"},
        {"id": "e-a", "source": "a", "target": "t", "sourceHandle": "out", "targetHandle": "in"},
    ],
)


class TestSeveralInputs:
    def test_any_node_orders_its_inputs_by_circle(self):
        spec = parse_workflow_dict(FAN_IN)
        assert spec.upstream_nodes("t") == ["a", "b"]
        assert spec.input_slots("t") == [0, 1]

    def test_the_sandbox_gets_both_inputs_and_the_chip_as_arg_indexed(self, tmp_curio):
        rec = _RecordingExec()
        report = runner.run_through_node(KEY, PID, FAN_IN, "t", exec_fn=rec)
        assert report["ok"] is True
        payload = rec.calls[-1][1]
        assert "return arg[1]" in payload["code"]
        assert payload["dataType"] == "outputs"
        a_path = report["nodes"]["a"]["output"]["path"]
        b_path = report["nodes"]["b"]["output"]["path"]
        assert payload["file_path"].index(a_path) < payload["file_path"].index(b_path)

    def test_a_chip_for_an_input_with_no_edge_fails_the_node_without_the_sandbox(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec([_node("t", "return [!! input 0 !!]")])
        report = runner.run_through_node(KEY, PID, spec, "t", exec_fn=rec)
        assert rec.calls == []
        assert report["ok"] is False and report["blocker"] == "t"
        assert "input 0 has no edge" in report["nodes"]["t"]["stderrTail"]
