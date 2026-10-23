"""``projects/node_provenance.py`` keys a saved dataflow's node histories as a load does.

Both sides run the cases in ``nodeProvenanceKeys.cases.json`` beside
``utils/nodeProvenanceKeys.ts`` (``src/tests/utils/nodeProvenanceKeysCases.test.ts``
is the other half): the agents' ``node.history.read`` reads a node's history
under the key its Provenance drawer finds it by, older dataflows' keys
included.

``node_provenance`` is imported inside each test, so a checkout without it
fails each test on its own instead of failing the whole collection.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CASES_FILE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "utils" / "nodeProvenanceKeys.cases.json"
)


def _cases():
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


@pytest.mark.parametrize("case", _cases())
def test_a_saved_history_is_keyed_as_a_load_keys_it(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.projects import node_provenance

    assert node_provenance.rekey_node_provenance(case["saved"], case["nodeIds"]) == case["keyed"]


def test_the_saved_histories_are_left_as_they_were():
    """Keying reads what the dataflow holds and writes none of it."""
    from utk_curio.backend.app.projects import node_provenance

    saved = {
        "node-1": [{"id": 2, "parentId": 1, "code": "b"}],
        "loading@1-node-1": [{"id": 1, "parentId": None, "code": "a"}],
    }
    before = json.loads(json.dumps(saved))
    keyed = node_provenance.rekey_node_provenance(saved, ["node-1"])
    assert [record["id"] for record in keyed["node-1"]] == [1, 2]
    assert saved == before
