"""A grammar node and the backend name a node's inputs alike, and refuse the
same Autark documents with the same sentence.

``contracts.input_table_name`` and ``autk_view_problem`` run the cases in
``contracts/autkGrammar.cases.json``, which
``src/tests/contracts/autkGrammarCases.test.ts`` runs through the node's own
``inputTableName`` and ``autkViewProblem`` (``contracts/autkGrammar.ts``).
A case holds the sentence a document is told, one of the ``viewRules`` of
``autkGrammar.json``, the file both sides read them from, filled. The files
are read inside each test, so a checkout without them fails each test on its
own.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CONTRACTS = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "contracts"
)
CASES_FILE = CONTRACTS / "autkGrammar.cases.json"
SHARED_FILE = CONTRACTS / "autkGrammar.json"


def _cases(kind: str):
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))[kind]
    return [pytest.param(case, id=str(case.get("name", case.get("position")))) for case in cases]


def _shared() -> dict:
    assert SHARED_FILE.is_file(), f"{SHARED_FILE} is missing"
    return json.loads(SHARED_FILE.read_text(encoding="utf-8"))


def _shape(template: str) -> re.Pattern:
    """A sentence of ``viewRules``, as a pattern its filled sentences match."""
    return re.compile("^" + re.sub(r"\\\{\w+\\\}", ".*", re.escape(template)) + "$")


def test_the_cases_cover_both_answers_and_every_rule_of_the_views():
    assert CASES_FILE.is_file(), f"{CASES_FILE} is missing"
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    said = [case["says"] for case in cases["views"] if case["says"] is not None]
    assert 0 < len(said) < len(cases["views"])
    for name, template in _shared()["viewRules"].items():
        assert any(_shape(template).match(sentence) for sentence in said), name
    assert len(cases["inputTableNames"]) > 1


@pytest.mark.parametrize("case", _cases("inputTableNames"))
def test_an_input_is_read_by_the_name_the_node_gives_it(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.agents.domain import contracts

    assert case["name"] == f"{_shared()['inputTablePrefix']}{case['position']}"
    assert contracts.input_table_name(case["position"]) == case["name"]


@pytest.mark.parametrize("case", _cases("views"))
def test_a_document_is_told_what_the_node_tells_it(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.agents.domain import contracts

    said = contracts.autk_view_problem(case["spec"])
    assert said == case["says"]
    # Whatever the document, the only sentences it can be told are the file's.
    if said is not None:
        assert any(_shape(template).match(said) for template in _shared()["viewRules"].values()), said


@pytest.mark.parametrize("case", [
    param for param in _cases("views")
    if param.values[0] is None or param.values[0]["says"] is not None
])
def test_the_document_check_refuses_it_with_that_sentence(case):
    """The agents' document check refuses a document whose views the node
    refuses, before the schema, with the node's sentence."""
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.agents.domain import document_validation as dv

    verdict = dv.validate("curio.builtin/autk-grammar", json.dumps(case["spec"]))
    assert verdict == {"status": dv.STATUS_INVALID, "detail": case["says"]}
