"""The vendored Autark schema is the release its record names.

``scripts/sync_autk_schema.py`` copies the JSON Schema autk-grammar publishes,
byte for byte, and records where it came from. These tests check the copy
against that record offline; the scheduled ``autk-schema`` workflow re-fetches
the release itself.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import urllib.error
from pathlib import Path

import jsonschema
import pytest

from utk_curio.backend.app.agents import contracts

REPO_ROOT = Path(__file__).resolve().parents[4]
RECORD = contracts.AUTK_SCHEMA_PATH.with_name("autk-grammar.v1.source.json")


def _load_script():
    path = REPO_ROOT / "scripts" / "sync_autk_schema.py"
    spec = importlib.util.spec_from_file_location("_scripts_sync_autk_schema", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


sync = _load_script()


def test_the_copy_is_the_file_the_record_names():
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    data = contracts.AUTK_SCHEMA_PATH.read_bytes()
    assert record["package"] == "@urban-toolkit/autk-grammar"
    assert hashlib.sha256(data).hexdigest() == record["sha256"]
    assert json.loads(data)["$id"] == record["id"]


def test_the_record_is_what_the_script_writes():
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    data = contracts.AUTK_SCHEMA_PATH.read_bytes()
    assert sync.record_for(data, record["version"], record["source"]) == record
    assert sync.SCHEMA == contracts.AUTK_SCHEMA_PATH


def test_the_schema_is_a_valid_draft_07_schema():
    schema = contracts.load_autk_schema()
    validator = jsonschema.validators.validator_for(schema, default=jsonschema.Draft7Validator)
    validator.check_schema(schema)
    assert validator is jsonschema.Draft7Validator


def test_the_version_in_the_id_is_the_version_in_the_file_name():
    schema = contracts.load_autk_schema()
    # https://autarkjs.org/schema/autk-grammar/v1.json <-> autk-grammar.v1.json
    assert "/".join(schema["$id"].rsplit("/", 2)[-2:]) == contracts.AUTK_SCHEMA_PATH.name.replace(".", "/", 1)


class TestTheScript:
    def test_check_passes_when_the_release_matches(self, monkeypatch, capsys):
        monkeypatch.setattr(sync, "fetch_release", lambda version: contracts.AUTK_SCHEMA_PATH.read_bytes())
        assert sync.main(["--check"]) == 0
        assert "matches" in capsys.readouterr().out

    def test_check_fails_and_names_the_fix_when_it_differs(self, monkeypatch, capsys):
        monkeypatch.setattr(sync, "fetch_release", lambda version: b"{}")
        assert sync.main(["--check"]) == 1
        assert "sync_autk_schema.py --version" in capsys.readouterr().out

    def test_a_local_build_is_vendored_with_its_record(self, tmp_path, monkeypatch):
        built = tmp_path / "autk-grammar-schema.json"
        built.write_bytes(b'{"$id": "https://example.test/v1.json"}')
        monkeypatch.setattr(sync, "SCHEMA", tmp_path / "out" / "autk-grammar.v1.json")
        monkeypatch.setattr(sync, "RECORD", tmp_path / "out" / "autk-grammar.v1.source.json")
        monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
        assert sync.main(["--from", str(built), "--version", "9.9.9"]) == 0
        assert sync.SCHEMA.read_bytes() == built.read_bytes()
        record = json.loads(sync.RECORD.read_text(encoding="utf-8"))
        assert record["version"] == "9.9.9" and record["source"] == "local build"
        assert record["id"] == "https://example.test/v1.json"

    def test_a_release_missing_from_npm_is_named(self, monkeypatch):
        def _not_found(url, timeout):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

        monkeypatch.setattr(sync.urllib.request, "urlopen", _not_found)
        with pytest.raises(SystemExit, match="autk-grammar@0.0.0 could not be fetched from npm: HTTP 404"):
            sync.fetch_release("0.0.0")
