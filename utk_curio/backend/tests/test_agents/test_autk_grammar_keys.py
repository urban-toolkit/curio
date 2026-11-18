"""The agents' document check refuses the documents an Autark node refuses for
their keys, with the same sentence.

``contracts.autk_key_problem`` runs the "keys" cases of
``contracts/autkGrammar.cases.json``, which
``src/tests/contracts/autkGrammarKeys.test.ts`` runs through the node's own
``autkKeyProblem``: a key autk-grammar 5 renamed is named with its new name,
and a key a node does not run yet is named as one, both with where they are
written. The files are read inside each test, so a checkout without them
fails each test on its own.
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
AUTK = "curio.builtin/autk-grammar"


def _cases(refused_only: bool = False):
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8")).get("keys", [])
    if refused_only:
        cases = [case for case in cases if case["says"] is not None]
    return [pytest.param(case, id=case["name"]) for case in cases] or [pytest.param(None, id="no-key-cases")]


def _shared() -> dict:
    assert SHARED_FILE.is_file(), f"{SHARED_FILE} is missing"
    return json.loads(SHARED_FILE.read_text(encoding="utf-8"))


def test_the_cases_refuse_every_key_the_file_names_and_run_documents_that_write_none():
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8")).get("keys", [])
    shared = _shared()
    said = [case["says"] or "" for case in cases]
    for rule in shared["renamedKeys"]:
        assert any(f'"{rule["key"]}"' in s and f'"{rule["renamedTo"]}"' in s for s in said), rule
    for rule in shared["notRunYet"]:
        assert any(f"uses {rule['what']}" in s for s in said), rule
    assert len([case for case in cases if case["says"] is None]) > 1


@pytest.mark.parametrize("case", _cases())
def test_a_document_is_told_what_the_node_tells_it_of_its_keys(case):
    assert case is not None, f"{CASES_FILE} holds no key cases"
    from utk_curio.backend.app.agents.domain import contracts

    assert contracts.autk_key_problem(case["spec"]) == case["says"]


@pytest.mark.parametrize("case", _cases(refused_only=True))
def test_the_document_check_refuses_it_with_that_sentence(case):
    assert case is not None, f"{CASES_FILE} holds no key cases"
    from utk_curio.backend.app.agents.domain import document_validation as dv

    verdict = dv.validate(AUTK, json.dumps(case["spec"]))
    assert verdict == {"status": dv.STATUS_INVALID, "detail": case["says"]}


def test_a_document_is_told_only_the_files_sentences():
    from utk_curio.backend.app.agents.domain import contracts

    shared = _shared()
    shapes = [
        re.compile("^" + re.sub(r"\\\{\w+\\\}", ".*", re.escape(template)) + "$")
        for template in (shared["renamedKey"], shared["notRunYetKey"])
    ]
    for case in json.loads(CASES_FILE.read_text(encoding="utf-8")).get("keys", []):
        said = contracts.autk_key_problem(case["spec"])
        if said is not None:
            assert any(shape.match(said) for shape in shapes), said
