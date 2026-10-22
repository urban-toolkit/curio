"""What a check tells a model when it refuses or corrects what the model wrote is a section of messages.md.

A tool call the runtime does not run, a proposal it does not make, a plan, a
request, code or a document it sends back for another attempt: each says why
in words the base entry holds, ``agents/agent.curio.builtin@1/messages.md``,
one section per message, by its id. A check reads its message by id through
``agent_text.message``, which fills each ``{name}`` with a value the check
gives, such as a node's id or the problems it found, so the words are the
page's and the values are the run's. Errors people see, such as a node's
error on Play, stay with their feature.

These tests read every call of ``agent_text.message`` in ``utk_curio/``: each
names a message the page holds and fills exactly the values its section
names, and every section is some check's message. An edit to the page reaches
what the checks say, the fill is strict and runs once, a check reads no file
after the backend starts, and no message's words are still a string in
Python.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS = REPO_ROOT / "agents"
BASE = AGENTS / "agent.curio.builtin@1"
PAGE = "messages.md"
#: A value's place in a message, as the page writes it.
PLACE_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def _fresh_loader(monkeypatch):
    """The loader as in a process that has not started: nothing rendered and
    no ``--dev``. The test's end restores the process's own renders."""
    from utk_curio.backend.app.agents.domain import agent_text

    monkeypatch.delenv("CURIO_DEV", raising=False)
    monkeypatch.setattr(agent_text, "_TEXTS", {})
    monkeypatch.setattr(agent_text, "_STARTED", False)
    return agent_text


def _agents_copy(tmp_path, monkeypatch) -> Path:
    """A copy of ``agents/`` the test may edit, read with ``--dev`` so each read
    renders the page as it is then."""
    from utk_curio.backend.app.agents.domain import agent_text, builtin

    root = tmp_path / "agents"
    shutil.copytree(AGENTS, root)
    monkeypatch.setattr(builtin, "agents_dir", lambda: root)
    monkeypatch.setattr(agent_text, "base_dir", lambda: root / BASE.name)
    _fresh_loader(monkeypatch)
    monkeypatch.setenv("CURIO_DEV", "1")
    return root / BASE.name


def _python_files() -> list[Path]:
    """Every Python file in ``utk_curio/`` but the tests."""
    return [
        path for path in sorted((REPO_ROOT / "utk_curio").rglob("*.py"))
        if "/tests/" not in path.relative_to(REPO_ROOT).as_posix()
    ]


def _message_calls() -> list[tuple[str, object, list[str], bool]]:
    """Each ``agent_text.message(...)`` call in ``utk_curio/``: where it is, its
    id (a string, or the expression it is not), the values it names, and
    whether it spreads a mapping it does not name."""
    calls = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "message"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "agent_text"
            ):
                continue
            first = node.args[0] if node.args else None
            message_id = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else ast.dump(first) if first else None
            named = [keyword.arg for keyword in node.keywords if keyword.arg is not None]
            spread = any(keyword.arg is None for keyword in node.keywords) or len(node.args) != 1
            calls.append((f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}", message_id, named, spread))
    return calls


def test_the_base_entry_lists_the_messages_page():
    listed = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))["pages"]
    assert PAGE in listed and (BASE / PAGE).is_file(), "the base entry holds no messages.md, or does not list it"


def test_every_check_names_a_message_of_the_page_and_fills_exactly_its_values(monkeypatch):
    """Each call names its message by a literal id that is a section of the
    page, and gives exactly the values its section has places for; every
    section is a message some check says."""
    from utk_curio.backend.app.agents.domain import agent_text

    _fresh_loader(monkeypatch)
    sections = agent_text.sections(PAGE)
    calls = _message_calls()
    assert len(sections) > 100 and len(calls) >= len(sections), (
        f"the page holds {len(sections)} messages and the checks say {len(calls)}; this test would mean nothing"
    )
    wrong = []
    for where, message_id, named, spread in calls:
        if not isinstance(message_id, str) or spread:
            wrong.append(f"{where}: names its message by {message_id}, or gives values the scan cannot read")
        elif message_id not in sections:
            wrong.append(f"{where}: {message_id} is no section of {PAGE}")
        elif sorted(set(named)) != sorted(set(PLACE_RE.findall(sections[message_id]))) or len(named) != len(set(named)):
            wrong.append(
                f"{where}: {message_id} gives {sorted(named)}, where its section has places for "
                f"{sorted(set(PLACE_RE.findall(sections[message_id])))}"
            )
    said = {message_id for _, message_id, _, _ in calls}
    wrong += [f"{PAGE}, section {name}: no check says it" for name in sections if name not in said]
    assert not wrong, "\n".join(wrong)


def test_a_message_is_its_section_with_its_values_filled_once(tmp_path, monkeypatch):
    """The fill is strict: a value the section has no place for, or a place
    no value fills, is refused, naming the page and the section; a message
    the page lacks is refused; a value that reads like a place is written as
    it is, not filled again."""
    from utk_curio.backend.app.agents.domain import agent_text

    base = _agents_copy(tmp_path, monkeypatch)
    page = base / PAGE
    page.write_text(
        page.read_text(encoding="utf-8")
        + "\n## test.two-places\n\nthe node {node} reads {column}, and {node} again\n",
        encoding="utf-8",
    )
    assert agent_text.message("test.two-places", node="n1", column="{node}") == "the node n1 reads {node}, and n1 again"
    with pytest.raises(agent_text.AgentTextError, match=r"messages\.md, section test\.two-places names \{column\}"):
        agent_text.message("test.two-places", node="n1")
    with pytest.raises(agent_text.AgentTextError, match=r"has no place for \{row\}"):
        agent_text.message("test.two-places", node="n1", column="c", row="r")
    with pytest.raises(agent_text.AgentTextError, match="has no section 'test.none'"):
        agent_text.message("test.none")
    # a value is written as an f-string writes it
    assert agent_text.message("test.two-places", node=7, column=None) == "the node 7 reads None, and 7 again"


def test_an_edit_to_a_message_reaches_what_the_check_says(tmp_path, monkeypatch):
    """With ``--dev`` the page is rendered at each read, so an edit to a
    message reaches the model: the words are the page's, not a copy."""
    from utk_curio.backend.app.agents.application import tool_rounds

    base = _agents_copy(tmp_path, monkeypatch)
    page = base / PAGE
    text = page.read_text(encoding="utf-8")

    def edit(message_id: str) -> None:
        nonlocal text
        heading = f"\n## {message_id}\n\n"
        assert text.count(heading) == 1, message_id
        text = text.replace(heading, heading + "EDITED ")
        page.write_text(text, encoding="utf-8")

    edit("tool-round.tool-invalid")
    assert tool_rounds._tool_correction_message(["a problem"])["content"].startswith("EDITED [tool validation]")
    edit("tool-round.final-round")
    assert tool_rounds._native_result_text("ok", "the body", final=True).startswith("the body\nEDITED ")
    for message_id, said in _edited_checks():
        edit(message_id)
        assert "EDITED " in said(), message_id


def _edited_checks():
    """A message of each kind of check, and how to make the check say it."""
    from utk_curio.backend.app.agents.application import source_grounding
    from utk_curio.backend.app.agents.domain import content, document_validation, result_shape

    def grounding():
        ctx = source_grounding.GroundingContext(is_data_loading=True)
        verdict = source_grounding.check_grounding('import pandas as pd\ndf = pd.read_csv("/no/such.csv")\n', "python", ctx)
        return source_grounding.refusal_text(verdict, ctx)

    def document():
        verdict = document_validation.validate("curio.builtin/vis-vega", "not a document")
        return document_validation.refusal_text("curio.builtin/vis-vega", verdict)

    def empty():
        return result_shape.refusal_text(summary={"kind": "dataframe", "rowCount": 0}, upstream_outputs=None)

    def plan():
        _plan, errors = content.parse_dataflow_plan_verbose({"nodes": [], "edges": []})
        return "\n".join(errors)

    return [
        ("grounding.refused", grounding),
        ("grounding.local-file-unseen", grounding),
        ("document.refused", document),
        ("result-shape.empty", empty),
        ("plan.changes-nothing", plan),
    ]


def test_the_backend_renders_the_messages_when_it_starts_and_a_check_reads_no_file(monkeypatch):
    """The start-up render covers the page, so a check that refuses reads the
    render and no file."""
    from utk_curio.backend.app.agents.application import tool_rounds

    agent_text = _fresh_loader(monkeypatch)
    agent_text.render_at_start()
    assert (BASE / PAGE).resolve() in {path.resolve() for path in agent_text.rendered()}
    reads = []
    monkeypatch.setattr(agent_text, "_source", lambda file: reads.append(file) or "")
    tool_rounds._tool_correction_message(["a problem"], native=True)
    tool_rounds._plan_correction_message(["a problem"])
    for _message_id, said in _edited_checks():
        said()
    assert reads == [], f"a check read {reads}"


#: A message's words are looked for in Python by its sentences and clauses as
#: long as this, cut at each value too: a copy is caught by any one of them.
_PIECE_CHARS = 30
_CUT_RE = re.compile(r"(?<=[.;:!?])\s+|\n|\{[a-z][a-z0-9_]*\}")


def _python_strings() -> list[tuple[str, str]]:
    """Every string literal in ``utk_curio/``'s Python, its tests left out,
    with where it is: adjacent literals joined as Python joins them, and each
    literal part of an f-string."""
    found = []
    for path in _python_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append((f"{relative}:{node.lineno}", node.value))
    return found


def test_no_message_is_left_in_python(monkeypatch):
    """No sentence or clause of a message is still a string in ``utk_curio/``:
    each message has one home, which an edit to the page reaches."""
    from utk_curio.backend.app.agents.domain import agent_text

    _fresh_loader(monkeypatch)
    pieces = {}
    for name, text in agent_text.sections(PAGE).items():
        for piece in _CUT_RE.split(text):
            piece = piece.strip()
            if len(piece) >= _PIECE_CHARS:
                pieces.setdefault(piece, name)
    assert len(pieces) > 100, f"the scan cut only {len(pieces)} pieces of the messages; it would mean nothing"
    python = _python_strings()
    left = sorted({
        f"{location}: {piece!r} ({name})"
        for piece, name in pieces.items()
        for location, literal in python
        if piece in literal
    })
    assert not left, "messages still in Python:\n" + "\n".join(left[:40])
