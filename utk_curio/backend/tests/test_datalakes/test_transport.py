"""The transport: the fixture one, and how the real one is selected.

The fixture transport is the mechanism that lets the whole backend stack run
under test without a socket, so its own guarantees are worth pinning: an exact
lookup, a loud miss, and a refusal to activate anywhere that is not a test rig.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.datalakes.domain.errors import DownloadTooLarge
from utk_curio.backend.app.datalakes.infrastructure import transport as T

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
        t = T.FixtureLakeTransport(corpus)
        assert json.loads(t.json_get("https://portal.example/ok")) == {"hello": "world"}

    def test_it_records_every_url_asked_for(self, corpus):
        """So a test can assert a cached search issued ZERO requests, which is
        otherwise unobservable."""
        t = T.FixtureLakeTransport(corpus)
        t.json_get("https://portal.example/ok")
        t.json_get("https://portal.example/ok")
        assert t.calls == ["https://portal.example/ok"] * 2

    def test_a_miss_names_the_url_and_how_to_record_it(self, corpus):
        t = T.FixtureLakeTransport(corpus)
        with pytest.raises(T.FixtureMissing) as exc:
            t.json_get("https://portal.example/never")
        assert "https://portal.example/never" in str(exc.value)
        assert "record_datalake_fixtures" in str(exc.value)

    def test_a_missing_index_is_refused_at_construction(self, tmp_path):
        with pytest.raises(T.LakeTransportError, match="no fixture index"):
            T.FixtureLakeTransport(tmp_path)

    def test_a_recorded_error_status_behaves_like_the_real_one(self, corpus):
        t = T.FixtureLakeTransport(corpus)
        with pytest.raises(T.LakeTransportError, match="500"):
            t.json_get("https://portal.example/boom")

    def test_a_recorded_transport_error_raises(self, corpus):
        """This is how the federated partial-failure path gets a deterministic
        failing leg instead of being mocked at a higher level."""
        t = T.FixtureLakeTransport(corpus)
        with pytest.raises(T.LakeTransportError, match="timeout"):
            t.json_get("https://portal.example/slow")


class TestFixtureDownload:
    def test_it_writes_to_the_sink_and_hashes(self, corpus):
        import hashlib

        t = T.FixtureLakeTransport(corpus)
        got = []
        result = t.download("https://portal.example/data.csv", got.append, max_bytes=1024)
        assert b"".join(got) == b"a,b\n1,2\n"
        assert result.sha256 == hashlib.sha256(b"a,b\n1,2\n").hexdigest()
        assert result.content_type == "text/csv"

    def test_a_declared_length_over_the_bound_refuses_before_any_bytes(self, corpus):
        """The real transport refuses on Content-Length before reading a body,
        so the fixture one must too or that branch is never exercised."""
        t = T.FixtureLakeTransport(corpus)
        got = []
        with pytest.raises(DownloadTooLarge, match="declares"):
            t.download("https://portal.example/huge", got.append, max_bytes=16)
        assert got == []

    def test_an_oversized_body_is_refused_too(self, corpus):
        t = T.FixtureLakeTransport(corpus)
        with pytest.raises(DownloadTooLarge):
            t.download("https://portal.example/data.csv", lambda b: None, max_bytes=2)

    def test_a_recorded_too_large_entry_raises_the_typed_error(self, corpus):
        t = T.FixtureLakeTransport(corpus)
        with pytest.raises(DownloadTooLarge):
            t.download("https://portal.example/toobig", lambda b: None, max_bytes=1024)

    def test_the_server_ceiling_still_applies(self, corpus, monkeypatch):
        """A caller may ask for more than the server allows; it does not get it."""
        monkeypatch.setattr(T, "MAX_LAKE_DOWNLOAD_BYTES", 4)
        t = T.FixtureLakeTransport(corpus)
        with pytest.raises(DownloadTooLarge):
            t.download("https://portal.example/data.csv", lambda b: None, max_bytes=10 ** 9)


class TestSelection:
    def test_without_the_env_var_the_real_transport_is_built(self, monkeypatch):
        monkeypatch.delenv(T.ENV_FIXTURES, raising=False)
        assert isinstance(T.build_transport(), T.HttpLakeTransport)

    def test_with_the_env_var_in_a_test_rig_the_fixture_one_is_built(self, monkeypatch, corpus):
        monkeypatch.setenv(T.ENV_FIXTURES, str(corpus))
        monkeypatch.setenv("CURIO_TESTING", "1")
        assert isinstance(T.build_transport(), T.FixtureLakeTransport)

    def test_it_refuses_to_serve_fixtures_outside_a_test_rig(self, monkeypatch, corpus):
        """Double-gated exactly as app/testing/routes.py is, and checked at CALL
        time rather than import, so a stray env var on a real deployment cannot
        quietly start serving stale recordings."""
        monkeypatch.setenv(T.ENV_FIXTURES, str(corpus))
        monkeypatch.delenv("CURIO_TESTING", raising=False)
        with pytest.raises(T.LakeTransportError, match="not a test rig"):
            T.build_transport()

    def test_the_metadata_bound_is_bigger_than_the_agent_one(self):
        """Portal metadata is not prompt text. GeoSampa's capabilities document
        is 425 KB and a CKAN package_search routinely passes 256 KiB."""
        from utk_curio.backend.app.agents import egress

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
