"""Code references in the headless runner (#662).

A node's widgets live at ``metadata.widgets`` and its code places each one as a
``[!! name !!]`` reference; its inputs are placed as ``[!! input_1 !!]`` and
their columns as ``[!! input_1.height !!]``; its selection tags, at
``metadata.selections``, as ``[!! selection name !!]``. The browser resolves them in
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
from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict


def resolve_code_references(*args, **kwargs):
    from utk_curio.backend.app.execution.workflow_spec import resolve_code_references as resolve

    return resolve(*args, **kwargs)

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
            # A JSON case may name its document's grammar, such as vega-lite.
            grammar = {"grammar": case["grammar"]} if "grammar" in case else {}
            try:
                code, problems = resolve_references(
                    case["code"], case["widgets"], case["language"], case.get("inputs", []),
                    selections=case.get("selections", []), **grammar,
                )
            except Exception as exc:  # one case that raises is a mismatch, the others are still read
                mismatches.append(f"{case['name']}: raised {exc!r}")
                continue
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
            "has no layer",
            "Its layers are",
            "It carries no named layers",
            "carries several layers",
            "the edge for this input was deleted",
            "names an input the old way",
            "has no column",
            "has no selection tag named",
            "does not name a selection tag",
            "a selection tag takes",
            "is for a Vega-Lite spec, not for code",
            "has no input to stack",
        ):
            assert kind in messages, kind

    def test_the_table_has_input_and_column_references_in_every_language(self):
        cases = _cases()
        for language in ("python", "javascript", "json"):
            codes = " ".join(c["code"] for c in cases if c["language"] == language)
            assert "[!! input_0" in codes or "[!! input_1" in codes, language

    def test_the_table_has_layer_references_in_every_language(self):
        """A layer chip resolves in Python and JavaScript code too, not only in
        a Vega-Lite or Autark spec."""
        cases = _cases()
        for language in ("python", "javascript", "json"):
            resolved = [
                c for c in cases
                if c["language"] == language and re.search(r"\[!! input_\d+:[^.\s]+ !!\]", c["code"])
                and not c.get("problems")
            ]
            assert resolved, f"no layer reference resolves in a {language} case"

    def test_the_table_refuses_a_name_that_starts_with_at_in_every_language(self):
        """``[!! @name !!]`` names no widget: a value several nodes read reaches
        each by an edge, so no chip names another node's widget."""
        cases = _cases()
        for language in ("python", "javascript", "json"):
            refused = [
                c for c in cases
                if c["language"] == language and "[!! @" in c["code"]
                and any(p.startswith("[!! @") and "does not name a widget." in p for p in c.get("problems", []))
            ]
            assert refused, f"no {language} case refuses a name that starts with @"
            resolving = [c for c in cases if c["language"] == language and "[!! @" in c["expected"] and not c.get("problems")]
            assert not resolving, f"a {language} case resolves a name that starts with @"

    def test_the_table_has_selection_references_in_every_language(self):
        cases = _cases()
        for language in ("python", "javascript", "json"):
            resolved = [
                c for c in cases
                if c["language"] == language and "[!! selection " in c["code"] and not c.get("problems")
            ]
            assert resolved, f"no selection reference resolves in a {language} case"

    def test_the_table_has_the_scenario_chips_and_their_problems(self):
        """Each scenario chip, the dataset ``inputs`` and a field of it resolve
        in a spec, and each is refused where it must be: in code, misspelled,
        with no edge or a deleted one, inside quotes, with its boxes unknown,
        naming no field, or on a node with no input to stack."""
        cases = _cases()
        resolving = " ".join(c["code"] for c in cases if c["language"] == "json" and not c.get("problems"))
        for chip in (
            "scenario colors", "scenario text_colors", "scenario order", "scenario input_1", "inputs",
            "inputs.scenario_name",
        ):
            assert f"[!! {chip} !!]" in resolving, chip
        messages = " ".join(m for c in cases for m in c.get("problems", []))
        for kind in (
            "is for a Vega-Lite or Autark spec, not for code",
            "is for a Vega-Lite spec, not for code",
            "names no scenario chip",
            "write scenario input_<k> for a circle that has one",
            "is a scale, not text",
            "is a list of names, not text",
            "comes from is not known here",
            "the dataset inputs has no field",
            "has no input to stack",
        ):
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

    def test_the_old_input_reference_pattern(self):
        from utk_curio.backend.app.execution.code_references import LEGACY_INPUT_REFERENCE_RE

        written = re.search(
            r"LEGACY_INPUT_REFERENCE_PATTERN = String\.raw`(.*?)`", self._ts("codeReferences.ts", REFERENCES_DIR)
        )
        assert written and written.group(1) == LEGACY_INPUT_REFERENCE_RE.pattern

    def test_an_input_reference_is_never_a_widget_name(self):
        from utk_curio.backend.app.execution.code_references import (
            INPUT_REFERENCE_RE,
            check_widget_def,
            parse_reference,
        )

        for inner in ("input_0", "input_12", "input_0.height", "input_?", "input_?.a"):
            assert INPUT_REFERENCE_RE.match(inner), inner
            assert parse_reference(inner)["kind"] == "input", inner
        # An input's name is a widget name's shape, so no widget may take it.
        assert check_widget_def({"name": "input_12", "type": "number", "default": 1}) is not None

    def test_an_old_input_reference_is_neither_an_input_nor_a_widget(self):
        from utk_curio.backend.app.execution.code_references import (
            INPUT_REFERENCE_RE,
            LEGACY_INPUT_REFERENCE_RE,
            WIDGET_NAME_RE,
        )

        for inner in ("input 0", "input 12", "input 0.height", "input ?", "input 0:roads.lanes"):
            assert LEGACY_INPUT_REFERENCE_RE.match(inner), inner
            assert not INPUT_REFERENCE_RE.match(inner), inner
            assert not WIDGET_NAME_RE.match(inner), inner

    def test_the_greys_of_the_inputs_from_no_box(self):
        from utk_curio.backend.app.execution.code_references import NO_SCENARIO_COLOR, NO_SCENARIO_GREYS

        written = re.search(
            r"NO_SCENARIO_GREYS: readonly string\[\] = \[(.*?)\];",
            self._ts("scenarioColors.ts", REFERENCES_DIR.parent / "scenarios"),
        )
        assert written and re.findall(r'"(#[0-9a-f]{6})"', written.group(1)) == list(NO_SCENARIO_GREYS)
        assert NO_SCENARIO_GREYS[0] == NO_SCENARIO_COLOR
        assert len(set(NO_SCENARIO_GREYS)) == len(NO_SCENARIO_GREYS)

    def test_the_selection_reference_pattern(self):
        from utk_curio.backend.app.execution.code_references import SELECTION_REFERENCE_RE

        written = re.search(
            r"SELECTION_REFERENCE_PATTERN = String\.raw`(.*?)`", self._ts("codeReferences.ts", REFERENCES_DIR)
        )
        assert written and written.group(1) == SELECTION_REFERENCE_RE.pattern

    def test_a_selection_reference_is_never_a_widget_or_an_input(self):
        from utk_curio.backend.app.execution.code_references import parse_reference

        assert parse_reference("selection picked") == {"kind": "selection", "name": "picked"}
        for inner, kind in (("selection", "widget"), ("selection_2", "widget"), ("@selection", "widget")):
            assert parse_reference(inner)["kind"] == kind, inner

    def test_the_scenario_and_stacked_reference_patterns(self):
        from utk_curio.backend.app.execution.code_references import SCENARIO_REFERENCE_RE, STACKED_REFERENCE_RE

        source = self._ts("codeReferences.ts", REFERENCES_DIR)
        for name, compiled in (("SCENARIO_REFERENCE_PATTERN", SCENARIO_REFERENCE_RE), ("STACKED_REFERENCE_PATTERN", STACKED_REFERENCE_RE)):
            written = re.search(name + r" = String\.raw`(.*?)`", source)
            assert written and written.group(1) == compiled.pattern, name

    def test_a_scenario_chip_is_never_a_widget_or_an_input(self):
        """``scenario colors`` has a space and ``inputs.scenario_name`` a dot,
        which no widget name holds, and neither starts as an input does. What
        the owner first called them would read as a widget, or as a column of
        input_1. ``inputs`` names the dataset itself, a name no widget takes."""
        from utk_curio.backend.app.execution.code_references import parse_reference

        assert parse_reference("scenario colors") == {"kind": "scenario", "chip": "colors"}
        assert parse_reference("scenario text_colors") == {"kind": "scenario", "chip": "text_colors"}
        assert parse_reference("scenario order") == {"kind": "scenario", "chip": "order"}
        assert parse_reference("scenario input_2") == {"kind": "scenario", "chip": "input", "slot": 2}
        assert parse_reference("scenario input_?") == {"kind": "scenario", "chip": "input", "slot": None}
        assert parse_reference("scenario colours") == {"kind": "scenario", "chip": None}
        assert parse_reference("inputs.rain.mm") == {"kind": "stacked", "column": "rain.mm"}
        assert parse_reference("inputs") == {"kind": "dataset"}
        assert parse_reference("scenario_colors") == {"kind": "widget", "name": "scenario_colors"}
        assert parse_reference("scenario") == {"kind": "widget", "name": "scenario"}
        assert parse_reference("input_1.scenario_color") == {"kind": "input", "slot": 1, "column": "scenario_color"}

    def test_the_selection_cap_is_one_number(self):
        from utk_curio.backend.app.execution.code_references import SELECTION_ID_CAP

        written = re.search(r"SELECTION_ID_CAP = (\d+);", self._ts("selectionTags.ts", REFERENCES_DIR))
        assert written and int(written.group(1)) == SELECTION_ID_CAP
        trill = json.loads((REPO_ROOT / "docs/schemas/trill.v1.json").read_text(encoding="utf-8"))
        tag = trill["$defs"]["selectionTag"]["properties"]
        assert tag["ids"]["maxItems"] == SELECTION_ID_CAP
        assert tag["count"]["minimum"] == SELECTION_ID_CAP + 1

    def test_the_name_pattern(self):
        """The Widgets tab and a package manifest refuse a name of another
        shape; the schemas refuse it in an editor too. The
        packages domain, which imports no other feature, keeps its own copy for
        the widgets a function's parameters suggest."""
        from utk_curio.backend.app.execution.code_references import WIDGET_NAME_RE
        from utk_curio.backend.app.packages.domain import function_nodes

        written = re.search(r"WIDGET_NAME_PATTERN = String\.raw`(.*?)`", self._ts("widgetModel.ts"))
        assert written and written.group(1) == WIDGET_NAME_RE.pattern
        for schema in self._schemas():
            assert schema["properties"]["name"]["pattern"] == WIDGET_NAME_RE.pattern
        assert function_nodes.WIDGET_NAME_RE.pattern == WIDGET_NAME_RE.pattern

    def test_the_stacked_dataset_is_one_name(self):
        """The dataset a Vega-Lite spec reads its inputs stacked in, which its
        chip ``[!! inputs !!]`` writes, is one name in the browser, the runner
        and the agents' check, and no widget takes it."""
        from utk_curio.backend.app.agents.domain.document_validation import INPUTS_DATASET
        from utk_curio.backend.app.execution.code_references import INPUT_NAME_ONLY_RE, STACKED_DATASET

        written = re.search(r'INPUTS_DATASET = "(.*?)";', self._ts("vegaDatasets.ts", SRC_DIR / "utils"))
        assert written and written.group(1) == STACKED_DATASET == INPUTS_DATASET == "inputs"
        assert INPUT_NAME_ONLY_RE.fullmatch(STACKED_DATASET)

    def test_the_input_name_no_widget_takes(self):
        """The Widgets tab and a package manifest refuse one name pattern; the
        schema refuses it in an editor too."""
        from utk_curio.backend.app.execution.code_references import INPUT_NAME_ONLY_RE

        written = re.search(r"INPUT_NAME_ONLY_PATTERN = String\.raw`(.*?)`", self._ts("widgetModel.ts"))
        assert written and written.group(1) == INPUT_NAME_ONLY_RE.pattern
        package = self._schemas()[1]
        assert package["properties"]["name"]["not"] == {"pattern": INPUT_NAME_ONLY_RE.pattern}

    def test_the_widget_types(self):
        """The Widgets tab, an agent's widget and a package manifest refuse a
        type outside these kinds; the schemas refuse it in an editor too."""
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
    def test_an_input_is_the_name_of_its_circle(self):
        assert resolve_code_references("return [!! input_0 !!]", (), "python", [0]) == "return input_0"
        assert resolve_code_references("return [!! input_1 !!]", (), "python", [0, 1]) == "return input_1"
        assert resolve_code_references("return [!! input_3 !!]", (), "python", [3]) == "return input_3"

    def test_an_input_with_no_edge_is_refused(self):
        with pytest.raises(_reference_error()) as exc:
            resolve_code_references("return [!! input_2 !!]", (), "python", [0, 1])
        assert "input_2 has no edge" in str(exc.value)

    def test_an_old_chip_is_refused_naming_its_new_spelling(self):
        with pytest.raises(_reference_error()) as exc:
            resolve_code_references("return [!! input 1 !!]", (), "python", [0, 1])
        assert "names an input the old way" in str(exc.value)
        assert "Write [!! input_1 !!]" in str(exc.value)

    def test_a_column_is_its_name_without_the_data(self):
        assert resolve_code_references("s = input_0[[!! input_0.area !!]]", (), "python", [0]) == 's = input_0["area"]'

    def test_a_reference_takes_the_set_value(self):
        widgets = [{"name": "factor", "type": "number", "default": 1, "value": 3}]
        assert resolve_code_references("x = [!! factor !!]", widgets) == "x = 3"

    def test_without_a_set_value_the_default(self):
        widgets = [{"name": "factor", "type": "number", "default": 1}]
        assert resolve_code_references("x = [!! factor !!]", widgets) == "x = 1"

    def test_code_without_references_is_unchanged(self):
        assert resolve_code_references("return input_0") == "return input_0"

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

    def test_a_vega_lite_spec_of_a_node_writes_a_column_escaped_in_a_field(self):
        """A node's spec resolved as the canvas resolves a Vega-Lite chart's
        (issue 1042): its column chip in a field escaped, in its title the
        name; the same document of no grammar writes the name in both."""
        spec = parse_workflow_dict({"dataflow": {"nodes": [
            {"id": "rain", "type": "curio.builtin/data-loading", "content": "return df"},
            {"id": "chart", "type": "curio.builtin/vis-vega",
             "content": '{"encoding": {"y": {"field": [!! input_0.rain.mm !!], "title": "[!! input_0.rain.mm !!]"}}}'},
        ], "edges": [{"id": "e", "source": "rain", "target": "chart"}]}})
        chart = next(n for n in spec.nodes if n.id == "chart")
        assert spec.node_code(chart, "json", grammar="vega-lite") == (
            '{"encoding": {"y": {"field": "rain\\\\.mm", "title": "rain.mm"}}}'
        )
        assert spec.node_code(chart, "json") == '{"encoding": {"y": {"field": "rain.mm", "title": "rain.mm"}}}'


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

    def test_a_name_that_ends_in_a_line_break_is_dropped_as_the_browser_drops_it(self):
        """The browser's ``normalizeWidgets`` reads the name pattern as
        ECMA-262 does, where ``$`` ends the text, so it drops this widget.
        Python's ``re.match`` lets a final line break through."""
        from utk_curio.backend.app.execution.code_references import normalize_widgets

        widget = {"name": "factor\n", "type": "number", "default": 1}
        assert normalize_widgets([widget]) == []
        spec = parse_workflow_dict({"dataflow": {"nodes": [
            {"id": "a", "type": "curio.builtin/data-loading", "content": "x", "metadata": {"widgets": [widget]}},
        ], "edges": []}})
        assert spec.nodes[0].widgets == []


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
            [_node("a", "return [!! missing !!]", FACTOR), _node("b", "return input_0")],
            [{"id": "e1", "source": "a", "target": "b"}],
        )
        report = runner.run_through_node(KEY, PID, spec, "b", exec_fn=rec)
        assert rec.calls == []
        assert report["ok"] is False and report["blocker"] == "a"
        assert "upstream" in report["error"]
        assert "no widget named missing" in report["nodes"]["a"]["stderrTail"]


#: Two loaders into one Python node, on circles 0 and 1, listed in the
#: opposite order: the circle decides which input_k each is.
FAN_IN = _spec(
    [
        _node("a", "return 1", node_type="curio.builtin/data-loading"),
        _node("b", "return 2", node_type="curio.builtin/data-loading"),
        _node("t", "return [!! input_1 !!]"),
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

    def test_the_sandbox_gets_both_inputs_and_the_chip_as_its_circles_name(self, tmp_curio):
        rec = _RecordingExec()
        report = runner.run_through_node(KEY, PID, FAN_IN, "t", exec_fn=rec)
        assert report["ok"] is True
        payload = rec.calls[-1][1]
        assert "return input_1" in payload["code"]
        assert payload["input_slots"] == [0, 1]
        assert payload["dataType"] == "outputs"
        a_path = report["nodes"]["a"]["output"]["path"]
        b_path = report["nodes"]["b"]["output"]["path"]
        assert payload["file_path"].index(a_path) < payload["file_path"].index(b_path)

    def test_a_chip_for_an_input_with_no_edge_fails_the_node_without_the_sandbox(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec([_node("t", "return [!! input_0 !!]")])
        report = runner.run_through_node(KEY, PID, spec, "t", exec_fn=rec)
        assert rec.calls == []
        assert report["ok"] is False and report["blocker"] == "t"
        assert "input_0 has no edge" in report["nodes"]["t"]["stderrTail"]


class TestLayerChips:
    """``[!! input_k:layer !!]`` in Python and JavaScript code: the call that
    picks the layer out of input_k when the node runs, ``curio_layer`` in the
    sandbox (``util/input_layers.py``, ``util/js_wrapper.mjs``)."""

    def test_the_sandbox_gets_the_layer_chip_as_the_call_that_picks_it(self, tmp_curio):
        from utk_curio.backend.app.execution.code_references import LAYER_HELPER

        rec = _RecordingExec()
        spec = _spec(
            [
                _node("osm", "{}", node_type="curio.builtin/data-loading"),
                _node("t", "roads = [!! input_0:table_osm_roads !!]\nreturn roads[[!! input_0:table_osm_roads.highway !!]]"),
            ],
            [{"id": "e", "source": "osm", "target": "t", "sourceHandle": "out", "targetHandle": "in"}],
        )
        report = runner.run_through_node(KEY, PID, spec, "t", exec_fn=rec)
        assert report["ok"] is True, report
        assert LAYER_HELPER == "curio_layer"
        # The runner indents the node's code into its function body.
        assert '    roads = curio_layer(input_0, "table_osm_roads", 0)\n    return roads["highway"]' in rec.calls[-1][1]["code"]

    def test_a_javascript_node_gets_the_same_call(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec(
            [
                _node("a", "return 1", node_type="curio.builtin/data-loading"),
                _node("b", "return 2", node_type="curio.builtin/data-loading"),
                _node("j", "return [!! input_1:roads !!];", node_type="curio.builtin/js-computation"),
            ],
            [
                {"id": "e-a", "source": "a", "target": "j", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-b", "source": "b", "target": "j", "sourceHandle": "out", "targetHandle": "in_1"},
            ],
        )
        report = runner.run_through_node(KEY, PID, spec, "j", exec_fn=rec)
        assert report["ok"] is True, report
        endpoint, payload = rec.calls[-1]
        assert endpoint == "/execJs"
        assert 'return curio_layer(input_1, "roads", 1);' in payload["code"]

    def test_the_names_and_the_missing_layer_message_are_the_sandboxs(self):
        """The resolver, the browser and both sandbox helpers name one call and
        say one thing of a missing layer."""
        from utk_curio.backend.app.execution.code_references import (
            LAYER_HELPER,
            input_reference_inner,
            missing_layer_message,
            reference_text,
        )
        from utk_curio.sandbox.util import input_layers

        assert input_layers.LAYER_HELPER == LAYER_HELPER
        for names in (["table_osm_roads", "table_osm_buildings"], []):
            written = reference_text(input_reference_inner(2, layer="parks"))
            assert input_layers.missing_layer_message(2, "parks", names) == missing_layer_message(written, 2, "parks", names)
        ts = (REFERENCES_DIR / "codeReferences.ts").read_text(encoding="utf-8")
        assert f'export const LAYER_HELPER = "{LAYER_HELPER}";' in ts
        wrapper = (REPO_ROOT / "utk_curio/sandbox/util/js_wrapper.mjs").read_text(encoding="utf-8")
        assert f"const {LAYER_HELPER} = (value, layer, slot = 0) =>" in wrapper


class TestANameThatStartsWithAt:
    """``[!! @name !!]`` names no widget: a value several nodes read is a
    widget on one node that returns it, wired into each reader. A saved node
    of the removed ``curio.builtin/parameter`` type changes nothing."""

    def test_it_fails_the_node_without_the_sandbox(self, tmp_curio):
        rec = _RecordingExec()
        saved = {
            "id": "p", "type": "curio.builtin/parameter@1", "content": "",
            "metadata": {"widgets": [{"name": "factor", "type": "number", "default": 2, "value": 5}]},
        }
        spec = _spec([saved, _node("a", "return [!! @factor !!] - [!! factor !!]", FACTOR)])
        report = runner.run_through_node(KEY, PID, spec, "a", exec_fn=rec)
        assert rec.calls == []
        assert report["ok"] is False and report["blocker"] == "a"
        assert (
            "[!! @factor !!] does not name a widget. Widget names are letters, digits and underscores."
            in report["nodes"]["a"]["stderrTail"]
        )


PICKED = {"name": "picked", "node": "chart", "column": "osm_id", "ids": [101, 104]}


def _picker(node_id, content, selections, node_type="curio.builtin/computation-analysis"):
    return {"id": node_id, "type": node_type, "content": content, "goal": "", "metadata": {"selections": selections}}


class TestSelectionTags:
    """``[!! selection name !!]`` names one of the node's selection tags, which
    holds the ids of the rows a view's selection picks (``metadata.selections``).
    The ids are saved with the dataflow, so the runner reads the ones the canvas
    showed."""

    def test_metadata_selections_reach_the_node(self):
        from utk_curio.backend.app.execution.code_references import normalize_selections

        spec = parse_workflow_dict(_spec([_picker("a", "x", [PICKED]), _node("b", "x")]))
        by_id = {n.id: n for n in spec.nodes}
        assert by_id["a"].selections == [PICKED]
        assert by_id["b"].selections == []
        raw = [
            PICKED,
            {**PICKED, "ids": [1]},
            {"name": "many", "node": "chart", "column": "osm_id", "count": 20000},
            {"name": "no_ids", "node": "chart", "column": "osm_id"},
            {"name": "no_view", "column": "osm_id", "ids": []},
            "not an object",
        ]
        assert normalize_selections(raw) == [PICKED, raw[2]]

    def test_a_tag_whose_name_ends_in_a_line_break_is_dropped_as_the_browser_drops_it(self):
        """The browser's ``normalizeSelections`` reads the name pattern as
        ECMA-262 does, where ``$`` ends the text. Python's ``re.match`` lets a
        final line break through."""
        from utk_curio.backend.app.execution.code_references import normalize_selections

        assert normalize_selections([{**PICKED, "name": "picked\n"}]) == []
        spec = parse_workflow_dict(_spec([_picker("a", "x", [{**PICKED, "name": "picked\n"}])]))
        assert spec.nodes[0].selections == []

    def test_the_sandbox_gets_the_ids(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec([_picker("a", "picked = [!! selection picked !!]\nreturn len(picked)", [PICKED])])
        report = runner.run_through_node(KEY, PID, spec, "a", exec_fn=rec)
        assert report["ok"] is True
        assert "picked = [101, 104]" in rec.calls[0][1]["code"]
        assert "[!!" not in rec.calls[0][1]["code"]

    def test_a_javascript_node_gets_a_javascript_list(self, tmp_curio):
        rec = _RecordingExec()
        tag = {**PICKED, "ids": ["w12", 7]}
        spec = _spec([_picker("j", "return [!! selection picked !!].length;", [tag], "curio.builtin/js-computation")])
        report = runner.run_through_node(KEY, PID, spec, "j", exec_fn=rec)
        assert report["ok"] is True
        assert 'return ["w12", 7].length;' in rec.calls[0][1]["code"]

    def test_a_selection_over_the_cap_fails_the_node_without_the_sandbox(self, tmp_curio):
        from utk_curio.backend.app.execution.code_references import SELECTION_ID_CAP

        rec = _RecordingExec()
        over = {"name": "picked", "node": "chart", "column": "osm_id", "count": 25000}
        spec = _spec([_picker("a", "return [!! selection picked !!]", [over])])
        report = runner.run_through_node(KEY, PID, spec, "a", exec_fn=rec)
        assert rec.calls == []
        assert report["ok"] is False and report["blocker"] == "a"
        assert (
            f"the selection holds 25000 ids, more than the {SELECTION_ID_CAP} a selection tag takes"
            in report["nodes"]["a"]["stderrTail"]
        )

    def test_a_hand_edited_list_longer_than_the_cap_is_refused_the_same_way(self):
        from utk_curio.backend.app.execution.code_references import SELECTION_ID_CAP

        tag = {**PICKED, "ids": list(range(SELECTION_ID_CAP + 1))}
        with pytest.raises(_reference_error()) as exc:
            resolve_code_references("x = [!! selection picked !!]", (), "python", (), selections=[tag])
        assert f"holds {SELECTION_ID_CAP + 1} ids, more than the {SELECTION_ID_CAP}" in str(exc.value)

    def test_a_tag_the_node_does_not_have_fails_the_node(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec([_picker("a", "return [!! selection other !!]", [PICKED])])
        report = runner.run_through_node(KEY, PID, spec, "a", exec_fn=rec)
        assert rec.calls == []
        assert "this node has no selection tag named other" in report["nodes"]["a"]["stderrTail"]


class TestChipPlaceholders:
    """A spec read for its shape before its chips are resolved (what an Autark
    document declares): each chip standing on its own is held by a string of
    itself, so any bare chip, a list or a scale included, leaves it JSON, as
    ``withChipPlaceholders`` in ``codeReferences.ts`` does."""

    def test_each_chip_standing_on_its_own_is_held_by_a_string_of_itself(self):
        from utk_curio.backend.app.execution.code_references import with_chip_placeholders

        spec = (
            '{"encoding": {"x": {"field": "scenario_name", "sort": [!! scenario order !!]}, '
            '"color": {"field": "scenario_name", "scale": [!! scenario colors !!]}, "y": {"field": "[!! inputs.sunlight !!]"}}, '
            '"width": [!! size !!], "title": "Sun in \\"[!! season !!]\\""}'
        )
        with pytest.raises(ValueError):
            json.loads(spec)
        held = json.loads(with_chip_placeholders(spec))
        assert held["encoding"]["x"]["sort"] == "[!! scenario order !!]"
        assert held["encoding"]["color"]["scale"] == "[!! scenario colors !!]"
        assert held["encoding"]["y"]["field"] == "[!! inputs.sunlight !!]"
        assert held["width"] == "[!! size !!]"
        assert held["title"] == 'Sun in "[!! season !!]"'

    def test_a_spec_with_no_chip_standing_on_its_own_is_itself(self):
        from utk_curio.backend.app.execution.code_references import with_chip_placeholders

        assert with_chip_placeholders('{"mark": "bar"}') == '{"mark": "bar"}'
        assert with_chip_placeholders('{"title": "[!! season !!]"}') == '{"title": "[!! season !!]"}'
