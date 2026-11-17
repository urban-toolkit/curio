"""The vendored Autark schema is the file its record names.

``scripts/sync_autk_schema.py`` copies the JSON Schema autk-grammar publishes,
byte for byte, from its npm release or from the autk-grammar tarball the
frontend installs from ``vendor/autark/``, and records where it came from.
These tests check the copy against that record offline; the scheduled
``autk-schema`` workflow runs the script's ``--check``, which fetches a
recorded release again from npm and reads a recorded tarball in the checkout.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
import urllib.error
from pathlib import Path

import jsonschema
import pytest

from utk_curio.backend.app.agents.domain import contracts

REPO_ROOT = Path(__file__).resolve().parents[4]
RECORD = contracts.AUTK_SCHEMA_PATH.with_name("autk-grammar.v1.source.json")
FRONTEND = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows"


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
    assert sync.record_for(data, record["version"], record["source"], record.get("tarball")) == record
    assert sync.SCHEMA == contracts.AUTK_SCHEMA_PATH


def test_the_copy_is_the_schema_of_the_grammar_the_frontend_installs():
    """The record names the autk-grammar the frontend's lockfile installs: its
    release on npm, or the tarball in vendor/autark/, which then holds the copy
    byte for byte. Moving the grammar without its schema fails here."""
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    lockfile = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    installed = lockfile["packages"]["node_modules/@urban-toolkit/autk-grammar"]
    assert installed["version"] == record["version"]
    tarball = record.get("tarball")
    if tarball is None:
        assert record["source"] == "npm"
        assert installed["resolved"] == sync.tarball_url(record["version"])
        return
    assert record["source"] == sync.TARBALL_SOURCE
    assert installed["resolved"] == "file:" + (REPO_ROOT / tarball).relative_to(FRONTEND).as_posix()
    data, version = sync.read_tarball(REPO_ROOT / tarball)
    assert version == record["version"]
    assert data == contracts.AUTK_SCHEMA_PATH.read_bytes()


def test_the_schema_is_a_valid_draft_07_schema():
    schema = contracts.load_autk_schema()
    validator = jsonschema.validators.validator_for(schema, default=jsonschema.Draft7Validator)
    validator.check_schema(schema)
    assert validator is jsonschema.Draft7Validator


def test_the_version_in_the_id_is_the_version_in_the_file_name():
    schema = contracts.load_autk_schema()
    # https://autarkjs.org/schema/autk-grammar/v1.json <-> autk-grammar.v1.json
    assert "/".join(schema["$id"].rsplit("/", 2)[-2:]) == contracts.AUTK_SCHEMA_PATH.name.replace(".", "/", 1)


def _pack(path: Path, schema: bytes, version: str = "4.5.0-curio.1",
          name: str = "@urban-toolkit/autk-grammar") -> Path:
    """A packed autk-grammar at *path*, as ``npm pack`` writes one: its
    package.json and its schema under ``package/``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.dumps({"name": name, "version": version}).encode("utf-8")
    with tarfile.open(path, "w:gz") as tar:
        for member, data in (("package/package.json", manifest), ("package/build/autk-grammar-schema.json", schema)):
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def _never_npm(version):
    raise AssertionError(f"npm was asked for {version}")


class TestTheScript:
    @pytest.fixture
    def in_tmp(self, tmp_path, monkeypatch):
        """The script writing its copy and record in *tmp_path*, its repository."""
        monkeypatch.setattr(sync, "SCHEMA", tmp_path / "out" / "autk-grammar.v1.json")
        monkeypatch.setattr(sync, "RECORD", tmp_path / "out" / "autk-grammar.v1.source.json")
        monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
        return tmp_path

    @pytest.fixture
    def npm_copy(self, in_tmp):
        """The vendored schema with a record that names a release on npm."""
        data = contracts.AUTK_SCHEMA_PATH.read_bytes()
        sync.SCHEMA.parent.mkdir(parents=True)
        sync.SCHEMA.write_bytes(data)
        sync.RECORD.write_text(json.dumps(sync.record_for(data, "9.9.9", "npm")), encoding="utf-8")
        return data

    def test_check_passes_when_the_release_matches(self, npm_copy, monkeypatch, capsys):
        asked = []
        monkeypatch.setattr(sync, "fetch_release", lambda version: asked.append(version) or npm_copy)
        assert sync.main(["--check"]) == 0
        assert asked == ["9.9.9"]
        assert "matches @urban-toolkit/autk-grammar@9.9.9 on npm" in capsys.readouterr().out

    def test_check_fails_and_names_the_fix_when_it_differs(self, npm_copy, monkeypatch, capsys):
        monkeypatch.setattr(sync, "fetch_release", lambda version: b"{}")
        assert sync.main(["--check"]) == 1
        assert "sync_autk_schema.py --version 9.9.9" in capsys.readouterr().out

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

    def test_a_tarball_is_vendored_with_a_record_that_names_it(self, in_tmp, monkeypatch):
        schema = b'{"$id": "https://example.test/v1.json"}'
        tarball = _pack(in_tmp / "vendor" / "autark" / "grammar.tgz", schema)
        monkeypatch.setattr(sync, "fetch_release", _never_npm)
        assert sync.main(["--tarball", str(tarball)]) == 0
        assert sync.SCHEMA.read_bytes() == schema
        assert json.loads(sync.RECORD.read_text(encoding="utf-8")) == {
            "package": "@urban-toolkit/autk-grammar",
            "version": "4.5.0-curio.1",
            "source": "vendored tarball",
            "tarball": "vendor/autark/grammar.tgz",
            "id": "https://example.test/v1.json",
            "sha256": hashlib.sha256(schema).hexdigest(),
        }

    def test_check_compares_with_the_recorded_tarball_and_never_asks_npm(self, in_tmp, monkeypatch, capsys):
        tarball = _pack(in_tmp / "vendor" / "autark" / "grammar.tgz", b'{"$id": "https://example.test/v1.json"}')
        assert sync.main(["--tarball", str(tarball)]) == 0
        monkeypatch.setattr(sync, "fetch_release", _never_npm)
        assert sync.main(["--check"]) == 0
        assert "matches the vendored tarball vendor/autark/grammar.tgz" in capsys.readouterr().out

    def test_check_fails_and_names_the_fix_when_the_copy_differs_from_the_tarball(self, in_tmp, monkeypatch, capsys):
        tarball = _pack(in_tmp / "vendor" / "autark" / "grammar.tgz", b'{"$id": "https://example.test/v1.json"}')
        assert sync.main(["--tarball", str(tarball)]) == 0
        _pack(tarball, b'{"$id": "https://example.test/v1.json", "definitions": {}}')
        monkeypatch.setattr(sync, "fetch_release", _never_npm)
        assert sync.main(["--check"]) == 1
        out = capsys.readouterr().out
        assert "differs from the vendored tarball vendor/autark/grammar.tgz" in out
        assert "sync_autk_schema.py --tarball vendor/autark/grammar.tgz" in out

    def test_check_fails_when_the_tarball_is_another_version_than_its_record(self, in_tmp, monkeypatch, capsys):
        schema = b'{"$id": "https://example.test/v1.json"}'
        tarball = _pack(in_tmp / "vendor" / "autark" / "grammar.tgz", schema)
        assert sync.main(["--tarball", str(tarball)]) == 0
        _pack(tarball, schema, version="4.5.0-curio.2")
        monkeypatch.setattr(sync, "fetch_release", _never_npm)
        assert sync.main(["--check"]) == 1
        assert "@urban-toolkit/autk-grammar@4.5.0-curio.2, not the 4.5.0-curio.1 its record names" in (
            capsys.readouterr().out
        )

    def test_a_tarball_outside_the_repository_is_refused(self, in_tmp, tmp_path_factory):
        tarball = _pack(tmp_path_factory.mktemp("elsewhere") / "grammar.tgz", b"{}")
        with pytest.raises(SystemExit, match="is not in the repository"):
            sync.main(["--tarball", str(tarball)])
        assert not sync.RECORD.exists()

    def test_a_tarball_of_another_package_is_refused(self, in_tmp):
        tarball = _pack(in_tmp / "vendor" / "autark" / "map.tgz", b"{}", name="@urban-toolkit/autk-map")
        with pytest.raises(SystemExit, match="not @urban-toolkit/autk-grammar"):
            sync.main(["--tarball", str(tarball)])
        assert not sync.RECORD.exists()
