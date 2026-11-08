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
    "columns": {"timestamp": "timestamp", "image_timestamp_ns": "value.image_timestamp_ns"},
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

    def test_with_no_options_the_lines_fields_are_the_columns(self):
        assert R.read_options({}).names is None

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


class TestWhatALineGives:
    def test_the_real_lines_end_as_they_do_in_the_bucket(self):
        assert [raw[-1:] for raw in LINES[:5]] == [b"\r"] * 5 and not LINES[5].endswith(b"}")

    def test_one_row_per_detection_each_naming_its_model(self):
        assert rows(R.read_line(line(1)), DETECTIONS) == [
            ("2025-07-17T03:00:16.492384585+00:00", 1752721216492384585, "YOLOv5n", 7.03928017616272,
             "car", 0.30116063356399536, 81.07574462890625, 861.7494506835938, 356.38250732421875, 977.5149536132812),
            ("2025-07-17T03:00:16.492384585+00:00", 1752721216492384585, "YOLOv8n", 7.090479373931885,
             "car", 0.691710352897644, 78.55874633789062, 860.984130859375, 351.3250427246094, 979.396728515625),
            ("2025-07-17T03:00:16.492384585+00:00", 1752721216492384585, "YOLOv10n", 7.114571809768677,
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
    ])
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
