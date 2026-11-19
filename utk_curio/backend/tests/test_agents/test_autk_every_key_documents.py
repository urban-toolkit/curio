"""The agents' document check takes every key a node runs.

The documents of ``src/tests/fixtures/autk-every-key.json`` write every key of
autk-grammar 5.0.0's maps, plots, compute passes and data sources between
them, and an Autark node runs each (``src/tests/adapters/node/autkEveryKey.test.tsx``
and ``utk_curio/sandbox/tests/test_autk_server_data_keys.py``). So the check
the agents' documents go through (``document_validation.validate``) takes each
as it is, and an agent may write any of those keys. The fixture is read inside
each test, so a checkout without it fails each test on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "tests" / "fixtures" / "autk-every-key.json"
)
AUTK = "curio.builtin/autk-grammar"
SECTIONS = ("views", "passes", "data")


def _cases():
    if not FIXTURE.is_file():
        return [pytest.param(None, id="fixture-missing")]
    held = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = [case for section in SECTIONS for case in held.get(section, [])]
    return [pytest.param(case, id=case["name"]) for case in cases] or [pytest.param(None, id="no-cases")]


@pytest.mark.parametrize("case", _cases())
def test_the_document_check_takes_every_key_a_node_runs(case):
    assert case is not None, f"{FIXTURE} holds no documents"
    from utk_curio.backend.app.agents.domain import document_validation as dv

    assert dv.validate(AUTK, json.dumps(case["document"])) == {"status": dv.STATUS_VALID}
