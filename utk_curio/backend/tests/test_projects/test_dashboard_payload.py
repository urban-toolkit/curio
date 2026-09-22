"""What travels inside a standalone dashboard page, and what must not.

A dashboard served as a finished HTML document carries its rows with it, so two
questions have to be answered before the page is built: whose rows, and how many
of them. Both are easy to get wrong quietly.

Whose: a dataflow saved under ``--save-node-outputs`` has an output for every
node it ran. Embedding all of them would put rows from nodes the dashboard never
shows into a page handed out by link. Only the nodes feeding a pinned tile
travel, which is the same walk the frontend does when it decides whose outputs to
save in the first place.

How many: the limit is a refusal. A page that silently falls back to fetching
what would not fit is a page that looks standalone and is not, and the owner
finds out when somebody opens it somewhere the server cannot be reached.
"""
import json

import pytest

from utk_curio.backend.app.projects.dashboard_payload import (
    DashboardTooLargeError,
    build_dashboard_payload,
    dashboard_source_node_ids,
)
from utk_curio.backend.app.projects.schemas import OutputRef


RENDER_SPEC = json.dumps({"map": {"layerRefs": []}})
COMPUTE_SPEC = json.dumps({"compute": [{"shader": "x"}]})
DATA_SPEC = json.dumps({"data": [{"type": "osm"}]})


def node(node_id, node_type, **data):
    return {"id": node_id, "type": "__curioUniversalNode", "data": {"nodeType": node_type, **data}}


def edge(source, target):
    return {"id": f"{source}-{target}", "source": source, "target": target}


def spec_of(nodes, edges=()):
    return {"dataflow": {"nodes": list(nodes), "edges": list(edges)}}


def envelope(rows=1):
    return {"dataType": "dataframe", "data": {"a": list(range(rows))}, "schema": {"a": "int64"}}


def refs(*pairs):
    return [
        OutputRef(node_id=node_id, filename=filename, data_type="dataframe")
        for node_id, filename in pairs
    ]


# ---------------------------------------------------------------------------
# Whose outputs travel
# ---------------------------------------------------------------------------

class TestWhichOutputsAreNeeded:
    def test_a_pinned_chart_needs_the_node_that_produced_its_rows(self):
        spec = spec_of(
            [
                node("py", "curio.builtin/computation-analysis"),
                node("chart", "curio.builtin/vis-vega", dashboardPinned=True),
            ],
            [edge("py", "chart")],
        )

        assert dashboard_source_node_ids(spec) == {"py"}

    def test_it_walks_through_a_pool_rather_than_stopping_at_it(self):
        # A Data Pool re-derives its rows from whatever reaches it, so its own
        # output is not what the tile needs.
        spec = spec_of(
            [
                node("py", "curio.builtin/computation-analysis"),
                node("pool", "curio.builtin/data-pool"),
                node("chart", "curio.builtin/vis-vega", dashboardPinned=True),
            ],
            [edge("py", "pool"), edge("pool", "chart")],
        )

        assert dashboard_source_node_ids(spec) == {"py"}

    def test_it_stops_at_the_nearest_producer_not_the_furthest(self):
        spec = spec_of(
            [
                node("a", "curio.builtin/computation-analysis"),
                node("b", "curio.builtin/computation-analysis"),
                node("chart", "curio.builtin/vis-vega", dashboardPinned=True),
            ],
            [edge("a", "b"), edge("b", "chart")],
        )

        assert dashboard_source_node_ids(spec) == {"b"}

    def test_an_autark_render_node_is_walked_through_but_a_data_node_is_not(self):
        spec = spec_of(
            [
                node("data", "curio.builtin/autk-grammar", code=DATA_SPEC),
                node("render", "curio.builtin/autk-grammar", code=RENDER_SPEC),
                node("map", "curio.builtin/autk-grammar", code=RENDER_SPEC, dashboardPinned=True),
            ],
            [edge("data", "render"), edge("render", "map")],
        )

        assert dashboard_source_node_ids(spec) == {"data"}

    def test_a_compute_node_is_a_producer(self):
        spec = spec_of(
            [
                node("compute", "curio.builtin/autk-grammar", code=COMPUTE_SPEC),
                node("map", "curio.builtin/autk-grammar", code=RENDER_SPEC, dashboardPinned=True),
            ],
            [edge("compute", "map")],
        )

        assert dashboard_source_node_ids(spec) == {"compute"}

    def test_a_versioned_node_type_resolves_to_the_same_kind(self):
        # Palette-dragged nodes persist `...@1`; an unnormalised comparison used
        # to miss them and treat a pass-through as a producer.
        spec = spec_of(
            [
                node("py", "curio.builtin/computation-analysis@2"),
                node("pool", "curio.builtin/data-pool@1"),
                node("chart", "curio.builtin/vis-vega@1", dashboardPinned=True),
            ],
            [edge("py", "pool"), edge("pool", "chart")],
        )

        assert dashboard_source_node_ids(spec) == {"py"}

    def test_a_cycle_terminates(self):
        spec = spec_of(
            [
                node("a", "curio.builtin/data-pool"),
                node("b", "curio.builtin/data-pool"),
                node("chart", "curio.builtin/vis-vega", dashboardPinned=True),
            ],
            [edge("a", "b"), edge("b", "a"), edge("b", "chart")],
        )

        assert dashboard_source_node_ids(spec) == set()

    def test_nothing_pinned_needs_nothing(self):
        spec = spec_of(
            [node("py", "curio.builtin/computation-analysis")],
            [],
        )

        assert dashboard_source_node_ids(spec) == set()

    def test_an_empty_spec_is_not_an_error(self):
        assert dashboard_source_node_ids({}) == set()


# ---------------------------------------------------------------------------
# Assembling the payload
# ---------------------------------------------------------------------------

class TestBuildPayload:
    def test_it_embeds_only_what_a_tile_reads(self):
        # `other` ran and was saved, but no pinned tile descends from it. Its
        # rows are somebody's data and have no business in a shared page.
        spec = spec_of(
            [
                node("py", "curio.builtin/computation-analysis"),
                node("other", "curio.builtin/computation-analysis"),
                node("chart", "curio.builtin/vis-vega", dashboardPinned=True),
            ],
            [edge("py", "chart")],
        )

        payload = build_dashboard_payload(
            spec=spec,
            output_refs=refs(("py", "py.parquet"), ("other", "other.parquet")),
            fetch_envelope=lambda name: envelope(),
        )

        assert set(payload.outputs) == {"py.parquet"}

    def test_it_keys_outputs_by_the_filename_a_tile_looks_up(self):
        spec = spec_of(
            [
                node("py", "curio.builtin/computation-analysis"),
                node("chart", "curio.builtin/vis-vega", dashboardPinned=True),
            ],
            [edge("py", "chart")],
        )
        wire = envelope(3)

        payload = build_dashboard_payload(
            spec=spec,
            output_refs=refs(("py", "1234_abcd_output.parquet")),
            fetch_envelope=lambda name: wire,
        )

        # Verbatim: the page reads an embedded envelope through the same code
        # that reads a fetched one, so any reshaping here would be a new format.
        assert payload.outputs["1234_abcd_output.parquet"] == wire

    def test_an_unreadable_output_is_skipped_rather_than_fatal(self):
        # Same outcome as today when an artifact has gone: the tile shows its
        # own empty state. Refusing to build the whole page would be worse.
        spec = spec_of(
            [
                node("py", "curio.builtin/computation-analysis"),
                node("chart", "curio.builtin/vis-vega", dashboardPinned=True),
            ],
            [edge("py", "chart")],
        )

        def boom(name):
            raise KeyError(name)

        payload = build_dashboard_payload(
            spec=spec,
            output_refs=refs(("py", "gone.parquet")),
            fetch_envelope=boom,
        )

        assert payload.outputs == {}

    def test_the_spec_travels_untouched(self):
        spec = spec_of(
            [node("chart", "curio.builtin/vis-vega", dashboardPinned=True, dashboardX=40)],
            [],
        )

        payload = build_dashboard_payload(
            spec=spec, output_refs=[], fetch_envelope=lambda name: envelope()
        )

        assert payload.spec is spec
        assert payload.to_dict()["spec"]["dataflow"]["nodes"][0]["data"]["dashboardX"] == 40


class TestSizeLimit:
    def _spec(self):
        return spec_of(
            [
                node("heavy", "curio.builtin/computation-analysis"),
                node("light", "curio.builtin/computation-analysis"),
                node("chart", "curio.builtin/vis-vega", dashboardPinned=True),
                node("chart2", "curio.builtin/vis-vega", dashboardPinned=True),
            ],
            [edge("heavy", "chart"), edge("light", "chart2")],
        )

    def test_under_budget_it_builds(self):
        payload = build_dashboard_payload(
            spec=self._spec(),
            output_refs=refs(("heavy", "h.parquet"), ("light", "l.parquet")),
            fetch_envelope=lambda name: envelope(10),
            limit_bytes=1_000_000,
        )

        assert set(payload.outputs) == {"h.parquet", "l.parquet"}
        assert payload.total_bytes > 0

    def test_over_budget_it_refuses(self):
        def fetch(name):
            return envelope(5000 if name == "h.parquet" else 2)

        with pytest.raises(DashboardTooLargeError) as caught:
            build_dashboard_payload(
                spec=self._spec(),
                output_refs=refs(("heavy", "h.parquet"), ("light", "l.parquet")),
                fetch_envelope=fetch,
                limit_bytes=1024,
            )

        assert caught.value.total_bytes > 1024
        assert caught.value.limit_bytes == 1024

    def test_the_refusal_names_the_heaviest_tile_first(self):
        # The owner has to know which node to aggregate; a byte count alone
        # sends them hunting.
        def fetch(name):
            return envelope(5000 if name == "h.parquet" else 2)

        with pytest.raises(DashboardTooLargeError) as caught:
            build_dashboard_payload(
                spec=self._spec(),
                output_refs=refs(("light", "l.parquet"), ("heavy", "h.parquet")),
                fetch_envelope=fetch,
                limit_bytes=1024,
            )

        assert caught.value.weights[0].node_id == "heavy"
        assert "heavy" in caught.value.describe()

    def test_an_output_no_tile_reads_does_not_count_against_the_budget(self):
        spec = spec_of(
            [
                node("py", "curio.builtin/computation-analysis"),
                node("other", "curio.builtin/computation-analysis"),
                node("chart", "curio.builtin/vis-vega", dashboardPinned=True),
            ],
            [edge("py", "chart")],
        )

        def fetch(name):
            return envelope(5000 if name == "other.parquet" else 2)

        payload = build_dashboard_payload(
            spec=spec,
            output_refs=refs(("py", "py.parquet"), ("other", "other.parquet")),
            fetch_envelope=fetch,
            limit_bytes=2048,
        )

        assert set(payload.outputs) == {"py.parquet"}
