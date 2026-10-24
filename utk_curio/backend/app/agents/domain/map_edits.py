"""Map Editor, as agents meet it.

A Map Editor node keeps its edits in its code: one call of
``curio_edit_features``, which the node writes from its edit list and reads
back. An agent writes that code too, so what it writes is held to what the
node reads (``utk_curio/sandbox/util/feature_edits_code.py``, a port of the
node's reader), and a run's report of ids no feature has tells an edit that
names features the data does not hold (``feature_edits.UNKNOWN_IDS_LINE``).

The checks are keyed by the template's ``behavior`` (``edit-features``),
never by its id, read from the account's copy of the template as a run finds
the node's package, else from the catalog's: a template a user made that
names the behavior gets them too. Code the node holds already is the user's
own and is never refused.
"""
from __future__ import annotations

import re

from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import plan_topology
from utk_curio.backend.app.execution import workflow_spec
from utk_curio.backend.app.packages import service as packages_services
from utk_curio.backend.app.agents.domain import agent_text

#: The behavior a Map Editor template names.
BEHAVIOR = "edit-features"
#: The kind of a Solve attempt these checks fail.
KIND = "map-edits"
#: The most of a neighbour's Map Editor call a node's context carries.
CALL_MAX_CHARS = 2000
#: The most made-up-id lines a refusal quotes.
_MAX_QUOTED = 10
#: The words a sentence of a node's goal starts with when it names an edit to
#: make: what each of the node's edits does, as its list says it ("Remove",
#: "Set", "Raise"), and the plain words for the same.
EDIT_WORDS = (
    "remove", "delete", "drop", "restore", "put back", "set", "change", "scale", "multiply",
    "raise", "lower", "increase", "decrease", "cut", "cap", "compute", "redraw", "reshape",
    "move", "add", "draw",
)
#: Where a goal's sentences and clauses part: after a stop, a colon or a
#: semicolon, at a dash between spaces (a plan's goal is its node's title, a
#: dash, then its intent) and at a line break.
_DASHES = "-" + chr(0x2013) + chr(0x2014)
_SENTENCES = re.compile(rf"(?<=[.!?;:])\s+|\s+[{_DASHES}]+\s+|\n+")
_EDIT_WORD = re.compile(r"(?:" + "|".join(re.escape(word) for word in EDIT_WORDS) + r")\b", re.IGNORECASE)


def is_map_edits(user_key, project_id, node_type) -> bool:
    """Whether a node of *node_type* in *user_key*'s dataflow *project_id* is
    a Map Editor node: its template names the Map Editor behavior, its copy in
    the account read as a run finds it, else the catalog's."""
    return packages_services.template_behavior(user_key, project_id, node_type) == BEHAVIOR


def read(code) -> dict:
    """What the node makes of *code* (``read_edit_features_code``)."""
    from utk_curio.sandbox.util.feature_edits_code import read_edit_features_code

    return read_edit_features_code(code)


def holds_no_edits(code) -> bool:
    """Whether *code* is a Map Editor node's code with nothing in it: blank, or
    a call the node reads with no edits and no new layers."""
    reading = read(code)
    if "problem" in reading:
        return False
    settings = reading.get("settings") or {}
    return not settings.get("edits") and not settings.get("newLayers")


def refusal(user_key, project_id, node_type, code, *, current: str | None = None) -> str | None:
    """Why *code*, written by an agent for a node of *node_type* in *user_key*'s
    dataflow *project_id*, is refused: Map Editor cannot read it, in the node's
    own words. None for a node of another kind, for code the node reads, and
    for the code the node holds already (*current*), which is the user's own:
    compared as an agent's code is written into a node (``extract_node_content``)."""
    if not is_map_edits(user_key, project_id, node_type):
        return None
    if current is not None and content.extract_node_content(code) == content.extract_node_content(current):
        return None
    problem = read(code).get("problem")
    return agent_text.message("map-edits.unreadable", problem=problem) if problem else None


def made_up_ids(stdout) -> list[str]:
    """The lines of a run's output in which the Map Editor step says an edit
    names ids no feature has, each once, in their order. *stdout* is the run's
    whole output, its text or its lines."""
    from utk_curio.sandbox.util.feature_edits import UNKNOWN_IDS_LINE

    lines = stdout.splitlines() if isinstance(stdout, str) else [str(line) for line in stdout or ()]
    found: list[str] = []
    for line in lines:
        text = line.strip()
        if UNKNOWN_IDS_LINE.fullmatch(text) and text not in found:
            found.append(text)
    return found


def made_up_ids_refusal(lines: list[str]) -> str:
    """The round's refusal for the run's lines that name ids no feature has."""
    quoted = lines[:_MAX_QUOTED]
    more = len(lines) - len(quoted)
    return agent_text.message(
        "map-edits.made-up-ids", lines="\n".join(quoted), more="\n" + agent_text.message(
            "map-edits.and-more", more=more,
        ) if more else "",
    )


def goal_names_edits(goal) -> bool:
    """Whether a Map Editor node's goal names the edits to make: one of its
    sentences or clauses starts with what an edit does ("Remove the towers
    ...", "Cut the parts ... down to ..."). A goal that says what the node is
    for ("Read the map's layers and edit them on the map") names none."""
    text = goal.strip() if isinstance(goal, str) else ""
    return any(_EDIT_WORD.match(sentence.strip()) for sentence in _SENTENCES.split(text) if sentence.strip())


def no_edits_reason() -> str:
    """Why Solve leaves an empty Map Editor node without edits."""
    return "Map Editor: its goal names no edits, so its call holds none; make them on its map"


def circles_into(node_id, edges) -> int:
    """How many circles feed the node *node_id*, as the node counts them
    (``circlesInto`` in ``mapLayerEdits.ts``): one past the highest circle a
    data edge goes into, the circle a run binds ``input_k`` by."""
    highest = 0
    for edge in edges or ():
        if not isinstance(edge, dict) or edge.get("target") != node_id:
            continue
        if plan_topology.is_interaction_edge(edge) or (
            edge.get("sourceHandle") == "in/out" and edge.get("targetHandle") == "in/out"
        ):
            continue
        highest = max(highest, workflow_spec.input_slot(edge) + 1)
    return max(highest, 1)


def new_node_code(node_id, edges) -> str:
    """The code of a Map Editor node *node_id* whose edits are left to the
    user: the code the node writes for itself when it is dropped, its call
    with no edits, over the circles that feed it."""
    from utk_curio.sandbox.util.feature_edits_code import new_node_code as written

    return written(circles_into(node_id, edges))


def context_call(code) -> str:
    """A Map Editor node's code as a neighbour's context carries it: its call,
    cut at ``CALL_MAX_CHARS`` and marked when cut."""
    text = str(code or "")
    if len(text) <= CALL_MAX_CHARS:
        return text
    return text[:CALL_MAX_CHARS] + ("\n" + agent_text.message("map-edits.call-truncated"))
