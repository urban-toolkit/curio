"""``node.history.read``: a node's history, as the saved dataflow keeps it.

The canvas saves each node's history under ``nodeProvenance``: its runs and
its edits, among them each change an agent made that the user applied, named
after the agent. The tool reads it from the saved spec, keyed by node id as a
load keys it (the shared cases, ``nodeProvenanceKeys.cases.json``). It lists a
node's entries, newest first, and gives one entry's code; a cut list or code
says how much it left out, as the other read tools do; a node with no history
and an entry the node does not have each answer in their own words. The Node
Builder and the Dataflow Builder are granted it, and the provenance skill every
agent reads says what an entry is.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

UKEY = "42"
PID = "p-history"
TOOL = "node.history.read"
CASES_FILE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "utils" / "nodeProvenanceKeys.cases.json"
)
#: The agents granted it: asked "what changed?" about a node or a dataflow in their chats.
GRANTED = ("agent.curio.node-builder", "agent.curio.dataflow-builder")


def _cases():
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


def _entry(entry_id: int, parent: int | None, code: str, **extra) -> dict:
    """An entry as the canvas saves it: a run, or an edit with ``kind`` and ``label``."""
    return {
        "id": entry_id, "parentId": parent, "code": code, "inputs": [], "outputs": [],
        "startTime": f"Oct 22 2026 10:{entry_id}:0", "endTime": f"Oct 22 2026 10:{entry_id}:1", **extra,
    }


def _write(history: dict | None, nodes=("n1",), content: str = "return input_0") -> None:
    from utk_curio.backend.app.projects import storage as projects_storage

    spec: dict = {"dataflow": {
        "nodes": [{"id": n, "type": "curio.builtin/computation-analysis", "content": content} for n in nodes],
        "edges": [],
    }}
    if history is not None:
        spec["nodeProvenance"] = history
    projects_storage.write_spec(UKEY, PID, spec)


def _read(params: dict, target: dict | None = None) -> tuple[str, str]:
    from utk_curio.backend.app.agents.application import tools

    return tools.execute_read_tool(TOOL, user_key=UKEY, project_id=PID, target=target, params=params)


@pytest.mark.parametrize("case", _cases())
def test_the_history_read_lists_entries_keyed_as_loads_key_them(case, tmp_curio):
    """Every node of the case's dataflow: the entries a load files under its
    id, newest first, and none of another node's."""
    assert case is not None, f"{CASES_FILE} is missing"
    _write(case["saved"], nodes=tuple(case["nodeIds"]))
    for node_id in case["nodeIds"]:
        status, text = _read({"nodeId": node_id})
        assert status == "ok", (case["name"], node_id, text)
        keyed = case["keyed"].get(node_id) or []
        listed = [entry["id"] for entry in json.loads(text)["entries"]]
        assert listed == sorted((record["id"] for record in keyed), reverse=True), (case["name"], node_id)


def test_each_entry_says_what_it_is(tmp_curio):
    """Its id and parent, run or edit, an edit's label (whoever made it),
    when it started and ended, the kinds of data it read and returned, and
    how long its code is. With no nodeId, the node the agent is attached to."""
    run = _entry(1, None, "return input_0[input_0['year'] >= 2020]", inputs=["DATAFRAME"], outputs=["DATAFRAME"])
    edit = _entry(2, 1, "return input_0", kind="edit", label="Node Builder")
    _write({"n1": [run, edit]})
    status, text = _read({}, target={"kind": "node", "targetId": "n1"})
    assert status == "ok", text
    assert json.loads(text) == {"nodeId": "n1", "entries": [
        {"id": 2, "parentId": 1, "kind": "edit", "label": "Node Builder", "startTime": edit["startTime"],
         "endTime": edit["endTime"], "inputs": [], "outputs": [], "codeChars": len(edit["code"])},
        {"id": 1, "parentId": None, "kind": "run", "startTime": run["startTime"], "endTime": run["endTime"],
         "inputs": ["DATAFRAME"], "outputs": ["DATAFRAME"], "codeChars": len(run["code"])},
    ]}


def test_it_gives_one_entrys_code(tmp_curio):
    """An entry's code by its id, a whole number however a model writes it;
    an edit that holds the code it replaced gives that too."""
    first = _entry(1, None, "x = 1", kind="edit", label="Node Builder", before="x = 0")
    _write({"n1": [first, _entry(2, 1, "x = 2")]})
    for asked in (1, "1", 1.0):
        status, text = _read({"nodeId": "n1", "entryId": asked})
        assert status == "ok", (asked, text)
        payload = json.loads(text)
        assert payload["nodeId"] == "n1"
        assert payload["entry"]["id"] == 1 and payload["entry"]["label"] == "Node Builder"
        assert payload["code"] == "x = 1"
        assert payload["before"] == "x = 0"
    status, text = _read({"nodeId": "n1", "entryId": 2})
    payload = json.loads(text)
    assert payload["entry"]["kind"] == "run" and payload["code"] == "x = 2"
    assert "before" not in payload


def test_it_reports_a_cut(tmp_curio):
    """A list past the tool's bound keeps the newest entries and says how many
    it left out, before the list; a code past it keeps its start and says how
    many characters it left out."""
    from utk_curio.backend.app.agents.application import tools

    bound = tools._NODE_HISTORY_MAX_ENTRIES
    code_bound = tools._NODE_HISTORY_CODE_MAX_CHARS
    last = bound + 4
    history = [_entry(i, i - 1 if i > 1 else None, f"x = {i}") for i in range(1, last)]
    history.append(_entry(last, last - 1, "y" * (code_bound + 7)))
    _write({"n1": history})

    status, text = _read({"nodeId": "n1"})
    assert status == "ok", text
    payload = json.loads(text)
    assert list(payload) == ["nodeId", "entriesElided", "entries"]
    assert payload["entriesElided"] == last - bound
    assert [entry["id"] for entry in payload["entries"]] == list(range(last, last - bound, -1))

    status, text = _read({"nodeId": "n1", "entryId": last})
    assert status == "ok", text[:200]
    payload = json.loads(text)
    assert payload["entry"]["codeChars"] == code_bound + 7
    assert payload["codeElided"] == 7
    assert payload["code"] == "y" * code_bound


def test_a_node_with_no_history_says_so(tmp_curio):
    from utk_curio.backend.app.agents.domain import agent_text

    said = {"nodeId": "n1", "entries": [], "note": agent_text.message("tools.node-history-none", node_id=repr("n1"))}
    _write(None)
    status, text = _read({"nodeId": "n1"})
    assert (status, json.loads(text)) == ("ok", said)
    # Another node's history is none of this node's.
    _write({"n2": [_entry(1, None, "x = 1")]}, nodes=("n1", "n2"))
    status, text = _read({"nodeId": "n1"})
    assert (status, json.loads(text)) == ("ok", said)


def test_an_entry_the_node_does_not_have_says_so(tmp_curio):
    from utk_curio.backend.app.agents.domain import agent_text

    _write({"n1": [_entry(1, None, "x = 1")]})
    for asked in (7, "seven", 1.5, True):
        status, text = _read({"nodeId": "n1", "entryId": asked})
        assert status == "error", asked
        assert text == agent_text.message("tools.node-history-no-entry", node_id=repr("n1"), entry_id=repr(asked))
    assert text != agent_text.message("tools.node-history-none", node_id=repr("n1"))
    # A node the dataflow does not have, and no node at all, as node.read says them.
    assert _read({"nodeId": "ghost"}) == ("error", agent_text.message("tools.node-not-in-spec", node_id=repr("ghost")))
    assert _read({}, target={"kind": "canvas"}) == ("error", agent_text.message("tools.no-node-id"))


def test_the_node_builder_and_the_dataflow_builder_are_granted_it():
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.domain import builtin

    contract = tools.REGISTRY[TOOL]
    assert contract.effect == "read" and contract.label and not contract.label.startswith("Propose ")
    for agent_id in GRANTED:
        manifest = builtin.get_builtin_manifest(builtin.builtin_coord(agent_id))
        assert TOOL in tools.resolve_grants(manifest.tools), agent_id
    # The Dataflow Reader runs only as a mode another agent asks for, and a
    # delegated mode runs with no tools: a grant to it would be dead.
    reader = builtin.get_builtin_manifest(builtin.builtin_coord("agent.curio.dataflow-reader"))
    assert TOOL not in tools.resolve_grants(reader.tools)
    # Offered natively under a name that decodes to its id, with its two params.
    (spec,) = tools.native_tools([TOOL])
    assert tools.tool_id_of(spec["name"]) == TOOL
    assert set(spec["parameters"]["properties"]) == {"nodeId", "entryId"}
    assert spec["parameters"]["properties"]["entryId"]["type"] == "integer"


def test_the_provenance_skill_reaches_every_chat_that_reads_a_nodes_history(tmp_curio):
    """The skill says what an entry is, that an agent's applied change is an
    edit named after the agent, and that putting an entry back is the user's
    action. Every chat granted the history tool lists it and loads it whole,
    once; the preamble every agent reads leaves it out."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import agent_text, builtin

    page = agent_text.skill_text("provenance")
    for words in ("a run or an edit", "named after the agent", "the user's action", TOOL):
        assert words in page, words
    listing = []
    for manifest in builtin.list_builtin_manifests():
        system = builtin.read_prompt_text(builtin.builtin_coord(manifest.agent_id), "system")
        assert page not in system, manifest.agent_id
        if "provenance" in (manifest.skills or ()):
            listing.append(manifest.agent_id)
    assert set(GRANTED) <= set(listing), listing
    assert sorted(listing) == ["agent.curio.dataflow-builder", "agent.curio.node-builder", "agent.curio.researcher"]
    for agent_id in listing:
        manifest = builtin.get_builtin_manifest(builtin.builtin_coord(agent_id))
        system = builtin.read_prompt_text(builtin.builtin_coord(agent_id), "system")
        chat = skill_runs.for_chat("4242", PID, manifest, {"dataflow": {"nodes": []}}, {"kind": "canvas"}, system, [])
        assert "provenance" in chat.names, agent_id
        status, loaded = skill_runs.read(chat, {"name": "provenance"})
        assert status == "ok" and loaded.count(page) == 1, agent_id
