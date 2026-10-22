"""The constants the browser and the server share are read from one set of
JSON files, by both.

``utk_curio/frontend/urban-workflows/src/contracts/`` holds them, one file per
vocabulary or table: the frontend imports each, and the backend reads it
through ``utk_curio/common/shared_constants.py``. These tests hold every
backend constant to its file, and find no Python module of Curio spelling a
shared sentence or palette color of its own. Jest's
``src/tests/contracts/sharedConstants.test.ts`` holds the frontend to the same
files. Every module is imported inside its test, so a checkout without the
files or the reader fails each test on its own.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "contracts"

#: Each shared file, by its name without ``.json``.
FILES = ("renderCauses", "solveStopReasons", "agentCategories", "noteColors", "autkGrammar", "visDefaults")


def _file(name: str):
    path = CONTRACTS / f"{name}.json"
    assert path.is_file(), f"{path} is missing"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", FILES)
def test_the_backend_reads_each_file_from_the_frontends_folder(name):
    from utk_curio.common import shared_constants

    assert shared_constants.CONTRACTS_DIR.resolve() == CONTRACTS.resolve()
    assert shared_constants.read(name) == _file(name)


def test_a_key_given_twice_is_refused_where_json_would_keep_the_last():
    from utk_curio.common import shared_constants

    with pytest.raises(ValueError, match="'budget'"):
        shared_constants.parse('{"phrases": {"budget": "a", "session": "b", "budget": "c"}}')
    with pytest.raises(ValueError, match="'least'"):
        shared_constants.parse('{"rules": [{"layers": {"least": 1, "least": 2}}]}')
    # Read as JSON.parse reads it: no NaN or Infinity.
    with pytest.raises(ValueError, match="NaN"):
        shared_constants.parse('{"minContrast": NaN}')
    assert shared_constants.parse('{"a": {"b": [1, 2]}, "c": 4.5}') == {"a": {"b": [1, 2]}, "c": 4.5}


def test_why_a_render_drew_nothing_is_the_files():
    from utk_curio.backend.app.agents.domain import contracts

    data = _file("renderCauses")
    assert contracts.EMPTY_RENDER_KIND == data["emptyRenderKind"]
    assert [(c.name, c.document_at_fault, c.description) for c in contracts.RENDER_CAUSES] == [
        (name, cause["documentAtFault"], cause["description"]) for name, cause in data["causes"].items()
    ]
    assert contracts.EMPTY_RENDER_CAUSES == tuple(data["causes"])
    for name, cause in data["causes"].items():
        assert contracts.is_document_at_fault(name) is cause["documentAtFault"], name


def test_why_a_repair_loop_stopped_is_the_files():
    from utk_curio.backend.app.agents.application.solve import rounds
    from utk_curio.backend.app.agents.domain import contracts

    phrases = _file("solveStopReasons")["phrases"]
    assert [(r.key, r.phrase) for r in contracts.SOLVE_STOP_REASONS] == list(phrases.items())
    assert contracts.STOPPED_BY_PHRASES == phrases
    assert list(contracts.STOPPED_BY_PHRASES) == list(phrases)
    assert rounds.STOPPED_BY_PHRASES is contracts.STOPPED_BY_PHRASES


def test_the_agent_categories_are_the_files():
    from utk_curio.backend.app.agents.domain.manifest import AGENT_CATEGORIES

    assert AGENT_CATEGORIES == tuple(_file("agentCategories")["categories"])


def test_a_notes_colors_are_the_files():
    """The palette, the default, the inks, the links and the contrast an
    agent's note is saved by, and the pairing the frontend draws: the dark ink
    and its link on a light note, the light ink and its link on a dark one."""
    from utk_curio.backend.app.packages.domain import node_appearance as appearance

    data = _file("noteColors")
    assert list(appearance.NAMED_COLORS.items()) == list(data["colors"].items())
    assert appearance.DEFAULT_COLOR_NAME == data["defaultColor"]
    assert appearance.DEFAULT_BACKGROUND == data["colors"][data["defaultColor"]]
    assert appearance.MIN_CONTRAST == data["minContrast"]
    assert (appearance.DARK_FOREGROUND, appearance.LIGHT_FOREGROUND) == (data["inks"]["dark"], data["inks"]["light"])
    assert (appearance.LINK_ON_LIGHT, appearance.LINK_ON_DARK) == (data["links"]["onLight"], data["links"]["onDark"])
    light, dark = appearance.derived_colors(data["defaultColor"]), appearance.derived_colors("#000000")
    assert (light["foreground"], light["link"]) == (data["inks"]["dark"], data["links"]["onLight"])
    assert (dark["foreground"], dark["link"]) == (data["inks"]["light"], data["links"]["onDark"])
    for name, color in data["colors"].items():
        assert appearance.derived_colors(name)["background"] == color, name
    assert appearance.resolve_background(None) == data["colors"][data["defaultColor"]]


def test_the_autark_facts_are_the_files_and_its_families_the_vendored_schemas():
    from utk_curio.backend.app.agents.domain import contracts

    data = _file("autkGrammar")
    assert contracts.INPUT_TABLE_PREFIX == data["inputTablePrefix"]
    assert contracts.input_table_name(3) == f"{data['inputTablePrefix']}3"
    assert contracts.AUTK_ONE_VIEW == data["oneView"]
    assert contracts.autk_one_view_problem({"map": {}, "plot": {}}) == data["oneView"]
    # The node routes the families the file lists; the grammar defines them.
    assert data["families"] == list(contracts.autk_families(contracts.load_autk_schema()))


def _rule(rule) -> dict:
    """A starter rule as the file writes it."""
    def count(c):
        return {"least": c.least, **({"most": c.most} if c.most is not None else {})}

    return {
        "id": rule.id,
        **({"layers": count(rule.layers)} if rule.layers is not None else {}),
        "columns": {role: count(c) for role, c in rule.columns},
        "produces": rule.produces,
        "description": rule.description,
    }


def test_what_a_visualization_node_does_by_itself_is_the_files():
    from utk_curio.backend.app.agents.domain import contracts

    data = _file("visDefaults")
    assert contracts.VEGA_SCHEMA_URL == data["vegaSchemaUrl"]
    assert contracts.COLUMN_ROLES == tuple(data["columnRoles"])
    assert [(e.role, list(e.names), list(e.prefixes)) for e in contracts.DTYPE_ROLES] == [
        (e["role"], e["names"], e["prefixes"]) for e in data["dtypeRoles"]
    ]
    assert [_rule(r) for r in contracts.VEGA_STARTER_LADDER] == data["vegaStarterLadder"]
    assert [_rule(r) for r in contracts.AUTK_STARTER_LADDER] == data["autkStarterLadder"]
    assert contracts.IMAGE_COLUMNS == tuple(data["imageColumns"])
    assert contracts.IMAGE_EXTENSIONS == tuple(data["imageExtensions"])
    assert contracts.IMAGE_MATCH_THRESHOLD == data["imageMatchThreshold"]


def test_the_starter_tables_are_well_formed():
    from utk_curio.backend.app.agents.domain import contracts

    families = contracts.autk_families(contracts.load_autk_schema())
    for rules in (contracts.VEGA_STARTER_LADDER, contracts.AUTK_STARTER_LADDER):
        ids = [rule.id for rule in rules]
        assert len(set(ids)) == len(ids)
        for rule in rules:
            assert {role for role, _ in rule.columns} <= set(contracts.COLUMN_ROLES), rule.id
            # The description is one line of the preamble's list.
            assert rule.description and "\n" not in rule.description, rule.id
    for rule in contracts.AUTK_STARTER_LADDER:
        assert rule.layers is not None, rule.id
        assert rule.produces in families, rule.id
    assert all(rule.layers is None for rule in contracts.VEGA_STARTER_LADDER)
    assert {entry.role for entry in contracts.DTYPE_ROLES} <= set(contracts.COLUMN_ROLES)


class TestTheRenderCauseTable:
    def test_the_cause_names_and_their_order(self):
        from utk_curio.backend.app.agents.domain import contracts

        assert contracts.EMPTY_RENDER_CAUSES == (
            "no-layers", "no-input-rows", "nothing-drawn", "empty-source",
        )

    def test_only_no_input_rows_spares_the_document(self):
        from utk_curio.backend.app.agents.domain import contracts

        at_fault = {c.name: c.document_at_fault for c in contracts.RENDER_CAUSES}
        assert at_fault == {
            "no-layers": True, "no-input-rows": False,
            "nothing-drawn": True, "empty-source": True,
        }

    def test_an_unknown_cause_is_still_the_documents_fault(self):
        from utk_curio.backend.app.agents.domain import contracts

        assert contracts.is_document_at_fault("teleported") is True
        assert contracts.is_document_at_fault("") is True
        assert contracts.is_document_at_fault(None) is True

    def test_every_cause_is_described_in_one_line(self):
        from utk_curio.backend.app.agents.domain import contracts

        for cause in contracts.RENDER_CAUSES:
            assert cause.description and "\n" not in cause.description


def _shared_sentences_and_colors() -> list[str]:
    """Every value of the shared files with a space in it (a sentence, a
    phrase or a description), and every color of a note's palette."""
    found: list[str] = []

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and " " in value:
            found.append(value)

    for name in FILES:
        walk(_file(name))
    found += [c for c in _file("noteColors")["colors"].values() if re.fullmatch(r"#[0-9a-f]{6}", c)]
    return sorted(set(found))


def _docstrings(tree: ast.AST) -> set[int]:
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                nodes.add(id(body[0].value))
    return nodes


def test_no_python_module_of_curio_spells_a_shared_sentence_or_color():
    # A string written out in a module is a second copy, which the file's
    # next change leaves behind. Docstrings may name a value; code reads it.
    values = set(_shared_sentences_and_colors())
    assert len(values) > 20
    copies = []
    for path in sorted((REPO_ROOT / "utk_curio").rglob("*.py")):
        if {"tests", "node_modules", "__pycache__"} & set(path.relative_to(REPO_ROOT).parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in values and id(node) not in skip:
                copies.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {node.value!r}")
    assert copies == []
