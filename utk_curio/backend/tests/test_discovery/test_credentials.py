"""Per-account source keys: declared by manifests, stored, resolved, never leaked.

A source manifest declares the key it sends (``auth.secretId`` and how API
Settings shows it); an account saves one through ``PATCH /api/auth/me``, keyed
by that id, in its owner-only file, and every response reports it as a boolean.
The tests that matter most here are the negative ones: a key must not appear in
a response, in a log line, in an audit record, or in a URL, and must reach no
origin but its source's.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.common.user_storage import users_base
from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
from utk_curio.backend.app.discovery.infrastructure import credentials, transport as T
from utk_curio.backend.tests.test_discovery.conftest import (
    SHIPPED_ROOT,
    a_manifest,
    write_source,
)

SECRET = "s0cr4ta-t0ken-do-not-log"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CHICAGO = "source.cityofchicago.data-portal@1"
SOCRATA_DEFAULT = "CURIO_DEFAULT_SOCRATA_APP_TOKEN"


def _shipped_secret_ids() -> list[str]:
    """The secret ids the shipped manifests name, read as plain JSON so that
    collecting this module never depends on the parser."""
    ids = set()
    for path in sorted(SHIPPED_ROOT.iterdir()):
        manifest = path / "manifest.json"
        if manifest.is_file():
            secret_id = (json.loads(manifest.read_text(encoding="utf-8")).get("auth") or {}).get("secretId")
            if secret_id:
                ids.add(secret_id)
    return sorted(ids)


SHIPPED_SECRET_IDS = _shipped_secret_ids()

#: The rows API Settings lists for the keys the shipped sources send: label,
#: help link, placeholder and note, as their manifests declare them.
SHIPPED_KEY_ROWS = {
    "socrata.app-token": (
        "Socrata app token",
        "https://evergreen.data.socrata.com/signup",
        "Your app token",
        "Socrata portals answer without one; a token raises the rate limit.",
    ),
    "huggingface.token": (
        "Hugging Face token",
        "https://huggingface.co/settings/tokens",
        "hf_...",
        None,
    ),
    "google.maps-key": (
        "Google Maps API key",
        "https://developers.google.com/maps/documentation/streetview/get-api-key",
        "AIza...",
        "Needs the Street View Static API enabled, and Google bills its requests to you. Google's terms "
        "allow storing only panorama IDs: images downloaded with your key are yours to keep within those terms.",
    ),
    "mapillary.token": (
        "Mapillary access token",
        "https://www.mapillary.com/dashboard/developers",
        "MLY|...",
        "Mapillary images are CC BY-SA 4.0: each one keeps its creator for attribution.",
    ),
}


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


def _save(user, secret_id, value=SECRET):
    """What ``PATCH /api/auth/me`` saves, written straight to the account's file."""
    from utk_curio.backend.app.users import source_keys

    source_keys.save_for(user, {secret_id: value})


def _patch_keys(client, auth, keys):
    return client.patch("/api/auth/me", headers=auth, json={"source_keys": keys})


def _shipped_keyed_manifests():
    manifests = [load_source_manifest(p) for p in sorted(SHIPPED_ROOT.iterdir()) if (p / "manifest.json").is_file()]
    keyed = [m for m in manifests if m.auth.secret_id]
    assert keyed, f"no shipped source under {SHIPPED_ROOT} sends a key"
    return keyed


def _a_guest_with_a_session(db, username="guest1"):
    from utk_curio.backend.app.users.models import User, UserSession

    guest = User(username=username, name="Guest", email="g@test.com", is_guest=True)
    db.session.add(guest)
    db.session.flush()
    db.session.add(UserSession(user_id=guest.id, token="guest-token"))
    db.session.commit()
    return guest


def _no_key_file_anywhere():
    return not list(users_base().glob("*/source-keys.json"))


def test_the_shipped_sources_send_keys():
    """Guards the parametrized classes below against passing vacuously."""
    assert SHIPPED_SECRET_IDS, f"no shipped manifest under {SHIPPED_ROOT} names a secretId"


class TestASourceDeclaresItsKey:
    """The manifest is the whole declaration: which key, and how API Settings
    shows it. Curio's code holds no list of keys."""

    def test_a_manifest_names_its_key_and_says_how_it_is_shown(self):
        parsed = M._parse_manifest(
            a_manifest(auth={"mode": "optional-token", "secretId": "socrata.app-token",
                             "headerName": "X-App-Token", "label": "Socrata app token",
                             "placeholder": "Your app token", "note": "Raises the rate limit.",
                             "helpUrl": "https://help.example", "operatorDefault": True}),
            where="manifest.json",
        )
        auth = parsed.auth
        assert (auth.secret_id, auth.label, auth.placeholder, auth.note, auth.help_url, auth.operator_default) == (
            "socrata.app-token", "Socrata app token", "Your app token", "Raises the rate limit.",
            "https://help.example", True,
        )

    def test_a_manifest_may_declare_a_key_curio_has_never_seen(self):
        parsed = M._parse_manifest(
            a_manifest(auth={"mode": "required-token", "secretId": "acme.tiles-key",
                             "headerName": "X-Acme-Key", "label": "Acme tiles key"}),
            where="manifest.json",
        )
        assert parsed.auth.secret_id == "acme.tiles-key"

    def test_a_malformed_secret_id_is_still_refused(self):
        with pytest.raises(M.ManifestError, match="secretId"):
            M._parse_manifest(
                a_manifest(auth={"mode": "optional-token", "secretId": "Evil Slot/../x",
                                 "headerName": "X-Evil", "label": "Evil"}),
                where="manifest.json",
            )


class TestResolution:
    def _manifest(self):
        return load_source_manifest(SHIPPED_ROOT / CHICAGO)

    def test_no_user_means_no_token(self):
        assert credentials.credential_header(None, self._manifest()) is None

    def test_a_user_without_one_means_no_token(self, app, db, user_and_token):
        user, _ = user_and_token
        assert credentials.has_key(user, self._manifest().auth) is False
        assert credentials.credential_header(user, self._manifest()) is None

    def test_a_stored_token_becomes_one_header(self, app, db, user_and_token):
        user, _ = user_and_token
        _save(user, "socrata.app-token")
        assert credentials.has_key(user, self._manifest().auth) is True
        assert credentials.credential_header(user, self._manifest()) == f"X-App-Token:{SECRET}"

    def test_a_public_source_never_gets_one_even_if_a_token_is_stored(self, app, db, user_and_token):
        user, _ = user_and_token
        _save(user, "socrata.app-token")
        public = load_source_manifest(SHIPPED_ROOT / "source.saopaulo.geosampa@1")
        assert credentials.credential_header(user, public) is None

    def test_an_unknown_slot_resolves_to_nothing(self, app, db, user_and_token):
        user, _ = user_and_token
        unknown = M.AuthSpec(mode="optional-token", secret_id="not.a.slot", header_name="X-Not")
        assert credentials.own_key(user, "not.a.slot") is None
        assert credentials.key_for(user, unknown) is None
        assert credentials.own_key(user, None) is None
        assert credentials.key_for(user, M.AuthSpec()) is None


class TestTheAccountSetting:
    """``PATCH /api/auth/me`` saves a key by the secret id its sources name."""

    def test_it_saves_and_reports_only_a_boolean(self, client, auth, shipped_root):
        res = _patch_keys(client, auth, {"socrata.app-token": SECRET})
        assert res.status_code == 200, res.get_data(as_text=True)
        body = res.get_json()
        assert body["has_source_keys"] == {"socrata.app-token": True}
        assert SECRET not in json.dumps(body)

    def test_blank_clears_it(self, client, auth, shipped_root):
        _patch_keys(client, auth, {"socrata.app-token": SECRET})
        res = _patch_keys(client, auth, {"socrata.app-token": ""})
        assert res.get_json()["has_source_keys"] == {}

    def test_omitting_it_keeps_it(self, client, auth, shipped_root):
        """Blank means clear; absent means keep. Re-typing a token to change an
        unrelated setting would be hostile."""
        _patch_keys(client, auth, {"socrata.app-token": SECRET})
        res = client.patch("/api/auth/me", headers=auth, json={"name": "Alice II"})
        assert res.get_json()["has_source_keys"] == {"socrata.app-token": True}

    def test_saving_one_keeps_the_others(self, client, auth, shipped_root):
        _patch_keys(client, auth, {"socrata.app-token": SECRET})
        res = _patch_keys(client, auth, {"huggingface.token": "hf_other"})
        assert res.get_json()["has_source_keys"] == {"socrata.app-token": True, "huggingface.token": True}

    def test_it_is_reported_by_the_me_endpoint(self, client, auth, shipped_root):
        _patch_keys(client, auth, {"socrata.app-token": SECRET})
        body = client.get("/api/auth/me", headers=auth).get_json()
        assert body["has_source_keys"] == {"socrata.app-token": True}
        assert SECRET not in json.dumps(body)

    def test_a_guest_is_refused_out_loud(self, app, db, client, shipped_root):
        """403, the way an LLM configuration refuses - not a silent discard.

        A guest account is shared, so a personal token saved on it would be
        everyone's. Accepting the value and quietly dropping it would leave the
        user believing they are authenticated when they are not. The refusal
        names the key as API Settings does.
        """
        _a_guest_with_a_session(db)
        res = client.patch(
            "/api/auth/me",
            headers={"Authorization": "Bearer guest-token"},
            json={"source_keys": {"socrata.app-token": SECRET}},
        )
        assert res.status_code == 403
        assert "Socrata app token" in res.get_json()["error"]
        assert _no_key_file_anywhere()

    def test_an_id_no_source_declares_is_refused(self, client, auth, shipped_root):
        """A key is kept only for a key some source sends."""
        res = _patch_keys(client, auth, {"acme.tiles-key": SECRET})
        assert res.status_code == 400
        assert "acme.tiles-key" in res.get_json()["error"]
        assert SECRET not in res.get_data(as_text=True)
        assert client.get("/api/auth/me", headers=auth).get_json()["has_source_keys"] == {}

    @pytest.mark.parametrize("value", ["tok\r\nX-Evil: 1", "tok\nmore", "   ", 42, None, ["tok"]])
    def test_a_value_is_one_line_of_text(self, client, auth, shipped_root, value):
        """It is written into a request header or a query parameter."""
        res = _patch_keys(client, auth, {"socrata.app-token": value})
        assert res.status_code == 400, res.get_data(as_text=True)
        assert client.get("/api/auth/me", headers=auth).get_json()["has_source_keys"] == {}

    def test_source_keys_is_a_map_by_secret_id(self, client, auth, shipped_root):
        res = client.patch("/api/auth/me", headers=auth, json={"source_keys": ["socrata.app-token", SECRET]})
        assert res.status_code == 400
        assert SECRET not in res.get_data(as_text=True)

    def test_one_refused_key_saves_none_of_them(self, client, auth, shipped_root):
        res = _patch_keys(client, auth, {"socrata.app-token": SECRET, "acme.tiles-key": SECRET})
        assert res.status_code == 400
        res = _patch_keys(client, auth, {"socrata.app-token": SECRET, "huggingface.token": "two\nlines"})
        assert res.status_code == 400
        assert client.get("/api/auth/me", headers=auth).get_json()["has_source_keys"] == {}


class TestItReachesThePortalAndNowhereElse:
    def _source(self, discovery_dir, mode="optional-token"):
        write_source(discovery_dir, "source.a.tokened@1", a_manifest(
            id="source.a.tokened", name="Tokened Portal",
            provider={"type": "socrata", "baseUrl": "https://portal.example"},
            auth={"mode": mode, "secretId": "socrata.app-token",
                  "headerName": "X-App-Token", "helpUrl": "https://help.example"},
            capabilities={"formats": ["csv"]}))
        return load_source_manifest(discovery_dir / "source.a.tokened@1")

    def test_the_transport_turns_it_into_a_header(self):
        assert T._merge(None, f"X-App-Token:{SECRET}") == {"X-App-Token": SECRET}

    def test_a_bound_transport_passes_it_without_the_provider_knowing(self, discovery_dir):
        """Providers call json_get(url) and never handle a token, which is what
        keeps one out of the URLs they build and anything they log."""
        seen = {}

        class Spy:
            def json_get(self, url, *, credential=None, headers=None):
                seen["url"] = url
                seen["credential"] = credential
                return "{}"

            def download(self, *a, **k):  # pragma: no cover
                raise NotImplementedError

        bound = T.CredentialedTransport(Spy(), f"X-App-Token:{SECRET}", origins=("https://portal.example",))
        bound.json_get("https://portal.example/api/catalog/v1")
        assert seen["credential"] == f"X-App-Token:{SECRET}"
        assert SECRET not in seen["url"]

    def test_a_bound_transport_sends_it_to_no_other_host(self):
        """A Mapillary thumbnail lives on a CDN; a portal may link a file on
        another server. Neither is the source, and neither gets its key."""
        seen = []

        class Spy:
            def json_get(self, url, *, credential=None, headers=None):
                seen.append((url, credential))
                return "{}"

            def get_page(self, url, *, credential=None, headers=None):
                seen.append((url, credential))
                return "{}", {}

            def download(self, url, sink, *, max_bytes, credential=None, **kwargs):
                seen.append((url, credential))

        bound = T.CredentialedTransport(Spy(), f"X-App-Token:{SECRET}", origins=("https://portal.example",))
        bound.json_get("https://portal.example.evil.net/api")
        bound.get_page("https://cdn.example/listing")
        bound.download("https://scontent-ord5-1.xx.fbcdn.net/t.jpg", lambda b: None, max_bytes=10)
        bound.download("https://portal.example/file.csv", lambda b: None, max_bytes=10)
        assert seen == [
            ("https://portal.example.evil.net/api", None),
            ("https://cdn.example/listing", None),
            ("https://scontent-ord5-1.xx.fbcdn.net/t.jpg", None),
            ("https://portal.example/file.csv", f"X-App-Token:{SECRET}"),
        ]

    def test_the_service_binds_it_to_the_manifest_host(self, discovery_dir, app, db, user_and_token):
        from utk_curio.backend.app.discovery.service import DiscoveryService

        manifest = self._source(discovery_dir)
        user, _token = user_and_token
        _save(user, "socrata.app-token")
        bound = DiscoveryService("alice", user=user)._transport_for(manifest)
        assert bound._for("https://portal.example/api", None) == f"X-App-Token:{SECRET}"
        assert bound._for("https://elsewhere.example/api", None) is None

    @pytest.mark.parametrize("base, url, sent", [
        ("https://portal.example", "https://portal.example/api", True),
        # A URL without a port is on the scheme's default one.
        ("https://portal.example", "https://portal.example:443/api", True),
        ("https://portal.example", "https://PORTAL.example/api", True),
        ("https://portal.example:443", "https://portal.example/api", True),
        ("https://portal.example:8443", "https://portal.example:8443/api", True),
        # The same host on another scheme or port is another origin.
        ("https://portal.example", "http://portal.example/api", False),
        ("https://portal.example", "http://portal.example:443/api", False),
        ("https://portal.example", "https://portal.example:8443/api", False),
        ("https://portal.example:8443", "https://portal.example/api", False),
    ])
    def test_the_service_sends_it_only_to_the_manifests_origin(
        self, discovery_dir, app, db, user_and_token, base, url, sent
    ):
        """Scheme, host and port, as a browser compares origins. Comparing the
        host alone sent a key for an https portal over plain http, and to any
        other port on that host."""
        from utk_curio.backend.app.discovery.service import DiscoveryService

        write_source(discovery_dir, "source.a.origin@1", a_manifest(
            id="source.a.origin", name="Origin Portal",
            provider={"type": "socrata", "baseUrl": base},
            auth={"mode": "optional-token", "secretId": "socrata.app-token",
                  "headerName": "X-App-Token"},
            capabilities={"formats": ["csv"]}))
        manifest = load_source_manifest(discovery_dir / "source.a.origin@1")
        user, _token = user_and_token
        _save(user, "socrata.app-token")
        seen = []

        class Spy:
            def json_get(self, url, *, credential=None, headers=None):
                seen.append(credential)
                return "{}"

            def get_page(self, url, *, credential=None, headers=None):
                seen.append(credential)
                return "{}", {}

            def download(self, url, sink, *, max_bytes, credential=None, **kwargs):
                seen.append(credential)

        bound = DiscoveryService("alice", user=user, transport=Spy())._transport_for(manifest)
        bound.json_get(url)
        bound.get_page(url)
        bound.download(url, lambda b: None, max_bytes=10)
        expected = f"X-App-Token:{SECRET}" if sent else None
        assert seen == [expected, expected, expected]

    def test_plain_http_defaults_to_port_80(self):
        """A manifest is https, so this is the binding on its own."""
        seen = []

        class Spy:
            def json_get(self, url, *, credential=None, headers=None):
                seen.append(credential)
                return "{}"

        bound = T.CredentialedTransport(Spy(), f"X-App-Token:{SECRET}", origins=("http://portal.example",))
        for url in ("http://portal.example:80/a", "http://portal.example/a", "https://portal.example/a",
                    "http://portal.example:8080/a", "not a url"):
            bound.json_get(url)
        key = f"X-App-Token:{SECRET}"
        assert seen == [key, key, None, None, None]

    def test_a_key_reaches_no_source_that_names_another(self, discovery_dir, app, db, user_and_token):
        """A key is sent by the sources that name its secret id, and by no other."""
        write_source(discovery_dir, "source.b.other@1", a_manifest(
            id="source.b.other", name="Other Portal",
            provider={"type": "socrata", "baseUrl": "https://portal.example"},
            auth={"mode": "optional-token", "secretId": "other.portal-token",
                  "headerName": "X-App-Token", "label": "Other portal token"},
            capabilities={"formats": ["csv"]}))
        user, _token = user_and_token
        _save(user, "socrata.app-token")
        assert credentials.credential_header(user, self._source(discovery_dir)) == f"X-App-Token:{SECRET}"
        other = load_source_manifest(discovery_dir / "source.b.other@1")
        assert credentials.credential_header(user, other) is None

    def test_a_required_token_source_refuses_rather_than_trying_empty(self, discovery_dir, app, db, user_and_token):
        from utk_curio.backend.app.discovery.application.browse import DiscoveryBrowse
        from utk_curio.backend.app.discovery.domain.errors import CredentialRequired
        from utk_curio.backend.app.discovery.domain.resource import SearchQuery

        manifest = self._source(discovery_dir, mode="required-token")
        browse = DiscoveryBrowse(
            user_key="alice",
            transport_for=lambda _m: T.FixtureDiscoveryTransport(FIXTURES),
            credential_for=lambda _m: None,
        )
        with pytest.raises(CredentialRequired) as exc:
            browse.search(manifest, SearchQuery(text="x"))
        # Names the slot and where to get one; never a value.
        assert "socrata.app-token" in str(exc.value)
        assert "help.example" in str(exc.value)


class TestNoResponseOrLogCarriesIt:
    def test_no_discovery_response_contains_a_secret_shaped_value(self, client, auth, shipped_root):
        res = _patch_keys(client, auth, {"socrata.app-token": SECRET})
        assert res.get_json()["has_source_keys"] == {"socrata.app-token": True}
        for path in (
            "/api/discovery/catalog",
            f"/api/discovery/sources/{CHICAGO}",
            "/api/discovery/keys",
        ):
            body = client.get(path, headers=auth).get_data(as_text=True)
            assert SECRET not in body, path

    def test_the_source_row_reports_presence_not_the_value(self, client, auth, shipped_root):
        _patch_keys(client, auth, {"socrata.app-token": SECRET})
        row = client.get(f"/api/discovery/sources/{CHICAGO}", headers=auth).get_json()
        assert row["auth"]["present"] is True
        assert row["auth"]["secretId"] == "socrata.app-token"
        assert SECRET not in json.dumps(row)

    def test_a_search_logs_nothing_that_contains_it(self, client, auth, shipped_root, fixture_corpus, caplog):
        _patch_keys(client, auth, {"socrata.app-token": SECRET})
        with caplog.at_level(logging.DEBUG):
            client.get(
                f"/api/discovery/sources/{CHICAGO}/search?q=crimes",
                headers=auth,
            )
        for record in caplog.records:
            assert SECRET not in record.getMessage(), record.name

    def test_saving_and_listing_one_logs_nothing_that_contains_it(self, client, auth, shipped_root, caplog):
        with caplog.at_level(logging.DEBUG):
            res = _patch_keys(client, auth, {"socrata.app-token": SECRET})
            client.get("/api/discovery/keys", headers=auth)
            client.get("/api/auth/me", headers=auth)
            _patch_keys(client, auth, {"socrata.app-token": "two\nlines " + SECRET})
        assert res.get_json()["has_source_keys"] == {"socrata.app-token": True}
        for record in caplog.records:
            assert SECRET not in record.getMessage(), record.name

    def test_an_egress_audit_record_cannot_carry_it(self):
        """Header-only auth is what guarantees this: the audit record holds
        urls and a byte count, and a secret never enters a URL."""
        from utk_curio.backend.app.agents.infrastructure import egress

        audit: list = []
        egress.fetch(
            "https://portal.example/api",
            request_fn=lambda m, u: (200, {}, b"{}", None),
            resolver=lambda h: ["93.184.216.34"],
            audit=audit,
        )
        assert set(audit[0]) == {"url", "finalUrl", "status", "bytes"}


class TestTheDeploymentFallback:
    """A user who sets nothing inherits what the operator configured, for a
    source whose manifest allows it (``auth.operatorDefault``).

    An operator running Curio for a class raises the rate limit for everyone
    with one environment variable, and any user can still override it with
    their own.
    """

    def _chicago(self):
        return load_source_manifest(SHIPPED_ROOT / CHICAGO)

    def test_with_nothing_configured_there_is_no_token(self, app, db, user_and_token, monkeypatch):
        monkeypatch.delenv(SOCRATA_DEFAULT, raising=False)
        user, _ = user_and_token
        assert credentials.key_for(user, self._chicago().auth) is None

    def test_the_deployment_token_is_inherited(self, app, db, user_and_token, monkeypatch):
        monkeypatch.setenv(SOCRATA_DEFAULT, "deployment-token")
        user, _ = user_and_token
        assert credentials.key_for(user, self._chicago().auth) == "deployment-token"
        assert credentials.has_key(user, self._chicago().auth) is True

    def test_a_users_own_token_wins(self, app, db, user_and_token, monkeypatch):
        monkeypatch.setenv(SOCRATA_DEFAULT, "deployment-token")
        user, _ = user_and_token
        _save(user, "socrata.app-token")
        assert credentials.key_for(user, self._chicago().auth) == SECRET

    def test_own_token_never_reports_the_deployments(self, app, db, user_and_token, monkeypatch):
        """The settings screen asks a different question - did YOU save one -
        and must not answer it with the operator's value."""
        monkeypatch.setenv(SOCRATA_DEFAULT, "deployment-token")
        user, _ = user_and_token
        assert credentials.own_key(user, "socrata.app-token") is None

    def test_the_me_payload_still_reports_only_your_own(self, client, auth, monkeypatch):
        monkeypatch.setenv(SOCRATA_DEFAULT, "deployment-token")
        body = client.get("/api/auth/me", headers=auth).get_json()
        assert body["has_source_keys"] == {}

    def test_it_is_read_at_call_time_not_import(self, app, db, user_and_token, monkeypatch):
        user, _ = user_and_token
        monkeypatch.delenv(SOCRATA_DEFAULT, raising=False)
        assert credentials.key_for(user, self._chicago().auth) is None
        monkeypatch.setenv(SOCRATA_DEFAULT, "set-later")
        assert credentials.key_for(user, self._chicago().auth) == "set-later"

    def test_a_required_token_source_is_satisfied_by_the_deployments(
        self, app, db, user_and_token, discovery_dir, monkeypatch
    ):
        """The gate asks "will a token be sent", not "did the user save one" -
        otherwise an operator-configured deployment would still refuse."""
        from utk_curio.backend.app.discovery.application.browse import DiscoveryBrowse
        from utk_curio.backend.app.discovery.domain.resource import SearchQuery

        monkeypatch.setenv(SOCRATA_DEFAULT, "deployment-token")
        user, _ = user_and_token
        write_source(discovery_dir, "source.a.gated@1", a_manifest(
            id="source.a.gated", name="Gated Portal",
            provider={"type": "socrata", "baseUrl": "https://portal.example"},
            auth={"mode": "required-token", "secretId": "socrata.app-token",
                  "headerName": "X-App-Token", "helpUrl": "https://help.example",
                  "operatorDefault": True},
            capabilities={"formats": ["csv"]}))
        manifest = load_source_manifest(discovery_dir / "source.a.gated@1")

        browse = DiscoveryBrowse(
            user_key="alice",
            transport_for=lambda _m: T.FixtureDiscoveryTransport(FIXTURES),
            credential_for=lambda m: credentials.credential_header(user, m),
        )
        # No FixtureMissing means the gate let it through to the provider.
        with pytest.raises(T.FixtureMissing):
            browse.search(manifest, SearchQuery(text="whatever"))

    def test_only_a_source_that_allows_it_inherits_one(self, client, auth, shipped_root, user_and_token, monkeypatch):
        """Each shipped key's variable set at once: only the Socrata portal's
        manifest allows a default. A Hugging Face, Google Maps or Mapillary key
        is each person's own."""
        keyed = _shipped_keyed_manifests()
        for manifest in keyed:
            monkeypatch.setenv(credentials.default_variable(manifest.auth.secret_id), "deployment-token")
        user, _ = user_and_token
        assert {m.auth.secret_id for m in keyed if credentials.key_for(user, m.auth)} == {"socrata.app-token"}
        rows = client.get("/api/discovery/keys", headers=auth).get_json()["keys"]
        assert {row["slot"]: row["inherited"] for row in rows} == {
            "socrata.app-token": True,
            "huggingface.token": False,
            "google.maps-key": False,
            "mapillary.token": False,
        }

    def test_a_manifest_that_does_not_allow_it_gets_none(self, discovery_dir, app, db, user_and_token, monkeypatch):
        monkeypatch.setenv(SOCRATA_DEFAULT, "deployment-token")
        user, _ = user_and_token
        write_source(discovery_dir, "source.a.own@1", a_manifest(
            id="source.a.own", name="Own Keys Only",
            provider={"type": "socrata", "baseUrl": "https://portal.example"},
            auth={"mode": "optional-token", "secretId": "socrata.app-token", "headerName": "X-App-Token"},
            capabilities={"formats": ["csv"]}))
        manifest = load_source_manifest(discovery_dir / "source.a.own@1")
        assert credentials.key_for(user, manifest.auth) is None
        assert credentials.credential_header(user, manifest) is None

    def test_the_variable_is_curio_default_and_the_secret_id(self):
        """Derived from the id, so a manifest can name no variable of its own."""
        assert credentials.default_variable("socrata.app-token") == SOCRATA_DEFAULT
        assert credentials.default_variable("a.b-c") == "CURIO_DEFAULT_A_B_C"
        for secret_id in ("path", "home", "ld-preload", "aws.secret-access-key", "x.y.z"):
            name = credentials.default_variable(secret_id)
            assert name.startswith("CURIO_DEFAULT_") and re.fullmatch(r"[A-Z0-9_]+", name), name


@pytest.mark.parametrize("secret_id", SHIPPED_SECRET_IDS)
class TestEveryShippedKeyIsAnAccountSetting:
    """Each key a shipped source sends is saved through PATCH /api/auth/me by
    its secret id, reported as a boolean, and refused out loud for a guest."""

    def test_it_saves_and_reports_only_a_boolean(self, client, auth, shipped_root, secret_id):
        res = _patch_keys(client, auth, {secret_id: SECRET})
        assert res.status_code == 200, res.get_data(as_text=True)
        body = res.get_json()
        assert body["has_source_keys"] == {secret_id: True}
        assert SECRET not in json.dumps(body)
        res = _patch_keys(client, auth, {secret_id: ""})
        assert res.get_json()["has_source_keys"] == {}

    def test_a_guest_is_refused_out_loud(self, app, db, client, shipped_root, secret_id):
        _a_guest_with_a_session(db)
        res = client.patch(
            "/api/auth/me",
            headers={"Authorization": "Bearer guest-token"},
            json={"source_keys": {secret_id: SECRET}},
        )
        assert res.status_code == 403
        assert SHIPPED_KEY_ROWS[secret_id][0] in res.get_json()["error"]
        assert _no_key_file_anywhere()


class TestTheKeysApiSettingsLists:
    """``GET /api/discovery/keys``: one row per key a source declares, booleans only."""

    def _rows(self, client, auth):
        res = client.get("/api/discovery/keys", headers=auth)
        assert res.status_code == 200, res.get_data(as_text=True)
        return {row["slot"]: row for row in res.get_json()["keys"]}

    def test_the_shipped_sources_declare_the_rows_it_lists(self, client, auth, shipped_root):
        rows = self._rows(client, auth)
        assert {
            slot: (row["label"], row["helpUrl"], row["placeholder"], row["note"]) for slot, row in rows.items()
        } == SHIPPED_KEY_ROWS
        for row in rows.values():
            assert set(row) == {"slot", "label", "helpUrl", "placeholder", "note", "present", "inherited", "sources"}

    def test_rows_are_in_the_order_of_their_labels(self, client, auth, shipped_root):
        res = client.get("/api/discovery/keys", headers=auth)
        labels = [row["label"] for row in res.get_json()["keys"]]
        assert labels == sorted(labels, key=str.lower)

    def test_presence_is_this_accounts_own_and_a_boolean(self, client, auth, shipped_root, monkeypatch):
        monkeypatch.delenv(SOCRATA_DEFAULT, raising=False)
        assert self._rows(client, auth)["socrata.app-token"]["present"] is False
        _patch_keys(client, auth, {"socrata.app-token": SECRET})
        row = self._rows(client, auth)["socrata.app-token"]
        assert row["present"] is True and row["inherited"] is False

    def test_a_deployment_key_is_reported_as_inherited_not_as_present(self, client, auth, shipped_root, monkeypatch):
        monkeypatch.setenv(SOCRATA_DEFAULT, "deployment-token")
        row = self._rows(client, auth)["socrata.app-token"]
        assert row["inherited"] is True and row["present"] is False

    def test_each_row_names_the_sources_that_send_it(self, client, auth, shipped_root):
        rows = self._rows(client, auth)
        assert {"name": "City of Chicago Data Portal", "dirName": "source.cityofchicago.data-portal@1"} in (
            rows["socrata.app-token"]["sources"]
        )
        assert {"name": "Hugging Face models", "dirName": "source.huggingface.models@1"} in (
            rows["huggingface.token"]["sources"]
        )

    def test_a_saved_value_never_appears(self, client, auth, shipped_root):
        res = _patch_keys(client, auth, {"socrata.app-token": SECRET, "huggingface.token": SECRET})
        assert res.get_json()["has_source_keys"] == {"socrata.app-token": True, "huggingface.token": True}
        body = client.get("/api/discovery/keys", headers=auth).get_data(as_text=True)
        assert SECRET not in body

    def test_it_needs_a_signed_in_caller(self, client, shipped_root):
        assert client.get("/api/discovery/keys").status_code == 401


ACME = "source.acme.tiles@1"


class TestANewSourcesKeyNeedsNoCode:
    """A key-gated source whose secret id Curio has never seen. Its manifest is
    all it takes: API Settings lists the key, an account saves it, and the key
    reaches that source's origin and no other."""

    @pytest.fixture()
    def acme(self, discovery_dir):
        write_source(discovery_dir, ACME, a_manifest(
            id="source.acme.tiles", name="Acme Tiles",
            provider={"type": "ckan", "baseUrl": "https://tiles.acme.example"},
            auth={"mode": "required-token", "secretId": "acme.tiles-key", "headerName": "X-Acme-Key",
                  "label": "Acme tiles key", "helpUrl": "https://acme.example/keys",
                  "placeholder": "acme_...", "note": "Acme bills each request to you."},
            capabilities={"formats": ["csv"]}))
        return discovery_dir / ACME

    def test_api_settings_lists_it_as_its_manifest_declares(self, client, auth, acme):
        res = client.get("/api/discovery/keys", headers=auth)
        assert res.get_json()["keys"] == [{
            "slot": "acme.tiles-key",
            "label": "Acme tiles key",
            "helpUrl": "https://acme.example/keys",
            "placeholder": "acme_...",
            "note": "Acme bills each request to you.",
            "present": False,
            "inherited": False,
            "sources": [{"name": "Acme Tiles", "dirName": ACME}],
        }]

    def test_an_account_saves_it_by_its_secret_id(self, client, auth, acme):
        res = _patch_keys(client, auth, {"acme.tiles-key": SECRET})
        assert res.status_code == 200, res.get_data(as_text=True)
        assert res.get_json()["has_source_keys"] == {"acme.tiles-key": True}
        row = client.get("/api/discovery/keys", headers=auth).get_json()["keys"][0]
        assert row["present"] is True
        assert SECRET not in json.dumps(row)
        source = client.get(f"/api/discovery/sources/{ACME}", headers=auth).get_json()
        assert source["auth"]["present"] is True

    def test_it_reaches_the_sources_origin_and_nowhere_else(self, client, auth, acme, user_and_token):
        from utk_curio.backend.app.discovery.service import DiscoveryService

        _patch_keys(client, auth, {"acme.tiles-key": SECRET})
        user, _token = user_and_token
        seen = []

        class Spy:
            def json_get(self, url, *, credential=None, headers=None):
                seen.append((url, credential))
                return "{}"

            def download(self, url, sink, *, max_bytes, credential=None, **kwargs):
                seen.append((url, credential))

        manifest = load_source_manifest(acme)
        bound = DiscoveryService(str(user.id), user=user, transport=Spy())._transport_for(manifest)
        bound.json_get("https://tiles.acme.example/api/3/action/package_search?q=x")
        bound.download("https://cdn.acme.example/tile.csv", lambda b: None, max_bytes=10)
        bound.json_get("http://tiles.acme.example/api/3/action/package_search")
        assert seen == [
            ("https://tiles.acme.example/api/3/action/package_search?q=x", f"X-Acme-Key:{SECRET}"),
            ("https://cdn.acme.example/tile.csv", None),
            ("http://tiles.acme.example/api/3/action/package_search", None),
        ]


class TestTheSharedGuestsKeysUnderDeploy:
    """Without ``--deploy`` the shared guest is the one local user, and the
    keys it saves are its own. With ``--deploy`` it is every guest at once, so
    keys it saved in local mode on the same ``.curio`` are never sent; the
    deployment's own key still is. Each test runs in both modes."""

    @pytest.fixture()
    def shared_guest(self, app, db):
        from utk_curio.backend import config
        from utk_curio.backend.app.common.user_storage import GUEST_KEY
        from utk_curio.backend.app.users import source_keys
        from utk_curio.backend.app.users.models import User, UserSession

        guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest",
                     email="guest@test.com", is_guest=True)
        db.session.add(guest)
        db.session.flush()
        db.session.add(UserSession(user_id=guest.id, token="shared-guest-token"))
        db.session.commit()
        # Saved while the instance ran without --deploy.
        source_keys.default_store().update(GUEST_KEY, {secret_id: SECRET for secret_id in SHIPPED_SECRET_IDS})
        return guest

    @staticmethod
    def _mode(monkeypatch, deploy):
        from utk_curio.backend import config

        monkeypatch.setattr(config, "CURIO_NO_AUTH", not deploy)
        monkeypatch.delenv(SOCRATA_DEFAULT, raising=False)

    @pytest.mark.parametrize("deploy", [False, True], ids=["local", "deploy"])
    def test_its_saved_keys_are_sent_only_without_deploy(self, shared_guest, monkeypatch, deploy):
        self._mode(monkeypatch, deploy)
        for manifest in _shipped_keyed_manifests():
            secret_id = manifest.auth.secret_id
            assert credentials.own_key(shared_guest, secret_id) == (None if deploy else SECRET), secret_id
            assert credentials.key_for(shared_guest, manifest.auth) == (None if deploy else SECRET), secret_id
            assert credentials.has_key(shared_guest, manifest.auth) is (not deploy), secret_id
        chicago = load_source_manifest(SHIPPED_ROOT / CHICAGO)
        assert credentials.credential_header(shared_guest, chicago) == (
            None if deploy else f"X-App-Token:{SECRET}"
        )

    @pytest.mark.parametrize("deploy", [False, True], ids=["local", "deploy"])
    def test_the_service_binds_none_under_deploy(self, discovery_dir, shared_guest, monkeypatch, deploy):
        from utk_curio.backend.app.discovery.service import DiscoveryService

        self._mode(monkeypatch, deploy)
        write_source(discovery_dir, "source.a.tokened@1", a_manifest(
            id="source.a.tokened", name="Tokened Portal",
            provider={"type": "socrata", "baseUrl": "https://portal.example"},
            auth={"mode": "optional-token", "secretId": "socrata.app-token",
                  "headerName": "X-App-Token"},
            capabilities={"formats": ["csv"]}))
        manifest = load_source_manifest(discovery_dir / "source.a.tokened@1")
        seen = []

        class Spy:
            def json_get(self, url, *, credential=None, headers=None):
                seen.append(credential)
                return "{}"

        DiscoveryService("guest", user=shared_guest, transport=Spy())._transport_for(manifest).json_get(
            "https://portal.example/api"
        )
        assert seen == [None if deploy else f"X-App-Token:{SECRET}"]

    @pytest.mark.parametrize("deploy", [False, True], ids=["local", "deploy"])
    def test_api_settings_reports_them_only_without_deploy(self, client, shipped_root, shared_guest,
                                                           monkeypatch, deploy):
        self._mode(monkeypatch, deploy)
        res = client.get("/api/discovery/keys", headers={"Authorization": "Bearer shared-guest-token"})
        assert res.status_code == 200, res.get_data(as_text=True)
        for row in res.get_json()["keys"]:
            assert row["present"] is (not deploy), row["slot"]
        assert SECRET not in res.get_data(as_text=True)

    @pytest.mark.parametrize("deploy", [False, True], ids=["local", "deploy"])
    def test_the_me_payload_reports_them_only_without_deploy(self, client, shared_guest, monkeypatch, deploy):
        self._mode(monkeypatch, deploy)
        res = client.get("/api/auth/me", headers={"Authorization": "Bearer shared-guest-token"})
        assert res.status_code == 200, res.get_data(as_text=True)
        expected = {} if deploy else {secret_id: True for secret_id in SHIPPED_SECRET_IDS}
        assert res.get_json()["has_source_keys"] == expected
        assert SECRET not in res.get_data(as_text=True)

    def test_under_deploy_the_deployments_key_is_sent_instead(self, shared_guest, monkeypatch):
        self._mode(monkeypatch, True)
        monkeypatch.setenv(SOCRATA_DEFAULT, "deployment-token")
        chicago = load_source_manifest(SHIPPED_ROOT / CHICAGO)
        assert credentials.key_for(shared_guest, chicago.auth) == "deployment-token"
