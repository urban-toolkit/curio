"""dev/129: resolution reads errors raised by ANY execution.

The owner's instruction — *"the dataflow resolution must be able to read errors
raised by any execution and properly act to fix it"* — against the shape that
produced it: Solve writes content, the user presses Play, the node raises, and
the next Solve used to regenerate from scratch as if the traceback on disk did
not exist.
"""

from __future__ import annotations

from utk_curio.backend.app.execution import runtime_journal

PLAY_TRACEBACK = (
    'Traceback (most recent call last):\n'
    '  File "/opt/conda/lib/python3.12/site-packages/pandas/core/reshape/merge.py", line 1620,'
    " in _get_merge_keys\n    right_keys.append(right._get_label_or_level_values(rk))\n"
    "KeyError: 'tract_id'\n"
)
CONTENT = "joined = bounds.merge(pop, left_on='area_numbe', right_on='tract_id')\nreturn joined"


class TestLastFailure:
    def _record(self, tmp_curio, *, status_ok: bool, validation: bool, code: str):
        runtime_journal.record_execution(
            "1", "p-129", "n1",
            code=code, stdout=[], stderr="" if status_ok else PLAY_TRACEBACK,
            output={"path": "art-1" if status_ok else "", "dataType": "dataframe"},
            started_at="2026-09-10T18:29:25Z", duration_ms=101, validation=validation,
        )

    def test_a_failed_play_run_is_readable_with_its_origin(self, tmp_curio):
        self._record(tmp_curio, status_ok=False, validation=False, code=CONTENT)
        failure = runtime_journal.last_failure("1", "p-129", "n1")
        assert failure["origin"] == "play"
        assert "KeyError: 'tract_id'" in failure["stderr"]
        assert failure["ranAt"] == "2026-09-10T18:29:25Z"
        assert failure["codeSha256"]

    def test_a_failed_validation_run_is_readable_too(self, tmp_curio):
        self._record(tmp_curio, status_ok=False, validation=True, code=CONTENT)
        assert runtime_journal.last_failure("1", "p-129", "n1")["origin"] == "validation"

    def test_a_successful_run_is_not_a_failure(self, tmp_curio):
        self._record(tmp_curio, status_ok=True, validation=False, code=CONTENT)
        assert runtime_journal.last_failure("1", "p-129", "n1") is None

    def test_a_node_that_never_ran_has_none(self, tmp_curio):
        assert runtime_journal.last_failure("1", "p-129", "ghost") is None

    def test_it_matches_only_the_code_the_node_still_holds(self, tmp_curio):
        self._record(tmp_curio, status_ok=False, validation=False, code=CONTENT)
        failure = runtime_journal.last_failure("1", "p-129", "n1")
        assert runtime_journal.failure_matches(failure, CONTENT) is True
        # Transport indentation must not matter (the route re-indents).
        assert runtime_journal.failure_matches(failure, "    " + CONTENT.replace("\n", "\n    ")) is True
        # The user edited it since: the record is about code that is gone.
        assert runtime_journal.failure_matches(failure, CONTENT + "\n# edited") is False
        assert runtime_journal.failure_matches(failure, "") is False
        assert runtime_journal.failure_matches(None, CONTENT) is False


class TestTheLoopStartsFromTheRecordedFailure:
    def test_the_trail_names_the_origin_and_the_error(self, app, tmp_curio):
        from utk_curio.backend.tests.test_agents.test_verified_rounds import CA, _Exec, _rounds

        node = {"id": "n1", "type": CA, "goal": "Densities", "content": CONTENT}
        exec_fn = _Exec(fail_markers=("right_on",), stderr=PLAY_TRACEBACK)
        events, outcome, inputs = _rounds(
            app, node,
            replies=["joined = bounds.merge(pop, on='community')\nreturn joined"],
            exec_fn=exec_fn, start_from_current=True,
            recorded_failure={
                "codeSha256": runtime_journal.normalized_code_sha256(CONTENT),
                "stderr": PLAY_TRACEBACK, "ranAt": "2026-09-10T18:29:25Z", "origin": "play",
            },
        )
        first = outcome["roundsTrace"][0]
        assert first.startswith("starting from the code on the node, which failed at play")
        assert "KeyError: 'tract_id'" in first
        # Round 0 ran the code that was there; the fix followed.
        assert outcome["attempts"][0]["source"] == "current content"
        assert outcome["verdict"] == "pass"
        # And the correction saw the real traceback.
        assert "tract_id" in inputs[0]["validationError"]

    def test_without_a_record_nothing_changes(self, app, tmp_curio):
        from utk_curio.backend.tests.test_agents.test_verified_rounds import CA, _Exec, _rounds

        node = {"id": "n1", "type": CA, "goal": "Densities", "content": ""}
        events, outcome, inputs = _rounds(
            app, node, replies=["return arg"], exec_fn=_Exec(),
        )
        assert not any("starting from the code" in line for line in outcome["roundsTrace"])
