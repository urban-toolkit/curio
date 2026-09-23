"""The errors route, the backend exception hook, and the browser ingest.

The 404 exclusion below is the one worth reading. Every routing refusal flows
through `handle_http_exception`, so hooking that handler would fill the log
with 404s and bury the faults it exists to surface. #279 already fixed the
mirror image of this bug (refusals being logged as 500s).
"""

import json

import pytest

from utk_curio.backend.app.monitor import errors, routes


class TestErrorsRoute:
    def test_an_empty_instance_returns_an_empty_list(self, client):
        body = client.get("/api/monitor/errors").get_json()
        assert body["errors"] == []
        assert body["serverWindow"] == errors.SERVER_WINDOW
        assert body["clientWindow"] == errors.CLIENT_WINDOW
        assert body["droppedClient"] == 0

    def test_entries_carry_the_documented_fields(self, client):
        errors.record("node", summary="KeyError: 'x'", detail="Traceback...",
                      context={"nodeType": "pkg/node"})
        entry = client.get("/api/monitor/errors").get_json()["errors"][0]
        assert entry["source"] == "node"
        assert entry["summary"] == "KeyError: 'x'"
        assert entry["detail"] == "Traceback..."
        assert entry["context"]["nodeType"] == "pkg/node"
        assert entry["count"] == 1

    def test_sandbox_entries_are_merged_in(self, client, monkeypatch):
        monkeypatch.setattr(routes, "_sandbox_monitor", lambda: {
            "errorWindow": 50,
            "errors": [{"at": "2099-01-01T00:00:00Z", "source": "sandbox",
                        "summary": "killed at 4096 MB", "detail": "",
                        "context": {}, "count": 1}],
        })
        body = client.get("/api/monitor/errors").get_json()
        assert body["sandboxWindow"] == 50
        assert body["errors"][0]["source"] == "sandbox"

    def test_an_unreachable_sandbox_still_returns_local_errors(self, client):
        errors.record("backend", summary="local failure")
        body = client.get("/api/monitor/errors").get_json()
        assert [e["summary"] for e in body["errors"]] == ["local failure"]
        assert body["sandboxWindow"] is None


class TestBackendExceptionHook:
    def test_an_unhandled_exception_is_logged(self, app, client):
        @app.route("/__boom__")
        def boom():
            raise RuntimeError("deliberate")

        client.get("/__boom__")

        entries = client.get("/api/monitor/errors").get_json()["errors"]
        assert len(entries) == 1
        assert entries[0]["source"] == "backend"
        assert "RuntimeError" in entries[0]["summary"]
        assert "/__boom__" in entries[0]["summary"]
        # The traceback is the reason this feature exists; it must be intact.
        assert "deliberate" in entries[0]["detail"]

    def test_a_404_is_not_logged(self, client):
        """Routing refusals are normal outcomes, not faults.

        They arrive through handle_http_exception, which is deliberately NOT
        hooked. If this starts failing, someone has hooked it, and the error
        log is about to become a 404 feed.
        """
        client.get("/no/such/route")
        assert client.get("/api/monitor/errors").get_json()["errors"] == []

    def test_a_403_is_not_logged(self, client):
        client.get("/")  # the root route aborts with 403
        assert client.get("/api/monitor/errors").get_json()["errors"] == []


class TestClientIngest:
    def test_a_browser_report_shows_up_as_a_client_error(self, client):
        client.post("/api/monitor/errors/client", json={
            "message": "TypeError: x is not a function",
            "stack": "at render (bundle.js:1)",
            "url": "http://localhost:8080/monitor",
            "userAgent": "TestBrowser/1.0",
        })
        entry = client.get("/api/monitor/errors").get_json()["errors"][0]
        assert entry["source"] == "client"
        assert entry["summary"] == "TypeError: x is not a function"
        assert entry["detail"] == "at render (bundle.js:1)"

    def test_client_spam_cannot_evict_a_server_error(self, client):
        """The reason the two windows are separate.

        This endpoint is unauthenticated. If a browser report could push a real
        failure out of the window, anyone could erase the error log by posting
        junk at it.
        """
        errors.record("node", summary="the real failure")
        for i in range(errors.CLIENT_WINDOW * 3):
            errors.record("client", summary=f"spam {i}")

        summaries = [e["summary"] for e in
                     client.get("/api/monitor/errors").get_json()["errors"]]
        assert "the real failure" in summaries

    def test_an_oversized_body_is_refused_and_counted(self, client):
        response = client.post(
            "/api/monitor/errors/client",
            data=json.dumps({"message": "x" * (routes.MAX_CLIENT_REPORT_BYTES + 100)}),
            content_type="application/json",
        )
        assert response.status_code == 204
        body = client.get("/api/monitor/errors").get_json()
        assert body["errors"] == []
        assert body["droppedClient"] == 1

    def test_message_and_stack_are_capped(self, client):
        # Under the 16KB body cap, over both per-field caps: this exercises the
        # truncation rather than the refusal the previous test covers.
        client.post("/api/monitor/errors/client", json={
            "message": "m" * 2500, "stack": "s" * 8500,
        })
        entry = client.get("/api/monitor/errors").get_json()["errors"][0]
        assert len(entry["summary"]) == routes.MAX_CLIENT_MESSAGE_CHARS
        assert len(entry["detail"]) == routes.MAX_CLIENT_STACK_CHARS

    def test_a_malformed_body_still_answers_204(self, client):
        response = client.post("/api/monitor/errors/client",
                               data="not json at all",
                               content_type="application/json")
        assert response.status_code == 204

    def test_an_empty_report_is_dropped_rather_than_logged(self, client):
        client.post("/api/monitor/errors/client", json={})
        body = client.get("/api/monitor/errors").get_json()
        assert body["errors"] == []
        assert body["droppedClient"] == 1

    def test_the_rate_limiter_stops_a_flood(self, client):
        for i in range(30):
            client.post("/api/monitor/errors/client", json={"message": f"m{i}"})

        body = client.get("/api/monitor/errors").get_json()
        # Ten per address per minute; the rest are counted, not stored.
        assert len(body["errors"]) == 10
        assert body["droppedClient"] == 20

    def test_the_endpoint_never_answers_anything_a_caller_would_retry(self, client):
        """A window.onerror handler must not be able to start a request loop."""
        for payload in ({}, {"message": "ok"}, {"message": "x" * 99999}):
            response = client.post("/api/monitor/errors/client", json=payload)
            assert response.status_code == 204
            assert response.get_data() == b""
