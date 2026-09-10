"""dev/128: the shape of `arg`, stated and enforced.

The owner's sentence is the specification — *"The merge node always outputs a
list called `arg`, where each item in this list corresponds to the linked nodes
in the order of their connections to the input handles of the merge node. Your
attempts always used `arg` alone; when I changed it to `arg[0]`, it worked
correctly."* — and the graph below is theirs, from dataflow `623b6620`.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import input_contract as ic

MERGE_SPEC = {
    "dataflow": {
        "nodes": [
            {"id": "b", "type": "curio.builtin/data-loading",
             "goal": "Chicago Community Boundaries"},
            {"id": "p", "type": "curio.builtin/data-loading", "goal": "Population Data"},
            {"id": "m", "type": "curio.builtin/merge-flow", "goal": "Merge Inputs"},
            {"id": "a", "type": "curio.builtin/computation-analysis",
             "goal": "Calculate Density"},
        ],
        "edges": [
            {"id": "e0", "source": "b", "target": "m", "targetHandle": "in_0"},
            {"id": "e1", "source": "p", "target": "m", "targetHandle": "in_1"},
            {"id": "e2", "source": "m", "target": "a", "targetHandle": "in"},
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
    def test_a_multi_input_merge_is_a_list_in_handle_order(self):
        shape = ic.arg_shape(MERGE_SPEC, "a")
        assert shape["kind"] == ic.KIND_LIST
        assert shape["length"] == 2
        assert shape["via"] == "m"
        assert [s["argIndex"] for s in shape["slots"]] == [0, 1]
        assert [s["goal"] for s in shape["slots"]] == [
            "Chicago Community Boundaries", "Population Data",
        ]

    def test_a_single_input_merge_passes_the_value_through(self):
        # The runner's own rule — the mirror bug a naive "merge → index it"
        # would have introduced.
        spec = {"dataflow": {
            "nodes": MERGE_SPEC["dataflow"]["nodes"],
            "edges": [
                {"id": "e0", "source": "b", "target": "m", "targetHandle": "in_0"},
                {"id": "e2", "source": "m", "target": "a", "targetHandle": "in"},
            ],
        }}
        shape = ic.arg_shape(spec, "a")
        assert shape["kind"] == ic.KIND_SINGLE
        assert shape["goal"] == "Chicago Community Boundaries"

    def test_a_code_upstream_is_a_single_value(self):
        spec = {"dataflow": {
            "nodes": MERGE_SPEC["dataflow"]["nodes"],
            "edges": [{"id": "e", "source": "b", "target": "a", "targetHandle": "in"}],
        }}
        assert ic.arg_shape(spec, "a")["kind"] == ic.KIND_SINGLE

    def test_no_upstream_is_none(self):
        assert ic.arg_shape(MERGE_SPEC, "b")["kind"] == ic.KIND_NONE
        assert ic.arg_shape(None, "a")["kind"] == ic.KIND_NONE

    def test_it_looks_through_a_pool_between_the_merge_and_the_node(self):
        spec = {"dataflow": {
            "nodes": MERGE_SPEC["dataflow"]["nodes"] + [
                {"id": "pool", "type": "curio.builtin/data-pool", "goal": "Pool"},
            ],
            "edges": [
                {"id": "e0", "source": "b", "target": "m", "targetHandle": "in_0"},
                {"id": "e1", "source": "p", "target": "m", "targetHandle": "in_1"},
                {"id": "e2", "source": "m", "target": "pool", "targetHandle": "in"},
                {"id": "e3", "source": "pool", "target": "a", "targetHandle": "in"},
            ],
        }}
        shape = ic.arg_shape(spec, "a")
        assert shape["kind"] == ic.KIND_LIST and shape["length"] == 2

    def test_describe_reads_as_a_sentence(self):
        line = ic.describe(ic.arg_shape(MERGE_SPEC, "a"))
        assert line.startswith("arg is a list of 2 inputs")
        assert "arg[0] = Chicago Community Boundaries" in line
        assert ic.describe(ic.arg_shape(MERGE_SPEC, "b")) == "this node has no input"
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
        shape = ic.with_schemas(ic.arg_shape(MERGE_SPEC, "a"), self.ROWS)
        assert [c["name"] for c in shape["slots"][0]["schema"]["columns"]] == [
            "community", "geometry",
        ]
        # One copy of the sample rows is enough — they ride upstreamOutputs.
        assert "sampleRows" not in shape["slots"][0]["schema"]
        assert "TOT_POP" in [c["name"] for c in shape["slots"][1]["schema"]["columns"]]

    def test_a_slot_whose_upstream_has_not_run_keeps_its_goal_alone(self):
        shape = ic.with_schemas(ic.arg_shape(MERGE_SPEC, "a"), [self.ROWS[0]])
        assert "schema" in shape["slots"][0]
        assert "schema" not in shape["slots"][1]

    def test_no_rows_changes_nothing(self):
        shape = ic.arg_shape(MERGE_SPEC, "a")
        assert ic.with_schemas(shape, None) == shape
        assert ic.with_schemas(shape, []) == shape


class TestCheck:
    def _shape(self):
        return ic.arg_shape(MERGE_SPEC, "a")

    def test_the_owners_code_is_refused_and_the_refusal_names_the_slots(self):
        violation = ic.check(ARG_AS_A_FRAME, self._shape())
        assert violation == {"attribute": "crs", "name": "gdf", "line": 5}
        text = ic.refusal_text(ic.with_schemas(self._shape(), TestWithSchemas.ROWS), violation)
        assert "`arg` is a LIST of 2 inputs" in text
        assert "arg[0] = Chicago Community Boundaries" in text
        assert "community" in text  # the columns of the slot it should have used
        assert "a list has no attribute 'crs'" in text
        assert "arg` alone is the list itself" in text

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
