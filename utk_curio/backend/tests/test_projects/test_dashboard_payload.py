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
import base64
import json
import re

import pytest

from utk_curio.backend.app.projects.dashboard_payload import (
    DashboardCannotBeStandaloneError,
    DashboardTooLargeError,
    build_dashboard_payload,
    dashboard_source_node_ids,
)
from utk_curio.backend.app.projects.schemas import OutputRef


RENDER_SPEC = json.dumps({"map": {"layerRefs": []}})
COMPUTE_SPEC = json.dumps({"compute": [{"shader": "x"}]})
DATA_SPEC = json.dumps({"data": [{"type": "osm"}]})


def node(node_id, node_type, code=None, **fields):
    """A node as a dataflow saved from the canvas holds it (``TrillGenerator``):
    the template id as ``type``, the code as ``content``, and
    ``dashboardPinned`` and the tile geometry on the node itself (#693)."""
    saved = {"id": node_id, "type": node_type, **fields}
    if code is not None:
        saved["content"] = code
    return saved


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

    def test_a_pinned_compare_scenarios_node_is_its_own_source(self):
        # Its tile charts the table its own run stacked (#662), so that table
        # travels, and what feeds the node does not.
        spec = spec_of(
            [
                node("a", "curio.builtin/computation-analysis"),
                node("b", "curio.builtin/computation-analysis"),
                node("compare", "curio.builtin/compare-scenarios@1", dashboardPinned=True),
                node("chart", "curio.builtin/vis-vega", dashboardPinned=True),
            ],
            [edge("a", "compare"), edge("b", "compare"), edge("a", "chart")],
        )

        assert dashboard_source_node_ids(spec) == {"compare", "a"}

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
        assert payload.to_dict()["spec"]["dataflow"]["nodes"][0]["dashboardX"] == 40


class TestATileThatFetchesItsOwnData:
    """An Autark tile can declare its own data sources and still be a render tile.

    Those sources are compiled and executed when it draws, which on a page that
    is supposed to need no server is a call to one. Refusing at build time puts
    the problem in front of the owner, who can move the data upstream; the
    alternative puts it in front of a viewer who opened the link on a train.
    """

    def _pinned_map(self, spec_text):
        return spec_of(
            [node("sh-map", "curio.builtin/autk-grammar", code=spec_text, dashboardPinned=True)],
            [],
        )

    def test_a_map_that_loads_its_own_data_is_refused(self):
        spec_text = json.dumps({"map": {"layerRefs": []}, "data": [{"type": "osm"}]})

        with pytest.raises(DashboardCannotBeStandaloneError) as caught:
            build_dashboard_payload(
                spec=self._pinned_map(spec_text),
                output_refs=[],
                fetch_envelope=lambda name: envelope(),
            )

        assert caught.value.offenders == ["sh-map"]
        assert "sh-map" in caught.value.describe()

    def test_a_map_fed_from_upstream_is_fine(self):
        # The shape every Autark example uses: data and compute are their own
        # nodes, so their outputs are saved and travel with the page.
        spec_text = json.dumps({"map": {"layerRefs": []}})

        payload = build_dashboard_payload(
            spec=self._pinned_map(spec_text),
            output_refs=[],
            fetch_envelope=lambda name: envelope(),
        )

        assert payload.outputs == {}

    def test_an_empty_data_section_is_not_a_refusal(self):
        spec_text = json.dumps({"map": {"layerRefs": []}, "data": []})

        payload = build_dashboard_payload(
            spec=self._pinned_map(spec_text),
            output_refs=[],
            fetch_envelope=lambda name: envelope(),
        )

        assert payload.outputs == {}

    def test_an_unpinned_node_with_data_sources_is_not_a_refusal(self):
        # It is not a tile, it is the shape the refusal tells people to move to:
        # a data node of its own, whose output is saved and travels with the
        # page. A data-only spec, deliberately, because a spec carrying a `map`
        # classifies as render however little else it does, and a render node is
        # walked through rather than treated as a producer.
        spec = spec_of(
            [
                node("loader", "curio.builtin/autk-grammar", code=DATA_SPEC),
                node("map", "curio.builtin/autk-grammar", code=RENDER_SPEC, dashboardPinned=True),
            ],
            [edge("loader", "map")],
        )

        payload = build_dashboard_payload(
            spec=spec,
            output_refs=refs(("loader", "l.parquet")),
            fetch_envelope=lambda name: envelope(),
        )

        assert set(payload.outputs) == {"l.parquet"}


# ---------------------------------------------------------------------------
# A raster behind a pinned map
# ---------------------------------------------------------------------------

#: What ``/get`` answers for a Python node's raster: the path of its file.
RASTER_ENVELOPE = {"dataType": "raster", "data": "/srv/curio/data/r.tif"}

#: A raster's description, as the sandbox's ``X-Curio-Raster`` header carries it.
RASTER_META = {
    "width": 40, "height": 30, "count": 1, "crs": "EPSG:32616", "crsWkt": None,
    "transform": [100.0, 0.0, 447000.0, 0.0, -100.0, 4637000.0],
    "nodata": None, "dtype": "float32",
}

GEOTIFF = b"II*\x00" + bytes(range(256)) * 4


def served(geotiff=GEOTIFF):
    """What the raster reader hands back for a raster ``/raster`` served."""
    return {"status": 200, "meta": RASTER_META, "geotiff": geotiff}


def raster_map_spec():
    return spec_of(
        [
            node("py", "curio.builtin/computation-analysis"),
            node("map", "curio.builtin/autk-grammar", code=RENDER_SPEC, dashboardPinned=True),
        ],
        [edge("py", "map")],
    )


def raster_refs(filename="r_output", data_type="raster"):
    return [OutputRef(node_id="py", filename=filename, data_type=data_type)]


class TestARasterBehindAPinnedMap:
    """An Autark map loads a Python node's raster as the GeoTIFF ``/raster``
    serves, which a page that needs no server cannot ask for. So the page
    carries what ``/raster`` answered when it was built, beside the envelope
    ``/get`` answered, and the map reads it there."""

    def test_the_geotiff_travels_with_its_description(self):
        asked = []

        def fetch_raster(filename, part):
            asked.append((filename, part))
            return served()

        payload = build_dashboard_payload(
            spec=raster_map_spec(),
            output_refs=raster_refs(),
            fetch_envelope=lambda name: RASTER_ENVELOPE,
            fetch_raster=fetch_raster,
        )
        body = payload.to_dict()

        assert asked == [("r_output", None)]
        # The envelope still travels as /get answered it.
        assert body["outputs"] == {"r_output": RASTER_ENVELOPE}
        [raster] = body["rasters"]
        assert (raster["filename"], raster["part"], raster["status"]) == ("r_output", None, 200)
        assert raster["meta"] == RASTER_META
        assert base64.b64decode(raster["geotiff"]) == GEOTIFF
        # The page carries it as JSON.
        assert json.loads(json.dumps(body))["rasters"] == [raster]

    def test_each_raster_of_a_tuple_travels_under_its_place_in_it(self):
        # A tuple's raster is asked for by its part, as the map asks for it.
        envelope = {"dataType": "outputs", "data": [
            {"dataType": "dataframe", "data": {"a": [1]}},
            {"dataType": "raster", "data": "/srv/a.tif"},
            {"dataType": "raster", "data": "/srv/b.tif"},
        ]}
        asked = []

        def fetch_raster(filename, part):
            asked.append((filename, part))
            return served(GEOTIFF + bytes([part]))

        payload = build_dashboard_payload(
            spec=raster_map_spec(),
            output_refs=raster_refs("t_output", "outputs"),
            fetch_envelope=lambda name: envelope,
            fetch_raster=fetch_raster,
        )
        rasters = payload.to_dict()["rasters"]

        assert asked == [("t_output", 1), ("t_output", 2)]
        assert [(r["filename"], r["part"]) for r in rasters] == [("t_output", 1), ("t_output", 2)]
        assert [base64.b64decode(r["geotiff"])[-1] for r in rasters] == [1, 2]

    def test_a_raster_that_travels_as_its_collection_needs_nothing_more(self):
        # A raster an Autark node handed on is its collection, inside the
        # envelope /get answered, which travels anyway.
        handed_on = {"dataType": "raster", "data": {"type": "FeatureCollection", "features": [], "grid": {}}}
        envelope = {"dataType": "outputs", "data": [handed_on]}

        def fetch_raster(filename, part):
            raise AssertionError("asked /raster for a raster the envelope already holds")

        payload = build_dashboard_payload(
            spec=raster_map_spec(),
            output_refs=raster_refs(data_type="outputs"),
            fetch_envelope=lambda name: envelope,
            fetch_raster=fetch_raster,
        )

        assert payload.to_dict()["rasters"] == []

    def test_an_output_saved_as_a_raster_is_asked_for_whole(self):
        # The map asks /raster for it by name whatever its envelope holds, so
        # the page carries that answer, here the sandbox's refusal.
        refusal = {"status": 422, "meta": None, "message": "artifact r_output is not a raster"}
        asked = []

        def fetch_raster(filename, part):
            asked.append((filename, part))
            return refusal

        payload = build_dashboard_payload(
            spec=raster_map_spec(),
            output_refs=raster_refs(),
            fetch_envelope=lambda name: {"dataType": "dict", "data": {"a": 1}},
            fetch_raster=fetch_raster,
        )

        assert asked == [("r_output", None)]
        assert payload.to_dict()["rasters"] == [{"filename": "r_output", "part": None, **refusal}]

    def test_a_refused_raster_travels_as_the_refusal(self):
        # The page then shows what the editor shows for it, here the raster's
        # size against what a map loads, and asks no server.
        refusal = {
            "status": 413,
            "meta": {**RASTER_META, "width": 5000, "height": 5000},
            "message": "the raster is 5000 by 5000 cells",
        }

        payload = build_dashboard_payload(
            spec=raster_map_spec(),
            output_refs=raster_refs(),
            fetch_envelope=lambda name: RASTER_ENVELOPE,
            fetch_raster=lambda filename, part: refusal,
        )

        assert payload.to_dict()["rasters"] == [{"filename": "r_output", "part": None, **refusal}]

    def test_a_raster_the_sandbox_cannot_be_asked_for_is_left_out(self):
        # As an envelope that cannot be read is.
        def unreachable(filename, part):
            raise KeyError(filename)

        payload = build_dashboard_payload(
            spec=raster_map_spec(),
            output_refs=raster_refs(),
            fetch_envelope=lambda name: RASTER_ENVELOPE,
            fetch_raster=unreachable,
        )
        body = payload.to_dict()

        assert body["rasters"] == []
        assert body["outputs"] == {"r_output": RASTER_ENVELOPE}

    def test_it_asks_for_no_more_than_the_editors_map_loads(self):
        # The page's map refuses a larger raster with the editor's sentence; the
        # reader asks /raster with the same limits (rasterLoad.ts), so such a
        # raster travels as that refusal and is never written out whole.
        from utk_curio.backend.app.projects.dashboard_payload import (
            RASTER_MAX_CELLS,
            RASTER_MAX_SIDE,
        )
        from utk_curio.backend.app.projects.seed import _repo_root

        source = (
            _repo_root() / "utk_curio" / "frontend" / "urban-workflows" / "src"
            / "utils" / "raster" / "rasterLoad.ts"
        ).read_text(encoding="utf-8")
        cells = re.search(r"export const RASTER_MAX_CELLS = (\d+) \* (\d+);", source)
        side = re.search(r"export const RASTER_MAX_SIDE = (\d+);", source)
        assert cells and side, "rasterLoad.ts no longer declares its limits the way this test reads them"
        assert RASTER_MAX_CELLS == int(cells[1]) * int(cells[2])
        assert RASTER_MAX_SIDE == int(side[1])


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

    def test_a_rasters_geotiff_counts_toward_the_budget(self):
        # Its envelope is a path, a few bytes; the page carries the GeoTIFF.
        payload = build_dashboard_payload(
            spec=raster_map_spec(),
            output_refs=raster_refs(),
            fetch_envelope=lambda name: RASTER_ENVELOPE,
            fetch_raster=lambda filename, part: served(b"\x00" * 3000),
            limit_bytes=1_000_000,
        )

        assert payload.total_bytes > len(base64.b64encode(b"\x00" * 3000))

    def test_a_raster_over_the_budget_is_refused_in_the_caps_own_words(self):
        with pytest.raises(DashboardTooLargeError) as caught:
            build_dashboard_payload(
                spec=raster_map_spec(),
                output_refs=raster_refs(),
                fetch_envelope=lambda name: RASTER_ENVELOPE,
                fetch_raster=lambda filename, part: served(b"\x00" * 3000),
                limit_bytes=2048,
            )

        heaviest = caught.value.weights[0]
        assert (heaviest.node_id, heaviest.data_type) == ("py", "raster")
        message = caught.value.describe()
        assert "over the 2 KB limit" in message
        assert "py" in message and "raster" in message

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
