"""dev/133: an empty result is a verdict.

Every shape below is the shape ``upstream_schema.summarize`` actually produces,
and the two frames in the join case are the owner's own — `e72c7080` merged
``area_numbe ∈ {32, 41}`` (community-area numbers) against
``tract_id ∈ {17031010100, …}`` (census tracts), ran clean, and returned zero
rows.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import result_shape as rs

BOUNDARIES = {
    "kind": "geotable",
    "rowCount": 2,
    "columns": [{"name": "community", "dtype": "str"},
                {"name": "area_numbe", "dtype": "int"}],
    "sampleRows": [{"community": "Loop", "area_numbe": 32}],
}
POPULATION = {
    "kind": "table",
    "rowCount": 3,
    "columns": [{"name": "tract_id", "dtype": "str"},
                {"name": "population", "dtype": "int"}],
    "sampleRows": [{"tract_id": "17031010100", "population": 4521}],
}
JOINED_EMPTY = {"kind": "geotable", "rowCount": 0, "columns": [
    {"name": "community", "dtype": "str"}, {"name": "density", "dtype": "float"},
], "sampleRows": []}


class TestRowCountAndEmptiness:
    def test_a_table_with_no_rows_is_empty(self):
        assert rs.is_empty({"kind": "table", "rowCount": 0}) is True
        assert rs.is_empty({"kind": "table", "rowCount": 5}) is False

    def test_a_geotable_with_no_features_is_empty(self):
        assert rs.is_empty(JOINED_EMPTY) is True
        assert rs.is_empty(BOUNDARIES) is False

    def test_parts_are_empty_only_when_every_part_is(self):
        empty = {"kind": "parts", "parts": [{"kind": "table", "rowCount": 0},
                                            {"kind": "table", "rowCount": 0}]}
        partly = {"kind": "parts", "parts": [{"kind": "table", "rowCount": 0},
                                             {"kind": "table", "rowCount": 4}]}
        assert rs.is_empty(empty) is True
        assert rs.is_empty(partly) is False
        assert rs.row_count(partly) == 4

    def test_an_uncountable_shape_is_never_empty(self):
        for summary in ({"kind": "dict"}, {"kind": "raster"}, {"kind": "value"},
                        {"kind": "table"}, {"kind": "parts", "parts": []}):
            assert rs.is_empty(summary) is False, summary

    def test_an_unknown_shape_is_never_empty(self):
        assert rs.is_empty(None) is False
        assert rs.is_empty({}) is False
        assert rs.row_count(None) is None


class TestWhetherTheInputsHadRows:
    def _rows(self, *summaries):
        return [{"goal": f"input {i}", "schema": s} for i, s in enumerate(summaries)]

    def test_all_inputs_with_rows_is_true(self):
        assert rs.inputs_had_rows(self._rows(BOUNDARIES, POPULATION)) is True

    def test_any_empty_input_is_false_and_the_node_is_not_blamed(self):
        empty = {"kind": "table", "rowCount": 0}
        assert rs.inputs_had_rows(self._rows(BOUNDARIES, empty)) is False

    def test_unknown_is_none_so_nothing_is_attributed(self):
        assert rs.inputs_had_rows(None) is None
        assert rs.inputs_had_rows([]) is None
        assert rs.inputs_had_rows([{"goal": "no schema"}]) is None
        assert rs.inputs_had_rows(self._rows({"kind": "dict"})) is None


class TestTheDiagnosis:
    def test_it_names_the_row_counts_the_columns_and_their_VALUES(self):
        rows = [
            {"goal": "Chicago Boundaries", "argIndex": 0, "schema": BOUNDARIES},
            {"goal": "Population Data", "argIndex": 1, "schema": POPULATION},
        ]
        text = rs.refusal_text(
            summary=JOINED_EMPTY, upstream_outputs=rows, output_data_type="geodataframe",
        )
        assert text.startswith("the code ran but produced an EMPTY result — 0 rows")
        assert "geodataframe" in text
        assert "arg[0] 'Chicago Boundaries'" in text and "2 rows" in text
        assert "arg[1] 'Population Data'" in text and "3 rows" in text
        # The VALUES are the point: the column names looked joinable.
        assert "area_numbe int e.g. 32" in text
        assert "tract_id str e.g. '17031010100'" in text
        # The cause class and the honest alternative.
        assert "A join, merge or filter matched nothing" in text
        assert "cannot be joined" in text

    def test_it_is_bounded_and_survives_missing_pieces(self):
        text = rs.refusal_text(
            summary=None,
            upstream_outputs=[{"goal": "x" * 200}, {"schema": {"kind": "table"}}],
        )
        assert len(text) <= 900
        assert "shape unknown" in text
        text_no_inputs = rs.refusal_text(summary=JOINED_EMPTY, upstream_outputs=None)
        assert "inputs were NOT empty" not in text_no_inputs
        assert "matched nothing" in text_no_inputs

    def test_many_columns_are_summarized_not_dumped(self):
        wide = {
            "kind": "table", "rowCount": 1,
            "columns": [{"name": f"c{i}", "dtype": "int"} for i in range(20)],
            "sampleRows": [{f"c{i}": i for i in range(20)}],
        }
        text = rs.refusal_text(
            summary=JOINED_EMPTY, upstream_outputs=[{"goal": "wide", "schema": wide}],
        )
        assert "12 more" in text  # 20 columns, 8 named
