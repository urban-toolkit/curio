"""Per-user portal tokens: stored, resolved, and never leaked.

The same shape as every other Curio credential - a column on the user's row,
written through ``PATCH /api/auth/me``, reported as a boolean. The tests that
matter most here are the negative ones: a token must not appear in a response,
in a log line, in an audit record, or in a URL.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

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


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


class TestTheSlotRegistryIsServerOwned:
    def test_the_manifest_validator_and_the_registry_agree(self):
        """Declared in two modules - a manifest must be readable without the
        ORM - so the agreement is asserted rather than assumed."""
        assert set(M.KNOWN_SECRET_SLOTS) == set(credentials.SLOT_COLUMNS)

    def test_a_manifest_may_name_a_known_slot(self, discovery_dir):
        parsed = M._parse_manifest(
            a_manifest(auth={"mode": "optional-token", "secretId": "socrata.app-token",
                             "headerName": "X-App-Token"}),
            where="manifest.json",
        )
        assert parsed.auth.secret_id == "socrata.app-token"

    def test_a_manifest_may_not_invent_one(self):
        """A manifest is operator-authored configuration. Letting it mint a
        slot would let it mint somewhere for a secret to live."""
        with pytest.raises(M.ManifestError, match="unknown credential slot"):
            M._parse_manifest(
                a_manifest(auth={"mode": "optional-token", "secretId": "evil.exfiltrate",
                                 "headerName": "X-Evil"}),
                where="manifest.json",
            )

    def test_the_refusal_says_how_to_add_one_properly(self):
        with pytest.raises(M.ManifestError, match="migration"):
            M._parse_manifest(
                a_manifest(auth={"mode": "required-token", "secretId": "new.thing",
                                 "headerName": "X-New"}),
                where="manifest.json",
            )

    def test_every_slot_maps_to_a_real_user_column(self):
        from utk_curio.backend.app.users.models import User

        for slot, column in credentials.SLOT_COLUMNS.items():
            assert hasattr(User, column), f"{slot} points at a column that does not exist"


class TestResolution:
    def _manifest(self):
        return load_source_manifest(SHIPPED_ROOT / "source.cityofchicago.data-portal@1")

    def test_no_user_means_no_token(self):
        assert credentials.credential_header(None, self._manifest()) is None

    def test_a_user_without_one_means_no_token(self, app, db, user_and_token):
        user, _ = user_and_token
        assert credentials.has_token(user, "socrata.app-token") is False
        assert credentials.credential_header(user, self._manifest()) is None

    def test_a_stored_token_becomes_one_header(self, app, db, user_and_token):
        user, _ = user_and_token
        user.socrata_app_token = SECRET
        db.session.commit()
        assert credentials.has_token(user, "socrata.app-token") is True
        assert credentials.credential_header(user, self._manifest()) == f"X-App-Token:{SECRET}"

    def test_a_public_source_never_gets_one_even_if_a_token_is_stored(self, app, db, user_and_token):
        user, _ = user_and_token
        user.socrata_app_token = SECRET
        db.session.commit()
        public = load_source_manifest(SHIPPED_ROOT / "source.saopaulo.geosampa@1")
        assert credentials.credential_header(user, public) is None

    def test_an_unknown_slot_resolves_to_nothing(self, app, db, user_and_token):
        user, _ = user_and_token
        assert credentials.token_for_slot(user, "not.a.slot") is None
        assert credentials.token_for_slot(user, None) is None


class TestTheAccountSetting:
    """The same surface as every other credential: PATCH /api/auth/me."""

    def test_it_saves_and_reports_only_a_boolean(self, client, auth):
        res = client.patch("/api/auth/me", headers=auth, json={"socrata_app_token": SECRET})
        assert res.status_code == 200, res.get_data(as_text=True)
        body = res.get_json()
        assert body["has_socrata_app_token"] is True
        assert SECRET not in json.dumps(body)

    def test_blank_clears_it(self, client, auth):
        client.patch("/api/auth/me", headers=auth, json={"socrata_app_token": SECRET})
        res = client.patch("/api/auth/me", headers=auth, json={"socrata_app_token": ""})
        assert res.get_json()["has_socrata_app_token"] is False

    def test_omitting_it_keeps_it(self, client, auth):
        """Blank means clear; absent means keep. Re-typing a token to change an
        unrelated setting would be hostile."""
        client.patch("/api/auth/me", headers=auth, json={"socrata_app_token": SECRET})
        res = client.patch("/api/auth/me", headers=auth, json={"name": "Alice II"})
        assert res.get_json()["has_socrata_app_token"] is True

    def test_it_is_reported_by_the_me_endpoint(self, client, auth):
        client.patch("/api/auth/me", headers=auth, json={"socrata_app_token": SECRET})
        body = client.get("/api/auth/me", headers=auth).get_json()
        assert body["has_socrata_app_token"] is True
        assert SECRET not in json.dumps(body)

    def test_a_guest_is_refused_out_loud(self, app, db, client):
        """403, the way the LLM key refuses - not a silent discard.

        A guest account is shared, so a personal token saved on it would be
        everyone's. Accepting the value and quietly dropping it would leave the
        user believing they are authenticated when they are not, which is the
        failure the LLM key's explicit refusal exists to avoid.
        """
        from utk_curio.backend.app.users.models import User, UserSession

        guest = User(username="guest1", name="Guest", email="g@test.com", is_guest=True)
        db.session.add(guest)
        db.session.flush()
        db.session.add(UserSession(user_id=guest.id, token="guest-token"))
        db.session.commit()
        res = client.patch(
            "/api/auth/me",
            headers={"Authorization": "Bearer guest-token"},
            json={"socrata_app_token": SECRET},
        )
        assert res.status_code == 403
        assert "portal token" in res.get_json()["error"]
        assert db.session.get(User, guest.id).socrata_app_token is None


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
        user.socrata_app_token = SECRET
        db.session.commit()
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
        user.socrata_app_token = SECRET
        db.session.commit()
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
        client.patch("/api/auth/me", headers=auth, json={"socrata_app_token": SECRET})
        for path in (
            "/api/discovery/catalog",
            "/api/discovery/sources/source.cityofchicago.data-portal@1",
        ):
            body = client.get(path, headers=auth).get_data(as_text=True)
            assert SECRET not in body, path

    def test_the_source_row_reports_presence_not_the_value(self, client, auth, shipped_root):
        client.patch("/api/auth/me", headers=auth, json={"socrata_app_token": SECRET})
        row = client.get(
            "/api/discovery/sources/source.cityofchicago.data-portal@1", headers=auth
        ).get_json()
        assert row["auth"]["present"] is True
        assert row["auth"]["secretId"] == "socrata.app-token"
        assert SECRET not in json.dumps(row)

    def test_a_search_logs_nothing_that_contains_it(self, client, auth, shipped_root, fixture_corpus, caplog):
        client.patch("/api/auth/me", headers=auth, json={"socrata_app_token": SECRET})
        with caplog.at_level(logging.DEBUG):
            client.get(
                "/api/discovery/sources/source.cityofchicago.data-portal@1/search?q=crimes",
                headers=auth,
            )
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
    """A user who sets nothing inherits what the operator configured.

    An operator running Curio for a class raises the rate limit for everyone
    with one environment variable, and any user can still override it with
    their own.
    """

    def test_with_nothing_configured_there_is_no_token(self, app, db, user_and_token, monkeypatch):
        monkeypatch.delenv("CURIO_DEFAULT_SOCRATA_APP_TOKEN", raising=False)
        user, _ = user_and_token
        assert credentials.token_for_slot(user, "socrata.app-token") is None

    def test_the_deployment_token_is_inherited(self, app, db, user_and_token, monkeypatch):
        monkeypatch.setenv("CURIO_DEFAULT_SOCRATA_APP_TOKEN", "deployment-token")
        user, _ = user_and_token
        assert credentials.token_for_slot(user, "socrata.app-token") == "deployment-token"
        assert credentials.has_token(user, "socrata.app-token") is True

    def test_a_users_own_token_wins(self, app, db, user_and_token, monkeypatch):
        monkeypatch.setenv("CURIO_DEFAULT_SOCRATA_APP_TOKEN", "deployment-token")
        user, _ = user_and_token
        user.socrata_app_token = SECRET
        db.session.commit()
        assert credentials.token_for_slot(user, "socrata.app-token") == SECRET

    def test_own_token_never_reports_the_deployments(self, app, db, user_and_token, monkeypatch):
        """The settings screen asks a different question - did YOU save one -
        and must not answer it with the operator's value."""
        monkeypatch.setenv("CURIO_DEFAULT_SOCRATA_APP_TOKEN", "deployment-token")
        user, _ = user_and_token
        assert credentials.own_token(user, "socrata.app-token") is None

    def test_the_me_payload_still_reports_only_your_own(self, client, auth, monkeypatch):
        monkeypatch.setenv("CURIO_DEFAULT_SOCRATA_APP_TOKEN", "deployment-token")
        body = client.get("/api/auth/me", headers=auth).get_json()
        assert body["has_socrata_app_token"] is False

    def test_it_is_read_at_call_time_not_import(self, app, db, user_and_token, monkeypatch):
        user, _ = user_and_token
        monkeypatch.delenv("CURIO_DEFAULT_SOCRATA_APP_TOKEN", raising=False)
        assert credentials.token_for_slot(user, "socrata.app-token") is None
        monkeypatch.setenv("CURIO_DEFAULT_SOCRATA_APP_TOKEN", "set-later")
        assert credentials.token_for_slot(user, "socrata.app-token") == "set-later"

    def test_a_required_token_source_is_satisfied_by_the_deployments(
        self, app, db, user_and_token, discovery_dir, monkeypatch
    ):
        """The gate asks "will a token be sent", not "did the user save one" -
        otherwise an operator-configured deployment would still refuse."""
        from utk_curio.backend.app.discovery.application.browse import DiscoveryBrowse
        from utk_curio.backend.app.discovery.domain.resource import SearchQuery

        monkeypatch.setenv("CURIO_DEFAULT_SOCRATA_APP_TOKEN", "deployment-token")
        user, _ = user_and_token
        write_source(discovery_dir, "source.a.gated@1", a_manifest(
            id="source.a.gated", name="Gated Portal",
            provider={"type": "socrata", "baseUrl": "https://portal.example"},
            auth={"mode": "required-token", "secretId": "socrata.app-token",
                  "headerName": "X-App-Token", "helpUrl": "https://help.example"},
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


@pytest.mark.parametrize("slot", sorted(credentials.SLOTS))
class TestEverySlotIsAnAccountSetting:
    """Each slot API Settings lists is a field PATCH /api/auth/me takes, saved
    on the account, reported as a boolean, and refused out loud for a guest."""

    def test_it_saves_and_reports_only_a_boolean(self, client, auth, slot):
        column = credentials.SLOT_COLUMNS[slot]
        res = client.patch("/api/auth/me", headers=auth, json={column: SECRET})
        assert res.status_code == 200, res.get_data(as_text=True)
        body = res.get_json()
        assert body[f"has_{column}"] is True
        assert SECRET not in json.dumps(body)
        res = client.patch("/api/auth/me", headers=auth, json={column: ""})
        assert res.get_json()[f"has_{column}"] is False

    def test_a_guest_is_refused_out_loud(self, app, db, client, slot):
        from utk_curio.backend.app.users.models import User, UserSession

        column = credentials.SLOT_COLUMNS[slot]
        guest = User(username="guest1", name="Guest", email="g@test.com", is_guest=True)
        db.session.add(guest)
        db.session.flush()
        db.session.add(UserSession(user_id=guest.id, token="guest-token"))
        db.session.commit()
        res = client.patch(
            "/api/auth/me",
            headers={"Authorization": "Bearer guest-token"},
            json={column: SECRET},
        )
        assert res.status_code == 403
        assert getattr(db.session.get(User, guest.id), column) is None


class TestTheKeysApiSettingsLists:
    """``GET /api/discovery/keys``: one row per slot, booleans only."""

    def _rows(self, client, auth):
        res = client.get("/api/discovery/keys", headers=auth)
        assert res.status_code == 200, res.get_data(as_text=True)
        return {row["slot"]: row for row in res.get_json()["keys"]}

    def test_every_slot_is_listed_and_its_field_is_the_column_patch_takes(self, client, auth, shipped_root):
        rows = self._rows(client, auth)
        assert set(rows) == set(credentials.SLOTS)
        for slot, row in rows.items():
            assert row["field"] == credentials.SLOT_COLUMNS[slot]
            assert row["label"]

    def test_presence_is_this_accounts_own_and_a_boolean(self, client, auth, shipped_root, monkeypatch):
        monkeypatch.delenv("CURIO_DEFAULT_SOCRATA_APP_TOKEN", raising=False)
        assert self._rows(client, auth)["socrata.app-token"]["present"] is False
        client.patch("/api/auth/me", headers=auth, json={"socrata_app_token": SECRET})
        row = self._rows(client, auth)["socrata.app-token"]
        assert row["present"] is True and row["inherited"] is False

    def test_a_deployment_key_is_reported_as_inherited_not_as_present(self, client, auth, shipped_root, monkeypatch):
        monkeypatch.setenv("CURIO_DEFAULT_SOCRATA_APP_TOKEN", "deployment-token")
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
        client.patch("/api/auth/me", headers=auth, json={"socrata_app_token": SECRET, "huggingface_token": SECRET})
        body = client.get("/api/discovery/keys", headers=auth).get_data(as_text=True)
        assert SECRET not in body

    def test_it_needs_a_signed_in_caller(self, client, shipped_root):
        assert client.get("/api/discovery/keys").status_code == 401
