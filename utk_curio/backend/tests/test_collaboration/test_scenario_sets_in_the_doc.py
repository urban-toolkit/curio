"""A dataflow's scenario sets in its doc (``collaboration/doc_mapping.py``,
``collaboration/dataflow_docs.py``).

The doc holds each set by its id, as it holds each scenario, so two tabs that
change different sets at once both land. Every scenario the doc holds is in a
set, with its context and outcomes, as the canvas writes them: a backend
writer's change is normalized as it is written (``dataflow_docs._write``), and
so is a doc built from a file saved before sets.
"""

from __future__ import annotations

import copy

from .test_dataflow_docs import SPEC, room  # noqa: F401 - room is a fixture

#: Two scenarios in two sets, beside two nodes.
DATAFLOW = {
    "nodes": [{"id": "n", "type": "t"}, {"id": "m", "type": "t"}],
    "edges": [],
    "scenarios": [
        {"id": "a", "name": "Heights", "color": "#4477aa", "nodes": ["n"], "set": "set-a", "context": [], "outcomes": []},
        {"id": "b", "name": "Roofs", "color": "#228833", "nodes": ["m"], "set": "set-b", "context": [], "outcomes": []},
    ],
    "scenarioSets": [{"id": "set-a", "name": "Tall towers"}, {"id": "set-b", "name": "Green roofs"}],
}


def _without_sets(spec: dict) -> dict:
    """*spec* with its scenarios as a dataflow saved before sets holds them."""
    out = copy.deepcopy(spec)
    out["dataflow"].pop("scenarioSets", None)
    for scenario in out["dataflow"].get("scenarios") or []:
        for key in ("set", "context", "outcomes"):
            scenario.pop(key, None)
    return out


def test_the_doc_holds_each_scenario_set_by_its_id():
    from pycrdt import Map

    from utk_curio.backend.app.collaboration import doc_mapping

    doc = doc_mapping.new_doc()
    doc_mapping.dataflow_to_doc(copy.deepcopy(DATAFLOW), doc, doc_id="sets")
    assert sorted(doc.get("scenarioSets", type=Map).keys()) == ["set-a", "set-b"]
    assert doc_mapping.doc_to_dataflow(doc)["scenarioSets"] == DATAFLOW["scenarioSets"]


def test_a_writers_scenarios_land_in_sets_on_the_doc_and_the_file(room):
    """A writer that saves a scenario with no set: the doc and the file hold
    it in a set the dataflow lists, with the context and outcomes it reads."""
    from utk_curio.backend.app.collaboration.dataflow_docs import by_agent, live, write

    alice = room.tab("alice")
    alice.sync()
    spec = live(room.owner_key, room.project_id)
    spec["dataflow"]["scenarios"] = [{"id": "s2", "name": "Charted", "color": "#228833", "nodes": ["chart"]}]
    spec["dataflow"].pop("scenarioSets", None)

    write(room.owner_key, room.project_id, spec, by_agent("agent.curio.dataflow-builder@1", room.owner_key, "plan"))

    for where, dataflow in (("the doc", alice.dataflow()), ("the file", room.on_disk()["dataflow"])):
        (scenario,) = dataflow["scenarios"]
        assert (scenario["set"], scenario["context"], scenario["outcomes"]) == ("set-s2", ["loader"], []), where
        assert dataflow["scenarioSets"] == [{"id": "set-s2", "name": "Shared"}], where


def test_a_doc_built_from_a_file_saved_before_sets_holds_its_scenarios_in_sets(room):
    room.write_elsewhere(_without_sets(SPEC))
    alice = room.tab("alice")
    alice.sync()
    (scenario,) = alice.dataflow()["scenarios"]
    assert (scenario["set"], scenario["context"], scenario["outcomes"]) == ("set-s1", [], ["chart"])
    assert alice.dataflow()["scenarioSets"] == [{"id": "set-s1", "name": "Shared"}]
