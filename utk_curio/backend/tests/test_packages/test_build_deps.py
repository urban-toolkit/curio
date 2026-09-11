"""Tests for :mod:`utk_curio.backend.app.packages.build_deps` (dev/89 commit 4):
scan+merge with explicit constraints winning, JS registry resolution with
lock/integrity/license/SBOM, verified-cache writes, policy gates, python
review without installation, and package-dep checks.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from utk_curio.backend.app.packages.build_deps import (
    DependencyPolicy,
    HttpRegistryFetcher,
    DependencyResolutionError,
    merge_declared_and_detected,
    resolve_dependencies,
    resolve_js_dependencies,
    review_package_dependencies,
    review_python_dependencies,
)
from utk_curio.backend.app.packages.build_models import parse_build_request


def _sri(data: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def _npm_tgz(name: str, version: str) -> bytes:
    """A real npm-style tarball (package/index.js) so downstream phases —
    the compiler's materialization — can extract what the resolver cached."""
    import io
    import tarfile

    body = f"{name}@{version}".encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("package/index.js")
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
    return buf.getvalue()


class FakeFetcher:
    """In-memory registry: {name: {version: {"deps": {...}, "license": str}}}."""

    def __init__(self, registry: dict):
        self.registry = registry
        self.tarballs: dict[str, bytes] = {}
        self.corrupt: set[str] = set()
        for name, versions in registry.items():
            for version in versions:
                self.tarballs[f"https://reg.test/{name}/-/{version}.tgz"] = (
                    _npm_tgz(name, version)
                )

    def fetch_metadata(self, name: str) -> dict:
        if name not in self.registry:
            raise RuntimeError(f"404 for {name}")
        versions = {}
        for version, meta in self.registry[name].items():
            url = f"https://reg.test/{name}/-/{version}.tgz"
            data = self.tarballs[url]
            integrity = meta.get("integrity", _sri(data))
            versions[version] = {
                "dependencies": meta.get("deps", {}),
                "license": meta.get("license", "MIT"),
                "dist": {"tarball": url, "integrity": integrity},
            }
        return {"versions": versions}

    def fetch_tarball(self, url: str, max_bytes: int) -> bytes:
        data = self.tarballs[url]
        if url in self.corrupt:
            return b"corrupted-" + data
        return data


def _request(files=None, dependencies=None):
    return parse_build_request({
        "mode": "create",
        "target": "ai.test.demo@1",
        "manifest": {"id": "ai.test.demo", "compatibility": {"major": 1},
                     "templates": [{"id": "demo-kind"}]},
        "files": files or {},
        "dependencies": dependencies or {},
    })


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


class TestMerge:
    def test_explicit_constraint_never_overwritten(self):
        request = _request(
            files={"sources/note.tsx": {"text": 'import {marked} from "marked"\n'}},
            dependencies={"js": {"marked": "12.0.0"}},
        )
        _, js, findings = merge_declared_and_detected(request)
        assert js["marked"] == {"constraint": "12.0.0", "source": "both"}
        assert "js-undeclared-import" not in _codes(findings)

    def test_detected_undeclared_defaults_to_star_with_warning(self):
        request = _request(
            files={"sources/calc.py": {"text": "import pandas\nreturn arg\n"}},
        )
        py, _, findings = merge_declared_and_detected(request)
        assert py["pandas"] == {"constraint": "*", "source": "detected"}
        assert _codes(findings) == ["python-undeclared-import"]
        assert findings[0].severity == "warn"

    def test_declared_unused_is_a_note(self):
        request = _request(dependencies={"python": {"numpy": ">=1.0"}})
        py, _, findings = merge_declared_and_detected(request)
        assert py["numpy"]["source"] == "declared"
        assert _codes(findings) == ["python-declared-unused"]
        assert findings[0].severity == "note"

    def test_binary_files_are_skipped(self):
        request = _request(files={"icons/i.svg": {"base64": "AAECAwQ="}})
        py, js, findings = merge_declared_and_detected(request)
        assert py == {} and js == {} and findings == []

    def test_detected_runtime_external_import_is_a_note_not_a_dependency(self):
        # dev/89 commit 9: behavior sources IMPORT react — that is the
        # externals contract, never a dependency (only an EXPLICIT react
        # declaration blocks, in resolve_js_dependencies).
        request = _request(
            files={"sources/note.tsx": {"text": 'import React from "react"\n'}},
        )
        _, js, findings = merge_declared_and_detected(request)
        assert "react" not in js
        assert _codes(findings) == ["js-runtime-external-import"]
        assert findings[0].severity == "note"


class TestJsResolution:
    def test_pinned_resolution_locks_and_caches(self, tmp_path):
        fetcher = FakeFetcher({"marked": {"12.0.0": {"license": "MIT"}}})
        direct, lock, findings = resolve_js_dependencies(
            {"marked": {"constraint": "12.0.0", "source": "declared"}},
            fetcher=fetcher, policy=DependencyPolicy(), cache_dir=tmp_path,
        )
        assert direct == [{"name": "marked", "constraint": "12.0.0",
                           "resolvedVersion": "12.0.0", "source": "declared"}]
        entry = lock["marked"]
        assert entry["version"] == "12.0.0"
        assert entry["license"] == "MIT"
        assert entry["integrity"].startswith("sha512-")
        assert entry["requestedBy"] == "<draft>"
        # The verified tarball landed in the cache for the offline compile.
        cached = tmp_path / entry["cached"]
        assert cached.read_bytes() == fetcher.tarballs["https://reg.test/marked/-/12.0.0.tgz"]
        assert not [f for f in findings if f.severity == "block"]

    def test_transitive_closure_with_attribution(self, tmp_path):
        fetcher = FakeFetcher({
            "chart-lib": {"2.0.0": {"deps": {"tiny-color": "^1.0.0"}}},
            "tiny-color": {"1.2.3": {}},
        })
        _, lock, findings = resolve_js_dependencies(
            {"chart-lib": {"constraint": "2.0.0", "source": "declared"}},
            fetcher=fetcher, policy=DependencyPolicy(), cache_dir=tmp_path,
        )
        assert set(lock) == {"chart-lib", "tiny-color"}
        assert lock["tiny-color"]["requestedBy"] == "chart-lib@2.0.0"
        assert not [f for f in findings if f.severity == "block"]

    def test_unpinned_resolves_highest_with_warning(self):
        fetcher = FakeFetcher({"marked": {"11.0.0": {}, "12.0.0": {}}})
        _, lock, findings = resolve_js_dependencies(
            {"marked": {"constraint": "*", "source": "detected"}},
            fetcher=fetcher, policy=DependencyPolicy(),
        )
        assert lock["marked"]["version"] == "12.0.0"
        unpinned = [f for f in findings if f.code == "js-unpinned"]
        assert len(unpinned) == 1 and unpinned[0].severity == "warn"

    def test_unpinned_blocks_under_hardened_policy(self):
        fetcher = FakeFetcher({"marked": {"12.0.0": {}}})
        _, _, findings = resolve_js_dependencies(
            {"marked": {"constraint": "*", "source": "detected"}},
            fetcher=fetcher, policy=DependencyPolicy(block_unpinned_js=True),
        )
        assert any(f.code == "js-unpinned" and f.severity == "block" for f in findings)

    def test_runtime_externals_refused_directly(self):
        _, lock, findings = resolve_js_dependencies(
            {"react": {"constraint": "18.0.0", "source": "declared"}},
            fetcher=FakeFetcher({}), policy=DependencyPolicy(),
        )
        assert lock == {}
        assert _codes(findings) == ["js-runtime-external"]
        assert findings[0].severity == "block"

    def test_transitive_runtime_external_noted_not_fetched(self, tmp_path):
        fetcher = FakeFetcher({
            "chart-lib": {"2.0.0": {"deps": {"react": "^18.0.0"}}},
        })
        _, lock, findings = resolve_js_dependencies(
            {"chart-lib": {"constraint": "2.0.0", "source": "declared"}},
            fetcher=fetcher, policy=DependencyPolicy(), cache_dir=tmp_path,
        )
        assert "react" not in lock
        assert any(f.code == "js-runtime-external-transitive" and f.severity == "note"
                   for f in findings)

    def test_no_registry_configured_blocks_honestly(self):
        _, lock, findings = resolve_js_dependencies(
            {"marked": {"constraint": "12.0.0", "source": "declared"}},
            fetcher=None, policy=DependencyPolicy(),
        )
        assert lock == {}
        assert _codes(findings) == ["js-registry-missing"]
        assert findings[0].severity == "block"

    def test_missing_integrity_blocks(self):
        fetcher = FakeFetcher({"shady": {"1.0.0": {"integrity": ""}}})
        _, lock, findings = resolve_js_dependencies(
            {"shady": {"constraint": "1.0.0", "source": "declared"}},
            fetcher=fetcher, policy=DependencyPolicy(),
        )
        assert lock == {} and any(f.code == "js-no-integrity" for f in findings)

    def test_integrity_mismatch_blocks(self, tmp_path):
        fetcher = FakeFetcher({"marked": {"12.0.0": {}}})
        fetcher.corrupt.add("https://reg.test/marked/-/12.0.0.tgz")
        _, lock, findings = resolve_js_dependencies(
            {"marked": {"constraint": "12.0.0", "source": "declared"}},
            fetcher=fetcher, policy=DependencyPolicy(), cache_dir=tmp_path,
        )
        assert lock == {}
        assert any(f.code == "js-integrity-mismatch" and f.severity == "block"
                   for f in findings)

    def test_denied_name_and_license_block(self):
        fetcher = FakeFetcher({"gplware": {"1.0.0": {"license": "GPL-3.0"}},
                               "banned": {"1.0.0": {}}})
        _, lock, findings = resolve_js_dependencies(
            {"gplware": {"constraint": "1.0.0", "source": "declared"},
             "banned": {"constraint": "1.0.0", "source": "declared"}},
            fetcher=fetcher,
            policy=DependencyPolicy(denied_names=frozenset({"banned"}),
                                    denied_licenses=frozenset({"gpl-3.0"})),
        )
        assert lock == {}
        assert set(_codes(findings)) == {"js-name-denied", "js-license-denied"}

    def test_unknown_package_is_a_retryable_block(self):
        _, lock, findings = resolve_js_dependencies(
            {"ghost-lib": {"constraint": "1.0.0", "source": "declared"}},
            fetcher=FakeFetcher({}), policy=DependencyPolicy(),
        )
        assert lock == {}
        assert any(f.code == "js-resolve-failed" and "retryable" in f.message
                   for f in findings)

    def test_no_satisfying_version_blocks(self):
        fetcher = FakeFetcher({"marked": {"11.0.0": {}}})
        _, _, findings = resolve_js_dependencies(
            {"marked": {"constraint": ">=12.0.0", "source": "declared"}},
            fetcher=fetcher, policy=DependencyPolicy(),
        )
        assert any(f.code == "js-no-version" for f in findings)


class TestHttpFetcherGuards:
    def test_requires_https(self):
        with pytest.raises(DependencyResolutionError, match="https"):
            HttpRegistryFetcher("http://reg.test")

    def test_refuses_non_registry_egress(self):
        fetcher = HttpRegistryFetcher("https://reg.test/npm")
        with pytest.raises(DependencyResolutionError, match="non-registry egress"):
            fetcher._open("https://evil.test/steal", 100)
        with pytest.raises(DependencyResolutionError, match="non-registry egress"):
            fetcher._open("https://reg.test.evil.test/npm/x", 100)


class TestPythonReview:
    def test_rows_and_unpinned_warning_without_installation(self, tmp_curio):
        rows, findings = review_python_dependencies(
            {"pandas": {"constraint": ">=2.0", "source": "declared"},
             "left-pad-py": {"constraint": "*", "source": "detected"}},
            "guest", is_satisfied=lambda name, spec: name == "pandas",
        )
        by_name = {r["name"]: r for r in rows}
        assert by_name["pandas"]["pinned"] is True
        assert by_name["pandas"]["versionSatisfied"] is True
        assert by_name["left-pad-py"]["versionSatisfied"] is False
        assert any(f.code == "py-unpinned" and f.severity == "warn" for f in findings)

    def test_the_row_does_not_claim_a_library_is_installed(self, tmp_curio):
        """It measured metadata, so metadata is all it may say.

        ``is_satisfied`` is satisfied by a wheel whose native extension cannot
        load - the everyday rasterio-against-a-different-GDAL case - and this
        row is read on the card a user approves from. Calling that "installed"
        is the same conflation the import probe exists to end.
        """
        rows, _ = review_python_dependencies(
            {"rasterio": {"constraint": ">=1.3", "source": "declared"}},
            "guest", is_satisfied=lambda *_: True,
        )
        assert "installed" not in rows[0]
        assert rows[0]["versionSatisfied"] is True

    def test_bad_constraint_blocks(self, tmp_curio):
        _, findings = review_python_dependencies(
            {"pandas": {"constraint": "latest-ish", "source": "declared"}},
            "guest", is_satisfied=lambda *_: False,
        )
        assert any(f.code == "py-bad-constraint" and f.severity == "block"
                   for f in findings)

    def test_conflict_with_installed_package_blocks(self, tmp_curio, install_packageage,
                                                    manifest_dict):
        install_packageage("guest",
                           manifest=manifest_dict(python_deps={"rasterio": "^1.3.0"}))
        _, findings = review_python_dependencies(
            {"rasterio": {"constraint": ">=2.0.0", "source": "declared"}},
            "guest", is_satisfied=lambda *_: False,
        )
        conflict = [f for f in findings if f.code == "py-conflict"]
        assert len(conflict) == 1 and conflict[0].severity == "block"
        assert "rasterio" in conflict[0].message

    def test_compatible_with_installed_package_passes(self, tmp_curio, install_packageage,
                                                      manifest_dict):
        install_packageage("guest",
                           manifest=manifest_dict(python_deps={"rasterio": "^1.3.0"}))
        _, findings = review_python_dependencies(
            {"rasterio": {"constraint": "^1.3.0", "source": "declared"}},
            "guest", is_satisfied=lambda *_: False,
        )
        assert not [f for f in findings if f.code == "py-conflict"]


class TestPackageDeps:
    def test_installed_in_range_passes(self, tmp_curio, install_packageage):
        install_packageage("guest")  # ai.test.demo@1 version 1.0.0
        rows, findings = review_package_dependencies({"ai.test.demo": "^1.0.0"}, "guest")
        assert rows[0]["status"] == "installed"
        assert rows[0]["installedVersion"] == "1.0.0"
        assert findings == []

    def test_missing_blocks(self, tmp_curio):
        rows, findings = review_package_dependencies({"ai.test.ghost": "^1.0.0"}, "guest")
        assert rows[0]["status"] == "missing"
        assert any(f.code == "package-dep-missing" and f.severity == "block"
                   for f in findings)

    def test_version_mismatch_blocks(self, tmp_curio, install_packageage):
        install_packageage("guest")  # version 1.0.0
        rows, findings = review_package_dependencies({"ai.test.demo": ">=2.0.0"}, "guest")
        assert rows[0]["status"] == "version-mismatch"
        assert any(f.code == "package-dep-version" for f in findings)


class TestOrchestrator:
    def test_full_report_payload(self, tmp_curio, tmp_path):
        request = _request(
            files={"sources/note.tsx": {"text": 'import {marked} from "marked"\n'}},
            dependencies={"js": {"marked": "12.0.0"},
                          "python": {"curio-test-fake-lib": "^1.0.0"}},
        )
        fetcher = FakeFetcher({"marked": {"12.0.0": {}}})
        report = resolve_dependencies("guest", request, fetcher=fetcher,
                                      policy=DependencyPolicy(), cache_dir=tmp_path)
        payload = report.to_payload()
        assert payload["js"]["lock"]["marked"]["version"] == "12.0.0"
        assert payload["python"][0]["name"] == "curio-test-fake-lib"
        assert payload["blocked"] is False
        json.dumps(payload)  # review-card safe

    def test_blocked_flag_rides_any_block_finding(self, tmp_curio):
        request = _request(dependencies={"js": {"marked": "12.0.0"}})
        report = resolve_dependencies("guest", request, fetcher=None,
                                      policy=DependencyPolicy())
        assert report.blocked is True
        assert any(f.code == "js-registry-missing" for f in report.findings)
