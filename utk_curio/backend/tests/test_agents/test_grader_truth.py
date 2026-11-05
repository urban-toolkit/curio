"""The grader truth: answers to the skills' test cases whose grade is known, read and held to Curio's own checks.

``agents/evaluation/grader_truth.py`` reads each skill's ``evals/truth.json``:
for each test case, a golden answer, which passes every assertion, and
mutants, each failing the assertions it names; or a gap, where no shipped
example or test can answer the case. A grader's agreement with them is
measured on every assertion, and on a checked one its case's checks
(``checks.py``) decide it exactly. So these hold the truth to them:

- every shipped skill holds its truth, and each case a golden answer or a gap;
- every golden answer passes each check of its case, read from a run folder
  the answer is written into, as ``benchmark._final`` reads a run's;
- every mutant fails exactly the checked assertions it names, and passes its
  case's other checks;
- a document a golden answer writes passes Curio's own check of it, through
  the reader the runtime uses: the document check of a Vega-Lite or Autark
  node, the Map Editor node's reader, the plan grammar;
- each ``refused-`` mutant's planted output is refused by the check its source
  names, which passes the golden answer's;
- the shapes the reader holds an answer to are the ones the worker writes.

No model is called. New names are read inside each test, so this module
imports on a checkout without them and each test fails on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
VEGA = "curio.builtin/vis-vega"
AUTK = "curio.builtin/autk-grammar"
EDIT = "curio.builtin/edit-features"


def _grader_truth():
    from utk_curio.backend.app.agents.evaluation import grader_truth

    return grader_truth


def _checks():
    from utk_curio.backend.app.agents.evaluation import checks

    return checks


def _skill_evals():
    from utk_curio.backend.app.agents.evaluation import skill_evals

    return skill_evals


def _dv():
    from utk_curio.backend.app.agents.domain import document_validation

    return document_validation


def _shipped() -> list[tuple]:
    """Each shipped skill's evaluations and its grader truth."""
    grader_truth = _grader_truth()
    return [(evals, grader_truth.read(evals)) for evals in _skill_evals().shipped_evals()]


def _answers(kind: str | None = None) -> list[tuple]:
    """Each answer of the shipped truth, with its case: of *kind* when named."""
    found = []
    for evals, truth in _shipped():
        cases = {case.id: case for case in evals.cases}
        for answer in truth.answers if truth else ():
            if kind is None or answer.kind == kind:
                found.append((cases[answer.case], answer))
    return found


def _decided(case, answer, tmp_path: Path) -> dict:
    """What *case*'s checks decide of *answer*, written into a run folder and
    read back as ``benchmark._final`` reads a run's."""
    checks, skill_evals = _checks(), _skill_evals()
    folder = _grader_truth().write_outputs(answer, tmp_path / answer.skill / answer.key)
    context = case.context
    attached = context.node if context.target == skill_evals.NODE else None
    return checks.decided(case.checks, checks.RunRecord.of(folder, context.dataflow, attached))


def _written(answer, node_id: str | None = None) -> list[tuple]:
    """``(node id, node type, content)`` of each node the answer wrote: each
    node it added, and each node whose content it changed, as it is after."""
    nodes = answer.changes["changed"].get("nodes", {})
    found = [(n.get("id"), n.get("type"), n.get("content")) for n in nodes.get("added", [])]
    found += [(n.get("id"), n.get("type"), ((n.get("changes") or {}).get("content") or {}).get("after"))
              for n in nodes.get("changed", []) if "content" in (n.get("changes") or {})]
    return [(i, t, c) for i, t, c in found if isinstance(c, str) and c.strip() and (node_id is None or i == node_id)]


def _content(answer, node_id: str) -> str:
    [(_, _, content)] = _written(answer, node_id)
    return content


def _grammars() -> dict:
    """Each shipped template's grammar, by its type, as its manifest names it."""
    found = {}
    for path in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        package = path.parent.name.split("@", 1)[0]
        for template in manifest.get("templates") or []:
            if template.get("grammarId"):
                found[f"{package}/{template['id']}"] = template["grammarId"]
    return found


# --- The files ------------------------------------------------------------------------


def test_every_shipped_skill_holds_its_truth_and_every_case_a_golden_answer_or_a_gap():
    grader_truth = _grader_truth()
    shipped = _shipped()
    assert shipped, "no skill ships its evaluations"
    for evals, truth in shipped:
        assert truth is not None, f"{evals.name} holds no evals/{grader_truth.TRUTH_FILE}"
        gaps = {gap["case"] for gap in truth.gaps}
        for case in evals.cases:
            golden = truth.golden(case.id)
            assert (golden is None) == (case.id in gaps), (evals.name, case.id)
        for answer in truth.answers:
            assert answer.key == f"truth/eval-{answer.case}/{answer.name}"
            assert answer.source.strip(), (evals.name, answer.key)
    assert set(grader_truth.shipped()) == {evals.name for evals, _ in shipped}


def test_a_golden_answer_lands_every_call_it_makes():
    """A golden answer went through Curio's tools: none of its calls was
    refused, and every change it made has its card."""
    for case, answer in _answers("golden"):
        statuses = [(call["tool"], call["status"]) for call in answer.calls]
        assert not [s for s in statuses if s[1] in ("refused", "error")], (answer.skill, answer.key, statuses)


# --- The checks -----------------------------------------------------------------------


def test_every_golden_answer_passes_every_check_of_its_case(tmp_path):
    checked = 0
    for case, answer in _answers("golden"):
        decided = _decided(case, answer, tmp_path)
        assert all(decided.values()), (answer.skill, answer.key, decided)
        checked += len(decided)
    assert checked, "no golden answer's case holds a check"


def test_every_mutant_fails_exactly_its_checked_fails_and_passes_its_case_s_other_checks(tmp_path):
    mutants = _answers("mutant")
    assert mutants, "the truth holds no mutant"
    for case, answer in mutants:
        decided = _decided(case, answer, tmp_path)
        assert decided == {place: place not in answer.fails for place in decided}, (
            answer.skill, answer.key, answer.fails, decided)


# --- Curio's own checks ---------------------------------------------------------------


def _widgets(answer, case, node_id: str) -> list:
    """The widgets of *node_id* once the answer landed: an added node's own, else
    the ones the node holds in its case's dataflow."""
    for node in answer.changes["changed"].get("nodes", {}).get("added", []):
        if node.get("id") == node_id:
            return (node.get("metadata") or {}).get("widgets") or []
    if case.context.dataflow is None:
        return []
    nodes = json.loads(case.context.dataflow.read_text(encoding="utf-8"))["dataflow"]["nodes"]
    node = next((n for n in nodes if n.get("id") == node_id), {})
    return (node.get("metadata") or {}).get("widgets") or []


def test_a_document_a_golden_answer_writes_passes_curio_s_own_check_of_it():
    """The document check of a Vega-Lite or Autark node, its widgets' references
    resolved first as a run resolves them, the Map Editor node's reader, and the
    plan grammar a plan call is read with."""
    from utk_curio.backend.app.agents.domain import content, map_edits
    from utk_curio.backend.app.execution.code_references import resolve_references

    dv, grammars = _dv(), _grammars()
    held = 0
    for case, answer in _answers("golden"):
        for node_id, node_type, text in _written(answer):
            grammar = grammars.get(str(node_type).split("@", 1)[0])
            if grammar is not None:
                resolved, _ = resolve_references(text, _widgets(answer, case, node_id), "json", grammar=grammar)
                assert dv.validate(node_type, resolved, grammar_id=grammar) == {"status": dv.STATUS_VALID}, (
                    answer.skill, answer.key, node_id)
                held += 1
            elif node_type == EDIT:
                assert "problem" not in map_edits.read(text), (answer.skill, answer.key, map_edits.read(text))
                held += 1
        for call in answer.calls:
            if call["tool"] == "dataflow.plan.write" and call["status"] == "applied":
                _, errors = content.parse_dataflow_plan_verbose(call["arguments"])
                assert not errors, (answer.skill, answer.key, errors)
                held += 1
    assert held, "no golden answer writes a document"


def _vega_refuses(node_id: str | None = None, columns: list[str] | None = None):
    """The document check, given the columns the node's input has, refuses
    each Vega-Lite spec the answer wrote (into *node_id*)."""
    def refused(answer) -> bool:
        dv = _dv()
        written = [text for _, node_type, text in _written(answer, node_id) if node_type == VEGA]
        return bool(written) and all(
            dv.validate(VEGA, text, columns=columns)["status"] == dv.STATUS_INVALID for text in written)
    return refused


def _autk_refuses(node_id: str | None = None):
    """The document check refuses each Autark document the answer wrote (into *node_id*)."""
    def refused(answer) -> bool:
        dv = _dv()
        written = [text for _, node_type, text in _written(answer, node_id) if node_type == AUTK]
        return bool(written) and all(dv.validate(AUTK, text)["status"] == dv.STATUS_INVALID for text in written)
    return refused


def _templates() -> dict:
    """Each shipped template by its type, as its manifest writes it: the roster the plan check reads."""
    found = {}
    for path in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        package = path.parent.name.split("@", 1)[0]
        for template in manifest.get("templates") or []:
            found[f"{package}/{template['id']}"] = template
    return found


def _plan_refuses(dataflow: str):
    """The plan check refuses the interaction edges of the plan the answer wrote
    over the case's *dataflow* (``plan_topology.interaction_edge_errors``)."""
    def refused(answer) -> bool:
        from utk_curio.backend.app.agents.domain import plan_topology

        nodes = json.loads((REPO_ROOT / dataflow).read_text(encoding="utf-8"))["dataflow"]["nodes"]
        types = {node["id"]: node.get("type") for node in nodes}
        plans = [c["arguments"] for c in answer.calls if c["tool"] == "dataflow.plan.write" and c["status"] == "applied"]
        for plan in plans:
            planned = {node["ref"]: node["nodeType"] for node in plan.get("nodes") or []}
            if plan_topology.interaction_edge_errors(plan, lambda end: planned.get(end) or types.get(end), _templates()):
                return True
        return False
    return refused


def _grounding_refuses(*, datasets=(), models=None, data_loading: bool = False):
    """The grounding gate, on an account with *datasets* in its Data Catalog
    and *models* added, refuses the code the answer wrote."""
    def refused(answer) -> bool:
        from utk_curio.backend.app.agents.application import source_grounding as sg

        ctx = sg.GroundingContext(
            catalog_ids={i: sg.CatalogRef(i, i, "", "") for i in datasets}, is_data_loading=data_loading,
            models=None if models is None else {m: (1,) for m in models}, code_engine="python")
        return any(not sg.check_grounding(text, "python", ctx).ok for _, _, text in _written(answer))
    return refused


def _reference_refuses(dataflow: str, node_id: str):
    """The reference check a content write holds code to (``turns/grounding._reference_problems``,
    through ``code_references.resolve_references``) refuses what the answer wrote into *node_id*,
    over that node's widgets and selection tags in the case's *dataflow*."""
    def refused(answer) -> bool:
        from utk_curio.backend.app.execution.code_references import resolve_references

        nodes = json.loads((REPO_ROOT / dataflow).read_text(encoding="utf-8"))["dataflow"]["nodes"]
        metadata = next(node for node in nodes if node["id"] == node_id).get("metadata") or {}
        return any(resolve_references(text, metadata.get("widgets") or [], "python", (),
                                      selections=metadata.get("selections") or [])[1]
                   for _, _, text in _written(answer, node_id))
    return refused


def _map_edits_refuses(node_id: str):
    """The Map Editor node's reader (``map_edits.read``, which the content write holds code to)
    finds a problem in what the answer wrote into *node_id*."""
    def refused(answer) -> bool:
        from utk_curio.backend.app.agents.domain import map_edits

        return any("problem" in map_edits.read(text) for _, _, text in _written(answer, node_id))
    return refused


LAYERS = "docs/examples/dataflows/chicago-loop-layers.json"
QUAD = "docs/examples/dataflows/quad-cities-flood-vulnerability.json"
POOL_VEGA = "docs/examples/dataflows/data-pool-vega-2.json"
LAYERS_EDITOR = "ece11802-86f4-5ea9-9faf-f5cf6e2d732f"


def _refusals() -> dict:
    """Each ``refused-`` mutant, by its skill, case and name, and the check its
    source names, which refuses its planted output and passes its golden answer's."""
    return {
        ("vega-lite-starter", 1, "refused-field"): _vega_refuses("scores-chart", ["side", "accessibility", "coverage"]),
        ("vega-lite-starter", 2, "refused-field"): _vega_refuses("counts-chart", ["hour", "pedestrians", "cyclists"]),
        ("vega-lite-starter", 3, "refused-field"): _vega_refuses("roofs-chart", ["roof_id", "VEGETATED_SQFT"]),
        ("autark-starter", 1, "refused-layer"): _autk_refuses("blocks-map"),
        ("autark-starter", 2, "refused-layer"): _autk_refuses("blocks-parks-map"),
        ("autark", 1, "refused-spec"): _autk_refuses(),
        ("autark", 2, "refused-spec"): _autk_refuses("d517325b-266b-575d-ab48-2685bb889536"),
        ("autark", 3, "refused-layer"): _autk_refuses(),
        ("rasterization", 4, "refused-edge"): _plan_refuses(QUAD),
        ("node-functions", 1, "refused-code"): _grounding_refuses(
            datasets=["data.curio.chicago-loop-layers"], data_loading=True),
        ("node-functions", 3, "refused-code"): _grounding_refuses(
            datasets=["data.curio.mapillary-sample"], models=["model.curio.ddrnet23-slim"]),
        ("interaction-edges", 1, "refused-edge"): _plan_refuses(POOL_VEGA),
        ("interaction-edges", 4, "refused-edge"): _plan_refuses(POOL_VEGA),
        ("selection-chips", 2, "refused-code"): _reference_refuses(
            "skills/selection-chips/evals/files/roofs-picked-zips.json", "e8d24b91-3f05-4c7a-b6d1-0a9c27e5f413"),
        ("map-edits", 1, "refused-map-edit"): _map_edits_refuses(LAYERS_EDITOR),
        ("map-edits", 2, "refused-map-edit"): _map_edits_refuses(LAYERS_EDITOR),
        ("map-edits", 3, "refused-edge"): _plan_refuses(LAYERS),
        ("map-edits", 4, "refused-map-edit"): _map_edits_refuses(LAYERS_EDITOR),
        ("catalogs", 2, "refused-code"): _grounding_refuses(data_loading=True),
        ("data-sources", 1, "refused-code"): _grounding_refuses(
            datasets=["data.cityofchicago.energy-usage-2010"], data_loading=True),
        ("data-sources", 2, "refused-code"): _grounding_refuses(data_loading=True),
        ("data-sources", 4, "refused-code"): _grounding_refuses(data_loading=True),
        ("node-control", 2, "refused-code"): _grounding_refuses(),
        ("nodes", 3, "refused-code"): _grounding_refuses(datasets=["data.cityofchicago.neighborhoods"],
                                                         data_loading=True),
        ("vega-lite-maps", 1, "refused-field"): _vega_refuses(columns=["geometry", "accessibility", "neighborhood_name"]),
        ("vega-lite-maps", 3, "refused-field"): _vega_refuses("zip-map", ["zip", "roofs", "geometry", "centroid"]),
        ("vega-lite-charts", 2, "refused-edge"): _plan_refuses("docs/examples/dataflows/chicago-rain-wind-routing.json"),
        ("scenarios", 1, "refused-spec"): _vega_refuses(),
        ("scenarios", 4, "refused-code"): _reference_refuses(
            "docs/examples/dataflows/scenarios.json", "f6c0d4e8-3a1b-4c5f-8d94-8e3a2b1cadb5"),
    }


def test_each_refused_mutant_s_output_is_refused_by_the_check_its_source_names():
    grader_truth = _grader_truth()
    refusals = _refusals()
    planted = {(answer.skill, answer.case, answer.name): answer for _, answer in _answers("mutant")
               if answer.mutation == grader_truth.REFUSED}
    assert set(planted) == set(refusals), sorted(set(planted) ^ set(refusals))
    for (skill, case_id, name), refuses in refusals.items():
        answer = planted[(skill, case_id, name)]
        golden = next(a for c, a in _answers("golden") if a.skill == skill and a.case == case_id)
        assert refuses(answer), (skill, case_id, name)
        assert not refuses(golden), (skill, case_id, "golden")


# --- The shapes -----------------------------------------------------------------------


def test_the_shapes_an_answer_is_held_to_are_the_ones_the_worker_writes():
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.application.proposals import changes as agents_changes
    from utk_curio.tools import skill_eval_worker as worker

    grader_truth = _grader_truth()
    assert grader_truth.LAYOUT == worker._LAYOUT
    assert grader_truth.BOOKKEEPING == set(worker._BOOKKEEPING)
    assert grader_truth.CLIP == worker.PREVIEW_MAX_CHARS
    assert grader_truth.APPLIED == agents_changes.LANDED
    assert grader_truth.SKILL_READ == skill_runs.TOOL
    assert set(grader_truth.CHANGE_TOOLS) == set(agents_changes.KIND_OF_TOOL)
    before = {"dataflow": {"nodes": [{"id": "a", "type": "t", "title": "A", "content": "1", "x": 0},
                                     {"id": "b", "type": "t", "name": "B", "content": "2"}],
                           "edges": [{"id": "e", "source": "a", "target": "b", "sourceHandle": "out"}]}}
    after = {"dataflow": {"nodes": [{"id": "a", "type": "t", "title": "A", "content": "3", "x": 9},
                                    {"id": "c", "type": "t", "content": "4", "y": 1}], "edges": []}}
    changed = worker._dataflow_changes(before, after)
    assert set(changed) <= set(grader_truth.CHANGED_KINDS)
    for hows in changed.values():
        assert set(hows) <= set(grader_truth.CHANGED_HOWS)
        for item in hows.get("removed", []):
            assert set(item) <= grader_truth.REMOVED_KEYS, item
        for item in hows.get("changed", []):
            assert set(item) <= grader_truth.CHANGED_KEYS, item
        for item in hows.get("added", []):
            assert not set(item) & grader_truth.LAYOUT, item


def test_a_truth_file_that_breaks_the_format_is_refused_naming_each_problem(tmp_path):
    grader_truth, skill_evals = _grader_truth(), _skill_evals()
    folder = tmp_path / "street-trees"
    (folder / "evals").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {folder.name}\ndescription: Use this skill when counting street trees.\n---\n## Trees\n",
        encoding="utf-8")
    cases = [{"id": n, "prompt": "Count the oaks.", "expected_output": "A count.",
              "assertions": ["It counts oaks.", "It names its source."]} for n in (1, 2, 3)]
    (folder / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": folder.name, "agent": "agent.you.tree-counter@1", "evals": cases}), encoding="utf-8")
    evals = skill_evals.read(folder)
    assert grader_truth.read(evals) is None
    empty = {"changed": {}, "cards": [], "awaiting_review": []}
    good = {"case": 1, "name": "golden", "kind": "golden", "source": "an example", "fails": [],
            "reply": "There are 12 oaks.", "changes": empty, "calls": [{"tool": "node.read", "status": "ok"}]}
    broken = {"skill_name": "other-name", "answers": [
        good,
        {**good, "name": "fenced", "kind": "mutant", "fails": [3]},
        {**good, "case": 9},
        {**good, "case": 2, "kind": "golden", "fails": [1], "source": " "},
        {**good, "case": 2, "name": "guess", "kind": "mutant", "fails": [1]},
        {**good, "case": 1, "name": "refused-code", "kind": "mutant", "fails": [1],
         "calls": [{"tool": "skill.read", "status": "ok"}, {"tool": "node.create", "status": "refused",
                                                             "arguments": {}}]},
        {**good, "case": 1, "name": "refused-spec", "kind": "mutant", "fails": [2],
         "changes": {"changed": {"nodes": {"added": [{"id": "n", "x": 0}]}}, "cards": [{"tool": "node.create"}],
                     "awaiting_review": [{"tool": "package.install", "proposalId": "p"}]}},
        {**good, "case": 1, "name": "refused-plan", "kind": "mutant", "fails": [1],
         "calls": [{"tool": "dataflow.plan.write", "status": "applied", "arguments": {"goal": "g"}}]},
    ], "gaps": [{"case": 1, "why": "no example"}, {"case": 2, "why": ""}]}
    (folder / "evals" / grader_truth.TRUTH_FILE).write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(grader_truth.TruthError) as refused:
        grader_truth.read(evals)
    message = str(refused.value)
    for problem in ("skill_name must be 'street-trees'", "fails names [3], outside its case's 2 assertions",
                    "case must be the id of one of its skill's test cases, not 9",
                    "a golden answer fails nothing", "source must name what its content came from",
                    "a mutant is named 'fenced' or refused-<what>", "is skill.read, which the worker never shows",
                    "and arguments only once applied", "shows no layout, not x",
                    "a card shows its tool, undo and only", "none of its bookkeeping, not proposalId",
                    "1 dataflow.plan.write call(s) landed and only 0 card(s) say so",
                    "case 1 has a golden answer and a gap", "why must say why",
                    "case 3 has neither a golden answer nor a gap"):
        assert problem in message, (problem, message)
