"""Does every dataflow we ship match the published trill schema - and does that
schema actually constrain anything?

``docs/schemas/trill.v1.json`` is the first written contract the trill format has
ever had. Before it, the shape lived only in ``TrillGenerator.generateTrill``
(the canvas writer), ``useCode.loadTrill`` (the reader) and ``agents/services.py``
(agent-applied graph edits), and ``projects/storage.py`` persisted whatever it was
handed as opaque JSON. So these tests carry more weight than a normal fixture
check: nothing else in the codebase says what a trill file is.

The schema is deliberately permissive - ``additionalProperties: true`` on every
object, because five independent writers emit overlapping but different key sets
and closing it would reject real data on the next additive field. That
permissiveness is the reason the interesting tests here are NOT the instance
validation:

- ``TestDeclaredKeyCoverage`` is what makes the permissiveness safe. An open
  object accepts an undeclared key silently, so instance validation alone cannot
  notice a field being added to an example or to the writer. This does.
- ``TestTheSchemaRejects`` proves the constraints bite. A schema that asserts
  nothing passes instance validation trivially; every case here must fail, and
  two must deliberately pass.
- ``TestWriterShapes`` covers the fields the committed corpus never exercises -
  the agent sections, ``node.title``, ``metadata.appearance``, both provenance
  keys - which are specified from the code alone and would otherwise be unverified.
- ``TestSchemaMatchesConstants`` follows ``test_agents/test_schema_matches_validator.py``:
  assert the schema's patterns and enums *equal* the authoritative constants, not
  merely that they accept today's data. That file's docstring records three real
  drifts instance validation never caught.
- ``TestNodeTypesResolve`` covers the one class of correctness the schema
  deliberately cannot express. A node's ``type`` is a coordinate into a package
  manifest, and whether it resolves depends on which packages are installed, so
  the schema checks only its shape. This checks resolution.
"""
from __future__ import annotations

import glob
import json
import os
import re

import pytest
from jsonschema import Draft202012Validator

from utk_curio.backend.app.projects.seed import _repo_root

REPO_ROOT = str(_repo_root())
SCHEMA_PATH = os.path.join(REPO_ROOT, "docs", "schemas", "trill.v1.json")
EXAMPLES_DIR = os.path.join(REPO_ROOT, "docs", "examples")
DATAFLOWS_DIR = os.path.join(EXAMPLES_DIR, "dataflows")
PACKAGES_DIR = os.path.join(REPO_ROOT, "packages")

with open(SCHEMA_PATH, encoding="utf-8") as _fh:
    SCHEMA = json.load(_fh)

VALIDATOR = Draft202012Validator(SCHEMA)
DEFS = SCHEMA["$defs"]


def _spec(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _stem(path: str) -> str:
    return os.path.basename(path)[:-5]


def _errors(doc: dict) -> list:
    """All errors for *doc*, ordered by location rather than schema traversal."""
    return sorted(
        VALIDATOR.iter_errors(doc),
        key=lambda e: [str(p) for p in e.absolute_path],
    )


def _format(errors: list, cap: int = 5) -> str:
    lines = []
    for err in errors[:cap]:
        where = ".".join(str(p) for p in err.absolute_path) or "(root)"
        lines.append(f"  {where}: {err.message}")
    if len(errors) > cap:
        lines.append(f"  ... and {len(errors) - cap} more")
    return "\n".join(lines)


NUMBERED = sorted(glob.glob(os.path.join(EXAMPLES_DIR, "[0-9][0-9]-*.json")))
# Globbed, not hardcoded: test_frontend/conftest.py enumerates these by hand and
# test_frontend/test_examples.py covers only the numbered ones, so a newly added
# dataflow would otherwise land ungated.
DATAFLOWS = sorted(glob.glob(os.path.join(DATAFLOWS_DIR, "*.json")))
CORPUS = NUMBERED + DATAFLOWS
CORPUS_IDS = [_stem(p) for p in NUMBERED] + [
    f"dataflows/{_stem(p)}" for p in DATAFLOWS
]


# --------------------------------------------------------------------------
# 1. Instance validation, and 2. the schema's own validity
# --------------------------------------------------------------------------

def test_the_schema_is_itself_valid():
    # Catches a malformed pattern, a broken $ref, or a misspelled keyword -
    # all of which a validator would otherwise ignore in silence, leaving the
    # schema green and toothless.
    Draft202012Validator.check_schema(SCHEMA)


def test_both_corpora_were_discovered():
    # Without this the parametrized tests below would be a vacuous pass.
    assert NUMBERED, f"no numbered examples found under {EXAMPLES_DIR}"
    assert DATAFLOWS, f"no dataflow fixtures found under {DATAFLOWS_DIR}"


@pytest.mark.parametrize("path", CORPUS, ids=CORPUS_IDS)
def test_every_committed_spec_validates(path: str):
    errors = _errors(_spec(path))
    assert not errors, f"{path} fails the trill schema:\n{_format(errors)}"


# --------------------------------------------------------------------------
# 3. Declared-key coverage
# --------------------------------------------------------------------------

class TestDeclaredKeyCoverage:
    """Every key the corpus actually uses must be declared in the schema.

    ``additionalProperties: true`` is deliberate but it means an undeclared key
    validates silently. Without this test, adding a field to an example - or to
    ``generateTrill`` - would leave the schema quietly incomplete and the format
    undocumented again, which is the exact failure this schema exists to end.
    """

    def _declared(self, def_name: str) -> set[str]:
        return set(DEFS[def_name].get("properties", {}))

    def _collect(self) -> dict[str, set[tuple[str, str]]]:
        """Map level -> {(key, first file it appeared in)}."""
        seen: dict[str, set[tuple[str, str]]] = {
            k: set()
            for k in ("root", "dataflow", "node", "nodeMetadata", "edge", "edgeMetadata", "datasetRef")
        }
        for path in CORPUS:
            name = os.path.basename(path)
            doc = _spec(path)
            seen["root"] |= {(k, name) for k in doc}
            flow = doc.get("dataflow", {})
            seen["dataflow"] |= {(k, name) for k in flow}
            for node in flow.get("nodes", []):
                seen["node"] |= {(k, name) for k in node}
                seen["nodeMetadata"] |= {(k, name) for k in node.get("metadata", {})}
            for edge in flow.get("edges", []):
                seen["edge"] |= {(k, name) for k in edge}
                seen["edgeMetadata"] |= {(k, name) for k in edge.get("metadata", {})}
            for ref in flow.get("datasets", []):
                if isinstance(ref, dict):
                    seen["datasetRef"] |= {(k, name) for k in ref}
        return seen

    def _assert_covered(self, level: str, declared: set[str]) -> None:
        undeclared = {
            (key, where) for key, where in self._collect()[level] if key not in declared
        }
        assert not undeclared, (
            f"{level}: keys present in the corpus but not declared in the schema - "
            f"add them to docs/schemas/trill.v1.json with a description: "
            f"{sorted(undeclared)}"
        )

    def test_root_keys_are_declared(self):
        self._assert_covered("root", set(SCHEMA["properties"]))

    def test_dataflow_keys_are_declared(self):
        # Properties live on dataflowBase; "dataflow" and "snapshotDataflow" only
        # differ in what they require.
        self._assert_covered("dataflow", self._declared("dataflowBase"))

    def test_node_keys_are_declared(self):
        self._assert_covered("node", self._declared("node"))

    def test_node_metadata_keys_are_declared(self):
        self._assert_covered("nodeMetadata", self._declared("nodeMetadata"))

    def test_edge_keys_are_declared(self):
        self._assert_covered("edge", self._declared("edge"))

    def test_edge_metadata_keys_are_declared(self):
        declared = set(DEFS["edge"]["properties"]["metadata"].get("properties", {}))
        self._assert_covered("edgeMetadata", declared)

    def test_dataset_ref_keys_are_declared(self):
        self._assert_covered("datasetRef", self._declared("datasetRef"))


# --------------------------------------------------------------------------
# 4. Rejection - the constraints have to bite
# --------------------------------------------------------------------------

def _good() -> dict:
    """A minimal spec that validates, as the starting point for one mutation."""
    return {
        "dataflow": {
            "nodes": [
                {
                    "id": "n1",
                    "type": "curio.builtin/data-loading",
                    "x": 0,
                    "y": 0,
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "content": "print(1)",
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n1"}],
            "name": "Fixture",
            "task": "",
            "timestamp": 1748990000000,
            "provenance_id": "Fixture",
        }
    }


def _node(doc: dict) -> dict:
    return doc["dataflow"]["nodes"][0]


def _attachment(**over) -> dict:
    record = {
        "attachmentId": "a" * 32,
        "coord": "agent.node-explainer@1.0.0",
        "target": {"kind": "node", "targetId": "n1"},
        "sessionId": "b" * 32,
        "revision": 1,
    }
    record.update(over)
    return record


def _mutate(fn):
    doc = _good()
    fn(doc)
    return doc


REJECTED = {
    "legacy uppercase node type": lambda d: _node(d).update(type="DATA_LOADING"),
    "node type with a trailing @": lambda d: _node(d).update(type="curio.builtin/vis-vega@"),
    "node type package with one segment": lambda d: _node(d).update(type="nodots/thing"),
    "node type major out of range": lambda d: _node(d).update(type="curio.builtin/vis-vega@99999"),
    "timestamp as a string": lambda d: d["dataflow"].update(timestamp="1748990000000"),
    "port type MUTLIPLE (the old typo)": lambda d: _node(d).update({"in": "MUTLIPLE"}),
    "port type MULTIPLE (display-only)": lambda d: _node(d).update({"in": "MULTIPLE"}),
    "node without an id": lambda d: _node(d).pop("id"),
    "node without a type": lambda d: _node(d).pop("type"),
    "edge without a source": lambda d: d["dataflow"]["edges"][0].pop("source"),
    "edge type Data": lambda d: d["dataflow"]["edges"][0].update(type="Data"),
    "keywords as strings": lambda d: _node(d)["metadata"].update(keywords=["7"]),
    "keywords as floats": lambda d: _node(d)["metadata"].update(keywords=[7.5]),
    "dashboardY without dashboardX": lambda d: _node(d).update(dashboardY=5),
    "dashboardX without dashboardY": lambda d: _node(d).update(dashboardX=5),
    "dashboardWidth without height": lambda d: _node(d).update(dashboardWidth=5),
    "agent coord pinned to a major": lambda d: d["dataflow"].update(agents=["agent.foo@1"]),
    "package coord in the agent slot": lambda d: d["dataflow"].update(agents=["curio.builtin@1"]),
    "agent id without the prefix": lambda d: d["dataflow"].update(agents=["foo@1.0.0"]),
    "duplicate packages": lambda d: d["dataflow"].update(
        packages=["curio.builtin@1", "curio.builtin@1"]
    ),
    "package without a major": lambda d: d["dataflow"].update(packages=["curio.builtin"]),
    "attachment without a revision": lambda d: d["dataflow"].update(
        agentAttachments=[{k: v for k, v in _attachment().items() if k != "revision"}]
    ),
    "revision below one": lambda d: d["dataflow"].update(
        agentAttachments=[_attachment(revision=0)]
    ),
    "node target without a targetId": lambda d: d["dataflow"].update(
        agentAttachments=[_attachment(target={"kind": "node"})]
    ),
    "connection target without a targetId": lambda d: d["dataflow"].update(
        agentAttachments=[_attachment(target={"kind": "connection"})]
    ),
    "unknown target kind": lambda d: d["dataflow"].update(
        agentAttachments=[_attachment(target={"kind": "widget", "targetId": "n1"})]
    ),
    "attachment title over the cap": lambda d: d["dataflow"].update(
        agentAttachments=[_attachment(title="z" * 41)]
    ),
    "unknown proposal status": lambda d: d["dataflow"].update(
        agentAttachments=[
            _attachment(
                activeProposal={"proposalId": "p", "tool": "node.create", "status": "maybe"}
            )
        ]
    ),
    "dataset ref with neither id nor datasetId": lambda d: d["dataflow"].update(
        datasets=[{"dirName": "d1@1"}]
    ),
    "unknown dataset origin": lambda d: d["dataflow"].update(
        datasets=[{"datasetId": "d1", "origin": "elsewhere"}]
    ),
    "dataflow without a name": lambda d: d["dataflow"].pop("name"),
    "dataflow without a timestamp": lambda d: d["dataflow"].pop("timestamp"),
    "spec without a dataflow": lambda d: d.pop("dataflow"),
}

# Cases that look like they should be rejected but must not be. Each one is a
# real shape some writer emits, or a boundary the schema deliberately leaves open.
ACCEPTED = {
    "versioned node type": lambda d: _node(d).update(type="curio.builtin/vis-vega@1"),
    "major zero": lambda d: _node(d).update(type="curio.builtin/vis-vega@0"),
    "six-segment package id": lambda d: _node(d).update(type="a.b.c.d.e.f/thing"),
    # Resolution is a manifest question, not a schema one - see TestNodeTypesResolve.
    "grammatically valid but nonexistent template": lambda d: _node(d).update(
        type="curio.builtin/not-a-real-template"
    ),
    "width without height": lambda d: _node(d).update(width=640),
    "canvas target without a targetId": lambda d: d["dataflow"].update(
        agentAttachments=[_attachment(target={"kind": "canvas"})]
    ),
    "empty graph": lambda d: d["dataflow"].update(nodes=[], edges=[]),
    "fractional coordinates": lambda d: _node(d).update(x=12.5, y=-3.25),
}


def test_the_baseline_fixture_validates():
    # If this fails every rejection case below is meaningless.
    errors = _errors(_good())
    assert not errors, f"the baseline fixture should validate:\n{_format(errors)}"


class TestTheSchemaRejects:
    @pytest.mark.parametrize("case", sorted(REJECTED), ids=sorted(REJECTED))
    def test_invalid_shape_is_rejected(self, case: str):
        doc = _mutate(REJECTED[case])
        assert _errors(doc), (
            f"the schema accepted {case!r}, so that constraint is missing or too "
            f"loose - a schema that accepts everything passes instance validation "
            f"trivially"
        )

    @pytest.mark.parametrize("case", sorted(ACCEPTED), ids=sorted(ACCEPTED))
    def test_valid_shape_is_accepted(self, case: str):
        errors = _errors(_mutate(ACCEPTED[case]))
        assert not errors, (
            f"the schema rejected {case!r}, which is a shape a real writer emits "
            f"or a boundary it should leave open:\n{_format(errors)}"
        )


# --------------------------------------------------------------------------
# 5. Writer shapes the committed corpus never exercises
# --------------------------------------------------------------------------

# Written by agents/services.py when it applies a node.create proposal: no
# `in`, no `out`, no `metadata`. This is the shape that forced the node
# `required` list down to id/type/x/y, so it is the single most load-bearing
# fixture in this file.
AGENT_NODE = {
    "id": "n1",
    "type": "curio.builtin/data-loading",
    "content": "print(1)",
    "goal": "load it",
    "x": 1,
    "y": 2,
}
AGENT_EDGE = {
    "id": "e1",
    "source": "n1",
    "target": "n1",
    "sourceHandle": "out",
    "targetHandle": "in_0",
}
FULL_ATTACHMENT = _attachment(
    intent="explain this",
    title="Explain this node",
    titleEdited=True,
    activeProposal={
        "proposalId": "p" * 32,
        "tool": "node.content.write",
        "status": "pending",
        "summary": "rewrite the loader",
        "mintSequenceId": "1",
    },
    queuedProposals=[{"proposalId": "q" * 32, "tool": "node.create", "status": "pending"}],
    planProposal={
        "proposalId": "r" * 32,
        "tool": "dataflow.plan.write",
        "status": "superseded",
    },
    builderSession={"phase": "solving", "nodeIds": ["n1"], "cancelRequested": False},
)


def _flow(**over) -> dict:
    flow = {
        "nodes": [],
        "edges": [],
        "name": "Fixture",
        "task": "",
        "timestamp": 1748990000000,
        "provenance_id": "Fixture",
    }
    flow.update(over)
    return {"dataflow": flow}


WRITER_SHAPES = {
    "agent-minimal node": _flow(nodes=[AGENT_NODE]),
    "agent-minimal edge": _flow(nodes=[AGENT_NODE], edges=[AGENT_EDGE]),
    "all three agent sections": _flow(
        nodes=[AGENT_NODE],
        agents=["agent.node-explainer@1.0.0"],
        agentAttachments=[FULL_ATTACHMENT],
        agentDefaults={"agent.node-explainer@1.0.0": {"model": "x"}},
    ),
    "canvas-scoped attachment": _flow(
        agentAttachments=[_attachment(target={"kind": "canvas"})]
    ),
    # strip_agent_state removes all three sections from a shared copy, so the
    # stripped result has to stay valid or sharing would produce invalid specs.
    "share-stripped spec": _flow(nodes=[AGENT_NODE]),
    "lean folder dataset ref": _flow(
        datasets=[
            {
                "datasetId": "d1",
                "dirName": "d1@1",
                "origin": "imported",
                "producerNodeId": None,
                "consumerNodeIds": [],
                "installedAt": "2026-08-27T00:00:00Z",
            }
        ]
    ),
    "fat legacy dataset ref": _flow(
        datasets=[
            {
                "datasetId": "d1",
                "dirName": None,
                "title": "T",
                "description": "D",
                "sourceOrigin": None,
                "uri": "http://x/y.csv",
                "path": None,
                "format": "csv",
                "sizeBytes": None,
                "rowCount": None,
                "featureCount": None,
                "sourceLabel": "src",
                "license": None,
                "tags": ["a"],
                "updatedAt": "2026-08-27T00:00:00Z",
            }
        ]
    ),
    "frontend publish dataset ref": _flow(
        datasets=[
            {
                "datasetId": "d1",
                "dirName": "d1@1",
                "origin": "hub",
                "installedAt": "2026-08-27T00:00:00Z",
                "publishedToHub": True,
            }
        ]
    ),
    "dataset ref using the legacy id alias": _flow(datasets=[{"id": "d1", "dirName": "d1@1"}]),
    "title and a palette-name appearance": _flow(
        nodes=[
            {
                **AGENT_NODE,
                "title": "Finding",
                "metadata": {"appearance": {"backgroundColor": "sunflower"}},
            }
        ]
    ),
    "hex appearance": _flow(
        nodes=[{**AGENT_NODE, "metadata": {"appearance": {"backgroundColor": "#ffcc00"}}}]
    ),
    "dataset refs and source on a node": _flow(
        nodes=[
            {
                **AGENT_NODE,
                "metadata": {
                    "datasetRefs": ["data.urbanlab.acs"],
                    "datasetSource": {
                        "datasetId": "data.urbanlab.acs",
                        "title": "ACS",
                        "format": "csv",
                        "origin": "imported",
                    },
                },
            }
        ]
    ),
    "dashboard placement": _flow(
        nodes=[
            {
                **AGENT_NODE,
                "dashboardPinned": True,
                "dashboardX": 1,
                "dashboardY": 2,
                "dashboardWidth": 3,
                "dashboardHeight": 4,
                "saveOutputDataset": True,
            }
        ]
    ),
    # Every alias useCode.loadTrill still tolerates, plus the legacy top-level
    # name that execution/workflow_spec.py still reads.
    "legacy reader aliases": {
        "name": "legacy top-level name",
        "dataflow": _flow(
            nodes=[
                {
                    **AGENT_NODE,
                    "nodeWidth": 10,
                    "nodeHeight": 20,
                    "warnings": ["stale output"],
                    "data": {"nodeType": "curio.builtin/data-loading", "packageTemplateLabel": "L"},
                    "metadata": {"width": 1, "height": 2, "nodeWidth": 3, "nodeHeight": 4},
                }
            ]
        )["dataflow"],
    },
}

_PROVENANCE = _flow(nodes=[AGENT_NODE])
_PROVENANCE["nodeProvenance"] = {
    "n1": [
        {
            "id": 1,
            "parentId": None,
            "code": "print(1)",
            "inputs": [],
            "outputs": [],
            # Free-form on purpose: the producer does not emit ISO-8601, which is
            # why startTime/endTime carry no format constraint.
            "startTime": "Aug 24 2026 17:15:6",
            "endTime": "Aug 24 2026 17:15:7",
        }
    ]
}
_PROVENANCE["dataflowProvenance"] = {
    "id": "Fixture",
    "latest": "Fixture_1748990000000",
    "graph": {
        "id": "Fixture",
        "nodes": [
            {
                "id": "Fixture_1748990000000",
                "label": "Fixture (1748990000000)",
                "timestamp": 1748990000000,
                "preview": {
                    "nodes": [
                        {
                            "id": "n1",
                            "type": "curio.builtin/data-loading",
                            "x": 0,
                            "y": 0,
                            "w": None,
                            "h": None,
                        }
                    ],
                    "edges": [{"source": "n1", "target": "n1"}],
                },
            }
        ],
        "edges": [
            {
                "id": "Fixture_0_to_Fixture_1748990000000",
                "source": "Fixture_0",
                "target": "Fixture_1748990000000",
                "label": "Node added",
            }
        ],
    },
    # Exercises the trillSnapshot recursion.
    "versions": {"Fixture_1748990000000": _flow(nodes=[AGENT_NODE])},
}
WRITER_SHAPES["provenance with a version snapshot"] = _PROVENANCE


class TestWriterShapes:
    """Shapes real writers emit that no committed example contains.

    These fields are specified from the code alone, so without fixtures they
    would be the least-verified part of the schema.
    """

    @pytest.mark.parametrize("case", sorted(WRITER_SHAPES), ids=sorted(WRITER_SHAPES))
    def test_shape_validates(self, case: str):
        errors = _errors(WRITER_SHAPES[case])
        assert not errors, f"{case} should validate:\n{_format(errors)}"


class TestStubSpecsValidate:
    """Spec-producing code outside the canvas writer.

    ``testing/routes.py:_empty_spec`` put ``name`` at the top level instead of
    inside ``dataflow``, which is the footgun documented in
    ``test_frontend/README.md``: the canvas loaded with an undefined workflow name
    and its next save was rejected. It was corrected alongside this schema, and
    this test keeps it corrected - the stub feeds the e2e suite, so a regression
    here is expensive and confusing to diagnose.
    """

    def test_the_dev_stub_spec_validates(self):
        from utk_curio.backend.app.testing.routes import _empty_spec

        errors = _errors(_empty_spec())
        assert not errors, f"testing/routes.py:_empty_spec:\n{_format(errors)}"

    def test_a_spec_missing_its_identity_is_backfilled_on_save(self):
        """``save_project``/``update_project`` fill what a client left out.

        The canvas always writes all four identity fields, but ``write_spec``
        persists whatever it is handed, so a script or agent could save a spec
        that does not describe itself. A missing ``name`` is the expensive one:
        it lands in every provenance version key as the literal string
        'undefined'.
        """
        from utk_curio.backend.app.projects.services import _ensure_dataflow_identity

        spec = {"dataflow": {"nodes": [], "edges": []}}
        assert _errors(spec), "precondition: this spec should not validate yet"

        assert _ensure_dataflow_identity(spec, "My Dataflow") is True
        errors = _errors(spec)
        assert not errors, f"backfill should produce a valid spec:\n{_format(errors)}"
        assert spec["dataflow"]["name"] == "My Dataflow"
        assert spec["dataflow"]["provenance_id"] == "My Dataflow"

    def test_the_backfill_never_overwrites_the_specs_own_name(self):
        """#148: deriving a dataflow's name from the project renamed the examples.

        ``Vega-Lite chained transforms`` became ``Vega lite chained transforms``.
        The spec's own name wins; the backfill only fills absences.
        """
        from utk_curio.backend.app.projects.services import _ensure_dataflow_identity

        spec = {
            "dataflow": {
                "nodes": [],
                "edges": [],
                "name": "Vega-Lite chained transforms",
                "task": "explore",
                "timestamp": 1748990000000,
                "provenance_id": "original-id",
            }
        }
        assert _ensure_dataflow_identity(spec, "Something Else") is False
        assert spec["dataflow"]["name"] == "Vega-Lite chained transforms"
        assert spec["dataflow"]["task"] == "explore"
        assert spec["dataflow"]["timestamp"] == 1748990000000
        assert spec["dataflow"]["provenance_id"] == "original-id"

    def test_the_backfill_always_produces_a_valid_spec(self):
        """Whatever it fills, the result has to satisfy the schema.

        The subtle one is ``timestamp: true``: Python counts a bool as an int, so
        a naive isinstance check would leave it in place, and JSON Schema does not
        count it as an integer — the spec would come out of the backfill still
        invalid.
        """
        from utk_curio.backend.app.projects.services import _ensure_dataflow_identity

        for label, flow in {
            "nothing but a graph": {"nodes": [], "edges": []},
            "bool timestamp": {"nodes": [], "edges": [], "timestamp": True},
            "float timestamp": {"nodes": [], "edges": [], "timestamp": 1.5},
            "null name": {"nodes": [], "edges": [], "name": None},
            "numeric task": {"nodes": [], "edges": [], "task": 7},
        }.items():
            spec = {"dataflow": dict(flow)}
            _ensure_dataflow_identity(spec, "Backfilled")
            errors = _errors(spec)
            assert not errors, f"{label} was not repaired:\n{_format(errors)}"

    def test_the_backfill_tolerates_junk(self):
        from utk_curio.backend.app.projects.services import _ensure_dataflow_identity

        # Never raise on a shape the readers would merely skip.
        for junk in (None, {}, {"dataflow": None}, {"dataflow": []}, "nonsense", 7):
            assert _ensure_dataflow_identity(junk, "N") is False

    def test_seeding_package_defaults_keeps_a_spec_valid(self):
        """``seed_spec_with_defaults`` must not invalidate the spec it is handed.

        It is a lockfile merge, not a spec writer: it fills in
        ``dataflow.packages`` and returns the same document. Its ``None`` branch
        is a defensive fallback that cannot be reached through ``save_project``
        (``ProjectCreate.spec`` is a required dict) and has no access to a project
        name, so it is deliberately not asserted to produce a complete trill -
        that would mean inventing a name. What matters is that a valid spec in
        stays valid on the way out.
        """
        from utk_curio.backend.app.packages.services import seed_spec_with_defaults

        merged = seed_spec_with_defaults("guest", _good())
        errors = _errors(merged)
        assert not errors, f"packages/services.py:seed_spec_with_defaults:\n{_format(errors)}"


# --------------------------------------------------------------------------
# 6. Parity between the schema and the constants it mirrors
# --------------------------------------------------------------------------

class TestSchemaMatchesConstants:
    """The schema is what people read; the code is what decides. Where they
    disagree, a spec validates green and then misbehaves at runtime.
    """

    def test_the_node_type_pattern_uses_the_backend_grammar(self):
        from utk_curio.backend.app.packages import spec_packages as sp

        expected = (
            f"^{sp._PKG_ID}/{sp._TEMPLATE_ID}(?:@{sp._MAJOR})?$"
        )
        assert DEFS["nodeTypeRef"]["pattern"] == expected, (
            "node.type must use the same grammar as _NODE_TYPE_VERSIONED_RE / "
            "_NODE_TYPE_UNVERSIONED_RE in packages/spec_packages.py"
        )

    def test_the_node_type_pattern_accepts_what_the_backend_accepts(self):
        from utk_curio.backend.app.packages import spec_packages as sp

        schema_re = re.compile(DEFS["nodeTypeRef"]["pattern"])
        for candidate in (
            "curio.builtin/data-loading",
            "curio.builtin/vis-vega@1",
            "ai.urbanlab.uhvi/uhvi-load",
            "a.b.c.d.e.f/thing@0",
        ):
            backend_ok = bool(
                sp._NODE_TYPE_VERSIONED_RE.match(candidate)
                or sp._NODE_TYPE_UNVERSIONED_RE.match(candidate)
            )
            assert bool(schema_re.match(candidate)) == backend_ok, candidate
        for candidate in ("DATA_LOADING", "nodots/thing", "curio.builtin/vis-vega@", "curio.builtin/"):
            backend_ok = bool(
                sp._NODE_TYPE_VERSIONED_RE.match(candidate)
                or sp._NODE_TYPE_UNVERSIONED_RE.match(candidate)
            )
            assert bool(schema_re.match(candidate)) == backend_ok, candidate

    def test_the_agent_coord_pattern_is_the_storage_grammar(self):
        from utk_curio.backend.app.agents.storage import AGENT_DIR_RE

        assert DEFS["agentCoord"]["pattern"] == AGENT_DIR_RE.pattern, (
            "dataflow.agents entries are agent directory names; the schema must "
            "use AGENT_DIR_RE from agents/storage.py verbatim"
        )

    def test_the_target_kinds_match_the_validator(self):
        from utk_curio.backend.app.agents.attachments import _TARGET_KINDS

        declared = DEFS["agentTarget"]["properties"]["kind"]["enum"]
        assert set(declared) == set(_TARGET_KINDS), (
            "agentAttachments[].target.kind must match _TARGET_KINDS in "
            "agents/attachments.py"
        )

    def test_the_attachment_title_cap_matches(self):
        from utk_curio.backend.app.agents.attachments import TITLE_MAX_CHARS

        assert DEFS["agentAttachment"]["properties"]["title"]["maxLength"] == TITLE_MAX_CHARS

    def test_every_agent_spec_key_is_declared(self):
        from utk_curio.backend.app.agents.project_agents import _AGENT_SPEC_KEYS

        declared = set(DEFS["dataflowBase"]["properties"])
        missing = set(_AGENT_SPEC_KEYS) - declared
        assert not missing, (
            f"the backend owns and strips these dataflow keys but the schema does "
            f"not declare them: {sorted(missing)}"
        )

    def test_the_port_types_mirror_the_frontend_enum(self):
        """node.in/out must be SupportedType plus exactly DEFAULT.

        Parsed from constants.ts rather than hardcoded, because the frontend has
        no Python-importable constant and a hardcoded copy is precisely the drift
        this test exists to catch.
        """
        source = os.path.join(
            REPO_ROOT, "utk_curio", "frontend", "urban-workflows", "src", "constants.ts"
        )
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        block = re.search(r"export enum SupportedType\s*\{(.*?)\}", text, re.S)
        assert block, "could not find the SupportedType enum in constants.ts"
        supported = set(re.findall(r'=\s*"([A-Z_]+)"', block.group(1)))
        assert supported, "parsed no members out of SupportedType"

        declared = set(DEFS["portType"]["enum"])
        assert declared == supported | {"DEFAULT"}, (
            f"node.in/out must be SupportedType plus DEFAULT. "
            f"schema-only: {sorted(declared - supported - {'DEFAULT'})}, "
            f"missing from schema: {sorted(supported - declared)}"
        )
        assert "MULTIPLE" not in declared, (
            "MULTIPLE is a display-only label in styles.tsx and is never "
            "serialized onto a node"
        )

    def test_the_port_types_extend_the_manifest_schema_by_exactly_default(self):
        """The manifest's port enum declares capability; this one records state.

        The one-value difference is intentional, so assert the relationship
        rather than either literal - otherwise someone tidies them into
        agreement and breaks one side.
        """
        manifest_path = os.path.join(REPO_ROOT, "docs", "schemas", "node-package.v4.json")
        with open(manifest_path, encoding="utf-8") as fh:
            manifest_schema = json.load(fh)
        port_types = set(
            manifest_schema["$defs"]["port"]["properties"]["types"]["items"]["enum"]
        )
        assert set(DEFS["portType"]["enum"]) == port_types | {"DEFAULT"}

    def test_the_template_id_grammar_matches_the_manifest_schema(self):
        """node.type's template half is the manifest's templates[].id grammar."""
        from utk_curio.backend.app.packages import spec_packages as sp

        manifest_path = os.path.join(REPO_ROOT, "docs", "schemas", "node-package.v4.json")
        with open(manifest_path, encoding="utf-8") as fh:
            manifest_schema = json.load(fh)
        template_id = manifest_schema["$defs"]["template"]["properties"]["id"]["pattern"]
        assert template_id == f"^{sp._TEMPLATE_ID}$", (
            "the manifest's template id grammar and the backend's _TEMPLATE_ID "
            "have diverged; node.type is built from the latter"
        )

    def test_the_schema_points_at_the_manifest_schema(self):
        # Nodes are defined by manifests; a reader who does not learn that from
        # the root description will look for template rules in the wrong file.
        assert "node-package.v4.json" in SCHEMA["description"]


# --------------------------------------------------------------------------
# 7. Cross-schema: the manifest coordinates actually resolve
# --------------------------------------------------------------------------

def _template_index() -> dict[str, dict]:
    """Map '<packageId>/<templateId>' -> template, from the in-repo packages.

    Deliberately the in-repo ``packages/`` tree rather than a user store: that is
    what makes ``curio.streetvision`` resolvable for example 10 even though the
    package is not auto-installed. Do not repoint this at ``.curio``.
    """
    index: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(PACKAGES_DIR, "*", "manifest.json"))):
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        for template in manifest.get("templates", []):
            index[f"{manifest['id']}/{template['id']}"] = template
    return index


TEMPLATES = _template_index()


class TestNodeTypesResolve:
    """The schema checks a node type's shape; only a manifest says it exists.

    This is the boundary between trill.v1.json and node-package.v4.json, and the
    reason node.type is a pattern rather than an enum.
    """

    def test_templates_were_discovered(self):
        assert TEMPLATES, f"no package manifests found under {PACKAGES_DIR}"

    @pytest.mark.parametrize("path", CORPUS, ids=CORPUS_IDS)
    def test_every_node_type_resolves_to_a_template(self, path: str):
        from utk_curio.backend.app.packages.spec_packages import unversioned_node_type

        unresolved = sorted(
            {
                node["type"]
                for node in _spec(path)["dataflow"].get("nodes", [])
                if unversioned_node_type(node.get("type", "")) not in TEMPLATES
            }
        )
        assert not unresolved, (
            f"{path} references node types with no template in packages/: "
            f"{unresolved}"
        )

    def test_content_presence_follows_the_templates_editor(self):
        """'editor: none' in the manifest is why some nodes carry no content.

        Asserted rather than assumed, so the trill schema does not have to guess
        which templates may omit content.
        """
        from utk_curio.backend.app.packages.spec_packages import unversioned_node_type

        wrong = []
        for path in CORPUS:
            for node in _spec(path)["dataflow"].get("nodes", []):
                template = TEMPLATES.get(unversioned_node_type(node.get("type", "")))
                if template is None:
                    continue
                has_content = bool(node.get("content"))
                presentation_only = template.get("editor") == "none"
                if has_content == presentation_only:
                    wrong.append(
                        f"{os.path.basename(path)}:{node['id']} "
                        f"(editor={template.get('editor')}, content={'yes' if has_content else 'no'})"
                    )
        assert not wrong, (
            "content presence should be the inverse of the template's "
            f"'editor: none': {wrong}"
        )

    def test_interaction_edges_touch_a_bidirectional_template(self):
        from utk_curio.backend.app.packages.spec_packages import unversioned_node_type

        offenders = []
        for path in CORPUS:
            flow = _spec(path)["dataflow"]
            by_id = {n["id"]: n for n in flow.get("nodes", [])}
            for edge in flow.get("edges", []):
                if edge.get("type") != "Interaction":
                    continue
                touched = [by_id.get(edge.get("source")), by_id.get(edge.get("target"))]
                templates = [
                    TEMPLATES.get(unversioned_node_type((n or {}).get("type", "")))
                    for n in touched
                ]
                if not any((t or {}).get("bidirectional") for t in templates):
                    offenders.append(f"{os.path.basename(path)}:{edge.get('id')}")
        assert not offenders, (
            "an Interaction edge must touch a node whose template declares "
            f"'bidirectional': {offenders}"
        )
