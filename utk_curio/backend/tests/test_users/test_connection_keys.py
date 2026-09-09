"""dev/116 (DEC-074) — per-user connection keys: the store never returns values
except through ``resolve``; the routes never return them at all."""

from __future__ import annotations

import json
import os
import stat
from types import SimpleNamespace

import pytest

from utk_curio.backend.app.users import connection_keys as ck
from utk_curio.backend.app.users.connection_keys import ConnectionKeyError, ConnectionKeyStore
from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME
from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401 - fixtures
    guest_user_and_token,
    tmp_curio,
    user_and_token,
)


class TestNormalisation:
    def test_names(self):
        assert ck.normalize_name("  Census ") == "census"
        assert ck.normalize_name("a" * 40) == "a" * 40
        for bad in ("", "-x", "a" * 41, "has space", "Ünicode", None):
            with pytest.raises(ConnectionKeyError):
                ck.normalize_name(bad)

    def test_hosts_are_bare_hostnames(self):
        assert ck.normalize_host("https://api.census.gov/data/2022?x=1") == "api.census.gov"
        assert ck.normalize_host("API.Census.GOV/data") == "api.census.gov"
        assert ck.normalize_host("user@host.example:8443") == "host.example"
        assert ck.normalize_host("localhost") == "localhost"
        for bad in ("", "not a host", "a..b", "-bad.example", "http://"):
            with pytest.raises(ConnectionKeyError):
                ck.normalize_host(bad)

    def test_delivery(self):
        assert ck.normalize_delivery(None) == "code"
        assert ck.normalize_delivery("") == "code"
        assert ck.normalize_delivery("query:key") == "query:key"
        assert ck.normalize_delivery(" header:X-Api-Key ") == "header:X-Api-Key"
        for bad in ("query:", "header:bad header", "cookie:x", "env"):
            with pytest.raises(ConnectionKeyError):
                ck.normalize_delivery(bad)

    def test_values(self):
        assert ck.normalize_value("  abc123  ") == "abc123"
        for bad in ("", "   ", "a\nb", 12, "x" * (ck.MAX_VALUE_CHARS + 1)):
            with pytest.raises(ConnectionKeyError):
                ck.normalize_value(bad)

    def test_suggest_name(self):
        assert ck.suggest_name("https://api.census.gov/data") == "census"
        assert ck.suggest_name("data.cityofchicago.org") == "cityofchicago"
        assert ck.suggest_name("localhost") == "localhost"
        assert ck.suggest_name("not a host") == ""

    def test_storage_key(self):
        assert ck.storage_key_for(SimpleNamespace(id=7, is_guest=False)) == "7"
        shared = SimpleNamespace(id=1, is_guest=True, username=CURIO_SHARED_GUEST_USERNAME)
        assert ck.storage_key_for(shared) == "guest"
        with pytest.raises(ConnectionKeyError) as exc:
            ck.storage_key_for(SimpleNamespace(id=2, is_guest=True, username="guest_abc"))
        assert exc.value.status == 403
        with pytest.raises(ConnectionKeyError) as exc:
            ck.storage_key_for(None)
        assert exc.value.status == 401


class TestStore:
    def test_round_trip_never_lists_values_and_resolve_is_the_only_reader(self, tmp_path):
        store = ConnectionKeyStore(base=tmp_path)
        ref, created = store.put("7", "census", "https://api.census.gov/data", "s3cr3tvalue", "query:key")
        assert created is True
        assert ref.name == "census" and ref.host == "api.census.gov" and ref.delivery == "query:key"
        assert ref.use_line == 'api_key = curio_secret("census")'
        listed = store.list("7")
        assert [r.name for r in listed] == ["census"]
        assert "value" not in json.dumps([r.to_payload() for r in listed])
        assert store.get("7", "census").host == "api.census.gov"
        assert store.get("7", "nope") is None
        assert store.resolve("7", ["census", "unknown", "BAD NAME"]) == {"census": "s3cr3tvalue"}
        assert store.get("7", "census").last_used_at is not None  # resolve touched it
        # Another user sees nothing.
        assert store.list("8") == [] and store.resolve("8", ["census"]) == {}

    def test_file_is_private_and_written_atomically(self, tmp_path):
        store = ConnectionKeyStore(base=tmp_path)
        store.put("7", "a", "x.org", "abcdefghij")
        path = store.path("7")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert not [p for p in path.parent.iterdir() if p.suffix == ".tmp"]
        doc = json.loads(path.read_text())
        assert doc["version"] == 1 and doc["keys"]["a"]["value"] == "abcdefghij"

    def test_rebind_needs_replace_and_overwrite_keeps_created_at(self, tmp_path):
        store = ConnectionKeyStore(base=tmp_path)
        ref, _ = store.put("7", "k", "one.org", "value-one-1")
        with pytest.raises(ConnectionKeyError) as exc:
            store.put("7", "k", "two.org", "value-two-2")
        assert exc.value.status == 409
        same, created = store.put("7", "k", "one.org", "value-one-3")
        assert created is False and same.created_at == ref.created_at
        moved, _ = store.put("7", "k", "two.org", "value-two-4", replace=True)
        assert moved.host == "two.org"
        assert store.resolve("7", ["k"]) == {"k": "value-two-4"}

    def test_delete_and_cap(self, tmp_path):
        store = ConnectionKeyStore(base=tmp_path)
        assert store.delete("7", "k") is False
        store.put("7", "k", "one.org", "value-one-1")
        assert store.delete("7", "k") is True and store.list("7") == []
        for i in range(ck.MAX_KEYS_PER_USER):
            store.put("9", f"k{i}", "one.org", "value-one-1")
        with pytest.raises(ConnectionKeyError):
            store.put("9", "overflow", "one.org", "value-one-1")
        store.put("9", "k0", "one.org", "value-one-2")  # overwriting is not a new key

    def test_corrupt_store_is_an_error_to_list_and_nothing_to_resolve(self, tmp_path):
        store = ConnectionKeyStore(base=tmp_path)
        store.put("7", "k", "one.org", "value-one-1")
        store.path("7").write_text("{not json")
        with pytest.raises(ConnectionKeyError) as exc:
            store.list("7")
        assert exc.value.status == 500
        assert store.resolve("7", ["k"]) == {}  # fail-open: the sandbox names the key
        store.path("7").write_text(json.dumps({"keys": []}))
        with pytest.raises(ConnectionKeyError):
            store.list("7")

    def test_invalid_user_key_is_refused(self, tmp_path):
        store = ConnectionKeyStore(base=tmp_path)
        with pytest.raises(ValueError):
            store.list("../alice")

    def test_default_store_lives_under_the_users_base(self, tmp_curio):
        store = ck.default_store()
        store.put("7", "k", "one.org", "value-one-1")
        assert store.path("7").is_relative_to(tmp_curio / ".curio")
        assert store.path("7").parts[-3:-1] == ("users", "7")


def _h(token):
    return {"Authorization": f"Bearer {token}"}


class TestRoutes:
    def test_requires_auth(self, client):
        assert client.get("/api/users/me/connection-keys").status_code == 401
        assert client.put("/api/users/me/connection-keys/census", json={}).status_code == 401

    def test_put_list_delete_never_carry_the_value(self, client, user_and_token, tmp_curio):
        _user, token = user_and_token
        r = client.put(
            "/api/users/me/connection-keys/Census",
            json={"host": "https://api.census.gov/data", "value": "s3cr3tvalue", "delivery": "query:key"},
            headers=_h(token),
        )
        assert r.status_code == 201, r.get_json()
        body = r.get_json()["key"]
        assert body["name"] == "census" and body["host"] == "api.census.gov"
        assert body["delivery"] == "query:key" and body["use"] == 'api_key = curio_secret("census")'
        assert "s3cr3tvalue" not in r.get_data(as_text=True)
        r = client.get("/api/users/me/connection-keys", headers=_h(token))
        assert r.status_code == 200
        assert [k["name"] for k in r.get_json()["keys"]] == ["census"]
        assert "s3cr3tvalue" not in r.get_data(as_text=True) and "value" not in r.get_json()["keys"][0]
        # Overwrite is 200; rebinding the host without replace is 409.
        r = client.put("/api/users/me/connection-keys/census",
                       json={"host": "api.census.gov", "value": "anothervalue"}, headers=_h(token))
        assert r.status_code == 200
        r = client.put("/api/users/me/connection-keys/census",
                       json={"host": "other.gov", "value": "anothervalue"}, headers=_h(token))
        assert r.status_code == 409 and "replace" in r.get_json()["error"]
        r = client.delete("/api/users/me/connection-keys/census", headers=_h(token))
        assert r.status_code == 200 and r.get_json() == {"deleted": "census"}
        assert client.delete("/api/users/me/connection-keys/census", headers=_h(token)).status_code == 404
        assert client.get("/api/users/me/connection-keys", headers=_h(token)).get_json() == {"keys": []}

    def test_validation_errors_are_400_with_the_rule_named(self, client, user_and_token, tmp_curio):
        _user, token = user_and_token
        r = client.put("/api/users/me/connection-keys/bad name",
                       json={"host": "x.org", "value": "abcdefgh"}, headers=_h(token))
        assert r.status_code == 400 and "key name" in r.get_json()["error"]
        r = client.put("/api/users/me/connection-keys/ok",
                       json={"host": "not a host", "value": "abcdefgh"}, headers=_h(token))
        assert r.status_code == 400 and "hostname" in r.get_json()["error"]
        r = client.put("/api/users/me/connection-keys/ok",
                       json={"host": "x.org", "value": ""}, headers=_h(token))
        assert r.status_code == 400 and "empty" in r.get_json()["error"]
        r = client.put("/api/users/me/connection-keys/ok",
                       json={"host": "x.org", "value": "abcdefgh", "delivery": "cookie:x"}, headers=_h(token))
        assert r.status_code == 400 and "delivery" in r.get_json()["error"]

    def test_temporary_guest_is_refused_and_suggest_name_works(self, client, guest_user_and_token, user_and_token, tmp_curio):
        _guest, gtoken = guest_user_and_token
        r = client.put("/api/users/me/connection-keys/k",
                       json={"host": "x.org", "value": "abcdefgh"}, headers=_h(gtoken))
        assert r.status_code == 403 and "Sign in" in r.get_json()["error"]
        assert client.get("/api/users/me/connection-keys", headers=_h(gtoken)).status_code == 403
        _user, token = user_and_token
        r = client.get("/api/users/me/connection-keys/suggest-name?host=https://api.census.gov/data",
                       headers=_h(token))
        assert r.get_json() == {"name": "census"}

    def test_shared_guest_uses_the_guest_store(self, client, db, tmp_curio):
        from utk_curio.backend.app.users.models import User, UserSession

        u = User(username=CURIO_SHARED_GUEST_USERNAME, name="Guest", is_guest=True)
        db.session.add(u)
        db.session.flush()
        db.session.add(UserSession(user_id=u.id, token="shared-token"))
        db.session.commit()
        r = client.put("/api/users/me/connection-keys/k",
                       json={"host": "x.org", "value": "abcdefgh"}, headers=_h("shared-token"))
        assert r.status_code == 201
        assert ck.default_store().path("guest").is_file()
