"""dev/67-2 (DEC-052) — the per-node runtime journal: observational, latest-
per-node, fail-open reads, and the `/process*Code` seam write."""

from __future__ import annotations

import json

from utk_curio.backend.app.execution import runtime_journal
from utk_curio.backend.app.projects import storage as projects_storage

KEY = "4242"  # storage user keys are numeric ids (or the guest sentinel)
PID = "proj-journal"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class TestJournalStore:
    def test_success_and_failure_use_the_path_predicate(self, tmp_curio):
        # Success: output.path non-empty — stderr may carry benign warnings.
        runtime_journal.record_execution(
            KEY, PID, "n1",
            code="print(1)", stdout=["hello"], stderr="FutureWarning: soon",
            output={"path": "art-1", "dataType": "dataframe"},
            started_at="2026-08-05T00:00:00Z", duration_ms=12.7,
        )
        record = runtime_journal.read_record(KEY, PID, "n1")
        assert record["status"] == "ok"
        assert record["output"] == {"path": "art-1", "dataType": "dataframe"}
        assert record["stdoutTail"] == "hello"
        assert record["stderrTail"] == "FutureWarning: soon"
        assert record["executionSeq"] == 1 and record["validation"] is False
        # Failure: empty path — the traceback tail is the evidence.
        runtime_journal.record_execution(
            KEY, PID, "n1",
            code="boom()", stdout=[], stderr="Traceback (most recent call last):\n  boom",
            output={"path": "", "dataType": "str"},
            started_at="2026-08-05T00:01:00Z", duration_ms=3.0,
        )
        record = runtime_journal.read_record(KEY, PID, "n1")
        assert record["status"] == "error"
        assert "Traceback" in record["stderrTail"]
        assert record["executionSeq"] == 2  # latest-per-node, seq monotonic

    def test_tails_are_bounded(self, tmp_curio):
        runtime_journal.record_execution(
            KEY, PID, "n2",
            code="x", stdout=["a" * 9000], stderr="e" * 9000,
            output={"path": "", "dataType": "str"},
            started_at="2026-08-05T00:00:00Z", duration_ms=1,
        )
        record = runtime_journal.read_record(KEY, PID, "n2")
        assert len(record["stdoutTail"]) == 2000
        assert len(record["stderrTail"]) == 4000

    def test_node_ids_are_filename_safe(self, tmp_curio):
        runtime_journal.record_execution(
            KEY, PID, "../../evil/../id with spaces",
            code="x", stdout=[], stderr="",
            output={"path": "p", "dataType": "str"},
            started_at="2026-08-05T00:00:00Z", duration_ms=1,
        )
        runtime_dir = projects_storage.project_dir(KEY, PID) / "runtime"
        (path,) = list(runtime_dir.glob("*.json"))
        assert path.parent == runtime_dir  # never escaped the journal dir
        record = runtime_journal.read_record(KEY, PID, "../../evil/../id with spaces")
        assert record["nodeId"] == "../../evil/../id with spaces"

    def test_reads_fail_open(self, tmp_curio):
        assert runtime_journal.read_record(KEY, PID, "never-ran") is None
        runtime_dir = projects_storage.ensure_project_dir(KEY, PID) / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / "broken.json").write_text("{not json", encoding="utf-8")
        assert runtime_journal.read_record(KEY, PID, "broken") is None
        # status_map skips the broken file rather than failing.
        assert "broken" not in runtime_journal.status_map(KEY, PID)

    def test_status_map_aggregates_latest_statuses(self, tmp_curio):
        for node_id, path in (("a", "art"), ("b", "")):
            runtime_journal.record_execution(
                KEY, PID, node_id,
                code="x", stdout=[], stderr="",
                output={"path": path, "dataType": "str"},
                started_at="2026-08-05T00:00:00Z", duration_ms=1,
            )
        statuses = runtime_journal.status_map(KEY, PID)
        assert statuses["a"]["status"] == "ok"
        assert statuses["b"]["status"] == "error"

    def test_normalized_sha_survives_transport_indentation(self):
        flush = "import x\nreturn x.f(arg)"
        indented = "    import x\n    return x.f(arg)"
        assert (
            runtime_journal.normalized_code_sha256(flush)
            == runtime_journal.normalized_code_sha256(indented)
        )


class TestExecutionSeamWrite:
    """The `/processPythonCode` seam (dev/67-2): a browser execution leaves a
    journal record implicitly — and only when the run has identity."""

    def _fake_sandbox(self, monkeypatch, payload):
        class _Resp:
            status_code = 200

            def json(self):
                return payload

        monkeypatch.setattr(
            "utk_curio.backend.app.api.routes._sandbox_call",
            lambda *a, **k: _Resp(),
        )

    def _post(self, client, token, body):
        return client.post(
            "/processPythonCode",
            json={"code": "print(1)", "nodeType": "curio.builtin/computation-analysis",
                  "input": None, "saveOutputDataset": False, **body},
            headers=_auth(token),
        )

    def test_execution_writes_the_journal(self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        self._fake_sandbox(monkeypatch, {
            "stdout": ["ran"], "stderr": "",
            "output": {"path": "art-9", "dataType": "dataframe"},
        })
        r = self._post(client, token, {"nodeId": "node-1", "dataflowId": "proj-1"})
        assert r.status_code == 200
        record = runtime_journal.read_record(_user_dir_key(user), "proj-1", "node-1")
        assert record["status"] == "ok" and record["stdoutTail"] == "ran"

    def test_failed_execution_records_the_traceback(self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        self._fake_sandbox(monkeypatch, {
            "stdout": [], "stderr": "Traceback (most recent call last):\n  ZeroDivisionError",
            "output": {"path": "", "dataType": "str"},
        })
        r = self._post(client, token, {"nodeId": "node-2", "dataflowId": "proj-1"})
        assert r.status_code == 200  # the response is unchanged by the journal
        record = runtime_journal.read_record(_user_dir_key(user), "proj-1", "node-2")
        assert record["status"] == "error"
        assert "ZeroDivisionError" in record["stderrTail"]

    def test_no_identity_no_journal(self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        self._fake_sandbox(monkeypatch, {
            "stdout": [], "stderr": "", "output": {"path": "p", "dataType": "str"},
        })
        assert self._post(client, token, {"nodeId": "node-3"}).status_code == 200  # no dataflowId
        assert runtime_journal.read_record(_user_dir_key(user), "proj-1", "node-3") is None


class TestBrowserExecutions:
    """dev/135: a run is a run wherever it happens.

    The owner's `a29d1ad8`: a Vega-Lite node visibly red with
    "outputs is not a valid input type for the 2D Plot (Vega-Lite)", and every
    agent reading the journal told `never-executed` — because the journal had
    three writers and all three were the sandbox.
    """

    VEGA_ERROR = "outputs is not a valid input type for the 2D Plot (Vega-Lite)"

    def test_a_render_error_is_journaled_with_its_message_and_origin(self, tmp_curio):
        assert runtime_journal.record_browser_execution(
            KEY, PID, "vega-1",
            status="error", message=self.VEGA_ERROR, duration_ms=12,
        ) is True
        # dev/137: a browser report has its OWN record — a render must never
        # erase what the node's code did.
        assert runtime_journal.read_record(KEY, PID, "vega-1") is None
        record = runtime_journal.read_render_record(KEY, PID, "vega-1")
        assert record["status"] == "error"
        assert record["origin"] == "browser"
        assert record["stderrTail"] == self.VEGA_ERROR
        # A client cannot mint an artifact id, so the record carries none.
        assert record["output"] == {"path": "", "dataType": ""}
        assert record["validation"] is False

    def test_a_successful_render_is_ok_even_with_no_artifact(self, tmp_curio):
        """The defect an explicit status exists for: `output.path == ""` is a
        SANDBOX predicate, and a chart that rendered perfectly has no path."""
        runtime_journal.record_browser_execution(
            KEY, PID, "vega-2", status="ok", output_type="dataframe", duration_ms=8,
        )
        record = runtime_journal.read_render_record(KEY, PID, "vega-2")
        assert record["status"] == "ok"
        assert record["output"]["dataType"] == "dataframe"
        assert record["stderrTail"] == ""

    def test_a_note_on_a_successful_run_rides_stdout_not_stderr(self, tmp_curio):
        runtime_journal.record_browser_execution(
            KEY, PID, "autk-1", status="ok", message="4 layers drawn",
        )
        record = runtime_journal.read_render_record(KEY, PID, "autk-1")
        assert record["status"] == "ok"
        assert record["stdoutTail"] == "4 layers drawn"
        assert record["stderrTail"] == ""  # nothing reads it as a failure

    def test_the_repair_loop_reads_a_browser_failure(self, tmp_curio):
        """dev/129's `last_failure` is the seed the fix starts from, and it now
        covers browser failures — dev/129 F2 / dev/131 F3, closed."""
        grammar = '{"mark": "bar"}'
        runtime_journal.record_browser_execution(
            KEY, PID, "vega-3", status="error", message=self.VEGA_ERROR, code=grammar,
        )
        failure = runtime_journal.last_failure(KEY, PID, "vega-3")
        assert failure["origin"] == "browser"
        assert failure["stderr"] == self.VEGA_ERROR
        assert runtime_journal.failure_matches(failure, grammar) is True

    def test_a_running_status_is_not_a_failure(self, tmp_curio):
        runtime_journal.record_browser_execution(KEY, PID, "autk-2", status="running")
        assert runtime_journal.read_render_record(KEY, PID, "autk-2")["status"] == "running"
        assert runtime_journal.last_failure(KEY, PID, "autk-2") is None

    def test_an_unknown_status_is_refused_and_writes_nothing(self, tmp_curio):
        assert runtime_journal.record_browser_execution(
            KEY, PID, "ghost", status="exploded", message="x",
        ) is False
        assert runtime_journal.read_render_record(KEY, PID, "ghost") is None

    def test_the_message_is_bounded(self, tmp_curio):
        runtime_journal.record_browser_execution(
            KEY, PID, "vega-4", status="error", message="e" * 9000,
        )
        record = runtime_journal.read_render_record(KEY, PID, "vega-4")
        assert len(record["stderrTail"]) <= runtime_journal.BROWSER_MESSAGE_CHARS

    def test_it_never_raises(self, tmp_curio):
        # An unwritable project directory must not take a render down with it.
        assert runtime_journal.record_browser_execution(
            "", "", "", status="error", message="x",
        ) is True  # attempted; the write itself fails open


class TestOriginOnEveryRecord:
    def test_the_sandbox_and_validation_origins_are_derived_as_before(self, tmp_curio):
        runtime_journal.record_execution(
            KEY, PID, "play-1", code="print(1)", stdout=[], stderr="",
            output={"path": "art-9", "dataType": "dataframe"},
            started_at="2026-09-10T00:00:00Z", duration_ms=1,
        )
        runtime_journal.record_execution(
            KEY, PID, "val-1", code="print(1)", stdout=[], stderr="",
            output={"path": "art-9", "dataType": "dataframe"},
            started_at="2026-09-10T00:00:00Z", duration_ms=1, validation=True,
        )
        assert runtime_journal.read_record(KEY, PID, "play-1")["origin"] == "sandbox"
        assert runtime_journal.read_record(KEY, PID, "val-1")["origin"] == "validation"
        # And the legacy projection keeps its own words.
        assert runtime_journal.last_failure(KEY, PID, "play-1") is None

    def test_status_map_reports_the_origin(self, tmp_curio):
        runtime_journal.record_browser_execution(KEY, PID, "vega-5", status="error",
                                                 message="boom")
        runtime_journal.record_execution(
            KEY, PID, "py-5", code="print(1)", stdout=[], stderr="",
            output={"path": "art-1", "dataType": "dataframe"},
            started_at="2026-09-10T00:00:00Z", duration_ms=1,
        )
        statuses = runtime_journal.status_map(KEY, PID)
        assert statuses["vega-5"] == {
            "status": "error", "updatedAt": statuses["vega-5"]["updatedAt"],
            "origin": "browser",
        }
        assert statuses["py-5"]["origin"] == "sandbox"

    def test_an_explicit_status_overrides_the_path_predicate(self, tmp_curio):
        runtime_journal.record_execution(
            KEY, PID, "n-explicit", code="", stdout=[], stderr="",
            output={"path": "", "dataType": "json"},
            started_at="2026-09-10T00:00:00Z", duration_ms=1,
            status="ok", origin="browser",
        )
        assert runtime_journal.read_record(KEY, PID, "n-explicit")["status"] == "ok"


class TestTheBrowserReportRoute:
    """dev/135: `POST /nodeRuntime` — the client's own write path, narrow
    because this is client-supplied data written into a store agents read."""

    VEGA_ERROR = "outputs is not a valid input type for the 2D Plot (Vega-Lite)"

    def _project(self, client, token):
        body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": []}}, "outputs": []}
        return client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]

    def _post(self, client, token, **body):
        return client.post("/nodeRuntime", json=body, headers=_auth(token))

    def test_a_reported_error_is_readable_by_every_journal_reader(
        self, client, user_and_token, tmp_curio
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        pid = self._project(client, token)
        r = self._post(client, token, dataflowId=pid, nodeId="vega-1", status="error",
                       message=self.VEGA_ERROR, durationMs=12, code='{"mark": "bar"}')
        assert r.status_code == 204
        key = _user_dir_key(user)
        record = runtime_journal.read_render_record(key, pid, "vega-1")
        assert record["status"] == "error" and record["origin"] == "browser"
        assert record["stderrTail"] == self.VEGA_ERROR
        assert runtime_journal.status_map(key, pid)["vega-1"]["origin"] == "browser"
        assert runtime_journal.last_failure(key, pid, "vega-1")["origin"] == "browser"

    def test_authentication_is_required(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        pid = self._project(client, token)
        r = client.post("/nodeRuntime", json={"dataflowId": pid, "nodeId": "n", "status": "ok"})
        assert r.status_code in (401, 403)

    def test_a_project_this_user_has_none_of_is_a_no_op_not_a_directory(
        self, client, user_and_token, tmp_curio
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key
        from utk_curio.backend.app.projects import storage as projects_storage

        user, token = user_and_token
        assert self._post(client, token, dataflowId="not-mine", nodeId="n1",
                          status="error", message="x").status_code == 204
        key = _user_dir_key(user)
        assert runtime_journal.read_render_record(key, "not-mine", "n1") is None
        assert not projects_storage.project_dir(key, "not-mine").is_dir()

    def test_the_payload_is_validated(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        pid = self._project(client, token)
        assert self._post(client, token, dataflowId=pid, status="ok").status_code == 400
        assert self._post(client, token, nodeId="n", status="ok").status_code == 400
        bad = self._post(client, token, dataflowId=pid, nodeId="n", status="exploded")
        assert bad.status_code == 400 and "status" in bad.get_json()["error"]

    def test_no_artifact_path_can_be_claimed_and_the_message_is_bounded(
        self, client, user_and_token, tmp_curio
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        pid = self._project(client, token)
        self._post(client, token, dataflowId=pid, nodeId="vega-2", status="ok",
                   outputType="dataframe", message="m" * 9000,
                   output={"path": "art-stolen", "dataType": "dataframe"},
                   path="art-stolen")
        record = runtime_journal.read_render_record(_user_dir_key(user), pid, "vega-2")
        assert record["output"] == {"path": "", "dataType": "dataframe"}
        assert len(record["stdoutTail"]) <= 2000
        assert record["status"] == "ok"

    def test_a_negative_or_unparseable_duration_is_ignored(
        self, client, user_and_token, tmp_curio
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        pid = self._project(client, token)
        for duration in (-5, "nonsense", None):
            self._post(client, token, dataflowId=pid, nodeId="vega-3", status="ok",
                       durationMs=duration)
            record = runtime_journal.read_render_record(_user_dir_key(user), pid, "vega-3")
            assert record["durationMs"] == 0


class TestTheOutcomeKind:
    """dev/136: an empty render is not the same problem as a render that threw,
    and the corrections differ — so the kind travels as a field, not as prose
    the harness would have to match."""

    EMPTY = ("rendered nothing — 12 rows arrived and no mark was drawn: an "
             "encoding, a transform or a scale domain removed every row.")

    def test_the_kind_rides_the_record_and_the_failure_projection(self, tmp_curio):
        runtime_journal.record_browser_execution(
            KEY, PID, "vega-9", status="error", message=self.EMPTY,
            kind="empty-render:nothing-drawn",
        )
        record = runtime_journal.read_render_record(KEY, PID, "vega-9")
        assert record["kind"] == "empty-render:nothing-drawn"
        failure = runtime_journal.last_failure(KEY, PID, "vega-9")
        assert failure["kind"] == "empty-render:nothing-drawn"
        assert failure["origin"] == "browser"

    def test_a_record_with_no_kind_carries_none(self, tmp_curio):
        runtime_journal.record_browser_execution(
            KEY, PID, "vega-10", status="error", message="it threw",
        )
        assert "kind" not in runtime_journal.read_render_record(KEY, PID, "vega-10")
        assert "kind" not in runtime_journal.last_failure(KEY, PID, "vega-10")

    def test_the_kind_is_bounded(self, tmp_curio):
        runtime_journal.record_browser_execution(
            KEY, PID, "vega-11", status="error", message="x", kind="k" * 500,
        )
        assert len(runtime_journal.read_render_record(KEY, PID, "vega-11")["kind"]) <= 40

    def test_the_route_passes_it_through(self, client, user_and_token, tmp_curio):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": []}}, "outputs": []}
        pid = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
        client.post("/nodeRuntime", json={
            "dataflowId": pid, "nodeId": "vega-1", "status": "error",
            "message": self.EMPTY, "kind": "empty-render:no-input-rows",
        }, headers=_auth(token))
        record = runtime_journal.read_render_record(_user_dir_key(user), pid, "vega-1")
        assert record["kind"] == "empty-render:no-input-rows"


class TestTwoOriginsNeverEraseEachOther:
    """dev/137, the regression the owner's `7a27b702` exposed.

    Its journal held six records and every one said ``origin: browser`` —
    including four PYTHON nodes whose editors showed a successful sandbox run.
    dev/135 wrote a browser report through ``record_execution``, which is
    latest-per-node, and the client always writes LAST (the sandbox responds,
    React settles the output, the reporter posts). So every code node's
    artifact, dataType and traceback were being overwritten by a render report
    that had none of them.
    """

    TRACEBACK = "Traceback (most recent call last):\n  KeyError: 'tract_id'"

    def test_a_browser_report_leaves_the_run_record_untouched(self, tmp_curio):
        runtime_journal.record_execution(
            KEY, PID, "py-1", code="return df", stdout=["ran"], stderr="",
            output={"path": "art-42", "dataType": "geodataframe"},
            started_at="2026-09-11T00:00:00Z", duration_ms=41,
        )
        runtime_journal.record_browser_execution(
            KEY, PID, "py-1", status="ok", output_type="", duration_ms=0,
        )
        run = runtime_journal.read_record(KEY, PID, "py-1")
        assert run["origin"] == "sandbox"
        assert run["output"] == {"path": "art-42", "dataType": "geodataframe"}
        assert run["stdoutTail"] == "ran"
        # And the render is readable in its own right.
        render = runtime_journal.read_render_record(KEY, PID, "py-1")
        assert render["origin"] == "browser" and render["output"]["path"] == ""

    def test_a_play_traceback_survives_a_later_browser_ok(self, tmp_curio):
        """The repair loop's input, restored: dev/129 reads this."""
        code = "joined = a.merge(b, on='id')\nreturn joined"
        runtime_journal.record_execution(
            KEY, PID, "py-2", code=code, stdout=[], stderr=self.TRACEBACK,
            output={"path": "", "dataType": "str"},
            started_at="2026-09-11T00:00:00Z", duration_ms=3,
        )
        runtime_journal.record_browser_execution(KEY, PID, "py-2", status="ok")
        failure = runtime_journal.last_failure(KEY, PID, "py-2")
        assert failure is not None, "the Play traceback must still be the failure"
        assert "KeyError" in failure["stderr"]
        assert failure["origin"] == "play"
        assert runtime_journal.failure_matches(failure, code) is True

    def test_a_render_failure_is_found_when_the_run_did_not_fail(self, tmp_curio):
        """dev/136's branch: a grammar node has no run, and a code node whose
        run PASSED can still have drawn nothing."""
        runtime_journal.record_execution(
            KEY, PID, "vega-a", code="{}", stdout=[], stderr="",
            output={"path": "art-1", "dataType": "dataframe"},
            started_at="2026-09-11T00:00:00Z", duration_ms=1,
        )
        runtime_journal.record_browser_execution(
            KEY, PID, "vega-a", status="error", message="rendered nothing — 0 rows",
            kind="empty-render:no-input-rows",
        )
        failure = runtime_journal.last_failure(KEY, PID, "vega-a")
        assert failure["origin"] == "browser"
        assert failure["kind"] == "empty-render:no-input-rows"

    def test_the_run_wins_in_the_status_map_and_in_read_outcome(self, tmp_curio):
        runtime_journal.record_browser_execution(KEY, PID, "py-3", status="error",
                                                 message="render blew up")
        runtime_journal.record_execution(
            KEY, PID, "py-3", code="return 1", stdout=[], stderr="",
            output={"path": "art-7", "dataType": "dataframe"},
            started_at="2026-09-11T00:00:00Z", duration_ms=2,
        )
        assert runtime_journal.status_map(KEY, PID)["py-3"]["origin"] == "sandbox"
        assert runtime_journal.read_outcome(KEY, PID, "py-3")["origin"] == "sandbox"
        # A node with ONLY a render is described by it.
        runtime_journal.record_browser_execution(KEY, PID, "vega-b", status="ok",
                                                 output_type="dataframe")
        assert runtime_journal.status_map(KEY, PID)["vega-b"]["origin"] == "browser"
        assert runtime_journal.read_outcome(KEY, PID, "vega-b")["origin"] == "browser"

    def test_the_render_record_keeps_its_own_sequence(self, tmp_curio):
        for _ in range(3):
            runtime_journal.record_browser_execution(KEY, PID, "vega-c", status="ok")
        assert runtime_journal.read_render_record(KEY, PID, "vega-c")["executionSeq"] == 3
        # …and does not disturb the run's.
        runtime_journal.record_execution(
            KEY, PID, "vega-c", code="x", stdout=[], stderr="",
            output={"path": "p", "dataType": "dataframe"},
            started_at="2026-09-11T00:00:00Z", duration_ms=1,
        )
        assert runtime_journal.read_record(KEY, PID, "vega-c")["executionSeq"] == 1


class TestAnAbsentOutputIsAFailedRun:
    """dev/138: `return None` still stores an artifact, and the sandbox types it
    "null" — so ``bool(output.path)`` called it success and the owner's
    `edd71e67` wrote a node that produced nothing and called it solved."""

    def test_a_null_output_type_is_an_error_with_a_stated_reason(self, tmp_curio):
        runtime_journal.record_execution(
            KEY, PID, "none-1", code="return None", stdout=[], stderr="",
            output={"path": "art-null", "dataType": "null"},
            started_at="2026-09-11T01:00:00Z", duration_ms=7,
        )
        record = runtime_journal.read_record(KEY, PID, "none-1")
        assert record["status"] == "error"
        assert "returned no output (None)" in record["stderrTail"]
        # And the repair loop can start from it, like any other failure.
        failure = runtime_journal.last_failure(KEY, PID, "none-1")
        assert failure is not None
        assert runtime_journal.failure_matches(failure, "return None") is True

    def test_every_spelling_of_absent_counts(self, tmp_curio):
        for index, dtype in enumerate(("null", "None", "NoneType", "")):
            runtime_journal.record_execution(
                KEY, PID, f"none-{index}-x", code="return None", stdout=[], stderr="",
                output={"path": "art", "dataType": dtype},
                started_at="2026-09-11T01:00:00Z", duration_ms=1,
            )
            record = runtime_journal.read_record(KEY, PID, f"none-{index}-x")
            assert record["status"] == "error", dtype

    def test_a_real_type_this_build_does_not_know_is_still_ok(self, tmp_curio):
        # "absent" is not "unknown": a new sandbox type must not read as a
        # failure, which is the whole distinction dev/138 rests on.
        runtime_journal.record_execution(
            KEY, PID, "tensor-1", code="return t", stdout=[], stderr="",
            output={"path": "art-t", "dataType": "tensor"},
            started_at="2026-09-11T01:00:00Z", duration_ms=1,
        )
        assert runtime_journal.read_record(KEY, PID, "tensor-1")["status"] == "ok"

    def test_a_real_traceback_is_never_replaced_by_the_reason(self, tmp_curio):
        runtime_journal.record_execution(
            KEY, PID, "boom-1", code="boom()", stdout=[],
            stderr="Traceback (most recent call last):\n  NameError: boom",
            output={"path": "", "dataType": "str"},
            started_at="2026-09-11T01:00:00Z", duration_ms=1,
        )
        record = runtime_journal.read_record(KEY, PID, "boom-1")
        assert "NameError" in record["stderrTail"]
        assert "returned no output" not in record["stderrTail"]

    def test_is_absent_output_is_the_one_predicate(self):
        assert runtime_journal.is_absent_output({"path": "a", "dataType": "null"}) is True
        assert runtime_journal.is_absent_output({"path": "", "dataType": "dataframe"}) is True
        assert runtime_journal.is_absent_output({"path": "a", "dataType": "dataframe"}) is False
        assert runtime_journal.is_absent_output({"path": "a", "dataType": "tensor"}) is False
        assert runtime_journal.is_absent_output(None) is True
