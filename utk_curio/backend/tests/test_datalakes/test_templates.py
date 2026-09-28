"""Path templates: a storage manifest's way of saying where its files are."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from utk_curio.backend.app.datalakes.domain.templates import TemplateError, compile_template


class TestCaptures:
    def test_captures_are_typed(self):
        t = compile_template("orthos/{year:int}/{tile}.tif")
        assert t.match("orthos/2024/tile_0001.tif") == {"year": 2024, "tile": "tile_0001"}

    def test_an_iso_date(self):
        t = compile_template("dashcam/{date:date}/{sequence}_{frame:int}.jpg")
        assert t.match("dashcam/2024-05-01/trip01_000123.jpg") == {
            "date": date(2024, 5, 1), "sequence": "trip01", "frame": 123,
        }

    def test_a_strftime_timestamp(self):
        t = compile_template("noise/{sensor}/{recorded:%Y%m%d_%H%M%S}.wav")
        assert t.match("noise/s1/20240501_060000.wav") == {
            "sensor": "s1", "recorded": datetime(2024, 5, 1, 6, 0, 0),
        }

    def test_a_well_shaped_value_that_is_not_a_date_does_not_match(self):
        t = compile_template("{day:date}.csv")
        assert t.match("2024-13-40.csv") is None

    def test_a_string_capture_stays_inside_its_folder(self):
        t = compile_template("{sensor}/{day}.csv")
        assert t.match("a/b/c.csv") is None

    def test_a_name_ending_in_a_newline_is_not_a_match(self):
        t = compile_template("{name}.csv", reserved=frozenset())
        assert t.match("a.csv\n") is None


class TestWildcards:
    def test_a_star_matches_within_a_name(self):
        t = compile_template("photos/*.jpg")
        assert t.match("photos/IMG_1.jpg") == {}
        assert t.match("photos/sub/IMG_1.jpg") is None

    def test_a_double_star_spans_any_depth(self):
        t = compile_template("survey/{year:int}/**/*")
        assert t.match("survey/2024/IMG.JPG") == {"year": 2024}
        assert t.match("survey/2024/a/b/IMG.JPG") == {"year": 2024}

    def test_the_literal_prefix_is_the_shared_folders(self):
        assert compile_template("orthos/{year:int}/{tile}.tif").literal_prefix == "orthos/"
        assert compile_template("a/b/{x}/c.csv").literal_prefix == "a/b/"
        assert compile_template("{x}.csv").literal_prefix == ""


@pytest.mark.parametrize(
    "text, reason",
    [
        ("/srv/x/{a}.csv", "relative"),
        ("C:/x/{a}.csv", "relative"),
        ("../x.csv", "'..'"),
        ("a/./b.csv", "'.'"),
        ("a//b.csv", "empty"),
        ("a\\b.csv", "backslash"),
        ("a/**", "last part"),
        ("a**b/c", "folder of its own"),
        ("a{b/c.csv", "unbalanced"),
        ("a}b{c.csv", "unbalanced"),
        ("{file_id}.csv", "already adds"),
        ("{a}/{a}.csv", "twice"),
        ("{A}.csv", "lowercase"),
        ("{x:float}.csv", "unknown capture type"),
        ("{x:%Q}.csv", "unsupported date directive"),
        ("{x:%Y%Y}.wav", "uses %Y twice"),
        ("", "non-empty"),
    ],
)
def test_a_bad_template_is_refused_with_a_reason(text, reason):
    with pytest.raises(TemplateError, match=reason):
        compile_template(text)


def test_frames_may_capture_sequence_and_frame():
    t = compile_template("{sequence}_{frame:int}.jpg")
    assert t.names == ("sequence", "frame")
