"""autk-grammar 5.5.0's compute ``writeBack`` and sources ``after: 'compute'``,
and 5.5.1's heatmap entries, reach Curio's agents as an Autark node runs them.

A pass of any kind keeps its result in autk-db with ``writeBack``, and a source
with ``after: 'compute'`` runs once the passes have run, so it reads what they
kept there. So the ``autark`` skill gives both keys in the schema's words, the
reply schema a provider holds a reply to keeps both, in both flavors, and the
agents' document check takes both. What the grammar's run refuses in a
document its schema takes, the check refuses in the grammar's words: a source
after compute that reads a table a pass writes without ``writeBack``, an
``after`` other than ``'compute'``, and a heatmap's ``groupBy`` entry with no
``aggregateFn``, which the skill says every entry names and the reply schema
requires, in both flavors. Everything is imported inside each test, so a
checkout without it fails each test on its own.
"""
from __future__ import annotations

import json

import pytest

AUTK = "curio.builtin/autk-grammar"

#: Documents of passes that keep their results in autk-db, and sources after compute that read them.
DOCUMENTS = {
    "a clusters pass kept in autk-db, counted by a SQL query after compute and plotted": {
        "data": [{
            "type": "sql", "outputTableName": "block_sizes", "after": "compute",
            "query": "SELECT properties->'compute'->>'block' AS block, count(*) AS buildings FROM blocks GROUP BY block",
        }],
        "compute": [{"type": "clusters", "dataRef": "input_0", "outputColumnName": "block", "outputTableName": "blocks",
                     "layerType": "polygons", "writeBack": True}],
        "plot": {"dataRef": "block_sizes", "mark": "bar", "axis": ["block", "buildings"]},
    },
    "windows kept in autk-db, binned by a heatmap after compute and drawn alone": {
        "data": [{"type": "heatmap", "outputTableName": "window_density", "joinDataRef": "windows",
                  "near": {"distance": 30}, "grid": {"rows": 4, "columns": 4}, "after": "compute"}],
        "compute": [{"type": "windows", "dataRef": "input_0", "floors": 3, "outputTableName": "windows",
                     "writeBack": True}],
        "map": {"layerRefs": [{"dataRef": "window_density", "getFnv": "count.windows"}]},
    },
    "a GPGPU pass in place kept in autk-db, joined onto zones after compute": {
        "data": [{"type": "join", "dataRef": "input_1", "joinDataRef": "input_0", "after": "compute",
                  "groupBy": [{"column": "compute.y", "aggregateFn": "max"}]}],
        "compute": [{"dataRef": "input_0", "attributes": {"x": "x"}, "wgslFunction": "return x * 2.0;",
                     "outputColumnName": "y", "writeBack": True}],
        "map": {"layerRefs": [{"dataRef": "input_1", "getFnv": "sjoin.max.input_0.compute.y"}]},
    },
}

#: What the grammar's run refuses in documents its schema takes, and the words it refuses them in.
REFUSED = [
    pytest.param(
        {"data": [{"type": "join", "dataRef": "input_1", "joinDataRef": "blocks", "after": "compute"}],
         "compute": [{"type": "clusters", "dataRef": "input_0", "outputColumnName": "block", "outputTableName": "blocks"}],
         "map": {"layerRefs": [{"dataRef": "input_1"}]}},
        'Data source 0 (join) runs after compute and reads "blocks", which compute pass 0 writes without '
        'writeBack, so autk-db holds "blocks" without that pass\'s result. Set writeBack: true on the pass.',
        id="a-source-after-compute-reading-a-table-no-pass-kept",
    ),
    pytest.param(
        {"data": [{"type": "heatmap", "outputTableName": "heat", "joinDataRef": "input_0",
                   "near": {"distance": 500}, "grid": {"rows": 2, "columns": 2},
                   "groupBy": [{"column": "*", "aggregateFn": "count"}, {"column": "severity"}]}],
         "map": {"layerRefs": [{"dataRef": "heat", "getFnv": "count.input_0"}]}},
        'Heatmap "heat": the groupBy entry for column "severity" has no aggregateFn to combine the rows near a cell, '
        "and a cell holds one value; use sum, avg, count, min, max or weighted.",
        id="a-heatmap-entry-without-an-aggregate",
    ),
]


def _grammar_refusal(document: dict):
    """What ``contracts.autk_grammar_refusal`` says of *document*, or None
    from a build without it, so such a build fails on the assertion that reads it."""
    from utk_curio.backend.app.agents.domain import contracts

    refusal = getattr(contracts, "autk_grammar_refusal", None)
    return refusal(document) if refusal else None


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_the_document_check_takes_passes_kept_in_autk_db_and_sources_after_compute(name):
    """guard: the check takes each document, which writes what the grammar runs."""
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.app.agents.domain import document_validation as dv

    document = DOCUMENTS[name]
    assert contracts.autk_key_problem(document) is None
    assert dv.validate(AUTK, json.dumps(document)) == {"status": dv.STATUS_VALID}


@pytest.mark.parametrize("flavor", ["closed", "strict"])
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_the_reply_schema_keeps_write_back_and_after(flavor, name):
    """A reply that writes the keys keeps them, whole, and fits the schema a provider holds it to."""
    import jsonschema

    from utk_curio.backend.app.agents.application import reply_schemas as rs

    reply = rs.autk_reply_schema(rs.FLAVOR_CLOSED if flavor == "closed" else rs.FLAVOR_STRICT)
    document = DOCUMENTS[name]
    encoded, dropped = reply.encode(document)
    assert dropped == []
    jsonschema.Draft202012Validator(reply.schema).validate(encoded)
    assert json.loads(reply.decode(json.dumps(encoded))) == document


@pytest.mark.parametrize("document, said", REFUSED)
def test_the_document_check_refuses_what_the_grammars_run_refuses_in_its_words(document, said):
    from utk_curio.backend.app.agents.domain import document_validation as dv

    verdict = dv.validate(AUTK, json.dumps(document))
    assert verdict["status"] == dv.STATUS_INVALID, verdict
    assert said in verdict["detail"], verdict["detail"]
    assert _grammar_refusal(document) == said


def test_a_source_after_compute_is_told_when_its_after_names_no_phase():
    """The schema refuses an ``after`` other than ``'compute'``, and the
    grammar's run refuses it in its own words, which the check gives too."""
    document = {"data": [{"type": "csv", "outputTableName": "t", "csvObject": [["a"], [1]], "after": "map"}]}
    assert _grammar_refusal(document) == (
        "Data source 0 (csv): after must be 'compute', the one phase a source runs after, not \"map\"."
    )


@pytest.mark.parametrize("flavor", ["closed", "strict"])
def test_the_reply_schema_has_every_heatmap_entry_name_its_aggregate(flavor):
    """The grammar's schema leaves a heatmap entry's ``aggregateFn`` out of what
    it requires, and its run refuses an entry without one: the reply schema
    requires it, and does not take null for it in the strict flavor."""
    import jsonschema

    from utk_curio.backend.app.agents.application import reply_schemas as rs

    reply = rs.autk_reply_schema(rs.FLAVOR_CLOSED if flavor == "closed" else rs.FLAVOR_STRICT)
    defs = reply.schema.get("$defs") or reply.schema.get("definitions") or {}
    group_by = defs["HeatmapSourceSpec"]["properties"]["groupBy"]
    lists = [group_by, *group_by.get("anyOf", [])]
    [entry] = [held["items"] for held in lists if isinstance(held.get("items"), dict)]
    assert "aggregateFn" in entry["required"], entry
    assert "$ref" in entry["properties"]["aggregateFn"], entry["properties"]["aggregateFn"]

    heatmap = {"type": "heatmap", "outputTableName": "heat", "joinDataRef": "input_0",
               "near": {"distance": 500}, "grid": {"rows": 2, "columns": 2}}

    def encoded(entry: dict) -> object:
        document = {"data": [{**heatmap, "groupBy": [entry]}], "map": {"layerRefs": [{"dataRef": "heat"}]}}
        return reply.encode(document)[0]

    # An entry that names its aggregate fits; one that names none, or null, does not.
    jsonschema.Draft202012Validator(reply.schema).validate(encoded({"column": "severity", "aggregateFn": "avg"}))
    for entry in ({"column": "severity"}, {"column": "severity", "aggregateFn": None}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(reply.schema).validate(encoded(entry))


def test_the_autark_skill_gives_write_back_after_and_the_heatmap_entries():
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.tests._support.prompt_files import prompt_text

    text = prompt_text("autark/SKILL.md")
    lines = text.splitlines()
    after = [line for line in lines if line.startswith('  - Every source also takes "after": ')]
    write_back = [line for line in lines if line.startswith('  - Every pass also takes "writeBack": ')]
    assert len(after) == 1 and len(write_back) == 1, (after, write_back)
    assert 'every entry names its "aggregateFn", and a heatmap without "groupBy" has one band that counts the rows' in text

    # Each in the schema's words, less its note on which adapters read it.
    schema = contracts.load_autk_schema()
    phase = contracts._definition(schema, "SourcePhase")["description"].split(" Read by the ", 1)[0]
    _description, branches = contracts._compute_passes(schema)[contracts.GPGPU_PASS]
    written_back = branches[0]["properties"]["writeBack"]["description"].split(" Read by the ", 1)[0]
    assert after == [f'  - Every source also takes "after": {phase}']
    assert write_back == [f'  - Every pass also takes "writeBack": {written_back}']
