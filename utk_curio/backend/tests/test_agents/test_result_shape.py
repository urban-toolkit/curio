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


class TestNullColumnsAreEmptinessToo:
    """dev/137, dev/133's own F1 arriving as a live defect.

    The owner's `7a27b702`: a `how="left"` join on keys that cannot match kept
    two rows and filled every population column with null. The row count
    passed, the chart's field check passed (the column exists) and both plots
    were empty — a result can be non-empty and still contain nothing.
    """

    JOINED = {
        "kind": "geotable", "rowCount": 2,
        "columns": [{"name": "community", "dtype": "str"},
                    {"name": "area_numbe", "dtype": "int"},
                    {"name": "population", "dtype": "unknown"},
                    {"name": "median_income", "dtype": "unknown"}],
        "sampleRows": [
            {"community": "Loop", "area_numbe": 32, "population": None,
             "median_income": None},
            {"community": "Hyde Park", "area_numbe": 41, "population": None,
             "median_income": None},
        ],
    }
    BOUNDARIES_IN = [{"goal": "Chicago Boundaries", "argIndex": 0, "schema": BOUNDARIES}]

    def test_the_owners_join_is_reported_by_its_null_columns(self):
        assert rs.null_columns(self.JOINED) == ["population", "median_income"]
        assert rs.is_empty(self.JOINED) is False      # it HAS rows
        assert rs.row_count(self.JOINED) == 2

    def test_a_partially_null_column_is_data_not_a_defect(self):
        partly = dict(self.JOINED, sampleRows=[
            {"community": "Loop", "population": 4521},
            {"community": "Hyde Park", "population": None},
        ])
        assert rs.null_columns(partly) == []

    def test_a_column_that_ARRIVED_null_is_not_this_nodes_doing(self):
        upstream = [{"goal": "Population", "schema": {
            "kind": "table", "rowCount": 3,
            "columns": [{"name": "population", "dtype": "unknown"}],
            "sampleRows": [{"population": None}],
        }}]
        # `population` came in null; only `median_income` is this node's.
        assert rs.created_null_columns(self.JOINED, upstream) == ["median_income"]

    def test_a_column_whose_NAME_exists_upstream_but_HAD_values_is_this_nodes_doing(self):
        """The owner's actual case: the population TABLE has values (4521,
        3890), and the joined frame's `population` is all null — so "the name
        exists upstream" would have excluded exactly the defect."""
        upstream = [{"goal": "Population Data", "schema": {
            "kind": "table", "rowCount": 3,
            "columns": [{"name": "population", "dtype": "int"},
                        {"name": "median_income", "dtype": "int"}],
            "sampleRows": [{"population": 4521, "median_income": 61200}],
        }}]
        assert rs.created_null_columns(self.JOINED, upstream) == [
            "population", "median_income",
        ]

    def test_with_no_upstream_described_every_null_column_counts(self):
        # A loader that read nothing useful is the loader's problem.
        assert rs.created_null_columns(self.JOINED, None) == [
            "population", "median_income",
        ]

    def test_no_sample_rows_means_no_claim(self):
        assert rs.null_columns(dict(self.JOINED, sampleRows=[])) == []
        assert rs.null_columns({"kind": "table", "rowCount": 5}) == []
        assert rs.null_columns(None) == []

    def test_parts_are_walked(self):
        merged = {"kind": "parts", "parts": [self.JOINED]}
        assert "population" in rs.null_columns(merged)

    def test_the_refusal_names_the_columns_the_rows_and_the_prohibition(self):
        text = rs.null_refusal_text(
            columns=["population", "median_income"], summary=self.JOINED,
            upstream_outputs=self.BOUNDARIES_IN,
        )
        assert "produced 2 rows" in text
        assert "every sampled value of population, median_income is NULL" in text
        assert "area_numbe int e.g. 32" in text          # what the input HAS
        assert 'how="left"' in text
        assert "say so in one line and return no code" in text
        assert len(text) <= 900


class TestTheAbsentOutputRefusal:
    """dev/138: quoting the node's own conclusion is what makes it land."""

    OWNERS = ("# These IDs do not match in type or scale.\n"
              "# A join is not possible with the provided columns.\n\nreturn None")

    def test_the_last_substantive_comment_is_the_conclusion(self):
        assert rs.declared_conclusion(self.OWNERS) == (
            "A join is not possible with the provided columns."
        )
        # Short markers ("# fix", "# TODO") are not conclusions.
        assert rs.declared_conclusion("# ok\nreturn None") == ""
        assert rs.declared_conclusion("return None") == ""
        assert rs.declared_conclusion(None) == ""

    def test_the_refusal_quotes_it_and_names_the_decline(self):
        text = rs.absent_output_refusal(
            code=self.OWNERS, output_data_type="null",
            upstream_outputs=[{"goal": "Boundaries", "schema": BOUNDARIES}],
        )
        assert text.startswith("the code ran and returned NO output")
        assert "'null'" in text
        assert "A join is not possible with the provided columns." in text
        assert "with no code at all" in text
        assert "What you were given:" in text
        assert len(text) <= 900

    def test_without_a_conclusion_it_still_names_the_decline(self):
        text = rs.absent_output_refusal(code="return None")
        assert "say so in one line with no code" in text
