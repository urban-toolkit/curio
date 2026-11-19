"""A Spatial Join saved before its join was code reads as one made now.

The cases in ``src/contracts/savedSpatialJoin.cases.json`` run through
``projects/saved_joins.converted_node``, as ``src/tests/contracts/
savedSpatialJoinCases.test.ts`` runs them through the canvas's twin, and the
reads of a dataflow's spec file give every saved join converted, so a run, an
agent or a dashboard reads one as the canvas does. The file itself is left as
it is until its dataflow is next written.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
CONTRACTS = REPO / "utk_curio" / "frontend" / "urban-workflows" / "src" / "contracts"
BUILTIN = REPO / "packages" / "curio.builtin@1"
CASES = json.loads((CONTRACTS / "savedSpatialJoin.cases.json").read_text(encoding="utf-8"))["cases"]


def _shared() -> dict:
    return json.loads((CONTRACTS / "savedSpatialJoin.json").read_text(encoding="utf-8"))


def _expected(case: dict) -> dict:
    """A case's converted node, its ``<code>`` the template's code and each of
    its widgets the template's of its place."""
    converted = case["converted"]
    if converted.get("content") != "<code>":
        return converted
    shared = _shared()
    metadata = dict(converted["metadata"])
    metadata["widgets"] = [{**shared["widgets"][k], **given} for k, given in enumerate(metadata["widgets"])]
    return {**converted, "content": shared["code"], "metadata": metadata}


def test_the_contract_holds_the_templates_code_and_widgets():
    manifest = json.loads((BUILTIN / "manifest.json").read_text(encoding="utf-8"))
    template = next(t for t in manifest["templates"] if t["id"] == "spatial-join")
    shared = _shared()
    assert shared["nodeType"] == f"{manifest['id']}/{template['id']}"
    assert shared["widgets"] == template["widgets"]
    assert shared["code"] == (BUILTIN / template["source"]).read_text(encoding="utf-8")
    assert shared["setting"] == "spatialJoin"
    assert shared["widgetOf"] == {"predicate": "operation", "output": "output"}


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_each_case_reads_as_its_cases_file_says(case):
    from utk_curio.backend.app.projects import saved_joins

    node = copy.deepcopy(case["node"])
    converted = saved_joins.converted_node(node)
    assert converted == _expected(case)
    # The node it was given is left as it is, and a converted node converts no further.
    assert node == case["node"]
    assert saved_joins.is_saved_join(converted) is False
    assert saved_joins.converted_node(converted) == converted


def test_a_dataflow_with_no_saved_join_is_read_as_it_is():
    """Nothing is copied when nothing is converted: the reads of every
    dataflow pass through the conversion."""
    from utk_curio.backend.app.projects import saved_joins

    spec = {"dataflow": {"nodes": [case["node"] for case in CASES if case["converted"].get("content") != "<code>"]}}
    assert saved_joins.converted_spec(spec) is spec
    assert saved_joins.converted_dataflow(spec["dataflow"]) is spec["dataflow"]
    for odd in (None, {}, {"dataflow": None}, {"dataflow": {"nodes": "none"}}):
        assert saved_joins.converted_spec(odd) is odd


def _saved_on_main() -> dict:
    """A dataflow saved before the join had code: two loaders, and a join of
    them set to within and counts, with no code."""
    return {
        "dataflow": {
            "nodes": [
                {"id": "points", "type": "curio.builtin/data-loading", "content": "return 1\n"},
                {"id": "zones", "type": "curio.builtin/data-loading", "content": "return 2\n"},
                {"id": "join", "type": "curio.builtin/spatial-join", "content": "", "goal": "",
                 "metadata": {"keywords": [], "spatialJoin": {"predicate": "within", "output": "counts"}}},
            ],
            "edges": [
                {"id": "e1", "source": "points", "target": "join", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e2", "source": "zones", "target": "join", "sourceHandle": "out", "targetHandle": "in_1"},
            ],
            "name": "Saved on main",
        },
    }


def _join(spec: dict) -> dict:
    return next(node for node in spec["dataflow"]["nodes"] if node["id"] == "join")


def test_every_read_of_a_spec_file_reads_a_saved_join_with_its_code_and_settings(tmp_curio):
    """``read_spec`` (every reader of a dataflow no tab opened: a run, an
    agent, a dashboard) and ``read_spec_file`` (what an open dataflow's doc is
    built from) both read the join with its code and its settings in its two
    widgets; the file on disk is as it was written."""
    from utk_curio.backend.app.projects import storage

    storage.write_spec("4242", "saved-on-main", _saved_on_main())
    shared = _shared()
    for spec in (storage.read_spec("4242", "saved-on-main"), storage.read_spec_file("4242", "saved-on-main").spec):
        join = _join(spec)
        assert join["content"] == shared["code"]
        assert join["metadata"] == {
            "keywords": [],
            "widgets": [{**shared["widgets"][0], "value": "within"}, {**shared["widgets"][1], "value": "counts"}],
        }
        assert [n["id"] for n in spec["dataflow"]["nodes"]] == ["points", "zones", "join"]
    on_disk = json.loads((storage.project_dir("4242", "saved-on-main") / storage.SPEC_FILE).read_text(encoding="utf-8"))
    assert _join(on_disk)["metadata"]["spatialJoin"] == {"predicate": "within", "output": "counts"}


def test_a_run_reads_the_saved_join_as_code_with_its_saved_operation(tmp_curio):
    """What a run on the server parses (``parse_workflow_dict``) from the read:
    the join is code, and its code calls ``spatial_join`` with the saved
    operation and output, on input_0 by its port ``in`` and input_1 by ``in_1``."""
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict
    from utk_curio.backend.app.projects import storage

    storage.write_spec("4242", "saved-on-main", _saved_on_main())
    spec = parse_workflow_dict(storage.read_spec("4242", "saved-on-main"))
    join = next(node for node in spec.nodes if node.id == "join")
    assert join.category == "code" and join.engine == "python"
    assert spec.input_slots("join") == [0, 1]
    assert spec.node_code(join, "python").splitlines()[-1] == (
        'return spatial_join(input_0, input_1, operation="within", output="counts")'
    )
