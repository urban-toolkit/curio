"""How a JSON Lines table's lines become rows (``domain/json_rows.py``): the
options a manifest declares, the paths they name, and what each line gives,
or why it gives none. The real lines are cut, byte for byte, from SAGE-IDOT's
detections on data.urbantk.org (``data/sage-idot-lines.jsonl``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.app.discovery.domain import json_rows as R

LINES = (Path(__file__).resolve().parent / "data" / "sage-idot-lines.jsonl").read_bytes().split(b"\n")

#: One row per detection: the line's time, the image's, the model, its time,
#: and the detection's class, confidence and box.
DETECTIONS = {
    "parse": ["value"],
    "columns": {"timestamp": {"path": "timestamp", "type": "timestamp"},
                "image_timestamp_ns": "value.image_timestamp_ns"},
    "unpack": [
        {"path": "value.models_results", "key": "model",
         "columns": {"inference_time_seconds": "inference_time_seconds"}},
        {"path": "detections",
         "columns": {"class": "class", "confidence": "confidence",
                     "x0": "bbox.0", "y0": "bbox.1", "x1": "bbox.2", "y1": "bbox.3"}},
    ],
}


def rows(record, options):
    return R.rows_of(record, R.read_options(options))


def line(number: int) -> bytes:
    """The fixture's line *number*, counted from 1, with its line break."""
    return LINES[number - 1] + b"\n"


class TestTheOptions:
    def test_the_detections_name_each_column_in_order(self):
        assert R.read_options(DETECTIONS).names == (
            "timestamp", "image_timestamp_ns", "model", "inference_time_seconds",
            "class", "confidence", "x0", "y0", "x1", "y1",
        )

    def test_each_column_has_its_type_or_none(self):
        assert R.read_options(DETECTIONS).types == ("timestamp",) + (None,) * 9

    def test_with_no_options_the_lines_fields_are_the_columns(self):
        assert R.read_options({}).names is None
        assert R.read_options({}).types is None

    @pytest.mark.parametrize("options, words", [
        ({"delimiter": ";"}, "a jsonl table reads no delimiter; its options are parse, columns and unpack"),
        ({"unpack": [{"path": "a"}]}, "unpack names no column: name the columns a row keeps"),
        ({"columns": {"a": "a", "A": "b"}}, "the column 'A' is named twice"),
        ({"unpack": [{"path": "a", "key": "k"}], "columns": {"k": "b"}}, "the column 'k' is named twice"),
        ({"columns": {"__Curio_row": "a"}}, "columns: a column name may not start with __curio_"),
        ({"columns": {}}, "columns must name at least one column"),
        ({"columns": ["a"]}, "columns must name at least one column, as an object of names and paths"),
        ({"columns": {"a": 3}}, "columns.a must be a path of at most 256 characters"),
        ({"columns": {"a": "b..c"}}, "columns.a: 'b..c' has an empty name between dots"),
        ({"columns": {"a": "x" * 257}}, "columns.a must be a path of at most 256 characters"),
        ({"columns": {"a\tb": "a"}}, "a column name is 1 to 128 characters, with no control characters"),
        ({"parse": []}, "parse must list 1 to 16 fields"),
        ({"parse": [""]}, "parse must name a field"),
        ({"unpack": []}, "unpack must list 1 to 8 levels"),
        ({"unpack": [{"path": "a", "columns": {f"c{n}": ""}} for n in range(9)]}, "unpack must list 1 to 8 levels"),
        ({"unpack": ["a"]}, "unpack[0] must be an object with a path"),
        ({"unpack": [{"key": "k"}]}, "unpack[0] needs a path"),
        ({"unpack": [{"path": "a", "keys": "k"}]}, "unpack[0] reads no keys; a level takes path, key and columns"),
        ({"columns": {f"c{n}": "a" for n in range(257)}}, "a row keeps at most 256 columns"),
        ({"columns": {"t": {"path": "t", "type": "date"}}},
         "columns.t.type must be one of timestamp, int, float, string, bool"),
        ({"columns": {"t": {"type": "int"}}}, "columns.t needs a path"),
        ({"columns": {"t": {"path": "t", "unit": "s"}}}, "columns.t reads no unit; a column takes path and type"),
        ({"unpack": [{"path": "a", "columns": {"c": {"path": "c..d", "type": "int"}}}]},
         "unpack[0].columns.c.path: 'c..d' has an empty name between dots"),
    ], ids=[
        "csv-option", "unpack-names-nothing", "same-name-any-case", "key-and-column-same-name",
        "reserved-prefix", "no-columns", "columns-not-an-object", "path-not-text", "empty-name-in-path",
        "path-too-long", "control-character-in-name", "parse-empty", "parse-empty-path", "unpack-empty",
        "too-many-levels", "level-not-an-object", "level-without-path", "unknown-level-key", "too-many-columns",
        "unknown-type", "typed-column-without-path", "unknown-column-key", "bad-path-in-a-typed-level-column",
    ])
    def test_options_that_cannot_be_read_are_refused_with_why(self, options, words):
        with pytest.raises(R.OptionError) as raised:
            R.read_options(options)
        assert words in str(raised.value)

    def test_another_format_does_not_take_them(self):
        with pytest.raises(R.OptionError, match="a csv table reads no unpack: parse, columns and unpack"):
            R.check_options("csv", {"unpack": [{"path": "a", "key": "k"}]})
        with pytest.raises(R.OptionError, match="a collection reads no parse, columns"):
            R.check_options(None, {"parse": ["a"], "columns": {"a": "a"}})
        R.check_options("csv", {"delimiter": ";"})


class TestPaths:
    def test_a_key_holding_dots_is_taken_before_the_keys_it_splits_into(self):
        record = {"meta.vsn": "W042", "meta": {"vsn": "elsewhere"}}
        assert rows(record, {"columns": {"vsn": "meta.vsn"}}) == [("W042",)]

    def test_a_path_whose_whole_key_is_not_there_goes_down_its_parts(self):
        assert rows({"meta": {"vsn": "W042"}}, {"columns": {"vsn": "meta.vsn"}}) == [("W042",)]

    def test_a_number_picks_an_item_of_a_list_and_names_a_key_of_an_object(self):
        record = {"bbox": [81.5, 861.0, 356.0, 977.5], "counts": {"0": 7}}
        options = {"columns": {"x0": "bbox.0", "y1": "bbox.3", "past": "bbox.4", "zero": "counts.0"}}
        assert rows(record, options) == [(81.5, 977.5, None, 7)]

    def test_what_is_not_there_is_null(self):
        assert rows({"a": {"b": 1}}, {"columns": {"c": "a.c", "d": "d", "e": "a.b.e"}}) == [(None, None, None)]

    def test_the_empty_path_is_the_item_itself(self):
        options = {"columns": {"id": "id"}, "unpack": [{"path": "tags", "columns": {"tag": ""}}]}
        assert rows({"id": 1, "tags": ["curb", "ramp"]}, options) == [(1, "curb"), (1, "ramp")]


class TestValues:
    def test_nan_and_the_infinities_read_as_null(self):
        assert R.read_line(b'{"a": NaN, "b": Infinity, "c": -Infinity, "d": 1.5}\r\n') == {
            "a": None, "b": None, "c": None, "d": 1.5,
        }

    def test_nan_in_a_parsed_field_reads_as_null_too(self):
        record = R.read_line(b'{"value": "{\\"score\\": NaN}"}')
        assert rows(record, {"parse": ["value"], "columns": {"score": "value.score"}}) == [(None,)]

    def test_an_object_or_a_list_lands_as_its_json_text(self):
        record = {"counts": {"car": 1, "bus": 2}, "bbox": [1, 2.5], "name": "São Paulo"}
        assert rows(record, {"columns": {"counts": "counts", "bbox": "bbox"}}) == [('{"car":1,"bus":2}', "[1,2.5]")]
        assert rows(record, {}) == [{"counts": '{"car":1,"bus":2}', "bbox": "[1,2.5]", "name": "São Paulo"}]

    def test_a_whole_number_past_two_to_the_53_is_kept_exactly(self):
        got = rows(R.read_line(line(1)), DETECTIONS)
        assert got[0][1] == 1752721216492384585 and isinstance(got[0][1], int)


def typed(kind: str, value):
    """What a column of type *kind* holds for *value*, and what it was told of it."""
    told: list = []
    got = R.rows_of(
        {"v": value}, R.read_options({"columns": {"v": {"path": "v", "type": kind}}}),
        lambda column, reason: told.append((column, reason)),
    )
    return got[0][0], told


class TestTypes:
    @pytest.mark.parametrize("value, nanoseconds", [
        ("2025-07-17T03:00:16.492384585+00:00", 1752721216492384585),
        ("2025-07-17T03:00:16.492384585Z", 1752721216492384585),
        ("2025-07-17T08:30:00.5-05:00", 1752759000500000000),
        ("2025-07-17 03:00:16+0530", 1752701416000000000),
        ("1970-01-01T00:00:00Z", 0),
    ], ids=["offset", "z", "west-of-utc-with-a-fraction", "space-and-offset-without-colon", "epoch"])
    def test_a_timestamp_lands_as_utc_nanoseconds(self, value, nanoseconds):
        assert typed("timestamp", value) == (nanoseconds, [])

    @pytest.mark.parametrize("kind, value, kept", [
        ("int", 12, 12), ("int", 3.0, 3), ("int", " -7 ", -7), ("int", -(2 ** 63), -(2 ** 63)),
        ("float", 1, 1.0), ("float", "1.5", 1.5), ("float", "1e3", 1000.0),
        ("bool", True, True), ("bool", " FALSE ", False),
        ("string", 1.5, "1.5"), ("string", True, "true"), ("string", {"a": [1]}, '{"a":[1]}'), ("string", "x", "x"),
    ], ids=[
        "int", "int-from-a-whole-float", "int-from-text", "int-lowest", "float-from-an-int", "float-from-text",
        "float-with-an-exponent", "bool", "bool-from-text", "string-from-a-number", "string-from-true",
        "string-from-an-object", "string",
    ])
    def test_a_value_its_type_reads(self, kind, value, kept):
        got, told = typed(kind, value)
        assert got == kept and type(got) is type(kept) and told == []

    @pytest.mark.parametrize("kind, value, reason", [
        ("timestamp", "2025-07-17T03:00:16", "not an ISO 8601 time with an offset"),
        ("timestamp", "2025-13-01T00:00:00Z", "not an ISO 8601 time with an offset"),
        ("timestamp", 1752721216, "not an ISO 8601 time with an offset"),
        ("timestamp", "2300-01-01T00:00:00Z", "outside the years 1678 to 2261"),
        ("int", 1.5, "not a whole number"),
        ("int", True, "not a whole number"),
        ("int", "1_000", "not a whole number"),
        ("int", 2 ** 63, "a whole number past 64 bits"),
        ("int", "9" * 5000, "a whole number past 64 bits"),
        ("float", True, "not a number"),
        ("float", "nan", "not a number"),
        ("float", "1e999", "not a number"),
        ("float", [1.5], "not a number"),
        ("bool", 1, "not true or false"),
        ("bool", "yes", "not true or false"),
    ], ids=[
        "timestamp-without-offset", "timestamp-month-13", "timestamp-as-a-number", "timestamp-past-2262",
        "int-with-a-fraction", "int-from-true", "int-with-underscores", "int-past-64-bits", "int-of-5000-digits",
        "float-from-true", "float-nan-text", "float-past-its-range", "float-from-a-list",
        "bool-from-a-number", "bool-from-yes",
    ])
    def test_a_value_its_type_cannot_read_is_left_empty_saying_why(self, kind, value, reason):
        assert typed(kind, value) == (None, [("v", reason)])

    def test_a_missing_or_null_value_is_empty_and_nothing_is_told(self):
        options = {"columns": {"a": {"path": "a", "type": "int"}, "b": {"path": "b", "type": "timestamp"}}}
        told: list = []
        assert R.rows_of({"b": None}, R.read_options(options), lambda *said: told.append(said)) == [(None, None)]
        assert told == []

    def test_a_typed_column_of_a_level_is_told_once_per_value(self):
        options = {"unpack": [{"path": "xs", "columns": {"n": {"path": "n", "type": "int"}}}]}
        told: list = []
        got = R.rows_of(
            {"xs": [{"n": "1"}, {"n": "x"}, {"n": 2.5}]}, R.read_options(options), lambda *said: told.append(said),
        )
        assert got == [(1,), (None,), (None,)]
        assert told == [("n", "not a whole number"), ("n", "not a whole number")]

    def test_a_skipped_line_tells_nothing_of_its_values(self):
        options = {"columns": {"t": {"path": "t", "type": "int"}}, "unpack": [{"path": "xs", "columns": {"c": "c"}}]}
        told: list = []
        with pytest.raises(R.LineSkipped):
            R.rows_of({"t": "x", "xs": 5}, R.read_options(options), lambda *said: told.append(said))
        assert told == []


class TestWhatALineGives:
    def test_the_real_lines_end_as_they_do_in_the_bucket(self):
        assert [raw[-1:] for raw in LINES[:5]] == [b"\r"] * 5 and not LINES[5].endswith(b"}")

    def test_one_row_per_detection_each_naming_its_model(self):
        # The line's time, 2025-07-17T03:00:16.492384585+00:00, read as UTC
        # nanoseconds, is the image's own to the nanosecond.
        assert rows(R.read_line(line(1)), DETECTIONS) == [
            (1752721216492384585, 1752721216492384585, "YOLOv5n", 7.03928017616272,
             "car", 0.30116063356399536, 81.07574462890625, 861.7494506835938, 356.38250732421875, 977.5149536132812),
            (1752721216492384585, 1752721216492384585, "YOLOv8n", 7.090479373931885,
             "car", 0.691710352897644, 78.55874633789062, 860.984130859375, 351.3250427246094, 979.396728515625),
            (1752721216492384585, 1752721216492384585, "YOLOv10n", 7.114571809768677,
             "car", 0.7614250779151917, 80.64509582519531, 862.4031372070312, 355.7934875488281, 980.1085205078125),
        ]

    def test_a_model_that_saw_nothing_gives_no_row_and_skips_nothing(self):
        got = rows(R.read_line(line(2)), DETECTIONS)
        assert [(row[2], row[4]) for row in got] == [("YOLOv5n", "person"), ("YOLOv8n", "car")]
        assert rows(R.read_line(line(3)), DETECTIONS) == []

    def test_a_list_names_each_item_by_its_position_and_an_object_by_its_key(self):
        options = {"unpack": [{"path": "runs", "key": "run"}, {"path": "boxes", "key": "box", "columns": {"c": "c"}}]}
        record = {"runs": {"a": {"boxes": [{"c": "car"}, {"c": "bus"}]}, "b": {"boxes": [{"c": "van"}]}}}
        assert rows(record, options) == [("a", 0, "car"), ("a", 1, "bus"), ("b", 0, "van")]

    def test_a_line_where_an_unpacked_path_holds_no_list_or_object_is_skipped_whole(self):
        record = {"models_results": {"a": {"detections": [{"c": 1}]}, "b": {"error": "no camera"}}}
        options = {"unpack": [{"path": "models_results", "key": "model"}, {"path": "detections", "columns": {"c": "c"}}]}
        with pytest.raises(R.LineSkipped) as skipped:
            rows(record, options)
        assert skipped.value.reason == "no list or object at detections under models_results"

    def test_an_error_report_and_an_upload_are_skipped_saying_why(self):
        with pytest.raises(R.LineSkipped) as error:
            rows(R.read_line(line(4)), DETECTIONS)
        assert error.value.reason == "no list or object at value.models_results"
        with pytest.raises(R.LineSkipped) as upload:
            rows(R.read_line(line(5)), DETECTIONS)
        assert upload.value.reason == "value is not JSON text"

    def test_a_parsed_field_that_is_missing_or_already_json_is_read_as_it_is(self):
        options = {"parse": ["value"], "columns": {"a": "value.a"}}
        assert rows({"value": {"a": 1}}, options) == [(1,)]
        assert rows({"other": 1}, options) == [(None,)]

    @pytest.mark.parametrize("raw, reason", [
        (LINES[5], "not JSON"),
        (b'["W042", 1]', "not a JSON object"),
        (b'{"name": "S\xe3o Paulo"}', "not UTF-8 text"),
        (b"[" * 100_000 + b"]" * 100_000, "not JSON"),
    ], ids=["cut-short", "a-list", "not-utf8", "nested-too-deep"])
    def test_a_line_that_is_not_a_json_object_is_skipped_saying_why(self, raw, reason):
        with pytest.raises(R.LineSkipped) as skipped:
            R.read_line(raw)
        assert skipped.value.reason == reason

    def test_with_no_options_a_line_keeps_its_fields_with_nan_as_null(self):
        (row,) = rows(R.read_line(line(1)), {})
        assert list(row)[:3] == ["timestamp", "name", "value"]
        assert row["meta.vsn"] == "W042" and row["meta.filename"] is None
        assert row["value"].startswith('{"image_timestamp_ns": 1752721216492384585, ')
        assert rows({}, {}) == []
