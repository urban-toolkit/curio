"""Curio's agents may write autk-grammar 5.0.0's ``workspace``, which an Autark
node runs on a source, a compute pass, a map and a plot.

The agents' document check passes a document that writes it, and both flavors
of the reply schema a provider holds a reply to keep it, so an agent's
``workspace`` reaches the node as written. Everything is imported inside each
test, so a checkout without it fails each test on its own.
"""
from __future__ import annotations

import json

import pytest

AUTK = "curio.builtin/autk-grammar"

#: Two tables in two workspaces, a pass in one of them, and a map of it.
SOURCES_PASS_MAP = {
    "data": [
        {"type": "geojson", "outputTableName": "lines", "geojsonFileUrl": "lines.geojson", "workspace": "east"},
        {"type": "csv", "csvFileUrl": "a.csv", "outputTableName": "a", "workspace": "west"},
    ],
    "compute": [{
        "workspace": "east", "dataRef": "lines", "attributes": {"x": "x"},
        "wgslFunction": "return x;", "outputColumnName": "y",
    }],
    "map": {"workspace": "east", "layerRefs": [{"dataRef": "lines"}]},
}
#: A plot of a table of another workspace than the default one.
PLOT = {"plot": {"workspace": "east", "dataRef": "input_0", "mark": "bar", "axis": ["x"]}}

DOCUMENTS = [pytest.param(SOURCES_PASS_MAP, id="sources-pass-map"), pytest.param(PLOT, id="plot")]


@pytest.mark.parametrize("document", DOCUMENTS)
def test_the_document_check_passes_a_document_that_writes_workspace(document):
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.app.agents.domain import document_validation as dv

    assert contracts.autk_key_problem(document) is None
    assert dv.validate(AUTK, json.dumps(document)) == {"status": dv.STATUS_VALID}


@pytest.mark.parametrize("flavor", ["closed", "strict"])
@pytest.mark.parametrize("document", DOCUMENTS)
def test_the_reply_schema_keeps_workspace(flavor, document):
    from utk_curio.backend.app.agents.application import reply_schemas as rs

    reply = rs.autk_reply_schema(rs.FLAVOR_CLOSED if flavor == "closed" else rs.FLAVOR_STRICT)
    encoded, dropped = reply.encode(document)
    assert dropped == []
    assert json.loads(reply.decode(json.dumps(encoded))) == document
