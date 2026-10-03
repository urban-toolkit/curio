"""The transport: the fixture one, and how the real one is selected.

The fixture transport is the mechanism that lets the whole backend stack run
under test without a socket, so its own guarantees are worth pinning: an exact
lookup, a loud miss, and a refusal to activate anywhere that is not a test rig.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.discovery.domain.errors import DownloadTooLarge
from utk_curio.backend.app.discovery.infrastructure import transport as T

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def corpus(tmp_path):
    """A tiny hand-built corpus, so these tests do not depend on the recorded one."""
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "ok.json").write_text('{"hello": "world"}', encoding="utf-8")
    (tmp_path / "p" / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "index.json").write_text(
        json.dumps(
            {
                "https://portal.example/ok": {
                    "file": "p/ok.json",
                    "status": 200,
                    "headers": {"Content-Type": "application/json"},
                },
                "https://portal.example/data.csv": {
                    "file": "p/data.csv",
                    "status": 200,
                    "headers": {"Content-Type": "text/csv", "Content-Length": "8"},
                },
                "https://portal.example/huge": {
                    "file": "p/data.csv",
                    "status": 200,
                    "headers": {"Content-Length": "999999999"},
                },
                "https://portal.example/boom": {"status": 500, "file": "p/ok.json"},
                "https://portal.example/slow": {"error": "timeout"},
                "https://portal.example/toobig": {"error": "too-large"},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


class TestFixtureLookup:
    def test_an_exact_url_returns_the_recorded_body(self, corpus):
        t = T.FixtureDiscoveryTransport(corpus)
        assert json.loads(t.json_get("https://portal.example/ok")) == {"hello": "world"}

    def test_it_records_every_url_asked_for(self, corpus):
        """So a test can assert a cached search issued ZERO requests, which is
        otherwise unobservable."""
        t = T.FixtureDiscoveryTransport(corpus)
        t.json_get("https://portal.example/ok")
        t.json_get("https://portal.example/ok")
        assert t.calls == ["https://portal.example/ok"] * 2

    def test_a_miss_names_the_url_and_how_to_record_it(self, corpus):
        t = T.FixtureDiscoveryTransport(corpus)
        with pytest.raises(T.FixtureMissing) as exc:
            t.json_get("https://portal.example/never")
        assert "https://portal.example/never" in str(exc.value)
        assert "record_discovery_fixtures" in str(exc.value)

    def test_a_missing_index_is_refused_at_construction(self, tmp_path):
        with pytest.raises(T.DiscoveryTransportError, match="no fixture index"):
            T.FixtureDiscoveryTransport(tmp_path)

    def test_a_recorded_error_status_behaves_like_the_real_one(self, corpus):
        t = T.FixtureDiscoveryTransport(corpus)
        with pytest.raises(T.DiscoveryTransportError, match="500"):
            t.json_get("https://portal.example/boom")

    def test_a_recorded_transport_error_raises(self, corpus):
        """This is how the federated partial-failure path gets a deterministic
        failing leg instead of being mocked at a higher level."""
        t = T.FixtureDiscoveryTransport(corpus)
        with pytest.raises(T.DiscoveryTransportError, match="timeout"):
            t.json_get("https://portal.example/slow")


class TestFixtureDownload:
    def test_it_writes_to_the_sink_and_hashes(self, corpus):
        import hashlib

        t = T.FixtureDiscoveryTransport(corpus)
        got = []
        result = t.download("https://portal.example/data.csv", got.append, max_bytes=1024)
        assert b"".join(got) == b"a,b\n1,2\n"
        assert result.sha256 == hashlib.sha256(b"a,b\n1,2\n").hexdigest()
        assert result.content_type == "text/csv"

    def test_a_declared_length_over_the_bound_refuses_before_any_bytes(self, corpus):
        """The real transport refuses on Content-Length before reading a body,
        so the fixture one must too or that branch is never exercised."""
        t = T.FixtureDiscoveryTransport(corpus)
        got = []
        with pytest.raises(DownloadTooLarge, match="declares"):
            t.download("https://portal.example/huge", got.append, max_bytes=16)
        assert got == []

    def test_an_oversized_body_is_refused_too(self, corpus):
        t = T.FixtureDiscoveryTransport(corpus)
        with pytest.raises(DownloadTooLarge):
            t.download("https://portal.example/data.csv", lambda b: None, max_bytes=2)

    def test_a_recorded_too_large_entry_raises_the_typed_error(self, corpus):
        t = T.FixtureDiscoveryTransport(corpus)
        with pytest.raises(DownloadTooLarge):
            t.download("https://portal.example/toobig", lambda b: None, max_bytes=1024)

    def test_the_server_ceiling_still_applies(self, corpus, monkeypatch):
        """A caller may ask for more than the server allows; it does not get it."""
        monkeypatch.setattr(T, "MAX_DISCOVERY_DOWNLOAD_BYTES", 4)
        t = T.FixtureDiscoveryTransport(corpus)
        with pytest.raises(DownloadTooLarge):
            t.download("https://portal.example/data.csv", lambda b: None, max_bytes=10 ** 9)


class TestSelection:
    def test_without_the_env_var_the_real_transport_is_built(self, monkeypatch):
        monkeypatch.delenv(T.ENV_FIXTURES, raising=False)
        assert isinstance(T.build_transport(), T.HttpDiscoveryTransport)

    def test_with_the_env_var_in_a_test_rig_the_fixture_one_is_built(self, monkeypatch, corpus):
        monkeypatch.setenv(T.ENV_FIXTURES, str(corpus))
        monkeypatch.setenv("CURIO_TESTING", "1")
        assert isinstance(T.build_transport(), T.FixtureDiscoveryTransport)

    def test_it_refuses_to_serve_fixtures_outside_a_test_rig(self, monkeypatch, corpus):
        """Double-gated exactly as app/testing/routes.py is, and checked at CALL
        time rather than import, so a stray env var on a real deployment cannot
        quietly start serving stale recordings."""
        monkeypatch.setenv(T.ENV_FIXTURES, str(corpus))
        monkeypatch.delenv("CURIO_TESTING", raising=False)
        with pytest.raises(T.DiscoveryTransportError, match="not a test rig"):
            T.build_transport()

    def test_the_metadata_bound_is_bigger_than_the_agent_one(self):
        """Portal metadata is not prompt text. GeoSampa's capabilities document
        is 425 KB and a CKAN package_search routinely passes 256 KiB."""
        from utk_curio.backend.app.agents.infrastructure import egress

        assert T.MAX_METADATA_BYTES > egress.MAX_BODY_BYTES
        assert T.MAX_METADATA_BYTES == 1024 * 1024


class TestCredentialHandling:
    def test_a_credential_becomes_a_header_and_nothing_else(self):
        assert T._merge(None, "X-App-Token:secret") == {"X-App-Token": "secret"}

    def test_no_credential_adds_no_header(self):
        assert T._merge({"Accept": "application/json"}, None) == {"Accept": "application/json"}

    def test_a_malformed_credential_is_dropped_rather_than_sent_raw(self):
        """Sending a half-parsed secret as a header NAME would put it somewhere
        it could be logged."""
        assert T._merge(None, "no-colon-here") == {}
        assert T._merge(None, ":novalue") == {}


class TestTheCorpusAnswersWhatTheAppAsks:
    """A recording is only useful at the limit a real request carries.

    Socrata, CKAN and ArcGIS all put the page size in the request URL, and the
    corpus is keyed on the exact URL. So a corpus recorded at one limit is
    simply absent when the app asks at another, and the symptom is not an
    error anyone reads: the browser renders "nothing matches" and the test
    that only checks the page loaded still passes. That is how this went
    unnoticed until the browser specs ran for the first time.
    """

    def test_the_recorder_records_at_the_limit_the_app_uses(self):
        import ast
        from pathlib import Path

        from utk_curio.backend.app.discovery.service import DEFAULT_SEARCH_LIMIT

        recorder = (
            Path(__file__).resolve().parents[4] / "scripts" / "record_discovery_fixtures.py"
        )
        tree = ast.parse(recorder.read_text(encoding="utf-8"))
        limits = [
            kw.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "SearchQuery"
            for kw in node.keywords
            if kw.arg == "limit"
        ]
        assert limits, "the recorder no longer passes a limit - check it still records at the app's"
        for value in limits:
            assert isinstance(value, ast.Name) and value.id == "DEFAULT_SEARCH_LIMIT", (
                "the recorder must record at the app's own default, not a literal: "
                "a corpus at any other limit answers a question the app never asks"
            )
        assert DEFAULT_SEARCH_LIMIT == 20

    def test_every_shipped_search_is_recorded_at_that_limit(self):
        """And the corpus on disk actually holds those recordings."""
        import json
        from pathlib import Path

        from utk_curio.backend.app.discovery.service import DEFAULT_SEARCH_LIMIT

        index = json.loads(
            (Path(__file__).resolve().parent / "fixtures" / "index.json").read_text(
                encoding="utf-8"
            )
        )
        # The three page-size spellings the providers use, one per portal API.
        wanted = (
            f"limit={DEFAULT_SEARCH_LIMIT}",
            f"rows={DEFAULT_SEARCH_LIMIT}",
            f"page[size]={DEFAULT_SEARCH_LIMIT}",
        )
        for spelling in wanted:
            assert any(spelling in url for url in index), (
                f"no recorded search carries {spelling!r} - a portal's search is "
                "recorded at a page size the app never requests"
            )


class _Wire:
    """``requests.request`` for the real transport: answers by URL, records
    what each hop sent. No socket is opened."""

    def __init__(self, routes):
        self.routes = routes
        self.sent = []

    def __call__(self, method, url, **kwargs):
        self.sent.append((url, dict(kwargs.get("headers") or {})))
        status, headers, body = self.routes[url]
        return _FakeResponse(status, headers, body)


class _FakeResponse:
    def __init__(self, status, headers, body):
        self.status_code = status
        self.headers = dict(headers)
        self._body = body

    def iter_content(self, chunk_size=8192):
        yield self._body

    def close(self):
        pass


@pytest.fixture()
def wire(monkeypatch):
    import requests

    from utk_curio.backend.app.common import egress_policy

    monkeypatch.setattr(egress_policy, "_default_resolver", lambda host: ["93.184.216.34"])

    def _install(routes):
        fake = _Wire(routes)
        monkeypatch.setattr(requests, "request", fake)
        return fake

    return _install


class TestTheRealTransport:
    KEY = "X-App-Token:s3cr3t-value-0123"

    def test_a_listing_page_returns_the_servers_headers(self, wire):
        """The Hugging Face listing follows ``Link: rel="next"``; reading the
        request's own headers instead stopped every listing after page one."""
        link = '<https://portal.example/api/tree?cursor=2>; rel="next"'
        wire({"https://portal.example/api/tree": (200, {"Link": link}, b"[]")})
        body, headers = T.HttpDiscoveryTransport().get_page(
            "https://portal.example/api/tree", credential=self.KEY
        )
        assert body == "[]"
        assert headers["Link"] == link
        assert "s3cr3t-value-0123" not in json.dumps(headers)

    def test_a_listing_redirected_elsewhere_carries_no_key(self, wire):
        fake = wire({
            "https://portal.example/api/x": (302, {"Location": "https://cdn.example/x"}, b""),
            "https://cdn.example/x": (200, {}, b"{}"),
        })
        T.HttpDiscoveryTransport().get_page("https://portal.example/api/x", credential=self.KEY)
        assert fake.sent[0][1]["X-App-Token"] == "s3cr3t-value-0123"
        assert "X-App-Token" not in fake.sent[1][1]

    @pytest.mark.parametrize("status", [401, 403, 404, 500])
    def test_a_download_that_answers_an_error_is_refused(self, wire, status):
        """As the recorded transport refuses one. Returned as a result instead,
        an error page was the file: a portal's JSON error installed as a JSON
        dataset, a CDN's 403 kept as an image."""
        wire({"https://portal.example/file.json": (status, {"Content-Type": "application/json"},
                                                   b'{"error": "not found"}')})
        with pytest.raises(T.DiscoveryTransportError, match=f"answered {status}"):
            T.HttpDiscoveryTransport().download(
                "https://portal.example/file.json", lambda b: None, max_bytes=100
            )

    def test_a_download_redirected_elsewhere_carries_no_key(self, wire):
        fake = wire({
            "https://portal.example/file.csv": (302, {"Location": "https://cdn.example/signed"}, b""),
            "https://cdn.example/signed": (200, {"Content-Length": "8"}, b"a,b\n1,2\n"),
        })
        out = []
        T.HttpDiscoveryTransport().download(
            "https://portal.example/file.csv", out.append, max_bytes=100, credential=self.KEY
        )
        assert b"".join(out) == b"a,b\n1,2\n"
        assert fake.sent[0][1]["X-App-Token"] == "s3cr3t-value-0123"
        assert "X-App-Token" not in fake.sent[1][1]


def _cancels():
    """Every exception a Discovery job maps to "cancelled"."""
    from utk_curio.backend.app.discovery import service

    return (service._Cancelled, service.StorageCancelled, service.ServiceCancelled)


class TestACancelledDownload:
    """A sink raises to stop a download when its job is cancelled. Through the
    real transport that exception has to come out as it went in: wrapped as a
    transport error, a cancelled download ended "failed"."""

    URL = "https://portal.example/model.onnx"

    @pytest.mark.parametrize("credential", [None, "X-App-Token:s3cr3t-value-0123", "?key=s3cr3t-value-0123"],
                             ids=["no-key", "header-key", "query-key"])
    @pytest.mark.parametrize("cancel", _cancels(), ids=lambda cls: f"{cls.__module__}.{cls.__name__}")
    def test_the_sinks_own_exception_passes_unchanged(self, wire, cancel, credential):
        sent, _key = T._keyed(self.URL, credential)
        wire({sent: (200, {"Content-Length": "4"}, b"\x00\x01\x02\x03")})
        raised = cancel()

        def sink(_chunk):
            raise raised

        with pytest.raises(cancel) as exc:
            T.HttpDiscoveryTransport().download(self.URL, sink, max_bytes=100, credential=credential)
        assert exc.value is raised

    def test_a_model_download_cancelled_mid_file_ends_as_cancelled(self, wire, tmp_path):
        """The model path: the job is cancelled after the file started, so the
        sink is the one that raises."""
        from types import SimpleNamespace

        from utk_curio.backend.app.discovery.application.model_acquire import ModelAcquire

        wire({self.URL: (200, {"Content-Length": "4"}, b"\x00\x01\x02\x03")})
        checks = []

        def cancelled():
            # False when the file starts, True by the time its first chunk lands.
            checks.append(None)
            return len(checks) > 1

        provider = SimpleNamespace(
            transport=T.HttpDiscoveryTransport(), file_url=lambda plan, path: self.URL
        )
        plan = SimpleNamespace(files=[("model.onnx", 4)], total_bytes=4, repo="org/model", gated=False)
        acquire_ = ModelAcquire(user_key="alice", provider_for=lambda m: provider, models=lambda: None)
        with pytest.raises(_cancels()):
            acquire_._fetch(provider, plan, tmp_path, progress=None, stage=None, cancelled=cancelled)
        assert len(checks) == 2
