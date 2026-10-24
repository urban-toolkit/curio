"""A grammar node and the backend name a node's inputs alike, and refuse the
same Autark documents with the same sentence.

``contracts.input_table_name`` and ``autk_one_view_problem`` run the cases in
``contracts/autkGrammar.cases.json``, which
``src/tests/contracts/autkGrammarCases.test.ts`` runs through the node's own
``inputTableName`` and ``autkOneViewProblem`` (``contracts/autkGrammar.ts``).
A case names the sentence a document is told by its key in
``autkGrammar.json``, the file both sides read it from. The files are read
inside each test, so a checkout without them fails each test on its own.
"""
from __future__ import annotations

import json
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


def test_the_cases_cover_both_answers_and_name_a_sentence_the_shared_file_holds():
    assert CASES_FILE.is_file(), f"{CASES_FILE} is missing"
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    named = [case["problem"] for case in cases["oneView"] if case["problem"] is not None]
    assert 0 < len(named) < len(cases["oneView"])
    shared = _shared()
    for key in named:
        assert isinstance(shared.get(key), str), key
    assert len(cases["inputTableNames"]) > 1


@pytest.mark.parametrize("case", _cases("inputTableNames"))
def test_an_input_is_read_by_the_name_the_node_gives_it(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.agents.domain import contracts

    assert case["name"] == f"{_shared()['inputTablePrefix']}{case['position']}"
    assert contracts.input_table_name(case["position"]) == case["name"]


@pytest.mark.parametrize("case", _cases("oneView"))
def test_a_document_is_told_what_the_node_tells_it(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.agents.domain import contracts

    shared = _shared()
    expected = None if case["problem"] is None else shared[case["problem"]]
    assert expected is None or isinstance(expected, str)
    assert contracts.autk_one_view_problem(case["spec"]) == expected
    # Whatever the document, the only sentence it can be told is the file's.
    assert contracts.autk_one_view_problem(case["spec"]) in (None, shared["oneView"])
