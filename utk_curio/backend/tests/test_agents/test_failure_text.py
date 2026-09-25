"""dev/127: what a failed round is called in front of the user.

The three tracebacks below are the owner's, from the Solve card of dataflow
`623b6620` — including the one that reached the chat as `round 2:
execution-error — de`. Each test states what the old character slice did to it.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import failure_text as ft

# round 1: pandas raised, looking for a column the code guessed.
PANDAS_KEYERROR = '''Traceback (most recent call last):
  File "/opt/conda/lib/python3.11/site-packages/pandas/core/generic.py", line 1776, in _get_label_or_level_values
    raise KeyError(key)
KeyError: 'community_area'
'''

# round 2: the CODE raised its own guard. The card showed "— de" and the strip
# attributed it to pandas.
SELF_RAISED = '''Traceback (most recent call last):
  File "<string>", line 24, in <module>
    raise KeyError('No common column found between boundaries and population datasets to perform a join.')
KeyError: 'No common column found between boundaries and population datasets to perform a join.'
'''

# round 3: the join lost the GeoDataFrame.
CRS_ATTRIBUTE = '''  File "/opt/conda/lib/python3.11/site-packages/pandas/core/generic.py", line 6206, in __getattr__
    return object.__getattribute__(self, name)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'DataFrame' object has no attribute 'crs'
'''

CHAINED = '''Traceback (most recent call last):
  File "<string>", line 3, in <module>
KeyError: 'x'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "<string>", line 6, in <module>
ValueError: could not convert 'x' to a column
'''


class TestExceptionLine:
    def test_the_type_and_message_survive_whole(self):
        assert ft.exception_line(PANDAS_KEYERROR) == "KeyError: 'community_area'"
        assert ft.exception_line(CRS_ATTRIBUTE) == (
            "AttributeError: 'DataFrame' object has no attribute 'crs'"
        )

    def test_the_last_exception_wins_in_a_chain(self):
        assert ft.exception_line(CHAINED) == "ValueError: could not convert 'x' to a column"
        assert ft.is_chained(CHAINED) is True
        assert ft.is_chained(PANDAS_KEYERROR) is False

    def test_prose_is_not_an_exception(self):
        assert ft.exception_line("the sandbox produced no output") is None
        assert ft.exception_line("") is None
        assert ft.exception_line(None) is None
        # A qualified type still counts.
        assert ft.exception_line("pandas.errors.MergeError: no common columns") == (
            "pandas.errors.MergeError: no common columns"
        )


class TestRaisingFrame:
    def test_the_innermost_frame_is_named_compactly(self):
        assert ft.raising_frame(PANDAS_KEYERROR) == (
            ".../pandas/core/generic.py:1776 in _get_label_or_level_values"
        )
        assert ft.raising_frame(CRS_ATTRIBUTE) == (
            ".../pandas/core/generic.py:6206 in __getattr__"
        )

    def test_the_candidate_frame_keeps_its_marker(self):
        assert ft.raising_frame(SELF_RAISED) == "<string>:24 in <module>"

    def test_no_frame_is_none(self):
        assert ft.raising_frame("KeyError: 'x'") is None


class TestSelfRaised:
    def test_the_candidates_own_guard_is_recognized_by_its_frame(self):
        assert ft.is_self_raised(SELF_RAISED) is True

    def test_or_by_the_code_that_raises_it(self):
        code = "if not common:\n    raise KeyError('No common column found')\n"
        raw = "  File \"/x/site-packages/pandas/core/frame.py\", line 9, in merge\nKeyError: 'No common column found'"
        assert ft.is_self_raised(raw, code) is True

    def test_a_library_failure_is_not_self_raised(self):
        assert ft.is_self_raised(PANDAS_KEYERROR) is False
        assert ft.is_self_raised(CRS_ATTRIBUTE, "gdf = gdf.to_crs(3395)") is False


class TestExcerpt:
    def test_never_returns_a_partial_line(self):
        # The old code did `raw[-160:]`, which produced 'ic.py", line 1776'.
        out = ft.excerpt(PANDAS_KEYERROR, limit=60)
        assert "ic.py" not in out.split("\n")[0] or out.startswith("…")
        for line in out.split("\n"):
            if line == "…":
                continue
            assert line in PANDAS_KEYERROR

    def test_marks_what_it_dropped(self):
        out = ft.excerpt(CRS_ATTRIBUTE, limit=70)
        assert out.startswith("…")
        assert out.endswith("AttributeError: 'DataFrame' object has no attribute 'crs'")

    def test_head_reads_from_the_top(self):
        out = ft.excerpt(CHAINED, limit=60, head=True)
        assert out.endswith("…")
        assert "KeyError: 'x'" in out

    def test_a_single_over_long_line_is_clipped_at_a_word(self):
        line = "ValueError: " + "column_name " * 40
        out = ft.excerpt(line, limit=60)
        assert len(out) <= 60
        assert out.endswith("…")
        assert not out.endswith("colum…")  # a word boundary, not mid-token

    def test_noise_lines_go_first(self):
        out = ft.excerpt(PANDAS_KEYERROR, limit=200)
        assert "Traceback (most recent call last)" not in out

    def test_empty_input(self):
        assert ft.excerpt("", limit=100) == ""
        assert ft.excerpt(None, limit=100) == ""


class TestSummary:
    def test_the_answer_comes_first_then_the_place(self):
        out = ft.summary(PANDAS_KEYERROR, limit=300)
        assert out.startswith("KeyError: 'community_area'")
        assert ".../pandas/core/generic.py:1776" in out

    def test_a_self_raised_error_says_so(self):
        out = ft.summary(SELF_RAISED, limit=300)
        assert out.startswith("KeyError: 'No common column found")
        assert "raised by the code's own check" in out

    def test_the_owners_three_rounds_all_read_clearly(self):
        for raw in (PANDAS_KEYERROR, SELF_RAISED, CRS_ATTRIBUTE):
            out = ft.summary(raw, limit=300)
            # The answer leads, always: the report's lines led with a path
            # fragment ("das/core/generic.py") or with two junk characters
            # ("de") because the slice started wherever 200 chars from the end
            # happened to fall.
            assert out.startswith(ft.exception_line(raw))
            assert not out.startswith(("de", "ic.py", "..."))

    def test_falls_back_to_whole_lines_without_an_exception(self):
        raw = "the node produced no output\nstderr was empty"
        assert ft.summary(raw, limit=300) == raw

    def test_respects_its_limit(self):
        out = ft.summary(SELF_RAISED, limit=80)
        assert len(out) <= 80
