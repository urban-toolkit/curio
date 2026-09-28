"""Reply schemas: an Autark document written under its schema.

A content generation run for an Autark node, on a provider that takes a reply
schema, holds the reply to a projection of the vendored Autark schema (closed
objects, maps as entries, open and recursive parts as JSON strings, no
conditionals) and decodes it back into the document the validator then checks.
Anything else (Vega-Lite, code, Gemini, an endpoint that refused one) is asked
as before.
"""

from __future__ import annotations

import dataclasses
import json

import jsonschema
import pytest

from utk_curio.backend.app.agents import (
    delegation,
    document_validation,
    reply_schemas as rs,
    services,
    testing_provider,
)
from utk_curio.backend.app.agents.providers import ProviderConfig
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.tests.test_agents.test_document_validation import (
    AUTK,
    VEGA,
    _shipped_autk_documents,
)
from utk_curio.backend.tests.test_agents.test_verified_rounds import _drive, _Exec

NCB = "agent.node-content-builder@1.0.0"
KEY = "4343"
PID = "p-reply-schema"

#: A document every part of which the vendored schema declares, drawn from the
#: node's own input (no source a grounding gate would probe).
DOCUMENT = {
    "compute": [{"dataRef": "upstream", "wglsFunction": "fn main() {}",
                 "attributes": {"height": "properties.height"}, "outputColumnName": "shade"}],
    "map": {"layerRefs": [{"dataRef": "upstream"}]},
}


@pytest.fixture(autouse=True)
def _fresh():
    testing_provider.reset()
    rs._refused.clear()
    yield
    testing_provider.reset()
    rs._refused.clear()


def _config(**kw) -> ProviderConfig:
    base = dict(api_key="", api_type="testing", base_url="", model="scripted", config_id="llm-00000000000b")
    base.update(kw)
    return ProviderConfig(**base)


def _walk(node, visit, path="#"):
    visit(node, path)
    if isinstance(node, dict):
        for key, value in node.items():
            _walk(value, visit, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _walk(value, visit, f"{path}[{i}]")


@pytest.mark.parametrize("flavor", [rs.FLAVOR_CLOSED, rs.FLAVOR_STRICT])
class TestTheProjection:
    def test_it_is_a_valid_schema_with_an_object_at_its_root(self, flavor):
        schema = rs.autk_reply_schema(flavor).schema
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object" and "anyOf" not in schema

    def test_every_object_is_closed_and_nothing_either_provider_refuses_is_left(self, flavor):
        problems = []

        def visit(node, path):
            if not isinstance(node, dict):
                return
            if node.get("type") == "object":
                if node.get("additionalProperties") is not False:
                    problems.append(("open object", path))
                if flavor == rs.FLAVOR_STRICT and set(node.get("required", ())) != set(node.get("properties", {})):
                    problems.append(("a key not required", path))
            for keyword in ("allOf", "if", "then", "else", "const", "minItems", "maxItems",
                            "pattern", "format", "minimum", "maximum", "not", "x-curio"):
                if keyword in node and not path.endswith("/properties"):
                    problems.append((keyword, path))

        _walk(rs.autk_reply_schema(flavor).schema, visit)
        assert problems == []

    def test_no_definition_reaches_itself(self, flavor):
        schema = rs.autk_reply_schema(flavor).schema
        assert rs._cycles(schema["$defs"]) == set()

    def test_objects_nest_no_deeper_than_openai_allows(self, flavor):
        schema = rs.autk_reply_schema(flavor).schema
        defs = schema["$defs"]

        def depth(node, seen=()):
            if isinstance(node, dict):
                if "$ref" in node:
                    name = node["$ref"].rsplit("/", 1)[-1]
                    return 0 if name in seen else depth(defs[name], (*seen, name))
                own = 1 if node.get("type") == "object" else 0
                return own + max([depth(v, seen) for k, v in node.items() if k != "$defs"] or [0])
            if isinstance(node, list):
                return max([depth(v, seen) for v in node] or [0])
            return 0

        assert depth(schema) <= 10

    def test_every_shipped_document_round_trips(self, flavor):
        """Encoded as a constrained reply, each shipped document is valid
        under the projection and decodes back to itself, less only the keys
        the vendored schema does not declare, and still validates."""
        reply = rs.autk_reply_schema(flavor)
        validator = jsonschema.Draft202012Validator(reply.schema)
        documents = _shipped_autk_documents()
        assert len(documents) >= 28
        for where, content in documents:
            document = json.loads(content)
            encoded, dropped = reply.encode(document)
            assert validator.is_valid(encoded), (where, next(validator.iter_errors(encoded)).message)
            decoded = json.loads(reply.decode(json.dumps(encoded)))
            assert decoded == _without(document, dropped), where
            assert document_validation.validate(AUTK, json.dumps(decoded))["status"] == "valid", where


def _without(document, paths):
    """*document* less the keys at *paths* (``$.a[0].b``)."""
    document = json.loads(json.dumps(document))
    for path in paths:
        parts = path[2:].replace("]", "").replace("[", ".").split(".")
        cursor = document
        for part in parts[:-1]:
            cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
        cursor.pop(parts[-1], None)
    return document


class TestDecoding:
    def test_maps_json_strings_and_nulls_become_the_document_again(self):
        reply = rs.autk_reply_schema(rs.FLAVOR_STRICT)
        document = {
            "compute": [{
                "dataRef": "points", "wglsFunction": "fn main() {}",
                "attributes": {"height": "properties.height"},
                "outputColumnName": "shade",
            }],
            "data": [{"type": "geojson", "outputTableName": "zones", "geojsonObject": {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {"name": "a"},
                              "geometry": {"type": "Point", "coordinates": [1, 2]}}],
            }}],
            "map": [{"layerRefs": [{"dataRef": "zones"}]}],
        }
        encoded, dropped = reply.encode(document)
        assert dropped == []
        compute = encoded["compute"][0]
        # A map is a list of entries.
        assert compute["attributes"] == [{"key": "height", "value": "properties.height"}]
        # Recursion is cut where it occurs: a geometry, and an open object,
        # are JSON strings.
        feature = encoded["data"][0]["geojsonObject"]["features"][0]
        assert json.loads(feature["geometry"]) == {"type": "Point", "coordinates": [1, 2]}
        assert json.loads(feature["properties"]) == {"name": "a"}
        assert encoded["plot"] is None  # strict mode: every key, the optional ones null
        assert json.loads(reply.decode(json.dumps(encoded))) == document

    def test_a_reply_that_is_not_a_document_is_left_for_the_validator(self):
        reply = rs.autk_reply_schema(rs.FLAVOR_CLOSED)
        assert reply.decode("I cannot write this.") == "I cannot write this."
        assert reply.decode("[1, 2]") == "[1, 2]"

    def test_a_form_the_projection_does_not_know_is_refused_loudly(self):
        source = {"$ref": "#/definitions/Root", "definitions": {"Root": {
            "type": "object", "properties": {"x": {"allOf": [{"type": "string"}, {"minLength": 2}]}}}}}
        with pytest.raises(rs.ReplySchemaError):
            rs._Projector(source, rs.FLAVOR_CLOSED).project(source["definitions"]["Root"])


class TestWhenARunSendsOne:
    def test_only_an_autark_document_on_a_provider_that_takes_one(self, tmp_curio):
        testing_provider.script_chat_capabilities(structured_output=True)
        assert rs.for_run(_config(), KEY, rs.GRAMMAR_AUTK).flavor == rs.FLAVOR_STRICT
        assert rs.for_run(_config(), KEY, "vega-lite") is None
        assert rs.for_run(_config(), KEY, None) is None
        testing_provider.script_chat_capabilities(structured_output=False)
        assert rs.for_run(_config(), KEY, rs.GRAMMAR_AUTK) is None

    @pytest.mark.parametrize("api_type, endpoint, flavor", [
        ("anthropic", "", rs.FLAVOR_CLOSED),
        ("openai_compatible", "https://api.openai.com/v1", rs.FLAVOR_STRICT),
        ("gemini", "", None),
    ])
    def test_each_provider_gets_its_own_flavor(self, tmp_curio, api_type, endpoint, flavor):
        reply = rs.for_run(_config(api_type=api_type, base_url=endpoint, api_key="k"), KEY, rs.GRAMMAR_AUTK)
        assert (reply.flavor if reply else None) == flavor

    def test_an_endpoint_that_refused_one_is_not_sent_another(self, tmp_curio):
        testing_provider.script_chat_capabilities(structured_output=True)
        rs.note_refused(_config())
        assert rs.for_run(_config(), KEY, rs.GRAMMAR_AUTK) is None
        assert rs.for_run(_config(model="another"), KEY, rs.GRAMMAR_AUTK) is not None

    def test_a_definition_without_the_instruction_for_it_is_never_constrained(self, tmp_curio):
        from utk_curio.backend.app.agents import builtin

        testing_provider.script_chat_capabilities(structured_output=True)
        manifest = builtin.get_builtin_manifest(NCB)
        inputs = {"nodeType": AUTK}
        assert delegation._reply_schema(KEY, PID, manifest, "node.content.generate", inputs, _config())
        bare = dataclasses.replace(manifest, prompts={
            k: v for k, v in manifest.prompts.items() if k != rs.AUTK_PROMPT_KEY})
        assert delegation._reply_schema(KEY, PID, bare, "node.content.generate", inputs, _config()) is None
        assert delegation._reply_schema(KEY, PID, manifest, "node.explain", inputs, _config()) is None


def _delegate(inputs, config=None):
    return delegation.run_delegate(
        KEY, PID, NCB, "node.content.generate", inputs, config or _config(),
        parent_execution_id="parent", parent_coord="agent.dataflow-builder@1.0.0", attachment_id=None,
    )


class TestADelegatedDocument:
    @pytest.fixture(autouse=True)
    def _project(self, tmp_curio):
        projects_storage.write_spec(KEY, PID, {"dataflow": {"nodes": [
            {"id": "n1", "type": AUTK, "goal": "map the points", "content": ""},
            {"id": "n2", "type": VEGA, "goal": "chart the points", "content": ""},
        ], "edges": [], "name": "wf", "task": "t"}})

    def test_the_reply_is_held_to_the_schema_and_decoded(self):
        testing_provider.script_chat_capabilities(structured_output=True)
        reply = rs.autk_reply_schema(rs.FLAVOR_STRICT)
        encoded, _ = reply.encode(DOCUMENT)
        testing_provider.push_reply(json.dumps(encoded))
        status, text, record = _delegate({"nodeType": AUTK, "intent": "map the points"})
        assert status == "ok"
        assert json.loads(text) == DOCUMENT
        (offer,) = testing_provider.offered()
        assert offer["replySchema"] == "autk_grammar_document"
        system = testing_provider.captured()[0][0]["content"]
        assert "Your reply is held to the Autark document's schema" in system
        assert "state that conclusion as your WHOLE reply" not in system
        assert record["pins"]["replySchema"] == "autk_grammar_document"

    @pytest.mark.parametrize("inputs", [
        {"nodeType": VEGA, "intent": "chart the points"},
        {"nodeType": "curio.builtin/computation-analysis", "intent": "count"},
    ])
    def test_another_kind_is_asked_as_before(self, inputs):
        testing_provider.script_chat_capabilities(structured_output=True)
        testing_provider.push_reply("{}")
        status, text, record = _delegate(inputs)
        assert status == "ok" and text == "{}"
        assert testing_provider.offered()[0]["replySchema"] is None
        assert "state that conclusion as your WHOLE reply" in testing_provider.captured()[0][0]["content"]
        assert "replySchema" not in record["pins"]

    def test_without_the_capability_it_is_asked_as_before(self):
        testing_provider.push_reply("{}")
        _delegate({"nodeType": AUTK})
        assert testing_provider.offered()[0]["replySchema"] is None

    def test_a_refused_schema_is_asked_again_without_it(self):
        testing_provider.script_chat_capabilities(structured_output=True)
        testing_provider.push_replies(
            {"error": "response_format json_schema is not supported for this model", "status": 400},
            json.dumps(DOCUMENT),
        )
        status, text, record = _delegate({"nodeType": AUTK})
        assert status == "ok" and json.loads(text) == DOCUMENT
        assert [o["replySchema"] for o in testing_provider.offered()] == ["autk_grammar_document", None]
        retry_system = testing_provider.captured()[1][0]["content"]
        assert "state that conclusion as your WHOLE reply" in retry_system
        assert record["pins"]["replySchemaRefused"] is True and "replySchema" not in record["pins"]
        # The next run on that model asks without one from the start.
        testing_provider.push_reply(json.dumps(DOCUMENT))
        _delegate({"nodeType": AUTK})
        assert testing_provider.offered()[2]["replySchema"] is None

    def test_the_correction_loop_runs_on_decoded_documents(self, app):
        """A constrained document the validator refuses is a round like any
        other, and the corrected one is what the loop keeps."""
        from utk_curio.backend.app.agents import builtin

        testing_provider.script_chat_capabilities(structured_output=True)
        reply = rs.autk_reply_schema(rs.FLAVOR_STRICT)
        refused, _ = reply.encode({"map": {"layerRefs": []}})
        fixed, _ = reply.encode(DOCUMENT)
        testing_provider.push_replies(json.dumps(refused), json.dumps(fixed))
        node = {"id": "n1", "type": AUTK, "goal": "map the points", "content": ""}
        spec = projects_storage.read_spec(KEY, PID)
        resolution = delegation.Resolution("ok", NCB, builtin.get_builtin_manifest(NCB))
        with app.test_request_context():
            events, outcome = _drive(services._verified_content_rounds(
                KEY, PID, spec=spec, node=node, resolution=resolution, config=_config(),
                parent_execution_id="exec-1", parent_coord="agent.dataflow-builder@1.0.0",
                attachment_id="att-1", exec_fn=_Exec(),
                grounding_loop_ctx={"granted": [], "manifest": None},
            ))
        assert [a["kind"] for a in outcome["attempts"]][0] == "document-invalid"
        assert json.loads(outcome["candidate"]) == DOCUMENT
        assert (outcome["evidence"] or {}).get("documentValidated") == "autk-grammar"
        assert [o["replySchema"] for o in testing_provider.offered()] == ["autk_grammar_document"] * 2
        correction = testing_provider.captured()[1][-1]["content"]
        assert "document refused" in correction
