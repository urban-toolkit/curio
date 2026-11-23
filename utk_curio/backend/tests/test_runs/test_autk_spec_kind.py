"""What a run on the server does with an Autark node: by the canvas's rule.

``execution/autk_spec_kind`` runs the cases in ``utils/autkSpecKind.cases.json``,
which ``src/tests/utils/autkSpecKindCases.test.ts`` runs through the canvas's
own ``classifyAutkSpecString`` and ``isPassThroughNode``. Each case says the
role a run gives its node: a run runs a node whose document only loads data,
forwards one that only draws its input, and leaves the rest to the browser, a
node that draws and also loads or computes among them.
``autk_spec_kind`` and ``run_plan`` are imported inside each test, so a
checkout without them fails each test on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CASES_FILE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "utils" / "autkSpecKind.cases.json"
)


def _cases():
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


@pytest.mark.parametrize("case", _cases())
def test_a_document_has_the_kind_the_canvas_gives_it(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.execution.autk_spec_kind import classify_autk_spec_string

    assert classify_autk_spec_string(case["spec"]) == case["kind"]


@pytest.mark.parametrize("case", _cases())
@pytest.mark.parametrize("node_type", ["curio.builtin/autk-grammar", "curio.builtin/autk-grammar@1"])
def test_a_run_runs_only_the_autark_nodes_that_only_load_data(case, node_type):
    """And forwards only those that only draw their input: the role each case says."""
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.execution.run_plan import node_role

    node = {"id": "n", "type": node_type, "content": case["spec"]}
    assert node_role(node) == case["role"]


def test_a_data_section_in_another_kind_of_node_is_not_an_autark_load():
    from utk_curio.backend.app.execution.autk_spec_kind import is_autk_data_node

    content = json.dumps({"data": [{"type": "osm"}]})
    assert is_autk_data_node({"id": "n", "type": "curio.builtin/autk-grammar", "content": content})
    assert not is_autk_data_node({"id": "n", "type": "curio.builtin/vis-vega", "content": content})
    assert not is_autk_data_node({"id": "n", "type": None, "content": content})
    assert not is_autk_data_node({"id": "n", "type": "curio.builtin/autk-grammar"})


SECTION_INPUTS_FILE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "adapters" / "node" / "autkSectionInputs.cases.json"
)


def _section_cases():
    if not SECTION_INPUTS_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(SECTION_INPUTS_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


@pytest.mark.parametrize("case", _section_cases())
def test_a_data_section_reads_the_tables_of_its_input_the_canvas_finds(case):
    """``section_input_tables`` runs ``autkSectionInputs.cases.json``, which
    ``src/tests/adapters/node/autkInputTables.test.ts`` runs through the
    node's own ``sectionInputTables``; a node that reads one runs on its input."""
    assert case is not None, f"{SECTION_INPUTS_FILE} is missing"
    from utk_curio.backend.app.execution.autk_spec_kind import reads_input_tables, section_input_tables

    assert section_input_tables(case["spec"]) == case["reads"]
    node = {"id": "n", "type": "curio.builtin/autk-grammar", "content": json.dumps(case["spec"])}
    assert reads_input_tables(node) == bool(case["reads"])


def test_a_chip_that_stands_for_a_table_names_one_of_the_input():
    """A chip standing on its own in a document names what the input carries,
    read before it is resolved: a node whose heatmap bins one runs on its input."""
    from utk_curio.backend.app.execution.autk_spec_kind import reads_input_tables

    content = ('{"data": [{"type": "heatmap", "joinDataRef": [!! input_0 !!], "outputTableName": "density", '
               '"near": {"distance": 200}, "grid": {"rows": 2, "columns": 2}}]}')
    assert reads_input_tables({"id": "n", "type": "curio.builtin/autk-grammar", "content": content})
