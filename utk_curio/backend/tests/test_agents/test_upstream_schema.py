"""dev/127: what a node's inputs actually contain.

The owner's failing node had to join two frames and was told neither's columns
as its own upstream was a node with no code (then a Merge Flow, gone with #662),
which is written but never executed, so dev/118's list of "upstreams that
passed" was EMPTY. These tests pin both halves of the fix: the summary of a
preview, and the walk that looks through a node with no output of its own (a
pool) in `arg` order.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.application.solve import budgets
from utk_curio.backend.app.agents.application.solve import session
from utk_curio.backend.app.agents.domain import upstream_schema as us

BOUNDARIES = {
    "dataType": "geodataframe",
    "data": {
        "type": "FeatureCollection",
        "features": [
            {"properties": {"area_numbe": "35", "community": "DOUGLAS",
                            "shape_area": "46004621.1"},
             "geometry": {"type": "MultiPolygon"}},
            {"properties": {"area_numbe": "36", "community": "OAKLAND",
                            "shape_area": "16913961.0"},
             "geometry": {"type": "MultiPolygon"}},
        ],
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
    },
}
POPULATION = {
    "dataType": "dataframe",
    "data": {
        "GEOID": [1, 2],
        "community_area_name": ["Rogers Park", "West Ridge"],
        "TOT_POP": [54991, 71942],
    },
    "totalRows": 77,
}


class TestSummarize:
    def test_a_dataframe_yields_its_columns_dtypes_and_shape(self):
        s = us.summarize(POPULATION)
        assert s["kind"] == "table"
        assert [c["name"] for c in s["columns"]] == [
            "GEOID", "community_area_name", "TOT_POP",
        ]
        assert [c["dtype"] for c in s["columns"]] == ["int", "str", "int"]
        assert s["rowCount"] == 77  # the TOTAL, not the preview's two rows
        assert s["sampleRows"][0]["community_area_name"] == "Rogers Park"

    def test_a_geodataframe_yields_its_properties_geometry_and_crs(self):
        s = us.summarize(BOUNDARIES)
        assert s["kind"] == "geotable"
        names = [c["name"] for c in s["columns"]]
        assert names[-1] == "geometry"
        assert "community" in names and "area_numbe" in names
        assert s["crs"].endswith("EPSG::4326")
        assert s["sampleRows"][0]["geometry"] == "<MultiPolygon>"

    def test_several_inputs_are_summarized_part_by_part_in_order(self):
        # This is what a node with several input circles receives as `arg`
        # (and what a pool with several inputs hands on), in circle order.
        s = us.summarize({"dataType": "outputs", "data": [BOUNDARIES, POPULATION]})
        assert s["kind"] == "parts"
        assert [p["kind"] for p in s["parts"]] == ["geotable", "table"]

    def test_a_list_is_described_up_to_as_many_parts_as_an_input_contract_lists(self):
        # The Merge Flow's five-input cap is gone (#662): a node takes as many
        # inputs as its circles, and the description stops where the input
        # contract's slot table does.
        from utk_curio.backend.app.agents.domain.input_contract import MAX_SLOTS

        assert us.MAX_PARTS == MAX_SLOTS
        parts = [POPULATION] * (MAX_SLOTS + 2)
        s = us.summarize({"dataType": "outputs", "data": parts})
        assert len(s["parts"]) == MAX_SLOTS
        assert len(us.summarize({"dataType": "outputs", "data": [POPULATION] * 6})["parts"]) == 6

    def test_an_unknown_shape_says_only_what_it_is(self):
        assert us.summarize({"dataType": "raster", "data": "x.tif"}) == {"kind": "raster"}
        assert us.summarize({"dataType": "", "data": None}) is None
        assert us.summarize("nope") is None
        assert us.summarize(None) is None

    def test_the_bounds_hold(self):
        wide = {"dataType": "dataframe",
                "data": {f"c{i}": [i] for i in range(us.MAX_COLUMNS + 20)}}
        s = us.summarize(wide)
        assert len(s["columns"]) == us.MAX_COLUMNS
        assert s["columnsElided"] == 20
        long_value = {"dataType": "dataframe", "data": {"c": ["x" * 500]}}
        assert len(us.summarize(long_value)["sampleRows"][0]["c"]) <= us.MAX_VALUE_CHARS + 1
        many_rows = {"dataType": "dataframe", "data": {"c": list(range(50))}}
        assert len(us.summarize(many_rows)["sampleRows"]) == us.MAX_SAMPLE_ROWS

    def test_describe_is_one_line(self):
        assert us.describe(us.summarize(POPULATION)) == (
            "table · 77 rows · GEOID, community_area_name, TOT_POP"
        )
        assert " | " in us.describe(
            us.summarize({"dataType": "outputs", "data": [BOUNDARIES, POPULATION]})
        )
        assert us.describe(None) == ""


class TestTheWalkThroughAPool:
    """The owner's graph shape with a node of no output between: two loaders
    on a pool's circles, the pool into the analysis. (Their Merge Flow left
    with #662; a pool is the node with no code that is left.)"""

    SPEC = {
        "dataflow": {
            "nodes": [
                {"id": "b", "type": "curio.builtin/data-loading", "goal": "Boundaries"},
                {"id": "p", "type": "curio.builtin/data-loading", "goal": "Population"},
                {"id": "m", "type": "curio.builtin/data-pool", "goal": "Pool"},
                {"id": "a", "type": "curio.builtin/computation-analysis", "goal": "Density"},
            ],
            "edges": [
                {"id": "e0", "source": "b", "target": "m", "targetHandle": "in"},
                {"id": "e1", "source": "p", "target": "m", "targetHandle": "in_1"},
                {"id": "e2", "source": "m", "target": "a", "targetHandle": "in"},
            ],
        }
    }
    #: The owner's graph as it is now: both loaders straight into the
    #: analysis, one circle each; listed and named against circle order.
    DIRECT_SPEC = {
        "dataflow": {
            "nodes": [
                {"id": "b", "type": "curio.builtin/data-loading", "goal": "Boundaries"},
                {"id": "p", "type": "curio.builtin/data-loading", "goal": "Population"},
                {"id": "a", "type": "curio.builtin/computation-analysis", "goal": "Density"},
            ],
            "edges": [
                {"id": "e0", "source": "p", "target": "a", "targetHandle": "in_1"},
                {"id": "e1", "source": "b", "target": "a", "targetHandle": "in"},
            ],
        }
    }

    def _wave_outputs(self):
        return {
            "b": {"nodeId": "b", "goal": "Boundaries", "outputDataType": "geodataframe",
                  "wave": 1, "output": {"path": "art-b", "dataType": "geodataframe"}},
            "p": {"nodeId": "p", "goal": "Population", "outputDataType": "dataframe",
                  "wave": 1, "output": {"path": "art-p", "dataType": "dataframe"}},
        }

    def test_it_looks_through_the_pool_in_arg_order(self):
        rows = session._upstream_outputs_for(self.SPEC, "a", self._wave_outputs())
        # dev/118 returned [] here: the pool holds no output of its own.
        assert [r["nodeId"] for r in rows] == ["b", "p"]
        assert [r["argIndex"] for r in rows] == [0, 1]

    def test_a_node_with_several_circles_reads_them_in_circle_order(self):
        rows = session._upstream_outputs_for(self.DIRECT_SPEC, "a", self._wave_outputs())
        assert [r["nodeId"] for r in rows] == ["b", "p"]
        assert [r["argIndex"] for r in rows] == [0, 1]

    def test_each_row_carries_the_columns_its_frame_holds(self):
        previews = {"art-b": BOUNDARIES, "art-p": POPULATION}
        asked: list[str] = []

        def _schema(artifact_id):
            asked.append(artifact_id)
            return us.summarize(previews[artifact_id])

        rows = session._upstream_outputs_for(
            self.SPEC, "a", self._wave_outputs(), schema_fn=_schema,
        )
        assert asked == ["art-b", "art-p"]
        assert rows[0]["schema"]["kind"] == "geotable"
        assert "community" in [c["name"] for c in rows[0]["schema"]["columns"]]
        assert "community_area_name" in [c["name"] for c in rows[1]["schema"]["columns"]]
        # The artifact itself never rides into a prompt — only its description.
        assert all("output" not in row for row in rows)

    def test_a_schema_that_cannot_be_read_leaves_the_row_without_one(self):
        rows = session._upstream_outputs_for(
            self.SPEC, "a", self._wave_outputs(),
            schema_fn=lambda _a: (_ for _ in ()).throw(RuntimeError("sandbox down")),
        )
        assert [r["nodeId"] for r in rows] == ["b", "p"]
        assert all("schema" not in row for row in rows)

    def test_a_direct_upstream_needs_no_arg_index(self):
        spec = {"dataflow": {
            "nodes": [{"id": "b", "type": "curio.builtin/data-loading", "goal": "Boundaries"},
                      {"id": "a", "type": "curio.builtin/computation-analysis", "goal": "D"}],
            "edges": [{"id": "e", "source": "b", "target": "a", "targetHandle": "in"}],
        }}
        rows = session._upstream_outputs_for(spec, "a", self._wave_outputs())
        assert [r["nodeId"] for r in rows] == ["b"]
        assert "argIndex" not in rows[0]

    def test_the_walk_is_depth_bounded(self):
        # A chain of pools longer than the bound resolves nothing rather than
        # walking forever.
        nodes = [{"id": "src", "type": "curio.builtin/data-loading", "goal": "S"}]
        edges = []
        prev = "src"
        for i in range(_DEEP := budgets._UPSTREAM_WALK_MAX_DEPTH + 3):
            nodes.append({"id": f"m{i}", "type": "curio.builtin/data-pool", "goal": f"M{i}"})
            edges.append({"id": f"e{i}", "source": prev, "target": f"m{i}",
                          "targetHandle": "in"})
            prev = f"m{i}"
        nodes.append({"id": "a", "type": "curio.builtin/computation-analysis", "goal": "A"})
        edges.append({"id": "ez", "source": prev, "target": "a", "targetHandle": "in"})
        wave = {"src": {"nodeId": "src", "goal": "S", "outputDataType": "dataframe",
                        "wave": 1, "output": {"path": "art-s"}}}
        rows = session._upstream_outputs_for(
            {"dataflow": {"nodes": nodes, "edges": edges}}, "a", wave,
        )
        assert rows == []

    def test_no_recorded_outputs_is_still_an_empty_list(self):
        assert session._upstream_outputs_for(self.SPEC, "a", {}) == []


class TestTheSchemaReachesTheChildOnEveryRound:
    """The inputs are what the report turned on: three rounds guessed a join
    key because nothing described the frames. A correction that still cannot
    see them would only guess again."""

    def test_generation_and_every_correction_carry_it(self, app, tmp_curio):
        from utk_curio.backend.tests.test_agents.test_verified_rounds import (
            CA,
            _Exec,
            _rounds,
        )

        rows = [
            {"nodeId": "b", "goal": "Boundaries", "outputDataType": "geodataframe",
             "argIndex": 0, "schema": us.summarize(BOUNDARIES)},
            {"nodeId": "p", "goal": "Population", "outputDataType": "dataframe",
             "argIndex": 1, "schema": us.summarize(POPULATION)},
        ]
        node = {"id": "a", "type": CA, "goal": "Calculate Density", "content": ""}
        exec_fn = _Exec(fail_markers=("bad",))
        events, outcome, inputs = _rounds(
            app, node, replies=["bad1()", "bad2()", "bad3()"], exec_fn=exec_fn,
            extra_inputs={"upstreamOutputs": rows},
        )
        assert len(inputs) >= 2, "at least one correction ran"
        for frame in inputs:
            got = frame["upstreamOutputs"]
            assert [r["argIndex"] for r in got] == [0, 1]
            assert "community" in [c["name"] for c in got[0]["schema"]["columns"]]
            assert "community_area_name" in [c["name"] for c in got[1]["schema"]["columns"]]
        # And the correction still gets what failed, as before.
        assert inputs[1]["previousAttempt"] == "bad1()"
