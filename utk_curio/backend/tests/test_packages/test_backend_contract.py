"""memo dev/91 commit 1 — the ``curio.pkgbackend.v1`` contract module, the
manifest's ``backend`` surface, and the installer's ``backend/`` bucket.

One contract module, one spelling (the dev/90 A15 lesson): these tests pin
the envelope shapes every party speaks — route, runtime, harness, probe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.packages import backend_contract as bc
from utk_curio.backend.app.packages.manifest import (
    ManifestError,
    load_packageage_manifest,
)


# ── envelope: requests ───────────────────────────────────────────────────────
class TestRequestEnvelope:
    def test_round_trip(self):
        raw = bc.build_request("word-count", {"text": "a b"})
        env = json.loads(raw)
        assert env == {
            "contract": bc.PKGBACKEND_CONTRACT_VERSION,
            "handler": "word-count",
            "payload": {"text": "a b"},
        }

    def test_bad_handler_name_refused(self):
        for name in ("", "UPPER", "1st", "has_underscore", "x" * 65):
            with pytest.raises(bc.BackendContractError, match="handler name"):
                bc.build_request(name, {})

    def test_oversized_payload_refused(self):
        big = {"blob": "x" * (bc.PAYLOAD_MAX_BYTES + 1)}
        with pytest.raises(bc.BackendContractError, match="request bound"):
            bc.build_request("h", big)

    def test_pathological_nesting_refused(self):
        deep: object = 1
        for _ in range(bc.PAYLOAD_MAX_DEPTH + 1):
            deep = [deep]
        with pytest.raises(bc.BackendContractError, match="nests deeper"):
            bc.build_request("h", deep)

    def test_unserializable_payload_refused(self):
        with pytest.raises(bc.BackendContractError, match="not JSON-serializable"):
            bc.build_request("h", {"x": object()})


# ── envelope: replies ────────────────────────────────────────────────────────
class TestReplyEnvelope:
    def _ok(self, result: object) -> bytes:
        return json.dumps({
            "contract": bc.PKGBACKEND_CONTRACT_VERSION, "ok": True, "result": result,
        }).encode()

    def test_success_round_trip(self):
        env = bc.parse_reply(self._ok({"n": 2}))
        assert env["ok"] is True and env["result"] == {"n": 2}

    def test_failure_round_trip(self):
        raw = json.dumps(bc.error_reply("handler-error", "boom")).encode()
        env = bc.parse_reply(raw)
        assert env["ok"] is False and env["kind"] == "handler-error"
        assert env["error"] == "boom"

    def test_raw_worker_bytes_never_pass(self):
        # Not JSON, wrong shape, wrong contract, missing fields — every
        # violation is a BackendContractError, never a pass-through.
        for raw in (
            b"Traceback (most recent call last): ...",
            b"[]",
            json.dumps({"contract": "curio.pkgbackend.v2", "ok": True, "result": 1}).encode(),
            json.dumps({"contract": bc.PKGBACKEND_CONTRACT_VERSION, "ok": True}).encode(),
            json.dumps({"contract": bc.PKGBACKEND_CONTRACT_VERSION, "ok": False,
                        "error": ""}).encode(),
            json.dumps({"contract": bc.PKGBACKEND_CONTRACT_VERSION, "ok": False,
                        "error": "x", "kind": "invented-kind"}).encode(),
        ):
            with pytest.raises(bc.BackendContractError):
                bc.parse_reply(raw)

    def test_oversized_reply_refused(self):
        raw = self._ok("x" * (bc.RESULT_MAX_BYTES + 1))
        with pytest.raises(bc.BackendContractError, match="result bound"):
            bc.parse_reply(raw)

    def test_error_text_is_truncated(self):
        env = bc.error_reply("contract-error", "e" * (bc.ERROR_TEXT_MAX_CHARS * 2))
        assert len(env["error"]) == bc.ERROR_TEXT_MAX_CHARS

    def test_probe_shape(self):
        assert bc.is_probe(bc.probe_payload())
        assert not bc.is_probe({"__probe__": "yes"})
        assert not bc.is_probe("__probe__")


# ── manifest: the backend surface ────────────────────────────────────────────
def _template(**extra: object) -> dict:
    t = {
        "id": "counter", "label": "Counter", "category": "computation",
        "engine": "python", "editor": "none", "hasCode": False,
        "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
    }
    t.update(extra)
    return t


def _write_pkg(base: Path, *, backend: object = None, permissions: list | None = None,
               templates: list | None = None) -> Path:
    root = base / "curio.counter@1"
    root.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "id": "curio.counter", "version": "1.0.0", "name": "Counter",
        "publisher": "t", "description": "d",
        "compatibility": {"major": 1},
        "permissions": permissions if permissions is not None else [],
        "templates": templates or [_template()],
    }
    if backend is not None:
        manifest["backend"] = backend
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


_GOOD_BACKEND = {
    "entry": "backend/handler.py",
    "handlers": [{"name": "word-count", "timeoutClass": "quick"}, {"name": "echo"}],
}


class TestManifestBackend:
    def test_parses_declaration(self, tmp_path: Path):
        d = _write_pkg(tmp_path, backend=_GOOD_BACKEND,
                       permissions=[bc.PERMISSION_SERVER_CODE])
        m = load_packageage_manifest(d)
        assert m.backend is not None
        assert m.backend.entry == "backend/handler.py"
        assert m.backend.handler_names == ["word-count", "echo"]
        assert m.backend.timeout_class_for("word-count") == "quick"
        assert m.backend.timeout_class_for("echo") == bc.DEFAULT_TIMEOUT_CLASS
        assert m.backend.timeout_class_for("ghost") is None

    def test_absent_backend_stays_none(self, tmp_path: Path):
        m = load_packageage_manifest(_write_pkg(tmp_path))
        assert m.backend is None

    def test_server_code_permission_required(self, tmp_path: Path):
        d = _write_pkg(tmp_path, backend=_GOOD_BACKEND, permissions=[])
        with pytest.raises(ManifestError, match="server-code"):
            load_packageage_manifest(d)

    @pytest.mark.parametrize("bad_entry", [
        "handler.py", "backend/", "backend/../escape.py", "backend/h.txt",
        "sources/h.py", "", "backend/./h.py",
    ])
    def test_bad_entry_refused_naming_the_grammar(self, tmp_path: Path, bad_entry: str):
        d = _write_pkg(
            tmp_path,
            backend={"entry": bad_entry, "handlers": [{"name": "h"}]},
            permissions=[bc.PERMISSION_SERVER_CODE],
        )
        with pytest.raises(ManifestError, match="backend"):
            load_packageage_manifest(d)

    def test_handler_validation(self, tmp_path: Path):
        for handlers, marker in [
            ([], "non-empty"),
            ([{"name": "Bad_Name"}], "name"),
            ([{"name": "h"}, {"name": "h"}], "twice"),
            ([{"name": "h", "timeoutClass": "forever"}], "timeoutClass"),
        ]:
            d = _write_pkg(
                tmp_path,
                backend={"entry": "backend/h.py", "handlers": handlers},
                permissions=[bc.PERMISSION_SERVER_CODE],
            )
            with pytest.raises(ManifestError, match=marker):
                load_packageage_manifest(d)

    def test_template_backend_handler_cross_checked(self, tmp_path: Path):
        # Names a declared handler → parses.
        d = _write_pkg(
            tmp_path, backend=_GOOD_BACKEND,
            permissions=[bc.PERMISSION_SERVER_CODE],
            templates=[_template(backendHandler="word-count")],
        )
        m = load_packageage_manifest(d)
        assert m.templates[0].backend_handler == "word-count"
        # Undeclared handler name → refused naming the declared set.
        d2 = _write_pkg(
            tmp_path, backend=_GOOD_BACKEND,
            permissions=[bc.PERMISSION_SERVER_CODE],
            templates=[_template(backendHandler="ghost")],
        )
        with pytest.raises(ManifestError, match="not declared"):
            load_packageage_manifest(d2)
        # backendHandler without a backend block → refused.
        d3 = _write_pkg(tmp_path, templates=[_template(backendHandler="word-count")])
        with pytest.raises(ManifestError, match="requires a top-level 'backend'"):
            load_packageage_manifest(d3)


# ── installer: the backend/ bucket ───────────────────────────────────────────
class TestInstallerBackendDir:
    def test_backend_is_an_allowed_top_dir(self):
        from utk_curio.backend.app.packages.installer import _ALLOWED_TOP_DIRS

        assert "backend" in _ALLOWED_TOP_DIRS


# ── schema: the canonical spec agrees with the parser ────────────────────────
class TestSchemaAgreement:
    def test_schema_declares_backend_and_backend_handler(self):
        schema_path = (
            Path(__file__).resolve().parents[4] / "docs" / "schemas" / "node-package.v4.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        backend = schema["properties"]["backend"]
        assert backend["required"] == ["entry", "handlers"]
        assert backend["properties"]["entry"]["pattern"] == "^backend/.+\\.py$"
        name_pattern = (
            backend["properties"]["handlers"]["items"]["properties"]["name"]["pattern"]
        )
        assert name_pattern == bc.HANDLER_NAME_RE.pattern
        tpl = schema["$defs"]["template"]["properties"]["backendHandler"]
        assert tpl["pattern"] == bc.HANDLER_NAME_RE.pattern
        classes = backend["properties"]["handlers"]["items"]["properties"]["timeoutClass"]
        assert tuple(classes["enum"]) == bc.TIMEOUT_CLASSES
