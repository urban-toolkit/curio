"""``execution/save_policy.py`` decides as ``utils/saveOutputDataset.ts`` does.

Both sides run the cases in ``saveOutputDataset.cases.json`` beside the
TypeScript (``src/tests/utils/saveOutputDatasetCases.test.ts`` is the other
half). Here each case's node is built the way a saved dataflow holds it:
``saveOutputDataset`` on the node, ``datasetSource`` under ``metadata``.

``save_policy`` is imported inside each test, so a checkout without it fails
each test on its own instead of failing the whole collection.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CASES_FILE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "utils" / "saveOutputDataset.cases.json"
)


def _cases():
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


def _saved_node(case: dict) -> dict:
    spec = case["node"]
    node = {"id": "n", "type": spec["nodeType"], "content": ""}
    if "saveOutputDataset" in spec:
        node["saveOutputDataset"] = spec["saveOutputDataset"]
    if spec.get("datasetSource"):
        node["metadata"] = {"datasetSource": {"datasetId": "data.curio.example"}}
    return node


@pytest.mark.parametrize("case", _cases())
def test_a_run_installs_the_output_when_the_canvas_would(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.execution import save_policy

    node = _saved_node(case)
    got = save_policy.should_save_output_on_run(
        node, case["defaultSave"], case["dashboardSource"],
    )
    assert got is case["onRun"]


@pytest.mark.parametrize("case", _cases())
def test_a_run_records_the_output_when_the_canvas_would(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.execution import save_policy

    node = _saved_node(case)
    sources = {"n"} if case["dashboardSource"] else set()
    got = save_policy.records_output_on_save(node, case["defaultSave"], sources)
    assert got is case["recorded"]


def test_the_cases_cover_every_rule():
    """A case file that lost the rows that tell the two decisions apart would
    let the twins drift with every case still green."""
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    pairs = {(c["onRun"], c["recorded"]) for c in cases}
    assert pairs == {(False, False), (True, True), (False, True), (True, False)}
    assert any(c["node"].get("datasetSource") for c in cases)
    assert any("vis-" in c["node"]["nodeType"] for c in cases)
    assert any(c["node"]["nodeType"].endswith("@1") for c in cases)


def test_the_default_comes_from_the_launch_setting(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.execution import save_policy

    node = {"id": "n", "type": "curio.builtin/computation-analysis"}
    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", True)
    assert save_policy.should_save_output_on_run(node) is True
    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    assert save_policy.should_save_output_on_run(node) is False
