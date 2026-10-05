"""Characterization tests for the four >150-line functions dev/143 B3 decomposes:
``run_build``, ``promote``, ``resolve_js_dependencies`` and ``invoke_handler``.

Each scenario runs the product code the way its own test module already does
(the fake esbuild / preview runner, the in-memory registry, a REAL sandbox
worker for the probes and invocations) and pins the OBSERVABLE outcome as a
golden: phase and journal sequences, result and reply shapes, finding codes,
ledger statuses. Values that vary per run (timestamps, durations, gzip'd
tarball digests, workspace paths) are reduced to their presence.

Recorded at 11b71328 (dev/143 commit 7, before B3 moved a line) and asserted
verbatim through every decomposition commit. To re-record after an INTENDED
change, run this file with ``CURIO_CHARACTERIZE=1`` and paste the printed
dictionaries below.
"""

from __future__ import annotations

import os
import pprint
import re

import pytest

from utk_curio.backend.app.packages.builder import jobs as build_jobs
from utk_curio.backend.app.packages.builder.compiler import toolchain_from_env
from utk_curio.backend.app.packages.builder.deps import (
    DependencyPolicy,
    resolve_js_dependencies,
)
from utk_curio.backend.app.packages.builder.extension import installed_package_digest
from utk_curio.backend.app.packages.builder.models import parse_build_request
from utk_curio.backend.app.packages.builder.pipeline import run_build
from utk_curio.backend.app.packages.builder.preview import runner_from_env
from utk_curio.backend.app.packages.builder.promotion import (
    PromotionError,
    load_journal,
    promote,
)
from utk_curio.backend.app.packages.domain import backend_contract as bc
from utk_curio.backend.app.packages.infrastructure import backend_runtime as rt
from utk_curio.backend.app.packages.infrastructure.pip_runner import PipInstallError
from utk_curio.backend.tests.test_packages.conftest import write_fake_tool
from utk_curio.backend.tests.test_packages.test_backend_build import _backend_request
from utk_curio.backend.tests.test_packages.test_backend_runtime import (
    FAST,
    PKG,
    USER,
    _install_pkg,
    _ledger_rows,
)
from utk_curio.backend.tests.test_packages.test_build_compiler import _FAKE_ESBUILD
from utk_curio.backend.tests.test_packages.test_build_deps import FakeFetcher
from utk_curio.backend.tests.test_packages.test_build_pipeline import (
    _behavior_request,
    _kind_manifest_for_extend,
)
from utk_curio.backend.tests.test_packages.test_build_preview import _FAKE_RUNNER
from utk_curio.backend.tests.test_packages.test_build_promotion import (
    _kind,
    _stage_backend_build,
    _stage_build,
)

RECORD = os.environ.get("CURIO_CHARACTERIZE") == "1"
_HEX = re.compile(r"\b[0-9a-f]{12,64}\b")


def _check(name: str, actual, golden) -> None:
    if RECORD:
        print(f"\n# --- {name}\n{name!r}: " + pprint.pformat(actual, width=88) + ",")
        return
    assert golden is not None, f"no golden recorded for {name}"
    assert actual == golden, f"{name} drifted:\n{pprint.pformat(actual)}"


def _scrub(text: str) -> str:
    return _HEX.sub("<hex>", text)


@pytest.fixture(autouse=True)
def _fresh_state():
    build_jobs.reset_registry()
    rt.reset_breakers()
    yield
    build_jobs.reset_registry()
    rt.reset_breakers()


# ── goldens (recorded 2026-09-29 at 11b71328, before B3) ────────────────────

GOLDEN: dict[str, dict | list | None] = {
    # build_behavior_pipeline
    'build_behavior_pipeline': {'backend': None,
 'dependencyKeys': ['filesIntegrity', 'manifest', 'sbom'],
 'diffKeys': ['baseDigest', 'files', 'mode', 'target', 'templates', 'warnings'],
 'final': 'ready',
 'findings': [],
 'hasArtifact': True,
 'phases': ['queued', 'resolving', 'compiling', 'previewing', 'packaging', 'ready'],
 'preview': 'ok',
 'sbomJsLock': ['marked'],
 'status': 'ready',
 'warnings': []},
    # build_backend_probe
    'build_backend_probe': {'entry': 'backend/handler.py',
 'final': 'ready',
 'findings': [],
 'handlers': [{'name': 'word-count', 'timeoutClass': 'quick'}],
 'phases': ['queued', 'resolving', 'probing', 'packaging', 'ready'],
 'probe': [{'handler': 'word-count', 'ok': True, 'workerStatus': 'ok'}],
 'probeKeys': ['durationMs', 'handler', 'limitsApplied', 'ok', 'workerStatus'],
 'status': 'ready'},
    # build_blocked_dependencies
    'build_blocked_dependencies': {'events': [('queued', 'build queued'),
            ('resolving', 'entered resolving'),
            ('failed',
             'resolving failed: dependency policy blocked the build: this deployment '
             'has no approved JS registry configured (CURIO_JS_REGISTRY_URL) — JS '
             'dependencies cannot be resolved; they are never fetched from an ambient '
             'source. Author the behavior SELF-CONTAINED (zero JS dependencies — write '
             'the rendering logic in the behavior source) and resubmit the draft')],
 'final': 'failed',
 'findings': ['block:js-registry-missing: this deployment has no approved JS registry '
              'configured (CURIO_JS_REGISTRY_URL) — JS dependencies cannot be '
              'resolved; they are never fetched from an ambient source. Author the '
              'behavior SELF-CONTAINED (zero JS dependencies — write the rendering '
              'logic in the behavior source) and resubmit the draft'],
 'hasArtifact': False,
 'status': 'failed',
 'warnings': ['dependency policy blocked the build: this deployment has no approved JS '
              'registry configured (CURIO_JS_REGISTRY_URL) — JS dependencies cannot be '
              'resolved; they are never fetched from an ambient source. Author the '
              'behavior SELF-CONTAINED (zero JS dependencies — write the rendering '
              'logic in the behavior source) and resubmit the draft']},
    # build_stale_extend
    'build_stale_extend': {'events': [('queued', 'build queued'),
            ('resolving', 'entered resolving'),
            ('failed',
             'resolving failed: stale base: request pins digest <hex> but the '
             'installed package hashes to <hex> — regenerate the draft against the '
             'current package')],
 'final': 'failed',
 'status': None},
    # promote_create_backend
    'promote_create_backend': {'backupHeld': False,
 'error': None,
 'hasEntryPin': True,
 'hasPriorDigest': False,
 'keys': ['artifactDigest',
          'backendEntryDigest',
          'backupHeld',
          'baseDigest',
          'contract',
          'error',
          'lockfileAdded',
          'projectId',
          'rollback',
          'status',
          'steps',
          'target'],
 'lockfileAdded': False,
 'rollback': None,
 'status': 'awaiting-activation',
 'steps': ['verified', 'installed']},
    # promote_extend_pip_rollback
    'promote_extend_pip_rollback': {'exception': {'message': 'python dependency install failed and the prior state was '
                          'restored: no wheel for left-pad-py',
               'status': 502},
 'journal': {'backupHeld': True,
             'error': 'pip install failed: no wheel for left-pad-py',
             'hasEntryPin': False,
             'hasPriorDigest': True,
             'keys': ['artifactDigest',
                      'backupHeld',
                      'baseDigest',
                      'contract',
                      'error',
                      'lockfileAdded',
                      'priorDigest',
                      'priorSeedRecord',
                      'projectId',
                      'rollback',
                      'status',
                      'steps',
                      'target'],
             'lockfileAdded': False,
             'rollback': {'reason': 'pip install failed: no wheel for left-pad-py',
                          'status': 'rolled-back'},
             'status': 'rolled-back',
             'steps': ['verified', 'backed-up', 'installed']},
 'restored': True},
    # promote_repeat_apply
    'promote_repeat_apply': {'journal': {'backupHeld': False,
             'error': None,
             'hasEntryPin': False,
             'hasPriorDigest': False,
             'keys': ['artifactDigest',
                      'backupHeld',
                      'baseDigest',
                      'contract',
                      'error',
                      'lockfileAdded',
                      'projectId',
                      'rollback',
                      'status',
                      'steps',
                      'target'],
             'lockfileAdded': False,
             'rollback': None,
             'status': 'awaiting-activation',
             'steps': ['verified', 'installed']},
 'same': True},
    # js_transitive_closure
    'js_transitive_closure': {'cachedFiles': ['js/chart-lib/2.0.0.tgz', 'js/tiny-color/1.2.3.tgz'],
 'direct': [{'constraint': '2.0.0',
             'name': 'chart-lib',
             'resolvedVersion': '2.0.0',
             'source': 'declared'}],
 'findings': [],
 'lock': {'chart-lib': {'bytes': True,
                        'cached': 'js/chart-lib/2.0.0.tgz',
                        'constraint': '2.0.0',
                        'integrity': 'sha512-<b64>',
                        'license': 'MIT',
                        'requestedBy': '<draft>',
                        'resolved': 'https://reg.test/chart-lib/-/2.0.0.tgz',
                        'version': '2.0.0'},
          'tiny-color': {'bytes': True,
                         'cached': 'js/tiny-color/1.2.3.tgz',
                         'constraint': '^1.0.0',
                         'integrity': 'sha512-<b64>',
                         'license': 'MIT',
                         'requestedBy': 'chart-lib@2.0.0',
                         'resolved': 'https://reg.test/tiny-color/-/1.2.3.tgz',
                         'version': '1.2.3'}}},
    # js_findings_ladder
    'js_findings_ladder': {'direct': [{'constraint': '1.0.0',
             'name': 'bad-dep',
             'resolvedVersion': '1.0.0',
             'source': 'declared'},
            {'constraint': '*',
             'name': 'marked',
             'resolvedVersion': '12.0.0',
             'source': 'detected'}],
 'findings': [('block',
               'js-runtime-external',
               "'react' is a Curio runtime external — it is provided by the host and "
               'externalized at compile time; bundling a second copy is refused'),
              ('block',
               'js-bad-name',
               "JS dependency name 'Bad Name!' (via <draft>) is not a valid registry "
               'package name'),
              ('block',
               'js-name-denied',
               "JS dependency 'denied-name' is denied by deployment policy"),
              ('block',
               'js-license-denied',
               "gpl-lib@1.0.0 license 'GPL-3.0' is denied by deployment policy"),
              ('warn',
               'js-unpinned',
               "JS dependency 'marked' is unpinned ('*') — resolved to 12.0.0; the "
               'lockfile pins it for this build'),
              ('block',
               'js-no-integrity',
               'registry entry no-sri@1.0.0 carries no usable SRI integrity — refused '
               '(never an unpinned ambient fallback)'),
              ('block',
               'js-resolve-failed',
               "could not fetch registry metadata for 'unknown-pkg' (via <draft>): 404 "
               'for unknown-pkg — retryable; never resolved from an ambient source'),
              ('block',
               'js-resolve-failed',
               "could not fetch registry metadata for 'left-pad' (via bad-dep@1.0.0): "
               '404 for left-pad — retryable; never resolved from an ambient source')],
 'lock': {'bad-dep': {'constraint': '1.0.0',
                      'integrity': 'sha512-<b64>',
                      'license': 'MIT',
                      'requestedBy': '<draft>',
                      'resolved': 'https://reg.test/bad-dep/-/1.0.0.tgz',
                      'version': '1.0.0'},
          'marked': {'constraint': '*',
                     'integrity': 'sha512-<b64>',
                     'license': 'MIT',
                     'requestedBy': '<draft>',
                     'resolved': 'https://reg.test/marked/-/12.0.0.tgz',
                     'version': '12.0.0'}}},
    # js_no_registry
    'js_no_registry': {'direct': [], 'findings': [('block', 'js-registry-missing')], 'lock': {}},
    # invoke_success
    'invoke_success': {'hasInvocationId': True,
 'ledger': [{'error': None,
             'handler': 'word-count',
             'hasResultBytes': True,
             'keys': ['dataDirBytes',
                      'durationMs',
                      'entryDigest',
                      'handler',
                      'invocationId',
                      'limitsApplied',
                      'payloadBytes',
                      'resultBytes',
                      'status',
                      'ts',
                      'workerStatus'],
             'payloadBytes': 17,
             'status': 'ok',
             'workerStatus': 'ok'}],
 'outKeys': ['durationMs',
             'entryDigest',
             'invocationId',
             'limitsApplied',
             'reply',
             'workerStatus'],
 'reply': {'contract': 'curio.pkgbackend.v1', 'ok': True, 'result': {'words': 3}},
 'workerStatus': 'ok'},
    # invoke_handler_error
    'invoke_handler_error': {'errorMentionsHandler': True,
 'kind': 'handler-error',
 'ledger': [{'error': None,
             'handler': 'boom',
             'hasResultBytes': True,
             'keys': ['dataDirBytes',
                      'durationMs',
                      'entryDigest',
                      'handler',
                      'invocationId',
                      'limitsApplied',
                      'payloadBytes',
                      'resultBytes',
                      'status',
                      'ts',
                      'workerStatus'],
             'payloadBytes': 2,
             'status': 'reply-handler-error',
             'workerStatus': 'ok'}],
 'ok': False},
    # invoke_refusals
    'invoke_refusals': {'digestDrift': (409,
                 'the backend entry changed on disk since install (digest mismatch) — '
                 'reinstall the package before invoking it'),
 'ledger': [],
 'unknownHandler': (404,
                    "handler 'nope' is not declared by 'curio.counter@1' (declared: "
                    "['word-count', 'env-probe', 'net', 'remember', 'boom', 'spin', "
                    "'unserializable'])"),
 'unknownPackage': (404, "package 'curio.missing@1' is not installed")},
}


# ── run_build ────────────────────────────────────────────────────────────────

class TestRunBuild:
    def test_behavior_pipeline(self, tmp_curio, manifest_dict, tmp_path, monkeypatch):
        monkeypatch.setenv("CURIO_BUILD_ESBUILD",
                           str(write_fake_tool(tmp_path, "fake-esbuild", _FAKE_ESBUILD)))
        monkeypatch.setenv("CURIO_BUILD_PREVIEW_RUNNER",
                           str(write_fake_tool(tmp_path, "fake-preview-runner", _FAKE_RUNNER)))
        job = run_build("guest", _behavior_request(manifest_dict),
                        fetcher=FakeFetcher({"marked": {"12.0.0": {}}}),
                        policy=DependencyPolicy(), toolchain=toolchain_from_env(),
                        preview_runner=runner_from_env())
        result = job.result
        actual = {
            "phases": [e["phase"] for e in job.events],
            "final": job.phase,
            "status": result.status,
            "preview": result.preview["status"],
            "sbomJsLock": sorted(result.dependencies["sbom"]["js"]["lock"]),
            "diffKeys": sorted(result.diff),
            "dependencyKeys": sorted(result.dependencies),
            "findings": list(result.policy_findings),
            "warnings": list(result.warnings),
            "backend": result.backend,
            "hasArtifact": bool(result.artifact_digest),
        }
        _check("build_behavior_pipeline", actual, GOLDEN.get("build_behavior_pipeline"))

    def test_backend_probe(self, tmp_curio, manifest_dict):
        job = run_build("guest", _backend_request(manifest_dict),
                        toolchain=None, preview_runner=None, probe_limits=FAST)
        backend = job.result.backend
        actual = {
            "phases": [e["phase"] for e in job.events],
            "final": job.phase,
            "status": job.result.status,
            "entry": backend["entry"],
            "handlers": backend["handlers"],
            "probe": [{k: row[k] for k in ("handler", "workerStatus", "ok")}
                      for row in backend["probe"]],
            "probeKeys": sorted(backend["probe"][0]),
            "findings": backend["findings"],
        }
        _check("build_backend_probe", actual, GOLDEN.get("build_backend_probe"))

    def test_blocked_dependencies(self, tmp_curio, manifest_dict):
        job = run_build("guest", _behavior_request(manifest_dict),
                        fetcher=None, policy=DependencyPolicy(),
                        toolchain=None, preview_runner=None)
        actual = {
            "events": [(e["phase"], _scrub(e["message"])) for e in job.events],
            "final": job.phase,
            "status": job.result.status,
            "findings": [_scrub(f) for f in job.result.policy_findings],
            "warnings": [_scrub(w) for w in job.result.warnings],
            "hasArtifact": bool(job.result.artifact_digest),
        }
        _check("build_blocked_dependencies", actual, GOLDEN.get("build_blocked_dependencies"))

    def test_stale_extend(self, tmp_curio, install_package, manifest_dict):
        base_manifest = _kind_manifest_for_extend(install_package, manifest_dict)
        request = parse_build_request({
            "mode": "extend", "target": "ai.test.demo@1",
            "baseDigest": "e" * 64, "manifest": dict(base_manifest, version="1.1.0"),
            "files": {},
        })
        job = run_build("guest", request, toolchain=None, preview_runner=None)
        actual = {
            "events": [(e["phase"], _scrub(e["message"])) for e in job.events],
            "final": job.phase,
            "status": job.result.status if job.result else None,
        }
        _check("build_stale_extend", actual, GOLDEN.get("build_stale_extend"))


# ── promote ──────────────────────────────────────────────────────────────────

def _journal_view(journal: dict) -> dict:
    return {
        "status": journal["status"],
        "steps": [s["step"] for s in journal["steps"]],
        "keys": sorted(journal),
        "backupHeld": journal["backupHeld"],
        "lockfileAdded": journal["lockfileAdded"],
        "error": _scrub(journal["error"]) if journal.get("error") else None,
        "rollback": journal.get("rollback"),
        "hasEntryPin": bool(journal.get("backendEntryDigest")),
        "hasPriorDigest": bool(journal.get("priorDigest")),
    }


class TestPromote:
    def test_create_with_post_apply_probe(self, tmp_curio, manifest_dict):
        digest = _stage_backend_build(
            manifest_dict, entry_src="def handle(payload):\n    return {'ok': True}\n")
        journal = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        assert load_journal("guest", digest) == journal
        _check("promote_create_backend", _journal_view(journal), GOLDEN.get("promote_create_backend"))

    def test_extend_pip_failure_rolls_back(self, tmp_curio, manifest_dict, monkeypatch,
                                           install_package):
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        install_package("guest", manifest=manifest_dict(kinds=[_kind()]),
                           sources={"demo-kind": {"Default.py": "def run():\n    return 1\n"}})
        base_digest = installed_package_digest("guest", "ai.test.demo@1")

        def _boom(deps):
            raise PipInstallError("no wheel for left-pad-py")

        monkeypatch.setattr(pip_runner, "install_python_deps", _boom)
        digest = _stage_build(manifest_dict, version="1.1.0", body="return 2\n",
                              python_deps={"left-pad-py": "^1.0.0"})
        with pytest.raises(PromotionError) as exc:
            promote("guest", target="ai.test.demo@1", artifact_digest=digest,
                    base_digest=base_digest)
        journal = load_journal("guest", digest)
        actual = {
            "exception": {"status": exc.value.status, "message": _scrub(str(exc.value))},
            "journal": _journal_view(journal),
            "restored": installed_package_digest("guest", "ai.test.demo@1") == base_digest,
        }
        _check("promote_extend_pip_rollback", actual, GOLDEN.get("promote_extend_pip_rollback"))

    def test_repeat_apply_returns_the_journal(self, tmp_curio, manifest_dict):
        digest = _stage_build(manifest_dict)
        first = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        second = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        actual = {"same": first == second, "journal": _journal_view(second)}
        _check("promote_repeat_apply", actual, GOLDEN.get("promote_repeat_apply"))


# ── resolve_js_dependencies ──────────────────────────────────────────────────

def _lock_view(lock: dict) -> dict:
    out = {}
    for name, entry in sorted(lock.items()):
        row = dict(entry)
        row["integrity"] = row["integrity"].split("-", 1)[0] + "-<b64>"
        if "bytes" in row:
            row["bytes"] = row["bytes"] > 0
        out[name] = row
    return out


class TestResolveJsDependencies:
    def test_transitive_closure_with_cache(self, tmp_path):
        fetcher = FakeFetcher({
            "chart-lib": {"2.0.0": {"deps": {"tiny-color": "^1.0.0"}, "license": "MIT"}},
            "tiny-color": {"1.2.3": {}, "1.0.0": {}},
        })
        direct, lock, findings = resolve_js_dependencies(
            {"chart-lib": {"constraint": "2.0.0", "source": "declared"}},
            fetcher=fetcher, policy=DependencyPolicy(), cache_dir=tmp_path,
        )
        actual = {
            "direct": direct,
            "lock": _lock_view(lock),
            "findings": [(f.severity, f.code) for f in findings],
            "cachedFiles": sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.tgz")),
        }
        _check("js_transitive_closure", actual, GOLDEN.get("js_transitive_closure"))

    def test_findings_ladder(self):
        fetcher = FakeFetcher({
            "marked": {"11.0.0": {}, "12.0.0": {}},
            "gpl-lib": {"1.0.0": {"license": "GPL-3.0"}},
            "no-sri": {"1.0.0": {"integrity": ""}},
            "bad-dep": {"1.0.0": {"deps": {"left-pad": "^1.0.0"}}},
        })
        direct, lock, findings = resolve_js_dependencies(
            {
                "react": {"constraint": "18.0.0", "source": "declared"},
                "marked": {"constraint": "*", "source": "detected"},
                "gpl-lib": {"constraint": "1.0.0", "source": "declared"},
                "no-sri": {"constraint": "1.0.0", "source": "declared"},
                "bad-dep": {"constraint": "1.0.0", "source": "declared"},
                "unknown-pkg": {"constraint": "^2.0.0", "source": "declared"},
                "denied-name": {"constraint": "1.0.0", "source": "declared"},
                "Bad Name!": {"constraint": "1.0.0", "source": "declared"},
            },
            fetcher=fetcher,
            policy=DependencyPolicy(denied_names=frozenset({"denied-name"}),
                                    denied_licenses=frozenset({"gpl-3.0"})),
            cache_dir=None,
        )
        actual = {
            "direct": direct,
            "lock": _lock_view(lock),
            "findings": [(f.severity, f.code, _scrub(f.message)) for f in findings],
        }
        _check("js_findings_ladder", actual, GOLDEN.get("js_findings_ladder"))

    def test_no_registry(self):
        direct, lock, findings = resolve_js_dependencies(
            {"marked": {"constraint": "12.0.0", "source": "declared"}},
            fetcher=None, policy=DependencyPolicy(),
        )
        actual = {"direct": direct, "lock": lock, "findings": [(f.severity, f.code) for f in findings]}
        _check("js_no_registry", actual, GOLDEN.get("js_no_registry"))


# ── invoke_handler ───────────────────────────────────────────────────────────

def _row_view(row: dict) -> dict:
    return {
        "keys": sorted(row),
        "status": row.get("status"),
        "handler": row.get("handler"),
        "payloadBytes": row.get("payloadBytes"),
        "hasResultBytes": row.get("resultBytes") is not None,
        "workerStatus": row.get("workerStatus"),
        "error": _scrub(row["error"]) if row.get("error") else None,
    }


class TestInvokeHandler:
    def test_success(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        out = rt.invoke_handler(USER, PKG, "word-count", {"text": "a b c"}, limits=FAST)
        actual = {
            "outKeys": sorted(out),
            "reply": out["reply"],
            "workerStatus": out["workerStatus"],
            "hasInvocationId": bool(out["invocationId"]),
            "ledger": [_row_view(r) for r in _ledger_rows(tmp_path)],
        }
        _check("invoke_success", actual, GOLDEN.get("invoke_success"))

    def test_handler_error(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        out = rt.invoke_handler(USER, PKG, "boom", {}, limits=FAST)
        actual = {
            "ok": out["reply"]["ok"],
            "kind": out["reply"]["kind"],
            "errorMentionsHandler": "the handler exploded" in out["reply"]["error"],
            "ledger": [_row_view(r) for r in _ledger_rows(tmp_path)],
        }
        _check("invoke_handler_error", actual, GOLDEN.get("invoke_handler_error"))

    def test_refusals(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        outcomes = {}
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "nope", {}, limits=FAST)
        outcomes["unknownHandler"] = (exc.value.status, _scrub(str(exc.value)))
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, "curio.missing@1", "word-count", {}, limits=FAST)
        outcomes["unknownPackage"] = (exc.value.status, _scrub(str(exc.value)))
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {}, expected_entry_digest="f" * 64, limits=FAST)
        outcomes["digestDrift"] = (exc.value.status, _scrub(str(exc.value)))
        outcomes["ledger"] = [_row_view(r) for r in _ledger_rows(tmp_path)]
        _check("invoke_refusals", outcomes, GOLDEN.get("invoke_refusals"))
