"""What the agents' chats name a node by, and text cut to fit on a word.

A node is named as its header on the canvas names it: by its title, whole;
with no title, by its template's label, else its type in words
(``node_names.saved_node_label``). A node with no type is named by its goal,
cut on a word with an ellipsis when it runs past :data:`GOAL_NAME_CHARS`, and
one with no goal by its id. A text that must fit a bound is cut the same way,
so no word shown is cut in half. Where several nodes are named at once, a
node in a scenario says its scenario, and names that still read alike end
with a short id (:func:`told_apart`).

A plan gives a node it lands its title and its intent as its goal, joined so
that the goal holds no second colon (:func:`planned_goal`).

The domain layer holds it so that every module that names a node, the
checks' messages among them, reads the one rule.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Mapping

from utk_curio.backend.app.execution import node_names

#: The most characters of its goal a node with no title or type is named by.
GOAL_NAME_CHARS = 60
#: How many characters of its id tell a node apart from one of the same name.
SHORT_ID_CHARS = 8
#: What a cut text ends with.
ELLIPSIS = "…"
#: How the chats say that a chart's or a map's document passed its check:
#: the sandbox does not run one, so its grammar's schema validates it.
DOCUMENT_VALIDATED = "validated against its grammar"


def _joins(char: str) -> bool:
    """Whether *char* joins words rather than ends them: a space, a comma, a
    semicolon, a colon or a dash, which a cut never ends on."""
    return char in " ,;:" or unicodedata.category(char) == "Pd"


def on_a_word(text: object, limit: int) -> str:
    """*text* with each run of white space made one space: whole when it is at
    most *limit* characters; else cut after the last whole word that fits,
    with an ellipsis. A first word longer than *limit* stands whole, with the
    ellipsis after it."""
    words = " ".join(str(text or "").split())
    if len(words) <= limit:
        return words
    head = words[:limit + 1]
    cut = head.rsplit(" ", 1)[0] if " " in head else words.split(" ", 1)[0]
    if cut == words:
        return words
    while cut and _joins(cut[-1]):
        cut = cut[:-1]
    return cut + ELLIPSIS


def fit(text: object, limit: int) -> str:
    """*text* as it is when it is at most *limit* characters; else cut on a
    word with its ellipsis within *limit* (:func:`on_a_word`). For a bound
    that must hold, such as a goal a listing carries or a title a node keeps,
    whose line breaks a reader keeps when it fits: a first word longer than
    the bound is the one word cut, so the bound holds."""
    text = str(text or "")
    if len(text) <= limit:
        return text
    cut = on_a_word(text, limit - 1)
    return cut if len(cut) <= limit else " ".join(text.split())[:limit - 1] + ELLIPSIS


def node_label(node: Mapping | None, *, templates: Mapping[str, str]) -> str:
    """What the agents' chats name *node* by, as its header on the canvas
    names it: its title, whole; with no title, its template's label from
    *templates* (each template's label by unversioned id, as
    ``node_names.template_labels`` reads a project's), else its type in
    words; with no type, its goal cut on a word (:func:`on_a_word`,
    :data:`GOAL_NAME_CHARS`); with no goal, its id; "" for no node."""
    node = node if isinstance(node, Mapping) else {}
    title = node_names.saved_node_title(node)
    if title:
        return title
    data = node.get("data") if isinstance(node.get("data"), Mapping) else {}
    if node.get("type") or data.get("nodeType"):
        named = node_names.saved_node_label(node, templates)
        if named:
            return named
    return on_a_word(node.get("goal"), GOAL_NAME_CHARS) or str(node.get("id") or "")


def scenario_names(dataflow: Mapping | None) -> dict[str, str]:
    """Each node a scenario of *dataflow* holds, by its id, to that
    scenario's name."""
    scenarios = (dataflow or {}).get("scenarios") if isinstance(dataflow, Mapping) else None
    return {
        str(node_id): str(scenario.get("name") or "")
        for scenario in scenarios or [] if isinstance(scenario, Mapping) and scenario.get("name")
        for node_id in scenario.get("nodes") or []
    }


def told_apart(
    nodes: Mapping[str, Mapping | None], *, templates: Mapping[str, str], scenarios: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The name of each node of *nodes* (by its id) where they are named at
    once, so no two read alike: its :func:`node_label`, with the name of the
    scenario that holds it (*scenarios*, :func:`scenario_names`) in brackets,
    as the plan's card names a copy and its original; where two names still
    read alike, each ends with a short id, "Load (1a2b3c4d)"."""
    parts: dict[str, list[str]] = {}
    for node_id in nodes:
        scenario = (scenarios or {}).get(node_id)
        parts[node_id] = [scenario] if scenario else []

    def named(node_id: str) -> str:
        name = node_label(nodes[node_id], templates=templates) or str(node_id)
        return f"{name} ({', '.join(parts[node_id])})" if parts[node_id] else name

    shared = Counter(named(node_id) for node_id in nodes)
    for node_id in nodes:
        if shared[named(node_id)] > 1:
            parts[node_id].append(str(node_id)[:SHORT_ID_CHARS])
    return {node_id: named(node_id) for node_id in nodes}


def planned_goal(title: str, intent: str) -> str:
    """The goal a plan gives a node it lands, the mission its agents read and
    their chats show: its title, a colon and its intent. A title that holds a
    colon of its own is joined to its intent with a semicolon instead, so the
    goal holds no second colon. The intent is kept as the plan wrote it."""
    return f"{title}{'; ' if ':' in title else ': '}{intent}"


def document_validated(verdict: object, evidence: Mapping | None) -> bool:
    """Whether a Solve's *verdict*, with its *evidence*, is a chart's or a
    map's document that its grammar's schema validated: the sandbox does not
    run one, and nothing failed."""
    return verdict == "not-executable" and bool((evidence or {}).get("documentValidated"))


def verdict_words(verdict: object, evidence: Mapping | None, *, capitals: bool = False) -> str:
    """A Solve's *verdict* as a card or a trail says it: a document its
    grammar validated (:func:`document_validated`) is
    :data:`DOCUMENT_VALIDATED`, and any other verdict is itself. With
    *capitals*, its first word is in capitals, as a card's title writes a
    verdict ("PASS", "VALIDATED against its grammar")."""
    words = DOCUMENT_VALIDATED if document_validated(verdict, evidence) else str(verdict or "")
    if not capitals:
        return words
    first, _, rest = words.partition(" ")
    return first.upper() + (f" {rest}" if rest else "")
