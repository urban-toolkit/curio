"""What the agents' chats name a node by, and text cut to fit on a word.

A node is named as its header on the canvas names it: by its title, whole.
A node with no title is named by its goal, cut on a word with an ellipsis when
it runs past :data:`GOAL_NAME_CHARS`, and one with no goal by its id. A text
that must fit a bound is cut the same way, so no word shown is cut in half.

The domain layer holds it so that every module that names a node, the
checks' messages among them, reads the one rule.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping

from utk_curio.backend.app.execution import node_names

#: The most characters of its goal a node with no title is named by.
GOAL_NAME_CHARS = 60
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


def node_label(node: Mapping | None) -> str:
    """What the agents' chats name *node* by: its title, whole, as its header
    on the canvas shows it; with no title, its goal cut on a word
    (:func:`on_a_word`, :data:`GOAL_NAME_CHARS`); with no goal, its id; ""
    for no node."""
    node = node if isinstance(node, Mapping) else {}
    title = node_names.saved_node_title(node)
    if title:
        return title
    return on_a_word(node.get("goal"), GOAL_NAME_CHARS) or str(node.get("id") or "")


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
