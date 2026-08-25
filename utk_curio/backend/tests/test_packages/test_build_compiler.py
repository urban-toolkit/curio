"""Tests for :mod:`utk_curio.backend.app.packages.build_compiler` (dev/89 commit 5):
pinned-toolchain resolution, the runtime-externals contract, offline
node_modules materialization from the verified cache (with tar-safety
refusals), deterministic bundling, and honest failure modes.

The "esbuild" here is a deterministic fake: it inlines each imported source's
CONTENT (in entry order), then records its alias names and materialized
modules — enough to prove ordering, aliasing, materialization, and
byte-reproducibility without a real Node toolchain on the test host.
"""

from __future__ import annotations

import io
import tarfile

import pytest

from utk_curio.backend.app.packages.build_compiler import (
    CompileError,
    CompilerToolchain,
    compile_behavior_bundle,
    materialize_node_modules,
    toolchain_from_env,
)
from utk_curio.backend.app.packages.build_models import parse_build_request
from utk_curio.backend.app.packages.build_workspace import (
    create_workspace,
    destroy_workspace,
    populate_inputs,
)

_FAKE_ESBUILD = r'''#!/usr/bin/env python3
import os, re, sys

argv = sys.argv[1:]
if "--version" in argv:
    print("0.99.9-test")
    raise SystemExit(0)

entry = argv[0]
outfile = next(a.split("=", 1)[1] for a in argv if a.startswith("--outfile="))
aliases = sorted(a.split(":", 1)[1].split("=", 1)[0] for a in argv if a.startswith("--alias:"))

sources = []
for line in open(entry, encoding="utf-8"):
    m = re.search(r'import "(.+)";', line)
    if m:
        sources.append(open(m.group(1), encoding="utf-8").read())

if any("//FAIL" in s for s in sources):
    sys.stderr.write("fake-esbuild: syntax error in behavior source\n")
    raise SystemExit(2)

modules = []
if os.path.isdir("node_modules"):
    for top in sorted(os.listdir("node_modules")):
        if top.startswith("@"):
            for child in sorted(os.listdir(os.path.join("node_modules", top))):
                modules.append(f"{top}/{child}")
        else:
            modules.append(top)

os.makedirs(os.path.dirname(outfile), exist_ok=True)
with open(outfile, "w", encoding="utf-8") as fh:
    fh.write("FAKEBUNDLE format=iife target=es2020\n")
    for name in aliases:
        fh.write(f"alias:{name}\n")
    for name in modules:
        fh.write(f"module:{name}\n")
    fh.write("".join(sources))

if any("//EXTRA" in s for s in sources):
    with open(os.path.join(os.path.dirname(outfile), "stray.txt"), "w") as fh:
        fh.write("stray")
'''


@pytest.fixture()
def toolchain(tmp_path, monkeypatch):
    tool = tmp_path / "fake-esbuild"
    tool.write_text(_FAKE_ESBUILD, encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("CURIO_BUILD_ESBUILD", str(tool))
    resolved = toolchain_from_env()
    assert resolved is not None
    return resolved


def _request(sources: dict[str, str], entries: list[str]):
    return parse_build_request({
        "mode": "create",
        "target": "ai.test.demo@1",
        "manifest": {"id": "ai.test.demo", "compatibility": {"major": 1},
                     "templates": [{"id": "note-kind"}]},
        "files": {path: {"text": body} for path, body in sources.items()},
        "behaviorEntries": entries,
    })


def _compile(request, js_lock=None, *, toolchain, populate=True):
    ws = create_workspace("test")
    try:
        if populate:
            populate_inputs(ws, request.files)
        for name, entry in (js_lock or {}).items():
            if "cached" in entry:
                target = ws.cache_dir / entry["cached"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(entry.pop("_tgz"))
        return compile_behavior_bundle(ws, request, js_lock or {}, toolchain=toolchain)
    finally:
        destroy_workspace(ws)


def _tgz(files: dict[str, bytes], **member_kwargs) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            for key, value in member_kwargs.items():
                setattr(info, key, value)
            tf.addfile(info, io.BytesIO(body))
    return buf.getvalue()


class TestToolchain:
    def test_unconfigured_is_none(self, monkeypatch):
        monkeypatch.delenv("CURIO_BUILD_ESBUILD", raising=False)
        assert toolchain_from_env() is None

    def test_probe_records_version(self, toolchain):
        assert toolchain.version == "esbuild/0.99.9-test"

    def test_unrunnable_binary_is_none(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURIO_BUILD_ESBUILD", str(tmp_path / "missing"))
        assert toolchain_from_env() is None

    def test_no_toolchain_fails_honestly(self):
        request = _request({"sources/a.tsx": "export const a = 1\n"}, ["sources/a.tsx"])
        ws = create_workspace("t")
        try:
            populate_inputs(ws, request.files)
            result = compile_behavior_bundle(ws, request, {}, toolchain=None)
        finally:
            destroy_workspace(ws)
        assert result.status == "failed"
        assert "not configured" in result.log_tail or "no pinned compiler" in result.log_tail
        assert "ambient Node installation is never used" in result.log_tail


class TestCompile:
    def test_happy_bundle_in_declared_entry_order(self, toolchain):
        request = _request(
            {"sources/b.tsx": "//SECOND\n", "sources/a.tsx": "//FIRST\n"},
            ["sources/a.tsx", "sources/b.tsx"],
        )
        result = _compile(request, toolchain=toolchain)
        assert result.status == "ok"
        text = result.bundle.decode()
        assert text.index("//FIRST") < text.index("//SECOND")
        assert result.toolchain_version == "esbuild/0.99.9-test"

    def test_externals_aliased_to_host_shims(self, toolchain):
        request = _request({"sources/a.tsx": "//A\n"}, ["sources/a.tsx"])
        result = _compile(request, toolchain=toolchain)
        text = result.bundle.decode()
        for name in ("react", "react-dom", "reactflow", "@curio/package-runtime"):
            assert f"alias:{name}" in text

    def test_deterministic_across_workspaces(self, toolchain):
        def _once():
            request = _request(
                {"sources/a.tsx": "//A\n", "sources/b.tsx": "//B\n"},
                ["sources/a.tsx", "sources/b.tsx"],
            )
            lock = {"marked": {"cached": "js/marked/12.0.0.tgz",
                               "_tgz": _tgz({"package/index.js": b"marked-src"})}}
            return _compile(request, lock, toolchain=toolchain).bundle

        assert _once() == _once()

    def test_node_modules_materialized_from_verified_cache(self, toolchain):
        request = _request({"sources/a.tsx": "//A\n"}, ["sources/a.tsx"])
        lock = {
            "marked": {"cached": "js/marked/12.0.0.tgz",
                       "_tgz": _tgz({"package/index.js": b"marked-src"})},
            "@scope/tiny": {"cached": "js/@scope__tiny/1.0.0.tgz",
                            "_tgz": _tgz({"package/index.js": b"tiny-src"})},
        }
        result = _compile(request, lock, toolchain=toolchain)
        assert result.status == "ok"
        text = result.bundle.decode()
        assert "module:marked" in text
        assert "module:@scope/tiny" in text

    def test_compiler_failure_is_data(self, toolchain):
        request = _request({"sources/a.tsx": "//FAIL\n"}, ["sources/a.tsx"])
        result = _compile(request, toolchain=toolchain)
        assert result.status == "failed" and result.bundle is None
        assert "syntax error" in result.log_tail

    def test_unexpected_outputs_refused(self, toolchain):
        request = _request({"sources/a.tsx": "//EXTRA\n"}, ["sources/a.tsx"])
        result = _compile(request, toolchain=toolchain)
        assert result.status == "failed"
        assert "unexpected outputs" in result.log_tail

    def test_no_entries_is_misuse(self, toolchain):
        request = _request({"sources/a.tsx": "//A\n"}, [])
        ws = create_workspace("t")
        try:
            with pytest.raises(CompileError, match="no behavior entries"):
                compile_behavior_bundle(ws, request, {}, toolchain=toolchain)
        finally:
            destroy_workspace(ws)


class TestMaterializationSafety:
    def _workspace_with_cache(self, name: str, tgz: bytes, cached: str):
        ws = create_workspace("t")
        target = ws.cache_dir / cached
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(tgz)
        return ws, {name: {"cached": cached}}

    def test_runtime_external_in_lock_refused(self):
        ws = create_workspace("t")
        try:
            with pytest.raises(CompileError, match="runtime external"):
                materialize_node_modules(ws, {"react": {"cached": "js/react/18.tgz"}})
        finally:
            destroy_workspace(ws)

    def test_lock_without_cached_tarball_refused(self):
        ws = create_workspace("t")
        try:
            with pytest.raises(CompileError, match="no verified cached tarball"):
                materialize_node_modules(ws, {"marked": {"version": "12.0.0"}})
        finally:
            destroy_workspace(ws)

    def test_missing_cache_file_refused(self):
        ws = create_workspace("t")
        try:
            with pytest.raises(CompileError, match="missing"):
                materialize_node_modules(ws, {"marked": {"cached": "js/marked/x.tgz"}})
        finally:
            destroy_workspace(ws)

    def test_traversal_member_refused(self):
        ws, lock = self._workspace_with_cache(
            "evil", _tgz({"package/../../evil.js": b"x"}), "js/evil/1.tgz")
        try:
            with pytest.raises(CompileError, match="unsafe"):
                materialize_node_modules(ws, lock)
        finally:
            destroy_workspace(ws)

    def test_link_member_refused(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo("package/link.js")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
        ws, lock = self._workspace_with_cache("evil", buf.getvalue(), "js/evil/1.tgz")
        try:
            with pytest.raises(CompileError, match="not a regular"):
                materialize_node_modules(ws, lock)
        finally:
            destroy_workspace(ws)

    def test_oversized_member_refused(self):
        from utk_curio.backend.app.packages import build_compiler

        big = b"x" * (build_compiler._MAX_TAR_MEMBER_BYTES + 1)
        ws, lock = self._workspace_with_cache(
            "big", _tgz({"package/big.js": big}), "js/big/1.tgz")
        try:
            with pytest.raises(CompileError, match="size cap"):
                materialize_node_modules(ws, lock)
        finally:
            destroy_workspace(ws)
