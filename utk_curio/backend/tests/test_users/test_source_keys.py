"""The owner-only file that holds an account's Data source keys, by secret id.

A source manifest declares the key it sends (``auth.secretId``), so the file is
keyed by that id: a key a new source declares needs no column and no
migration. Only one function returns a value; listing returns secret ids.

The module is imported inside each test, so this file collects on a checkout
that does not have it yet.
"""

from __future__ import annotations

import json
import logging
import stat
from types import SimpleNamespace

import pytest

from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME
from utk_curio.backend.tests._unit_fixtures import tmp_curio  # noqa: F401 - a fixture

SECRET = "s3cr3t-source-key-do-not-log"


def _store(tmp_path):
    from utk_curio.backend.app.users.source_keys import SourceKeyStore

    return SourceKeyStore(base=tmp_path)


def _mode(monkeypatch, deploy):
    from utk_curio.backend import config

    monkeypatch.setattr(config, "CURIO_NO_AUTH", not deploy)


class TestTheStore:
    def test_it_lists_secret_ids_and_only_value_reads_one(self, tmp_path):
        store = _store(tmp_path)
        store.update("7", {"acme.tiles-key": SECRET, "socrata.app-token": "tok"})
        assert store.saved("7") == ["acme.tiles-key", "socrata.app-token"]
        assert store.value("7", "acme.tiles-key") == SECRET
        assert store.value("7", "nothing.here") is None
        assert store.saved("8") == [] and store.value("8", "acme.tiles-key") is None

    def test_blank_clears_one_and_absent_keeps_the_others(self, tmp_path):
        store = _store(tmp_path)
        store.update("7", {"acme.tiles-key": SECRET, "socrata.app-token": "tok"})
        store.update("7", {"acme.tiles-key": ""})
        assert store.saved("7") == ["socrata.app-token"]
        assert store.value("7", "acme.tiles-key") is None
        assert store.value("7", "socrata.app-token") == "tok"

    def test_the_file_is_private_and_beside_the_accounts_other_key_files(self, tmp_path):
        from utk_curio.backend.app.users import connection_keys

        store = _store(tmp_path)
        store.update("7", {"acme.tiles-key": SECRET})
        path = store.path("7")
        assert path == tmp_path / "7" / "source-keys.json"
        assert path.parent == connection_keys.ConnectionKeyStore(base=tmp_path).path("7").parent
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert not [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")]
        assert json.loads(path.read_text(encoding="utf-8"))["keys"]["acme.tiles-key"]["value"] == SECRET

    def test_node_code_cannot_reach_one(self, tmp_path):
        """Node code reads connection keys by name (``curio_secret``); a source's
        key is in a file of its own, which that resolver never opens."""
        from utk_curio.backend.app.users import connection_keys, source_keys

        assert source_keys.STORE_FILENAME != connection_keys.STORE_FILENAME
        _store(tmp_path).update("7", {"census": SECRET})
        assert connection_keys.ConnectionKeyStore(base=tmp_path).resolve("7", ["census"]) == {}

    @pytest.mark.parametrize("value", ["tok\nX-Evil: 1", "tok\rmore", "   ", 7, None, ["tok"]])
    def test_a_value_is_one_line_of_text(self, tmp_path, value):
        from utk_curio.backend.app.users.source_keys import SourceKeyError

        store = _store(tmp_path)
        store.update("7", {"acme.tiles-key": "kept"})
        with pytest.raises(SourceKeyError) as exc:
            store.update("7", {"acme.tiles-key": value})
        assert exc.value.status == 400
        assert store.value("7", "acme.tiles-key") == "kept"

    def test_a_value_is_trimmed_and_bounded(self, tmp_path):
        from utk_curio.backend.app.users.source_keys import MAX_VALUE_CHARS, SourceKeyError

        store = _store(tmp_path)
        store.update("7", {"acme.tiles-key": "  tok  "})
        assert store.value("7", "acme.tiles-key") == "tok"
        store.update("7", {"acme.tiles-key": "x" * MAX_VALUE_CHARS})
        with pytest.raises(SourceKeyError):
            store.update("7", {"acme.tiles-key": "x" * (MAX_VALUE_CHARS + 1)})

    @pytest.mark.parametrize("changes", [["acme.tiles-key"], "acme.tiles-key", {"": "v"}, {7: "v"}, {"x" * 101: "v"}])
    def test_changes_map_secret_ids_to_values(self, tmp_path, changes):
        from utk_curio.backend.app.users.source_keys import SourceKeyError

        with pytest.raises(SourceKeyError) as exc:
            _store(tmp_path).update("7", changes)
        assert exc.value.status == 400

    def test_one_refused_value_saves_none_of_them(self, tmp_path):
        from utk_curio.backend.app.users.source_keys import SourceKeyError

        store = _store(tmp_path)
        store.update("7", {"acme.tiles-key": "kept"})
        with pytest.raises(SourceKeyError):
            store.update("7", {"socrata.app-token": "fine", "acme.tiles-key": "two\nlines"})
        assert store.saved("7") == ["acme.tiles-key"]
        assert store.value("7", "acme.tiles-key") == "kept"

    def test_an_account_holds_at_most_the_cap(self, tmp_path):
        from utk_curio.backend.app.users.source_keys import MAX_KEYS_PER_USER, SourceKeyError

        store = _store(tmp_path)
        store.update("7", {f"k{i}.key": "v" for i in range(MAX_KEYS_PER_USER)})
        with pytest.raises(SourceKeyError):
            store.update("7", {"one.more": "v"})
        store.update("7", {"k0.key": "replaced"})
        assert len(store.saved("7")) == MAX_KEYS_PER_USER
        assert store.value("7", "k0.key") == "replaced"

    def test_an_unreadable_file_lists_and_sends_nothing_and_is_never_overwritten(self, tmp_path, caplog):
        """Sign-in and the key list read it, so they must not fail on it; its
        contents are never logged; and a save does not replace what it cannot read."""
        from utk_curio.backend.app.users.source_keys import SourceKeyError

        store = _store(tmp_path)
        path = store.path("7")
        path.parent.mkdir(parents=True)
        path.write_text('{"version": 1, "keys": {"acme.tiles-key": {"value": "' + SECRET, encoding="utf-8")
        with caplog.at_level(logging.DEBUG):
            assert store.saved("7") == []
            assert store.value("7", "acme.tiles-key") is None
            with pytest.raises(SourceKeyError) as exc:
                store.update("7", {"socrata.app-token": "tok"})
        assert exc.value.status == 500
        assert SECRET not in caplog.text
        assert SECRET in path.read_text(encoding="utf-8")

    def test_saving_logs_nothing_of_the_value(self, tmp_path, caplog):
        with caplog.at_level(logging.DEBUG):
            store = _store(tmp_path)
            store.update("7", {"acme.tiles-key": SECRET})
            store.saved("7")
            store.value("7", "acme.tiles-key")
        assert SECRET not in caplog.text

    def test_a_user_key_that_names_no_account_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            _store(tmp_path).update("../other", {"acme.tiles-key": SECRET})


class TestWhoHoldsKeys:
    """An account by its id; the shared guest as ``guest``, but only without
    ``--deploy``. Under ``--deploy`` a guest is every visitor at once, so it
    holds none: nothing is listed or sent for it, and nothing is saved."""

    @pytest.mark.parametrize("deploy", [False, True], ids=["local", "deploy"])
    def test_the_storage_key(self, monkeypatch, deploy):
        from utk_curio.backend.app.users import source_keys

        _mode(monkeypatch, deploy)
        assert source_keys.storage_key_for(SimpleNamespace(id=7, is_guest=False, username="ada")) == "7"
        shared = SimpleNamespace(id=1, is_guest=True, username=CURIO_SHARED_GUEST_USERNAME)
        assert source_keys.storage_key_for(shared) == (None if deploy else "guest")
        assert source_keys.storage_key_for(SimpleNamespace(id=2, is_guest=True, username="guest_abc")) is None
        assert source_keys.storage_key_for(None) is None
        assert source_keys.storage_key_for(SimpleNamespace(is_guest=False, username="no id")) is None

    @pytest.mark.parametrize("deploy", [False, True], ids=["local", "deploy"])
    def test_the_shared_guests_keys_count_only_without_deploy(self, tmp_path, monkeypatch, deploy):
        from utk_curio.backend.app.users import source_keys

        monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
        monkeypatch.delenv("CURIO_STATE_DIR", raising=False)
        shared = SimpleNamespace(id=1, is_guest=True, username=CURIO_SHARED_GUEST_USERNAME)
        _mode(monkeypatch, False)
        source_keys.save_for(shared, {"acme.tiles-key": SECRET})
        _mode(monkeypatch, deploy)
        assert source_keys.saved_for(shared) == ([] if deploy else ["acme.tiles-key"])
        assert source_keys.value_for(shared, "acme.tiles-key") == (None if deploy else SECRET)
        if deploy:
            with pytest.raises(source_keys.SourceKeyError) as exc:
                source_keys.save_for(shared, {"acme.tiles-key": "new"})
            assert exc.value.status == 403
        # The file stays for the next run without --deploy.
        _mode(monkeypatch, False)
        assert source_keys.value_for(shared, "acme.tiles-key") == SECRET

    def test_the_default_store_lives_under_the_users_base(self, tmp_curio):
        from utk_curio.backend.app.common.user_storage import users_base
        from utk_curio.backend.app.users import source_keys

        assert source_keys.default_store().path("7") == users_base() / "7" / "source-keys.json"
