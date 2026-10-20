"""The scenario comparison charts test dataflow: nine example tables, each
charted a different way to compare its scenarios (re-made from komar41's
ScenarioCharts in #914 on main's nodes).

``docs/examples/dataflows/scenario-comparison-charts.json`` loads each example
table from the Data Catalog, keeps each scenario's rows in a Data
Transformation node whose Case widget picks them, and stacks them in a Compare
Scenarios node. The chart is the Compare node's own preset where one draws it
(grouped bars, a table), else a node of the Scout package
(``curio.scout@1``) after it: a Vega-Lite chart whose spec is its
template's, unchanged, and whose widgets name the columns it plots. No chart
names a scenario or a color: it draws them as its Compare node labels them.
The tables are ``datasets/data.curio.example-*@1``, which the seeded script
``scripts/build_example_scenario_charts.py`` writes.

Every file is read inside its test, so a checkout without them fails test by
test rather than at collection. The Python nodes run here as the sandbox runs
a node; ``test_frontend/test_scenario_comparison_charts_e2e.py`` runs the whole
dataflow in the browser.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import re
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DATAFLOW = REPO_ROOT / "docs" / "examples" / "dataflows" / "scenario-comparison-charts.json"
SCRIPT = REPO_ROOT / "scripts" / "build_example_scenario_charts.py"
COMPARE_DIR = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "compare"
BUILTIN_MANIFEST = REPO_ROOT / "packages" / "curio.builtin@1" / "manifest.json"
#: The package whose templates draw the charts no preset draws.
COMPARISON_DIR = "curio.scout@1"
COMPARISON = REPO_ROOT / "packages" / COMPARISON_DIR

LOAD = "curio.builtin/data-loading"
KEEP = "curio.builtin/data-transformation"
COMPARE = "curio.builtin/compare-scenarios"

STORMS = ["10-year storm", "50-year storm", "100-year storm"]

#: Each example table's chart: its scenarios in the Compare node's circle
#: order, the Compare node's preset, and the Scout template whose
#: node after it draws the chart, for a form no preset draws (None: the preset
#: is the chart).
CHARTS = {
    "data.curio.example-pedestrians-by-hour": (["Weekday", "Weekend"], "table", "lines-with-band"),
    "data.curio.example-flood-damage-curves": (["As built", "Floodproofed"], "table", "curves-by-group"),
    "data.curio.example-street-flooding": (STORMS, "table", "bars-with-error-bars"),
    "data.curio.example-peak-depths": (STORMS, "table", "ensemble-strips"),
    "data.curio.example-trips-by-mode": (["Today", "Bus lanes", "Bike network", "Car-free center"], "grouped-bar", None),
    "data.curio.example-building-carbon": (["Concrete frame", "Timber frame"], "table", "stacked-bars-with-totals"),
    "data.curio.example-park-shade": (["Open lawn", "Tree canopy"], "table", "donuts"),
    "data.curio.example-bike-route-factors": (["Route A", "Route B", "Route C"], "table", "weighted-matrix"),
    "data.curio.example-green-roofs": (["Extensive roof", "Semi-intensive roof", "Intensive roof"], "table", None),
}
DATASETS = list(CHARTS)
CHARTED = [dataset_id for dataset_id, (_names, _preset, template) in CHARTS.items() if template]
#: The seven chart nodes' types, one per template.
CHART_TYPES = {f"curio.scout/{CHARTS[dataset_id][2]}" for dataset_id in CHARTED}

#: What a reference chip looks like (``[!! y !!]``).
CHIP = re.compile(r"\[!!\s*(.*?)\s*!!\]")

#: The most the nine tables and their manifests may weigh together, the share
#: of the ``datasets/`` size check this example has (owner, step 19 of the
#: #914 plan).
BUDGET_BYTES = 105 * 1024

#: A node's size when neither it nor its template sets one (NodeContainer's).
NODE_SIZE = (525, 350)
#: How far a scenario's frame reaches past its nodes (``ScenarioLayers.tsx``).
FRAME_PAD = 18


def _flow() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]


def _of_type(flow: dict, node_type: str) -> list:
    return [node for node in flow["nodes"] if node["type"] == node_type]


def _circle(handle) -> int:
    return 0 if handle in (None, "in") else int(str(handle).split("_")[1])


def _inputs(flow: dict, node_id: str) -> list:
    """``(circle, source node id)`` for each edge into *node_id*, in circle order."""
    return sorted((_circle(e.get("targetHandle")), e["source"]) for e in flow["edges"] if e["target"] == node_id)


def _targets(flow: dict, node_id: str) -> list:
    return [e["target"] for e in flow["edges"] if e["source"] == node_id]


def _dataset_read_by(node: dict) -> str:
    found = re.findall(r'curio_load_data\("([^"]+)"\)', node.get("content") or "")
    assert len(found) == 1, f"{node.get('title')} reads {found}"
    return found[0]


def _row(flow: dict, dataset_id: str) -> dict:
    """The table's row of the dataflow: its loader, its Data Transformation
    nodes in the Compare node's circle order, its Compare node and the
    Vega-Lite node after it, if any."""
    by_id = {node["id"]: node for node in flow["nodes"]}
    [loader] = [node for node in _of_type(flow, LOAD) if _dataset_read_by(node) == dataset_id]
    keeps = [by_id[target] for target in _targets(flow, loader["id"])]
    assert keeps and {node["type"] for node in keeps} == {KEEP}, loader["title"]
    compares = {target for keep in keeps for target in _targets(flow, keep["id"])}
    assert len(compares) == 1 and all(len(_targets(flow, keep["id"])) == 1 for keep in keeps), loader["title"]
    compare = by_id[compares.pop()]
    assert compare["type"] == COMPARE
    circles = dict((source, circle) for circle, source in _inputs(flow, compare["id"]))
    keeps.sort(key=lambda node: circles[node["id"]])
    after = _targets(flow, compare["id"])
    assert len(after) <= 1, f"{compare['title']} feeds {len(after)} nodes"
    return {
        "loader": loader,
        "keeps": keeps,
        "compare": compare,
        "chart": by_id[after[0]] if after else None,
    }


def _manifest(dataset_id: str) -> dict:
    return json.loads((REPO_ROOT / "datasets" / f"{dataset_id}@1" / "manifest.json").read_text(encoding="utf-8"))


def _table(dataset_id: str) -> list:
    folder = REPO_ROOT / "datasets" / f"{dataset_id}@1"
    with open(folder / _manifest(dataset_id)["dataFile"], newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# --- the example tables ------------------------------------------------------


@pytest.mark.parametrize("dataset_id", DATASETS)
def test_each_example_table_is_a_csv_dataset_curio_publishes_under_mit(dataset_id):
    manifest = _manifest(dataset_id)
    assert manifest["id"] == dataset_id
    assert manifest["format"] == "csv"
    assert (manifest["publisher"], manifest["license"]) == ("Curio", "MIT")
    assert manifest["name"].startswith("Example table: "), manifest["name"]
    description = manifest["description"]
    assert "example tables that illustrate ways to chart a comparison of scenarios" in description
    assert "scripts/build_example_scenario_charts.py" in description
    # The owner's word for them (#914): example tables, never invented ones.
    for word in ("invented", "mock", "made-up", "fake"):
        assert word not in description.lower() and word not in manifest["name"].lower(), word
    rows = _table(dataset_id)
    assert manifest["rowCount"] == len(rows)
    assert list(rows[0])[0] == "case"
    assert list(dict.fromkeys(row["case"] for row in rows)) == CHARTS[dataset_id][0]


def test_the_tables_are_what_the_seeded_script_writes(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("build_example_scenario_charts", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, script)
    spec.loader.exec_module(script)
    assert [table.dataset_id for table in script.TABLES] == DATASETS
    script.write(tmp_path)
    for dataset_id in DATASETS:
        written = tmp_path / "datasets" / f"{dataset_id}@1"
        committed = REPO_ROOT / "datasets" / f"{dataset_id}@1"
        names = sorted(path.relative_to(written).as_posix() for path in written.rglob("*") if path.is_file())
        assert names == sorted(path.relative_to(committed).as_posix() for path in committed.rglob("*") if path.is_file())
        for name in names:
            assert (written / name).read_bytes() == (committed / name).read_bytes(), (
                f"datasets/{dataset_id}@1/{name} is not what {SCRIPT.name} writes: run it again"
            )


def test_the_nine_tables_and_their_manifests_fit_their_budget():
    sizes = {
        path.relative_to(REPO_ROOT).as_posix(): path.stat().st_size
        for dataset_id in DATASETS
        for path in (REPO_ROOT / "datasets" / f"{dataset_id}@1").rglob("*")
        if path.is_file()
    }
    assert len(sizes) == 2 * len(DATASETS), sorted(sizes)
    assert sum(sizes.values()) <= BUDGET_BYTES, sizes


# --- the dataflow ------------------------------------------------------------


def test_each_table_has_a_row_that_loads_keeps_compares_and_charts_it():
    flow = _flow()
    assert flow["name"] == "Nine ways to chart scenario comparisons"
    # Each chart no preset draws is one of Scout's seven charts.
    assert len(CHART_TYPES) == 7
    assert Counter(node["type"] for node in flow["nodes"]) == {
        LOAD: 9, KEEP: 24, COMPARE: 9, **{chart_type: 1 for chart_type in CHART_TYPES},
    }
    assert len(flow["edges"]) == 55
    assert sorted(_dataset_read_by(node) for node in _of_type(flow, LOAD)) == sorted(DATASETS)
    for dataset_id in DATASETS:
        row = _row(flow, dataset_id)
        names, _preset, template = CHARTS[dataset_id]
        assert len(row["keeps"]) == len(names)
        assert [circle for circle, _source in _inputs(flow, row["compare"]["id"])] == list(range(len(names)))
        assert (row["chart"] is not None) == bool(template), dataset_id


def test_the_dataflow_declares_the_datasets_it_reads_as_the_backend_writes_them():
    flow = _flow()
    used = {dataset_id for node in flow["nodes"]
            for dataset_id in re.findall(r'curio_load_data\("([^"]+)"\)', node.get("content") or "")}
    refs = flow["datasets"]
    assert sorted(ref["datasetId"] for ref in refs) == sorted(used) == sorted(DATASETS)
    for ref in refs:
        assert set(ref) == {"datasetId", "dirName", "origin", "producerNodeId", "consumerNodeIds", "installedAt"}
        assert ref["dirName"] == f"{ref['datasetId']}@1"
        assert (ref["origin"], ref["producerNodeId"], ref["consumerNodeIds"]) == ("imported", None, [])
        assert ref["installedAt"]
        assert (REPO_ROOT / "datasets" / ref["dirName"] / "manifest.json").is_file()
    # The package of its seven charts, which the stack installs with the
    # examples because the dataflow declares it.
    assert flow["packages"] == [COMPARISON_DIR]
    assert (COMPARISON / "manifest.json").is_file()
    assert not re.search(r"https?://(?!vega\.github\.io/schema/)", json.dumps(flow["nodes"])), (
        "a node reads from the network"
    )


def test_21_scenarios_each_keep_their_rows_with_a_case_widget():
    flow = _flow()
    scenarios = flow["scenarios"]
    assert len(scenarios) == 21
    scenario_of = {}
    for scenario in scenarios:
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", scenario["color"]), scenario
        for node_id in scenario["nodes"]:
            assert node_id not in scenario_of, f"{node_id} is in two scenarios"
            scenario_of[node_id] = scenario
    assert set(scenario_of) == {node["id"] for node in _of_type(flow, KEEP)}
    assert sorted(s["name"] for s in scenarios) == sorted({n for names, _p, _c in CHARTS.values() for n in names})
    for dataset_id in DATASETS:
        names = CHARTS[dataset_id][0]
        keeps = _row(flow, dataset_id)["keeps"]
        first = keeps[0]
        for circle, keep in enumerate(keeps):
            scenario = scenario_of[keep["id"]]
            assert scenario["name"] == names[circle]
            [widget] = keep["metadata"]["widgets"]
            assert (widget["name"], widget["type"]) == ("case", "choice")
            assert widget["options"]["choices"] == names
            assert widget.get("value", widget["default"]) == scenario["name"]
            # The lever is the widget: every scenario's node runs the same code.
            assert keep["content"] == first["content"] and "[!! case !!]" in keep["content"]
            if circle == 0:
                assert "value" not in widget and "copiedFrom" not in keep["metadata"]
            else:
                # Its lineage pairs it with the first scenario's in What differs.
                assert keep["metadata"]["copiedFrom"] == [first["id"]]
    for scenario in scenarios:
        compares = {_targets(flow, node_id)[0] for node_id in scenario["nodes"]}
        if scenario["name"] in STORMS:
            # A storm's ensemble feeds two charts: its node of each table.
            assert (len(scenario["nodes"]), len(compares)) == (2, 2), scenario["name"]
        else:
            assert len(scenario["nodes"]) == 1, scenario["name"]


def _stack_code(inputs) -> str:
    """The code a Compare Scenarios node writes for its ``(circle, label)``
    inputs (``utils/compare/compareCode.ts``)."""
    lines = [
        "# Compare Scenarios writes this code from its inputs: each input, under the",
        "# id and the name of its scenario. It is written again when they change.",
    ]
    if not inputs:
        return "\n".join([*lines, "return curio_stack_scenarios([])", ""])
    lines.append("return curio_stack_scenarios([")
    for circle, label in inputs:
        scenario = json.dumps(label["scenario"], ensure_ascii=False) if label.get("scenario") else "None"
        lines.append(f"    ({scenario}, {json.dumps(label['name'], ensure_ascii=False)}, [!! input_{circle} !!]),")
    lines.append("])")
    return "\n".join(lines) + "\n"


def test_the_code_written_here_is_the_code_the_node_writes():
    """``_stack_code`` against the cases the frontend's writer is pinned to,
    so the check below cannot drift from the node."""
    cases = json.loads((COMPARE_DIR / "compareCode.cases.json").read_text(encoding="utf-8"))["cases"]
    assert cases
    for case in cases:
        inputs = [(entry["slot"], entry["label"]) for entry in case["inputs"]]
        assert _stack_code(inputs) == case["code"], case["name"]


def test_each_compare_node_is_labelled_and_coded_for_its_inputs():
    """Its labels and its code are what the node writes for its inputs, so a
    load writes nothing again and the dataflow opens unchanged."""
    flow = _flow()
    scenario_of = {node_id: scenario for scenario in flow["scenarios"] for node_id in scenario["nodes"]}
    for dataset_id in DATASETS:
        names, preset, _template = CHARTS[dataset_id]
        compare = _row(flow, dataset_id)["compare"]
        labels = [
            {"scenario": scenario_of[source]["id"], "name": scenario_of[source]["name"],
             "color": scenario_of[source]["color"]}
            for _circle, source in _inputs(flow, compare["id"])
        ]
        assert [label["name"] for label in labels] == names
        settings = compare["metadata"]["compareScenarios"]
        assert settings["inputs"] == labels
        assert settings["mode"] == "chart"
        assert compare["content"] == _stack_code(list(enumerate(labels)))
        # Always a preset of its own, so the Chart tab never picks one.
        assert settings["chart"]["preset"] == preset
        if preset == "grouped-bar":
            assert settings["chart"] == {"preset": "grouped-bar", "x": "mode", "y": "daily_trips", "aggregate": "none"}


def test_every_chart_is_drawn_from_a_compare_node():
    """Nine charts: Scout's seven charts, each fed by one Compare node
    and nothing else, and two Compare nodes whose own preset is the chart."""
    flow = _flow()
    by_id = {node["id"]: node for node in flow["nodes"]}
    charts = [node for node in flow["nodes"] if node["type"] in CHART_TYPES]
    assert len(charts) == 7
    for chart in charts:
        assert [by_id[source]["type"] for _circle, source in _inputs(flow, chart["id"])] == [COMPARE]
        assert _targets(flow, chart["id"]) == []
    drawn_by = {}
    for dataset_id in DATASETS:
        row = _row(flow, dataset_id)
        _names, preset, template = CHARTS[dataset_id]
        if template:
            assert row["chart"]["type"] == f"curio.scout/{template}", dataset_id
            drawn_by[dataset_id] = "Scout"
        else:
            assert row["chart"] is None, dataset_id
            drawn_by[dataset_id] = preset
    assert Counter(drawn_by.values()) == {"Scout": 7, "grouped-bar": 1, "table": 1}


def _template(template_id: str) -> dict:
    manifest = json.loads((COMPARISON / "manifest.json").read_text(encoding="utf-8"))
    (template,) = [t for t in manifest["templates"] if t["id"] == template_id]
    return template


def _stacked_columns(dataset_id: str) -> list:
    """The columns of the table the table's Compare node stacks: the
    scenario's id and name, then the table's own but its case."""
    return ["scenario", "scenario_name", *[column for column in _table(dataset_id)[0] if column != "case"]]


@pytest.mark.parametrize("dataset_id", CHARTED)
def test_each_chart_is_its_templates_spec_with_the_columns_in_its_widgets(dataset_id):
    """The node's spec is its template's starter, byte for byte, so every
    chart of a kind is one spec; what differs is in its widgets: the
    template's own, in its order, each column one set to a column the Compare
    node's table has, Donuts' highlight to a value of its part column, and a
    title or a format set or left empty."""
    row = _row(_flow(), dataset_id)
    template = _template(CHARTS[dataset_id][2])
    chart = row["chart"]
    assert chart["content"] == (COMPARISON / template["source"]).read_text(encoding="utf-8")
    widgets = chart["metadata"]["widgets"]
    assert [{key: w[key] for key in w if key != "value"} for w in widgets] == template["widgets"]
    values = {w["name"]: w.get("value", w["default"]) for w in widgets}
    columns = _stacked_columns(dataset_id)
    for widget in widgets:
        name = widget["name"]
        if re.fullmatch(r".*_(title|format)", name):
            assert isinstance(values[name], str), widget
        elif name == "highlight":
            assert values[name] in {r[values["part"]] for r in _table(dataset_id)}, widget
        else:
            assert "value" in widget, f"{chart['title']}: {name} is left at its default"
            assert values[name] in columns, f"{chart['title']}: {name} = {values[name]!r}, not in {columns}"
    assert set(CHIP.findall(chart["content"])) == {w["name"] for w in widgets}


@pytest.mark.parametrize("dataset_id", CHARTED)
def test_no_chart_names_a_scenario_or_a_scenario_color(dataset_id):
    """The chart draws its scenarios as its Compare node labels them: the
    spec and the widgets name no scenario and no scenario's color, so one
    renamed or recolored is drawn as its box is (the e2e test recolors one of
    each chart's)."""
    flow = _flow()
    chart = _row(flow, dataset_id)["chart"]
    written = chart["content"] + json.dumps(chart["metadata"]["widgets"])
    for scenario in flow["scenarios"]:
        assert scenario["name"] not in written, f"{chart['title']} names {scenario['name']}"
        assert scenario["color"].lower() not in written.lower(), f"{chart['title']} writes {scenario['color']}"


def _python_output(target: str):
    """What the Python node *target* returns, run with the nodes above it as
    the sandbox runs a node: chips and widgets resolved as a server run
    resolves them, and ``input_k`` bound by circle."""
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.catalog_helpers import read_dataset
    from utk_curio.sandbox.util.input_names import call_as_node
    from utk_curio.sandbox.util.scenario_stack import stack_scenarios

    flow = _flow()
    nodes = {node["id"]: node for node in flow["nodes"]}

    def load_data(dataset_id):
        folder = REPO_ROOT / "datasets" / f"{dataset_id}@1"
        manifest = _manifest(dataset_id)
        return read_dataset(str(folder / manifest["dataFile"]), manifest["format"])

    done: dict = {}

    def output(node_id):
        if node_id in done:
            return done[node_id]
        node = nodes[node_id]
        wired = _inputs(flow, node_id)
        circles = [circle for circle, _source in wired]
        code, problems = resolve_references(
            node["content"], widgets=(node.get("metadata") or {}).get("widgets") or [],
            language="python", inputs=[{"slot": circle} for circle in circles],
        )
        assert not problems, f"{node.get('title')}: {problems}"
        values = [output(source) for _circle, source in wired]
        value = values[0] if len(values) == 1 else (values or None)
        scope = {"curio_load_data": load_data, "curio_stack_scenarios": stack_scenarios}
        done[node_id] = call_as_node(textwrap.indent(code, "    "), scope, value, circles or None)
        return done[node_id]

    return output(target)


@pytest.mark.parametrize("dataset_id", DATASETS)
def test_the_rows_stack_under_their_scenarios_and_the_chart_reads_columns_they_have(dataset_id):
    from utk_curio.backend.app.agents.domain.document_validation import STATUS_VALID, validate_vega_lite

    row = _row(_flow(), dataset_id)
    stacked = _python_output(row["compare"]["id"])
    labels = row["compare"]["metadata"]["compareScenarios"]["inputs"]
    assert list(dict.fromkeys(zip(stacked["scenario"], stacked["scenario_name"]))) == [
        (label["scenario"], label["name"]) for label in labels
    ]
    table = _table(dataset_id)
    assert stacked["scenario_name"].value_counts().to_dict() == dict(Counter(r["case"] for r in table))
    assert list(stacked.columns) == ["scenario", "scenario_name", *[c for c in table[0] if c != "case"]]
    chart = row["compare"]["metadata"]["compareScenarios"]["chart"]
    for key in ("x", "y"):
        if key in chart:
            assert chart[key] in stacked.columns, chart
    if row["chart"] is not None:
        # The spec as a run draws it: its chips given the widgets' values.
        from utk_curio.backend.app.execution.code_references import resolve_references

        spec, problems = resolve_references(
            row["chart"]["content"], widgets=row["chart"]["metadata"]["widgets"], language="json",
            inputs=[{"slot": 0}],
        )
        assert not problems and not CHIP.search(spec), problems
        result = validate_vega_lite(spec, columns=list(stacked.columns))
        assert result.get("status") == STATUS_VALID, result


def _box(node: dict, sizes: dict) -> tuple:
    width, height = sizes.get(node["type"].split("@")[0], NODE_SIZE)
    width, height = node.get("width", width), node.get("height", height)
    return node["x"], node["y"], node["x"] + width, node["y"] + height


def _overlap(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_no_two_nodes_overlap_and_each_scenario_frame_holds_only_its_own_nodes():
    """A storm's frame reaches over both its rows, so the rows stand one under
    the other and its nodes in one column."""
    manifest = json.loads(BUILTIN_MANIFEST.read_text(encoding="utf-8"))
    sizes = {
        f"{manifest['id']}/{template['id']}": (template["containerStyle"]["nodeWidth"],
                                                template["containerStyle"]["nodeHeight"])
        for template in manifest["templates"]
        if (template.get("containerStyle") or {}).get("nodeWidth")
    }
    flow = _flow()
    boxes = {node["id"]: _box(node, sizes) for node in flow["nodes"]}
    ids = list(boxes)
    for index, one in enumerate(ids):
        for other in ids[index + 1:]:
            assert not _overlap(boxes[one], boxes[other]), (one, other)
    for scenario in flow["scenarios"]:
        members = [boxes[node_id] for node_id in scenario["nodes"]]
        frame = (
            min(box[0] for box in members) - FRAME_PAD, min(box[1] for box in members) - FRAME_PAD,
            max(box[2] for box in members) + FRAME_PAD, max(box[3] for box in members) + FRAME_PAD,
        )
        inside = [node_id for node_id in ids if node_id not in scenario["nodes"] and _overlap(frame, boxes[node_id])]
        assert not inside, f"{scenario['name']}'s frame covers {inside}"
