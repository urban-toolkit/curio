"""dev/121 — the canonical graph form and the dependency scan.

Offline: no stack, no provider, no store. These tests pin the properties the
whole harness rests on -- that a reconstruction which differs only in ids,
positions, order or spelling is INDISTINGUISHABLE from the example, and that
anything a person would call a difference survives normalization.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.evaluation.canonical import (
    CanonicalGraph,
    CEdge,
    CNode,
    Sources,
    TemplateFacts,
    canonical_graph_from_spec,
    edge_kind,
    edge_slot,
    role_for_template,
)
from utk_curio.backend.app.agents.evaluation.dependencies import (
    declared_dependencies,
    referenced_sources,
    url_allowed,
)
from utk_curio.backend.app.agents.evaluation.fixtures import (
    FIXTURE_SCHEMA_PATH,
    example_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _template_index() -> dict:
    """Manifest facts for every shipped template, read from the manifests.

    Deliberately the same derivation the authoring aid uses
    (``scripts/example_fixture_skeleton.py::template_index``) and the same
    source the schema suite reads (``test_trill_schema.py::_template_index``):
    one place says what a node kind is (``DEC-062``).
    """
    index: dict = {}
    for manifest_path in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package_id = str(manifest.get("id") or "")
        for template in manifest.get("templates") or []:
            index[f"{package_id}/{template['id']}"] = TemplateFacts(
                template_id=str(template["id"]),
                category=str(template.get("category") or "computation"),
                engine=str(template.get("engine") or "python"),
                editor=str(template.get("editor") or "code"),
                has_code=bool(template.get("hasCode")),
                has_grammar=bool(template.get("hasGrammar")),
                behavior=template.get("behavior"),
                backend_handler=template.get("backendHandler"),
            )
    return index


TEMPLATES = _template_index()


def _spec(nodes, edges, **dataflow):
    return {"dataflow": {"nodes": nodes, "edges": edges, **dataflow}}


def _node(node_id, node_type, content="return 1", **extra):
    return {"id": node_id, "type": node_type, "content": content, **extra}


def _edge(source, target, **extra):
    return {"id": f"e-{source}-{target}", "source": source, "target": target, **extra}


LOADER = "curio.builtin/data-loading"
TRANSFORM = "curio.builtin/data-transformation"
VEGA = "curio.builtin/vis-vega"
POOL = "curio.builtin/data-pool"
#: A node that takes several inputs, one per circle (what a Merge Flow fed).
ANALYSIS = "curio.builtin/computation-analysis"


class TestTheSchemaItself:
    def test_the_fixture_schema_is_a_valid_schema(self):
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(
            json.loads(FIXTURE_SCHEMA_PATH.read_text(encoding="utf-8"))
        )

    def test_the_schema_forbids_unknown_top_level_keys(self):
        from jsonschema import Draft202012Validator

        schema = json.loads(FIXTURE_SCHEMA_PATH.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        # A fixture is an answer key: a typo'd field name must fail loudly
        # rather than be ignored the way trill's additive spec allows.
        validator = Draft202012Validator(schema)
        assert list(validator.iter_errors({"fixtureId": "x", "prmopt": "y"}))


class TestNormalizationIgnoresWhatItMust:
    """Generated ids, layout, order, formatting -- none of it is a difference."""

    def test_regenerated_ids_and_positions_do_not_change_the_graph(self):
        a = _spec(
            [_node("n1", LOADER), _node("n2", TRANSFORM)],
            [_edge("n1", "n2")],
        )
        b = _spec(
            [
                _node("7f3c-uuid", LOADER, x=900, y=-12, width="554", height="1613"),
                _node("beef-uuid", TRANSFORM, x=-5.5, y=3.25),
            ],
            [_edge("7f3c-uuid", "beef-uuid")],
        )
        assert canonical_graph_from_spec(a, templates=TEMPLATES) == canonical_graph_from_spec(
            b, templates=TEMPLATES
        )

    def test_node_and_edge_order_do_not_change_the_graph(self):
        nodes = [_node("a", LOADER), _node("b", TRANSFORM), _node("c", VEGA)]
        edges = [_edge("a", "b"), _edge("b", "c")]
        forward = canonical_graph_from_spec(_spec(nodes, edges), templates=TEMPLATES)
        reversed_ = canonical_graph_from_spec(
            _spec(list(reversed(nodes)), list(reversed(edges))), templates=TEMPLATES
        )
        assert forward == reversed_

    def test_every_legal_type_spelling_canonicalizes_to_one_graph(self):
        """dev/93 (DEC-062): versioned, legacy-enum and canonical spellings are
        all emitted by the system itself, so all three must reduce alike."""
        canonical = _spec([_node("a", LOADER)], [])
        versioned = _spec([_node("a", f"{LOADER}@1")], [])
        legacy = _spec([_node("a", "DATA_LOADING")], [])
        one = canonical_graph_from_spec(canonical, templates=TEMPLATES)
        assert one == canonical_graph_from_spec(versioned, templates=TEMPLATES)
        assert one == canonical_graph_from_spec(legacy, templates=TEMPLATES)
        assert one.nodes[0].type == LOADER

    def test_timestamps_names_and_metadata_are_not_part_of_the_graph(self):
        bare = _spec([_node("a", LOADER)], [])
        dressed = _spec(
            [_node("a", LOADER, metadata={"keywords": [7, 9]}, goal="load it")],
            [],
            name="A name",
            description="A description",
            timestamp=1778217921503,
            provenance_id="p-1",
            task="",
        )
        assert canonical_graph_from_spec(bare, templates=TEMPLATES) == (
            canonical_graph_from_spec(dressed, templates=TEMPLATES)
        )

    def test_content_text_is_not_compared_only_its_presence(self):
        one = _spec([_node("a", LOADER, content="import geopandas\nreturn gdf")], [])
        other = _spec([_node("a", LOADER, content="import pandas as pd\nreturn df")], [])
        empty = _spec([_node("a", LOADER, content="   ")], [])
        assert canonical_graph_from_spec(one, templates=TEMPLATES) == (
            canonical_graph_from_spec(other, templates=TEMPLATES)
        )
        assert canonical_graph_from_spec(empty, templates=TEMPLATES).nodes[0].has_content is False


class TestNormalizationKeepsWhatItMust:
    def test_a_missing_node_changes_the_graph(self):
        full = _spec([_node("a", LOADER), _node("b", TRANSFORM)], [_edge("a", "b")])
        short = _spec([_node("a", LOADER)], [])
        assert canonical_graph_from_spec(full, templates=TEMPLATES) != (
            canonical_graph_from_spec(short, templates=TEMPLATES)
        )

    def test_a_different_template_changes_the_graph(self):
        one = _spec([_node("a", LOADER), _node("b", TRANSFORM)], [_edge("a", "b")])
        other = _spec([_node("a", LOADER), _node("b", "curio.builtin/computation-analysis")],
                      [_edge("a", "b")])
        assert canonical_graph_from_spec(one, templates=TEMPLATES).type_counts() != (
            canonical_graph_from_spec(other, templates=TEMPLATES).type_counts()
        )

    def test_edge_direction_is_kept(self):
        forward = canonical_graph_from_spec(
            _spec([_node("a", LOADER), _node("b", TRANSFORM)], [_edge("a", "b")]),
            templates=TEMPLATES,
        )
        backward = canonical_graph_from_spec(
            _spec([_node("a", LOADER), _node("b", TRANSFORM)], [_edge("b", "a")]),
            templates=TEMPLATES,
        )
        assert forward.edges != backward.edges

    def test_a_dangling_edge_is_dropped_not_crashed_on(self):
        graph = canonical_graph_from_spec(
            _spec([_node("a", LOADER)], [_edge("a", "ghost")]), templates=TEMPLATES
        )
        assert graph.edges == ()


class TestEdgeKindAndSlot:
    """dev/112's two facts a reconstruction must get right."""

    def test_the_trill_interaction_type_is_recognised(self):
        assert edge_kind({"type": "Interaction"}) == "interaction"
        assert edge_kind({}) == "data"
        assert edge_kind({"type": "Data"}) == "data"

    def test_symmetric_handles_are_recognised_as_interaction(self):
        assert edge_kind({"sourceHandle": "in/out", "targetHandle": "in/out"}) == "interaction"
        assert edge_kind({"sourceHandle": "out", "targetHandle": "in/out"}) == "data"

    @pytest.mark.parametrize(
        "handle,expected",
        [("in_0", 0), ("in_1", 1), ("in_4", 4), ("in_12", 12), ("in", None),
         ("DEFAULT", None), (None, None), ("out", None), ("in/out", None),
         ("in_x", None), ("", None)],
    )
    def test_input_circles_come_from_the_target_handle(self, handle, expected):
        # Circle 0 is the plain "in" handle, a single-input port's own; the
        # circles after it are "in_1", "in_2", ...
        assert edge_slot({"targetHandle": handle}) == expected

    def test_an_interaction_edge_is_kept_as_such_in_the_graph(self):
        graph = canonical_graph_from_spec(
            _spec(
                [_node("v", VEGA, content="{}"), _node("p", POOL, content="")],
                [_edge("p", "v", type="Interaction")],
            ),
            templates=TEMPLATES,
        )
        assert len(graph.interaction_edges()) == 1

    def test_an_interaction_edge_does_not_make_its_target_a_transform(self):
        """Role derivation walks DATA edges only: a node fed solely by an
        interaction link is still the head of its flow."""
        graph = canonical_graph_from_spec(
            _spec(
                [_node("l", LOADER), _node("p", POOL, content="")],
                [_edge("p", "l", type="Interaction")],
            ),
            templates=TEMPLATES,
        )
        roles = {n.type: n.role for n in graph.nodes}
        assert roles[LOADER] == "loader"


class TestRoles:
    def test_roles_come_from_manifest_facts_and_position(self):
        assert role_for_template(TEMPLATES[LOADER], has_incoming_data_edge=False) == "loader"
        assert role_for_template(TEMPLATES[LOADER], has_incoming_data_edge=True) == "transform"
        assert role_for_template(TEMPLATES[VEGA], has_incoming_data_edge=True) == "visualization"
        assert role_for_template(TEMPLATES[POOL], has_incoming_data_edge=True) == "pool"
        assert role_for_template(
            TEMPLATES["curio.builtin/computation-analysis"], has_incoming_data_edge=True
        ) == "analysis"
        assert role_for_template(
            TEMPLATES["curio.builtin/data-export"], has_incoming_data_edge=True
        ) == "export"

    def test_a_flow_template_falls_through_to_the_generic_rules(self):
        """The ``merge`` role left with the Merge Flow (#662): no template
        derives it, and a ``flow``-category template is judged like any
        other, by its code."""
        from utk_curio.backend.app.agents.evaluation.canonical import ROLES

        assert "merge" not in ROLES
        assert "curio.builtin/merge-flow" not in TEMPLATES
        no_code = TemplateFacts(template_id="fan-in", category="flow", editor="none",
                                behavior="merge-flow")
        assert role_for_template(no_code, has_incoming_data_edge=True) == "endpoint"
        assert role_for_template(no_code, has_incoming_data_edge=False) == "endpoint"
        coded = TemplateFacts(template_id="fan-in", category="flow", has_code=True)
        assert role_for_template(coded, has_incoming_data_edge=True) == "analysis"
        for facts in TEMPLATES.values():
            for incoming in (False, True):
                assert role_for_template(facts, has_incoming_data_edge=incoming) in ROLES, facts

    def test_a_template_with_no_code_is_an_endpoint_never_executable(self):
        """dev/119 (DEC-076): spatial-join has no code the sandbox could run --
        a backend endpoint does its work. The harness must not credit or
        penalise it as an executable node."""
        facts = TEMPLATES["curio.builtin/spatial-join"]
        assert facts.executable is False
        assert role_for_template(facts, has_incoming_data_edge=True) == "endpoint"

    def test_an_unknown_template_claims_nothing(self):
        assert role_for_template(None, has_incoming_data_edge=True) == "endpoint"
        graph = canonical_graph_from_spec(
            _spec([_node("a", "someone.invented/a-kind")], []), templates=TEMPLATES
        )
        assert graph.nodes[0].executable is False
        assert graph.nodes[0].type == "someone.invented/a-kind"

    def test_executability_is_the_dec_076_derivation(self):
        assert TEMPLATES[LOADER].executable is True
        assert TEMPLATES[VEGA].executable is False  # grammar, no code
        assert TEMPLATES["curio.builtin/js-computation"].executable is True  # javascript
        assert TEMPLATES["curio.example-ui/column-filter"].executable is False  # package, no code
        # A model package's node with no source of its own: python, so executable.
        assert TEMPLATES["model.curio.ddrnet23-slim/image-segmentation"].executable is True


class TestDependencies:
    def test_declared_refs_are_the_source_of_truth(self):
        spec = _spec(
            [_node("a", LOADER, content='p = curio_data_path("data.x.y")')],
            [],
            datasets=[{"datasetId": "data.x.y", "dirName": "data.x.y@1", "origin": "imported"}],
            packages=["curio.weather@1"],
        )
        deps = declared_dependencies(spec)
        assert deps.datasets == ("data.x.y",)
        assert deps.packages == ("curio.weather@1",)

    def test_a_package_template_used_but_not_declared_is_undeclared(self):
        spec = _spec([_node("a", "model.curio.ddrnet23-slim/image-segmentation", content="")], [], packages=[])
        deps = declared_dependencies(spec, installed_majors_by_pkg={"model.curio.ddrnet23-slim": [1]})
        assert deps.undeclared_packages == ("model.curio.ddrnet23-slim@1",)

    def test_builtin_is_never_a_declared_dependency(self):
        spec = _spec([_node("a", LOADER)], [])
        assert declared_dependencies(spec).as_required_dict()["packages"] == []

    def test_the_source_scan_uses_the_production_grounding_scanner(self):
        spec = _spec(
            [
                _node("a", LOADER, content='p = curio_data_path("data.city.roads")'),
                _node("b", LOADER, content='gdf = gpd.read_file("docs/examples/data/x.geojson")'),
                _node("c", VEGA, content=(
                    '{"$schema": "https://vega.github.io/schema/v6.json",'
                    ' "data": {"url": "https://example.org/rows.csv"}}'
                )),
            ],
            [],
        )
        sources = referenced_sources(spec, templates=TEMPLATES)
        assert sources.dataset_ids == ("data.city.roads",)
        assert sources.paths == ("docs/examples/data/x.geojson",)
        # The document's own `$schema` is a format declaration, not data the
        # node loads, and the production scanner skips it; the url the spec
        # actually fetches is still here. See SCHEMA_DECLARATION_KEY.
        assert sources.urls == ("https://example.org/rows.csv",)

    def test_url_allowlist_is_prefix_matching_not_host_matching(self):
        allowed = ["https://vega.github.io/schema/"]
        assert url_allowed("https://vega.github.io/schema/vega-lite/v6.json", allowed)
        assert not url_allowed("https://vega.github.io/other", allowed)
        assert not url_allowed("https://evil.example/schema/", allowed)


class TestTheShippedCorpus:
    """The properties the harness relies on, asserted over the real examples."""

    def test_the_corpus_is_the_thirty_seven_examples(self):
        paths = example_paths()
        curated = [p for p in paths if p.parent.name == "examples"]
        legacy = [p for p in paths if p.parent.name == "dataflows"]
        assert len(curated) == 26, [p.name for p in curated]
        assert len(legacy) == 28, [p.name for p in legacy]

    @pytest.mark.parametrize("path", example_paths(), ids=lambda p: p.stem)
    def test_every_example_canonicalizes_with_known_templates(self, path):
        spec = json.loads(path.read_text(encoding="utf-8"))
        sources = referenced_sources(spec, templates=TEMPLATES)
        graph = canonical_graph_from_spec(spec, templates=TEMPLATES, sources=sources)
        assert graph.nodes, f"{path.name} canonicalized to no nodes"
        unknown = [n.type for n in graph.nodes if n.type not in TEMPLATES]
        assert not unknown, f"{path.name} uses templates outside the catalog: {unknown}"

    @pytest.mark.parametrize("path", example_paths(), ids=lambda p: p.stem)
    def test_canonicalizing_an_example_is_idempotent_and_order_free(self, path):
        spec = json.loads(path.read_text(encoding="utf-8"))
        dataflow = spec.get("dataflow", spec)
        shuffled = {
            "dataflow": {
                **dataflow,
                "nodes": list(reversed(dataflow["nodes"])),
                "edges": list(reversed(dataflow["edges"])),
            }
        }
        assert canonical_graph_from_spec(spec, templates=TEMPLATES) == (
            canonical_graph_from_spec(shuffled, templates=TEMPLATES)
        )

    def test_the_examples_that_need_interaction_edges_are_exactly_these(self):
        """The T2 set. dev/112's ``edges[].kind`` is not on this branch, so
        these ten cannot be reconstructed by any plan here -- a capability
        gap the harness reports rather than a bar it lowers."""
        with_interaction = set()
        for path in example_paths():
            spec = json.loads(path.read_text(encoding="utf-8"))
            if canonical_graph_from_spec(spec, templates=TEMPLATES).interaction_edges():
                with_interaction.add(path.stem)
        assert with_interaction == {
            "07-autark-gpu-shader",
            "08-autark-spatial-join-regression",
            "09-heterogeneous-data-linked-views",
            "11-autark-pbf-loading",
            "17-autark-geodataframe-maps",
            "interaction-autark",
            "interaction-vega",
            "interaction-vega-autark",
            "interaction-vega-simple",
            "regression",
        }

    def test_these_are_the_examples_whose_templates_need_a_package(self):
        """Example 09 declares ``curio.weather@1`` for its python LIBRARIES
        while using only builtin templates -- a different resolution route
        from examples 06, 10, 18, 21, 22 and 24 and the chicago-loop-shadow-towers,
        chicago-rain-wind-routing, lower-manhattan-park-shade,
        quad-cities-flood-vulnerability and scenario-comparison-charts test
        dataflows, whose templates themselves live in a package
        (``curio.media@1``, ``curio.scout@1``, and
        the model packages ``model.curio.ddrnet23-slim@1``,
        ``model.scout.deep-umbra@1`` and ``model.scout.weather-gnn@1``).
        quad-cities-flood-vulnerability's only package nodes are its Raster
        Calculators, which left the built-in nodes for SCOUT's package (the
        owner's call, 2026-10-18), and scenario-comparison-charts' are its
        nine charts, all Scout's (the plan for #914, step 28.2, and the plan
        answering komar41's review, step 6.2), ``curio.scout@1`` (that plan,
        step 10). chicago-rain-wind-routing charts its routes with Scout's
        Bars, and example 06 its scenarios' mean sunlight (that plan, step
        6.3)."""
        needs_package_templates = {}
        for path in example_paths():
            spec = json.loads(path.read_text(encoding="utf-8"))
            graph = canonical_graph_from_spec(spec, templates=TEMPLATES)
            foreign = sorted(
                {n.type for n in graph.nodes if not n.type.startswith("curio.builtin/")}
            )
            if foreign:
                needs_package_templates[path.stem] = foreign
        assert list(needs_package_templates) == [
            "06-back-bay-road-sunlight",
            "10-street-vision-cv-analysis",
            "18-storage-orthorectified-imagery",
            "21-storage-photos-and-videos",
            "22-storage-audio-recordings",
            "24-scout-shadow-model-chicago-loop",
            "chicago-loop-shadow-towers",
            "chicago-rain-wind-routing",
            "lower-manhattan-park-shade",
            "quad-cities-flood-vulnerability",
            "scenario-comparison-charts",
        ]
        # Its nine charts are Scout's, the grouped bars and the table among them.
        assert needs_package_templates["scenario-comparison-charts"] == [
            "curio.scout/bars-with-error-bars",
            "curio.scout/curves-by-group",
            "curio.scout/donuts",
            "curio.scout/ensemble-strips",
            "curio.scout/grouped-bars",
            "curio.scout/lines-with-band",
            "curio.scout/stacked-bars-with-totals",
            "curio.scout/table",
            "curio.scout/weighted-matrix",
        ]
        # SCOUT's two models are packages with nodes of their own.
        for stem in ("24-scout-shadow-model-chicago-loop", "chicago-loop-shadow-towers", "lower-manhattan-park-shade"):
            assert "model.scout.deep-umbra/accumulated-shadow" in needs_package_templates[stem], stem
        assert needs_package_templates["chicago-rain-wind-routing"] == [
            "curio.scout/bars",
            "model.scout.weather-gnn/weather-routing",
        ]
        assert needs_package_templates["06-back-bay-road-sunlight"] == ["curio.scout/bars"]
        # SCOUT's raster nodes are curio.scout@1's: the shadow dataflows
        # rasterize their buildings with it, and the two that take the
        # shadow's statistics and the flood dataflow use its Raster Calculator.
        assert needs_package_templates["24-scout-shadow-model-chicago-loop"] == needs_package_templates[
            "chicago-loop-shadow-towers"] == [
            "curio.scout/raster-calculator",
            "curio.scout/rasterize-buildings",
            "model.scout.deep-umbra/accumulated-shadow",
        ]
        assert needs_package_templates["lower-manhattan-park-shade"] == [
            "curio.scout/rasterize-buildings",
            "model.scout.deep-umbra/accumulated-shadow",
        ]
        assert needs_package_templates["quad-cities-flood-vulnerability"] == ["curio.scout/raster-calculator"]
        assert declared_dependencies(
            json.loads(
                (REPO_ROOT / "docs/examples/09-heterogeneous-data-linked-views.json").read_text()
            )
        ).packages == ("curio.weather@1",)


class TestExpectedBlockRoundTrip:
    def test_the_expected_block_names_every_node_and_edge(self):
        graph = CanonicalGraph(
            nodes=(
                CNode(type=LOADER, role="loader", executable=True, has_content=True),
                CNode(type=ANALYSIS, role="analysis", executable=True, has_content=True),
            ),
            # The loader feeds the analysis node's second circle, "in_1".
            edges=(CEdge(src=0, dst=1, kind="data", slot=1),),
            sources=Sources(dataset_ids=("data.x",)),
        )
        block = graph.as_expected_dict()
        # Default refs are readable and role-derived, so an intent can name a
        # node a person can find in the walkthrough.
        assert [n["ref"] for n in block["nodes"]] == ["loader1", "analysis1"]
        assert block["edges"] == [
            {"from": "loader1", "to": "analysis1", "kind": "data", "slot": 1}
        ]
        assert block["sources"]["datasetIds"] == ["data.x"]

    def test_default_refs_number_each_role_in_canonical_order(self):
        graph = CanonicalGraph(
            nodes=(
                CNode(type=LOADER, role="loader", executable=True, has_content=True),
                CNode(type=LOADER, role="loader", executable=True, has_content=True),
                CNode(type=VEGA, role="visualization", executable=False, has_content=True),
            )
        )
        assert graph.default_refs() == ["loader1", "loader2", "visualization1"]

    def test_refs_must_name_every_node(self):
        graph = CanonicalGraph(
            nodes=(CNode(type=LOADER, role="loader", executable=True, has_content=True),)
        )
        with pytest.raises(ValueError):
            graph.as_expected_dict(refs=["a", "b"])


def _feeding_circles(groups: int, feeders: int, *, charted: int | None = None, swapped: bool = False) -> dict:
    """*groups* copies of one shape: a loader whose rows *feeders* steps take,
    each step handing its rows to its own circle of one node, as each
    scenario's node feeds a Compare Scenarios node. With *charted*, the first
    group's step on that circle also feeds a chart; with *swapped*, the first
    group's first two steps trade circles."""
    nodes, edges = [], []
    for group in range(groups):
        nodes += [_node(f"l{group}", LOADER), _node(f"c{group}", ANALYSIS)]
        for step in range(feeders):
            nodes.append(_node(f"s{group}-{step}", TRANSFORM))
            edges.append(_edge(f"l{group}", f"s{group}-{step}"))
            circle = 1 - step if swapped and group == 0 and step in (0, 1) else step
            edges.append(_edge(f"s{group}-{step}", f"c{group}",
                               targetHandle="in" if circle == 0 else f"in_{circle}"))
    if charted is not None:
        nodes.append(_node("chart", VEGA, content="{}"))
        edges.append(_edge(f"s0-{charted}", "chart"))
    return _spec(nodes, edges)


def _record_searches(monkeypatch) -> list:
    """``(refines outgoing circles, exact)`` for each labeling search a
    canonicalization runs."""
    from utk_curio.backend.app.agents.evaluation import canonical

    runs: list = []
    search = canonical._search_order

    def recording(*args, **kwargs):
        order, exact = search(*args, **kwargs)
        runs.append((kwargs["out_slots"], exact))
        return order, exact

    monkeypatch.setattr(canonical, "_search_order", recording)
    return runs


class TestCanonicalLabeling:
    """The property the first cut of this module got wrong: sorting nodes by
    their attributes is NOT enough. Example 01's three Data Transformation
    nodes are attribute-identical, so file order decided their indices and a
    reversed file produced different edges. The labeling below is the fix."""

    def test_identical_nodes_with_different_structure_are_separated(self):
        # One transform feeds two charts; the other feeds one. Same attributes,
        # different structure -- refinement must tell them apart.
        spec = _spec(
            [
                _node("l", LOADER),
                _node("t1", TRANSFORM),
                _node("t2", TRANSFORM),
                _node("v1", VEGA, content="{}"),
                _node("v2", VEGA, content="{}"),
                _node("v3", VEGA, content="{}"),
            ],
            [
                _edge("l", "t1"), _edge("l", "t2"),
                _edge("t1", "v1"), _edge("t1", "v2"), _edge("t2", "v3"),
            ],
        )
        reversed_spec = _spec(
            list(reversed(spec["dataflow"]["nodes"])),
            list(reversed(spec["dataflow"]["edges"])),
        )
        assert canonical_graph_from_spec(spec, templates=TEMPLATES) == (
            canonical_graph_from_spec(reversed_spec, templates=TEMPLATES)
        )

    def test_a_symmetric_fan_out_is_automorphic_so_any_labeling_agrees(self):
        spec = _spec(
            [_node("l", LOADER), _node("a", TRANSFORM), _node("b", TRANSFORM)],
            [_edge("l", "a"), _edge("l", "b")],
        )
        swapped = _spec(
            [_node("l", LOADER), _node("b", TRANSFORM), _node("a", TRANSFORM)],
            [_edge("l", "b"), _edge("l", "a")],
        )
        assert canonical_graph_from_spec(spec, templates=TEMPLATES) == (
            canonical_graph_from_spec(swapped, templates=TEMPLATES)
        )

    def test_input_circles_are_part_of_the_labeling(self):
        """Two inputs into the same node are NOT interchangeable when their
        circles differ -- the labeling must see the circle, or a swapped
        wiring would canonicalize identically and the comparator could never
        report it. Successor of the Merge Flow's slots (#662)."""
        wired = _spec(
            [_node("a", LOADER), _node("b", TRANSFORM), _node("c", ANALYSIS)],
            [_edge("a", "c", targetHandle="in"), _edge("b", "c", targetHandle="in_1")],
        )
        swapped = _spec(
            [_node("a", LOADER), _node("b", TRANSFORM), _node("c", ANALYSIS)],
            [_edge("a", "c", targetHandle="in_1"), _edge("b", "c", targetHandle="in")],
        )
        one = canonical_graph_from_spec(wired, templates=TEMPLATES)
        other = canonical_graph_from_spec(swapped, templates=TEMPLATES)
        assert one != other
        assert sorted(e.slot is None for e in one.edges) == [False, True]
        assert {n.role for n in one.nodes if n.type == ANALYSIS} == {"analysis"}

    def test_steps_that_feed_one_nodes_circles_are_labeled_exactly(self, monkeypatch):
        """The steps of a group differ only in the circle they feed. Refined
        without the circles of their outgoing edges they stay alike, and four
        such groups run the search out of its budget. The labeling searches
        again with those circles refined too, and that order is exact and
        does not depend on the file's order (the fallback of komar41's #914,
        for the scenario comparison charts dataflow)."""
        spec = _feeding_circles(4, 3)
        runs = _record_searches(monkeypatch)
        graph = canonical_graph_from_spec(spec, templates=TEMPLATES)
        assert runs == [(False, False), (True, True)], runs
        assert graph.exact_labeling
        flow = spec["dataflow"]
        reversed_spec = _spec(list(reversed(flow["nodes"])), list(reversed(flow["edges"])))
        assert canonical_graph_from_spec(reversed_spec, templates=TEMPLATES) == graph

    def test_the_second_search_still_tells_the_circles_apart(self):
        """One step of the first group also feeds a chart. Wired into circle 0
        or into circle 1, that is two graphs, and an exact labeling of each
        must keep them apart."""
        one = canonical_graph_from_spec(_feeding_circles(4, 3, charted=0), templates=TEMPLATES)
        other = canonical_graph_from_spec(_feeding_circles(4, 3, charted=0, swapped=True), templates=TEMPLATES)
        assert one.exact_labeling and other.exact_labeling
        assert one != other

    def test_a_graph_the_first_search_labels_exactly_keeps_that_labeling(self, monkeypatch):
        """Three groups fit in the budget, so no second search runs and the
        order is the one the first search gives, as for every shipped example
        before the fallback (their fixtures' expected graphs pin it)."""
        runs = _record_searches(monkeypatch)
        graph = canonical_graph_from_spec(_feeding_circles(3, 3), templates=TEMPLATES)
        assert runs == [(False, True)], runs
        assert graph.exact_labeling

    @pytest.mark.parametrize("path", example_paths(), ids=lambda p: p.stem)
    def test_the_labeling_is_exact_for_every_shipped_example(self, path):
        spec = json.loads(path.read_text(encoding="utf-8"))
        graph = canonical_graph_from_spec(spec, templates=TEMPLATES)
        assert graph.exact_labeling, (
            f"{path.name}: the canonical labeling search hit its budget; a "
            "comparison of this example would be best-effort"
        )

    def test_exactness_is_not_part_of_graph_equality(self):
        one = CanonicalGraph(nodes=(CNode(LOADER, "loader", True, True),), exact_labeling=True)
        other = CanonicalGraph(nodes=(CNode(LOADER, "loader", True, True),), exact_labeling=False)
        assert one == other
