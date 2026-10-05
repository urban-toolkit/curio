"""dev/128: the shape of `arg`, stated and enforced.

The owner's sentence is the specification — *"The merge node always outputs a
list called `arg`, where each item in this list corresponds to the linked nodes
in the order of their connections to the input handles of the merge node. Your
attempts always used `arg` alone; when I changed it to `arg[0]`, it worked
correctly."*, and the graph below is theirs, from dataflow `623b6620`, with
the Merge Flow gone (#662): both loaders now feed the analysis node straight,
each on its own input circle, and its code reads them through input chips.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.domain import input_contract as ic

MULTI_INPUT_SPEC = {
    "dataflow": {
        "nodes": [
            {"id": "b", "type": "curio.builtin/data-loading",
             "goal": "Chicago Community Boundaries"},
            {"id": "p", "type": "curio.builtin/data-loading", "goal": "Population Data"},
            {"id": "a", "type": "curio.builtin/computation-analysis",
             "goal": "Calculate Density"},
        ],
        # Listed and named against circle order on purpose: circle "in" (0)
        # is the boundaries, circle "in_1" the population.
        "edges": [
            {"id": "e0", "source": "p", "target": "a", "targetHandle": "in_1"},
            {"id": "e1", "source": "b", "target": "a", "targetHandle": "in"},
        ],
    }
}

# The owner's own code, before their edit.
ARG_AS_A_FRAME = """import geopandas as gpd

gdf = arg

if gdf.crs is None:
    gdf = gdf.set_crs("EPSG:4326")

gdf = gdf.to_crs(3395)
return gdf
"""


class TestArgShape:
    def test_a_node_with_several_inputs_is_a_list_in_circle_order(self):
        shape = ic.arg_shape(MULTI_INPUT_SPEC, "a")
        assert shape["kind"] == ic.KIND_LIST
        assert shape["length"] == 2
        assert shape["via"] == "a"  # the node's own circles, no node between
        assert [s["argIndex"] for s in shape["slots"]] == [0, 1]
        assert [s["goal"] for s in shape["slots"]] == [
            "Chicago Community Boundaries", "Population Data",
        ]
        # The slot's type is named unambiguously — the child's own inputs carry
        # a "nodeType" for the node being generated.
        assert shape["slots"][0]["upstreamNodeType"] == "curio.builtin/data-loading"
        assert shape["slots"][0]["upstreamNodeId"] == "b"
        # Neither key shadows the child's own inputs for the node being made.
        assert all("nodeType" not in slot and "nodeId" not in slot for slot in shape["slots"])

    def test_one_connected_circle_passes_the_value_not_a_list(self):
        # The runner's own rule, the mirror bug a naive "it can take several
        # inputs, so index it" would introduce: a growing node with ONE edge
        # gets that value, even when the edge sits on circle "in_1".
        spec = {"dataflow": {
            "nodes": MULTI_INPUT_SPEC["dataflow"]["nodes"],
            "edges": [{"id": "e0", "source": "p", "target": "a", "targetHandle": "in_1"}],
        }}
        shape = ic.arg_shape(spec, "a")
        assert shape["kind"] == ic.KIND_SINGLE
        assert shape["goal"] == "Population Data"

    def test_a_node_with_no_code_and_one_input_passes_the_value_through(self):
        # What the single-input Merge did, a pool does: the node after it gets
        # the one value it forwards, named by the node that made it.
        spec = {"dataflow": {
            "nodes": MULTI_INPUT_SPEC["dataflow"]["nodes"] + [
                {"id": "pool", "type": "curio.builtin/data-pool", "goal": "Pool"},
            ],
            "edges": [
                {"id": "e0", "source": "b", "target": "pool", "targetHandle": "in"},
                {"id": "e1", "source": "pool", "target": "a", "targetHandle": "in"},
            ],
        }}
        shape = ic.arg_shape(spec, "a")
        assert shape["kind"] == ic.KIND_SINGLE
        assert shape["goal"] == "Chicago Community Boundaries"
        assert shape["upstreamNodeId"] == "b"

    def test_a_code_upstream_is_a_single_value(self):
        spec = {"dataflow": {
            "nodes": MULTI_INPUT_SPEC["dataflow"]["nodes"],
            "edges": [{"id": "e", "source": "b", "target": "a", "targetHandle": "in"}],
        }}
        assert ic.arg_shape(spec, "a")["kind"] == ic.KIND_SINGLE

    def test_no_upstream_is_none(self):
        assert ic.arg_shape(MULTI_INPUT_SPEC, "b")["kind"] == ic.KIND_NONE
        assert ic.arg_shape(None, "a")["kind"] == ic.KIND_NONE

    def test_it_looks_through_a_pool_with_several_inputs_to_the_node(self):
        # Both loaders on the pool's circles, the pool into the node: the node
        # gets the pool's list, in the pool's circle order.
        spec = {"dataflow": {
            "nodes": MULTI_INPUT_SPEC["dataflow"]["nodes"] + [
                {"id": "pool", "type": "curio.builtin/data-pool", "goal": "Pool"},
            ],
            "edges": [
                {"id": "e0", "source": "p", "target": "pool", "targetHandle": "in_1"},
                {"id": "e1", "source": "b", "target": "pool", "targetHandle": "in"},
                {"id": "e2", "source": "pool", "target": "a", "targetHandle": "in"},
            ],
        }}
        shape = ic.arg_shape(spec, "a")
        assert shape["kind"] == ic.KIND_LIST and shape["length"] == 2
        assert shape["via"] == "pool"
        assert [s["upstreamNodeId"] for s in shape["slots"]] == ["b", "p"]
        # The node has one input, the pool's list: its items are read by index.
        assert [s["chip"] for s in shape["slots"]] == ["[!! input 0 !!][0]", "[!! input 0 !!][1]"]

    def test_a_slot_is_read_by_the_chip_of_its_circle_not_its_position(self):
        # A plan can wire circles with a gap (`in`, `in_3`). The chip names the
        # circle, so the second input is `[!! input 3 !!]`, which the run turns
        # into arg[1]; `[!! input 1 !!]` would name a circle with no edge.
        spec = {"dataflow": {
            "nodes": MULTI_INPUT_SPEC["dataflow"]["nodes"],
            "edges": [
                {"id": "e0", "source": "p", "target": "a", "targetHandle": "in_3"},
                {"id": "e1", "source": "b", "target": "a", "targetHandle": "in"},
            ],
        }}
        shape = ic.arg_shape(spec, "a")
        assert shape["circles"] == [0, 3]
        assert [(s["argIndex"], s["circle"], s["chip"]) for s in shape["slots"]] == [
            (0, 0, "[!! input 0 !!]"), (1, 3, "[!! input 3 !!]"),
        ]
        assert "[!! input 3 !!] = Population Data" in ic.describe(shape)
        assert ic.check("gdf = [!! input 3 !!]\nreturn gdf.crs", shape) is None
        violation = ic.check("pop = [!! input 3 !!]\nreturn arg.crs", shape)
        assert violation == {"attribute": "crs", "name": "arg", "line": 2}
        refusal = ic.refusal_text(shape, violation)
        assert "([!! input 0 !!], [!! input 3 !!], ...)" in refusal

    def test_one_input_on_a_later_circle_is_read_by_that_circles_chip(self):
        spec = {"dataflow": {
            "nodes": MULTI_INPUT_SPEC["dataflow"]["nodes"],
            "edges": [{"id": "e0", "source": "p", "target": "a", "targetHandle": "in_1"}],
        }}
        assert ic.describe(ic.arg_shape(spec, "a")) == (
            "[!! input 1 !!] (arg) IS the value Population Data returned"
        )

    def test_describe_reads_as_a_sentence(self):
        line = ic.describe(ic.arg_shape(MULTI_INPUT_SPEC, "a"))
        assert line.startswith("arg is a list of 2 inputs: ")
        assert "[!! input 0 !!] = Chicago Community Boundaries" in line
        assert "[!! input 1 !!] = Population Data" in line
        single = {"dataflow": {
            "nodes": MULTI_INPUT_SPEC["dataflow"]["nodes"],
            "edges": [{"id": "e", "source": "b", "target": "a", "targetHandle": "in"}],
        }}
        assert ic.describe(ic.arg_shape(single, "a")) == (
            "[!! input 0 !!] (arg) IS the value Chicago Community Boundaries returned"
        )
        assert ic.describe(ic.arg_shape(MULTI_INPUT_SPEC, "b")) == "this node has no input"
        assert ic.describe(None) == ""


class TestWithSchemas:
    ROWS = [
        {"nodeId": "b", "schema": {"kind": "geotable", "rowCount": 77,
                                   "columns": [{"name": "community"}, {"name": "geometry"}],
                                   "sampleRows": [{"community": "DOUGLAS"}]}},
        {"nodeId": "p", "schema": {"kind": "table", "rowCount": 77,
                                   "columns": [{"name": "GEOID"}, {"name": "TOT_POP"}]}},
    ]

    def test_slots_gain_their_columns_and_drop_the_sample(self):
        shape = ic.with_schemas(ic.arg_shape(MULTI_INPUT_SPEC, "a"), self.ROWS)
        assert [c["name"] for c in shape["slots"][0]["schema"]["columns"]] == [
            "community", "geometry",
        ]
        # One copy of the sample rows is enough — they ride upstreamOutputs.
        assert "sampleRows" not in shape["slots"][0]["schema"]
        assert "TOT_POP" in [c["name"] for c in shape["slots"][1]["schema"]["columns"]]

    def test_a_slot_whose_upstream_has_not_run_keeps_its_goal_alone(self):
        shape = ic.with_schemas(ic.arg_shape(MULTI_INPUT_SPEC, "a"), [self.ROWS[0]])
        assert "schema" in shape["slots"][0]
        assert "schema" not in shape["slots"][1]

    def test_no_rows_changes_nothing(self):
        shape = ic.arg_shape(MULTI_INPUT_SPEC, "a")
        assert ic.with_schemas(shape, None) == shape
        assert ic.with_schemas(shape, []) == shape


class TestCheck:
    def _shape(self):
        return ic.arg_shape(MULTI_INPUT_SPEC, "a")

    def test_the_owners_code_is_refused_and_the_refusal_names_the_slots(self):
        violation = ic.check(ARG_AS_A_FRAME, self._shape())
        assert violation == {"attribute": "crs", "name": "gdf", "line": 5}
        text = ic.refusal_text(ic.with_schemas(self._shape(), TestWithSchemas.ROWS), violation)
        assert text.startswith(
            "input contract refused: this node has 2 inputs, so `arg` is a LIST "
            "of them in circle order: "
        )
        assert "[!! input 0 !!] = Chicago Community Boundaries" in text
        assert "[!! input 1 !!] = Population Data" in text
        assert "community" in text  # the columns of the slot it should have used
        assert "Your code used `gdf.crs (line 5)`: a list has no attribute 'crs'" in text
        assert "Read the input you need through its chip ([!! input 0 !!], [!! input 1 !!], ...)" in text
        assert "`arg` alone is the list itself" in text
        assert "merge" not in text.lower()

    def test_direct_attribute_access_on_arg_is_refused(self):
        for code in ("return arg.crs", "x = arg.merge(y)", "print(arg.columns)"):
            assert ic.check(code, self._shape()), code

    def test_legitimate_list_uses_are_never_refused(self):
        for code in (
            "gdf = arg[0]\nreturn gdf.to_crs(3395)",
            "return arg[0].crs",  # an attribute of a SUBSCRIPT
            "for frame in arg:\n    print(frame.shape)",
            "return len(arg)",
            "import pandas as pd\nreturn pd.concat(arg)",
            "return arg",
            "a, b = arg\nreturn a.merge(b)",
        ):
            assert ic.check(code, self._shape()) is None, code

    def test_a_single_shape_refuses_nothing(self):
        single = {"kind": ic.KIND_SINGLE, "nodeId": "b", "goal": "Boundaries"}
        assert ic.check("return arg.crs", single) is None
        assert ic.check("return arg[0]", single) is None

    def test_a_rebound_name_is_still_the_list(self):
        code = "gdf = arg\nother = gdf\nreturn other.to_crs(3395)"
        assert ic.check(code, self._shape())["attribute"] == "to_crs"

    def test_a_name_bound_to_a_slot_is_not_the_list(self):
        code = "gdf = arg[1]\nreturn gdf.to_crs(3395)"
        assert ic.check(code, self._shape()) is None

    def test_a_syntax_error_is_not_this_gates_business(self):
        assert ic.check("def broken(:\n  pass", self._shape()) is None

    def test_code_without_arg_cannot_violate_a_contract_about_it(self):
        assert ic.check("import pandas as pd\nreturn pd.DataFrame()", self._shape()) is None
        assert ic.check("", self._shape()) is None
        assert ic.check(None, self._shape()) is None

    def test_code_reading_its_inputs_through_chips_is_never_refused(self):
        # The way the prompts teach it: each chip becomes arg[k] at run time,
        # an attribute of a SUBSCRIPT.
        for code in (
            "gdf = [!! input 0 !!]\nif gdf.crs is None:\n    gdf = gdf.set_crs(4326)\nreturn gdf",
            "return [!! input 1 !!].merge([!! input 0 !!], on=[!! input 0.community !!])",
            "frames = [[!! input 0 !!], [!! input 1 !!]]\nreturn len(arg), frames[0].crs",
        ):
            assert ic.check(code, self._shape()) is None, code

    def test_chips_do_not_hide_an_attribute_of_the_list(self):
        # The code is judged as it runs: chips resolved, it still parses, and
        # `arg.crs` beside them is the owner's mistake again.
        code = "gdf = [!! input 0 !!]\npop = [!! input 1 !!]\nreturn arg.crs"
        assert ic.check(code, self._shape()) == {"attribute": "crs", "name": "arg", "line": 3}
        rebound = "frames = arg\nfirst = [!! input 0 !!]\nreturn frames.to_crs(3395)"
        assert ic.check(rebound, self._shape())["attribute"] == "to_crs"

    def test_widget_references_do_not_turn_the_gate_off(self):
        # #662: a widget or shared tag is a value when the node runs. Left in
        # place, the code did not parse and the gate let `arg.crs` through.
        code = "factor = [!! factor !!]\nseason = [!! @season !!]\nreturn arg.crs"
        assert ic.check(code, self._shape()) == {"attribute": "crs", "name": "arg", "line": 3}
        fine = "gdf = [!! input 0 !!]\ngdf['h'] = gdf['h'] * [!! factor !!]\nreturn gdf"
        assert ic.check(fine, self._shape()) is None


class TestTheGateInTheLoop:
    """dev/128: the refusal happens BEFORE the sandbox, and the correction is
    the model's — the owner's sequence, mechanised."""

    SPEC = {
        "dataflow": {
            "name": "wf", "task": "compare neighborhoods",
            "nodes": [
                {"id": "b", "type": "curio.builtin/data-loading", "goal": "Boundaries",
                 "content": "return 1"},
                {"id": "p", "type": "curio.builtin/data-loading", "goal": "Population",
                 "content": "return 2"},
                {"id": "t", "type": "curio.builtin/data-transformation", "goal": "Densities",
                 "content": ""},
            ],
            # Both loaders straight into the node, one circle each (#662).
            "edges": [
                {"id": "u1", "source": "b", "target": "t", "targetHandle": "in"},
                {"id": "u2", "source": "p", "target": "t", "targetHandle": "in_1"},
            ],
        }
    }

    def _rounds(self, app, **kw):
        from utk_curio.backend.tests.test_agents.test_verified_rounds import _Exec, _rounds

        node = self.SPEC["dataflow"]["nodes"][2]
        return _rounds(app, node, exec_fn=kw.pop("exec_fn", None) or _Exec(),
                       spec=self.SPEC, **kw)

    def test_arg_as_a_frame_is_refused_without_running_and_the_fix_passes(self, app, tmp_curio):
        from utk_curio.backend.tests.test_agents.test_verified_rounds import _Exec

        exec_fn = _Exec()
        events, outcome, inputs = self._rounds(
            app,
            replies=[ARG_AS_A_FRAME, "gdf = [!! input 0 !!]\nreturn gdf.to_crs(3395)"],
            exec_fn=exec_fn,
        )
        assert outcome["verdict"] == "pass"
        kinds = [a["kind"] for a in outcome["attempts"]]
        assert kinds == ["input-contract", "executed"]
        # Round 1 never reached the sandbox: the refusal is free. (The slice's
        # two upstream loaders run, as they always do — what must not appear is
        # the refused candidate.)
        ran = [c["code"] for c in exec_fn.calls]
        assert not any("set_crs" in code for code in ran), ran
        assert sum("to_crs(3395)" in code for code in ran) == 1
        # The fix read circle 0 through its chip, and ran as arg[0].
        assert any("gdf = arg[0]" in code for code in ran), ran
        assert not any("[!! input" in code for code in ran), ran
        # The refused round kept its code, so the trail shows arg, then the chip.
        assert outcome["attempts"][0]["code"].startswith("import geopandas")
        # And the correction was told exactly what was wrong.
        error = inputs[1]["validationError"]
        assert "this node has 2 inputs, so `arg` is a LIST of them in circle order" in error
        assert "[!! input 0 !!] = Boundaries" in error
        assert "[!! input 1 !!] = Population" in error

    def test_the_contract_rides_the_first_generation_and_every_correction(self, app, tmp_curio):
        events, outcome, inputs = self._rounds(
            app, replies=[ARG_AS_A_FRAME, "gdf = [!! input 0 !!]\nreturn gdf"],
        )
        assert len(inputs) == 2
        for frame in inputs:
            contract = frame["inputContract"]
            assert contract["kind"] == "list" and contract["length"] == 2
            assert [s["argIndex"] for s in contract["slots"]] == [0, 1]
            assert [s["goal"] for s in contract["slots"]] == ["Boundaries", "Population"]

    def test_a_node_with_a_single_upstream_is_never_gated(self, app, tmp_curio):
        from utk_curio.backend.tests.test_agents.test_verified_rounds import _Exec, _rounds

        spec = {"dataflow": {
            "name": "wf", "task": "t",
            "nodes": [
                {"id": "b", "type": "curio.builtin/data-loading", "goal": "B", "content": "return 1"},
                {"id": "t", "type": "curio.builtin/data-transformation", "goal": "T", "content": ""},
            ],
            "edges": [{"id": "e", "source": "b", "target": "t", "targetHandle": "in"}],
        }}
        exec_fn = _Exec()
        events, outcome, inputs = _rounds(
            app, spec["dataflow"]["nodes"][1], replies=["return arg.describe()"],
            exec_fn=exec_fn, spec=spec,
        )
        assert outcome["verdict"] == "pass"
        assert [a["kind"] for a in outcome["attempts"]] == ["executed"]
        assert inputs[0]["inputContract"]["kind"] == "single"

    def test_a_loader_gets_no_contract_at_all(self, app, tmp_curio):
        from utk_curio.backend.tests.test_agents.test_verified_rounds import _Exec, _rounds

        spec = {"dataflow": {"name": "wf", "task": "t", "nodes": [
            {"id": "b", "type": "curio.builtin/data-loading", "goal": "B", "content": ""},
        ], "edges": []}}
        events, outcome, inputs = _rounds(
            app, spec["dataflow"]["nodes"][0], replies=["return 1"], exec_fn=_Exec(), spec=spec,
        )
        assert "inputContract" not in inputs[0]
