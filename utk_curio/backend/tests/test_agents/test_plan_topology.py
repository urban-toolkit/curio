"""dev/112 (DEC-070) — the one plan-topology helper: acyclicity over DATA
edges of the NET graph, and the preamble's interaction-edge rule made
executable."""
from utk_curio.backend.app.agents import plan_topology as pt


def _edge(eid, src, dst, **over):
    e = {"id": eid, "source": src, "target": dst, "sourceHandle": "out", "targetHandle": "in"}
    e.update(over)
    return e


# The owner's 2026-08-25 canvas: Load → Transform → Merge → Pool → Vis.
EXISTING = [
    _edge("e1", "load", "xform"),
    _edge("e2", "xform", "merge", targetHandle="in_0"),
    _edge("e3", "merge", "pool"),
    _edge("e4", "pool", "vis"),
]
TYPES = {
    "load": "curio.builtin/data-loading@1",
    "xform": "curio.builtin/data-transformation@1",
    "merge": "curio.builtin/merge-flow@1",
    "pool": "curio.builtin/data-pool@1",
    "vis": "curio.builtin/vis-vega@1",
}


class TestFindDataCycle:
    def test_acyclic_graph_has_no_cycle(self):
        assert pt.find_data_cycle([(a, b) for a, b in (("a", "b"), ("b", "c"), ("a", "c"))]) is None

    def test_reports_the_cycle_as_a_closed_path(self):
        path = pt.find_data_cycle([("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")])
        assert path is not None
        assert path[0] == path[-1]
        assert set(path) == {"a", "b", "c"}

    def test_self_loop(self):
        assert pt.find_data_cycle([("a", "a")]) == ["a", "a"]

    def test_deterministic_and_stack_safe_on_a_long_chain(self):
        pairs = [(str(i), str(i + 1)) for i in range(5000)]
        assert pt.find_data_cycle(pairs) is None
        pairs.append(("5000", "0"))
        assert pt.find_data_cycle(pairs) is not None


class TestNetDataEdges:
    def test_the_owners_plan_closes_a_cycle(self):
        # vis → merge as a DATA edge closes Merge → Pool → Vis → Merge.
        plan = {"nodes": [], "edges": [{"from": "vis", "to": "merge"}], "removeEdges": []}
        pairs = pt.net_data_edges(EXISTING, plan, set(), set())
        path = pt.find_data_cycle(pairs)
        assert path is not None and set(path) == {"merge", "pool", "vis"}

    def test_the_same_edge_as_interaction_does_not_count(self):
        plan = {"nodes": [], "edges": [{"from": "vis", "to": "pool", "kind": "interaction"}]}
        assert pt.find_data_cycle(pt.net_data_edges(EXISTING, plan, set(), set())) is None

    def test_existing_interaction_edges_are_excluded(self):
        existing = EXISTING + [_edge("e5", "vis", "pool", type="Interaction")]
        assert pt.find_data_cycle(pt.net_data_edges(existing, {"edges": []}, set(), set())) is None

    def test_removals_and_cascade_break_cycles(self):
        cyclic = EXISTING + [_edge("e5", "vis", "merge")]
        # Remove-only plan naming the closing edge → acyclic.
        assert pt.find_data_cycle(pt.net_data_edges(cyclic, {"edges": []}, set(), {"e5"})) is None
        # Removing the vis node cascades e4 and e5 away → acyclic.
        assert pt.find_data_cycle(pt.net_data_edges(cyclic, {"edges": []}, {"vis"}, set())) is None
        # Untouched → the cycle is still there (reported, not blamed on the plan).
        assert pt.find_data_cycle(pt.net_data_edges(cyclic, {"edges": []}, set(), set())) is not None

    def test_ref_to_id_maps_plan_refs_to_minted_ids(self):
        plan = {"nodes": [{"ref": "n1"}], "edges": [{"from": "vis", "to": "n1"}, {"from": "n1", "to": "merge"}]}
        pairs = pt.net_data_edges(EXISTING, plan, set(), set(), ref_to_id={"n1": "real-1"})
        assert ("vis", "real-1") in pairs and ("real-1", "merge") in pairs
        assert pt.find_data_cycle(pairs) is not None

    def test_remove_and_readd_the_same_data_edge_is_still_a_cycle(self):
        # The five-round loop: removeEdges the closing edge, add it back as data.
        cyclic = EXISTING + [_edge("e5", "vis", "merge")]
        plan = {"nodes": [], "edges": [{"from": "vis", "to": "merge"}], "removeEdges": ["e5"]}
        assert pt.find_data_cycle(pt.net_data_edges(cyclic, plan, set(), {"e5"})) is not None


class TestInteractionEdgeErrors:
    type_of = staticmethod(lambda ep: TYPES.get(ep))

    def test_vis_to_pool_is_legal_both_directions(self):
        for src, dst in (("vis", "pool"), ("pool", "vis")):
            plan = {"edges": [{"from": src, "to": dst, "kind": "interaction"}]}
            assert pt.interaction_edge_errors(plan, self.type_of) == []

    def test_vis_to_merge_names_the_offender_and_the_fix(self):
        plan = {"edges": [{"from": "vis", "to": "merge", "kind": "interaction"}]}
        (err,) = pt.interaction_edge_errors(plan, self.type_of)
        assert err.startswith("edges[0]: an interaction edge connects a visualization")
        assert "'merge' is merge-flow" in err
        assert "target the data-pool" in err

    def test_pool_to_pool_is_refused(self):
        types = dict(TYPES, pool2="curio.builtin/data-pool")
        plan = {"edges": [{"from": "pool", "to": "pool2", "kind": "interaction"}]}
        assert len(pt.interaction_edge_errors(plan, types.get)) == 1

    def test_unknown_template_fails_open(self):
        plan = {"edges": [{"from": "vis", "to": "mystery", "kind": "interaction"}]}
        assert pt.interaction_edge_errors(plan, self.type_of) == []

    def test_data_edges_are_never_judged(self):
        plan = {"edges": [{"from": "vis", "to": "merge"}]}
        assert pt.interaction_edge_errors(plan, self.type_of) == []

    def test_other_capable_visualizations(self):
        types = {"m": "acme.maps/autk-map@2", "s": "curio.builtin/vis-simple", "p": "x/data-pool"}
        for v in ("m", "s"):
            plan = {"edges": [{"from": v, "to": "p", "kind": "interaction"}]}
            assert pt.interaction_edge_errors(plan, types.get) == []


class TestHelpers:
    def test_template_suffix_and_strip(self):
        assert pt.strip_type_version("curio.builtin/merge-flow@1") == "curio.builtin/merge-flow"
        assert pt.template_suffix("curio.builtin/vis-vega@1") == "vis-vega"
        assert pt.template_suffix(None) == ""

    def test_is_interaction_edge_reads_spec_and_plan_shapes(self):
        assert pt.is_interaction_edge({"type": "Interaction"})
        assert pt.is_interaction_edge({"kind": "interaction"})
        assert not pt.is_interaction_edge({"sourceHandle": "out"})

    def test_format_cycle_uses_labels(self):
        assert pt.format_cycle(["a", "b", "a"], {"a": "A", "b": "B"}.get) == "A → B → A"
