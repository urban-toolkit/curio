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
