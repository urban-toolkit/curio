"""Controlled dependency resolution for package builds (memo dev/89 §3.4).

Three ecosystems, three postures, one SBOM:

* **JavaScript** — resolved in a dedicated FETCH phase against the
  operator-configured registry only (``CURIO_JS_REGISTRY_URL``): pinned
  versions, required SRI integrity, license metadata, size caps, and a
  generated lockfile. Verified tarballs land in the build workspace's
  ``cache/`` so the compile phase (dev/89 commit 5) runs offline from the
  verified cache. No registry configured + JS deps requested = a blocking
  finding, never a fallback to an ambient npm install.
* **Python** — resolved FOR REVIEW only: constraints validated through the
  project resolver's grammar and intersected against every installed
  package's declarations (conflicts block). Nothing is pip-installed here —
  actual installation stays with the reviewed package installer on Apply.
* **Package-to-package** — checked against the user's installed package
  store with the same range grammar the project resolver locks.

Import scanning (the factory's ``dependency_scanner``) runs over the draft's
sources and MERGES with the request's explicit constraints: an explicit
constraint is never overwritten by the scanner's ``"*"`` default — a
detected-but-undeclared import is added as ``"*"`` WITH a warning finding,
so the unpinned default is always surfaced, never silent (dev/89 §3.4).

Policy gates (dev/89 §3.4/§3.5): Curio runtime externals (React, ReactDOM,
ReactFlow) are refused as fetchable dependencies — they are host singletons
the compiler externalizes, and bundling a second copy is the exact failure
the memo forbids. Operator policy may additionally deny names and licenses.

Every outcome is a :class:`DependencyReport` — the SBOM the review card
shows before Apply. Findings carry ``block`` / ``warn`` / ``note`` severity;
any ``block`` marks the whole report blocked.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from utk_curio.backend.app.packages.build_models import PackageBuildRequest
from utk_curio.backend.app.packages.dependency_scanner import scan_imports_for_filename
from utk_curio.backend.app.packages.manifest import ManifestError, load_packageage_manifest
from utk_curio.backend.app.packages.resolver import (
    ResolverError,
    merge_python_deps,
    parse_range,
    parse_version,
)
from utk_curio.backend.app.packages.locks import package_seed_lock
from utk_curio.backend.app.packages.storage import list_user_packageages

log = logging.getLogger(__name__)

# Host singletons the compiler externalizes (docs/EXTENDING.md §5); fetching
# or bundling them would ship a second copy into the page. Always refused.
RUNTIME_EXTERNALS = frozenset({"react", "react-dom", "reactflow"})

# Resolution bounds.
MAX_JS_PACKAGES_TOTAL = 64  # direct + transitive
MAX_JS_DEPTH = 6
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_TARBALL_BYTES = 16 * 1024 * 1024
MAX_CACHE_TOTAL_BYTES = 64 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 20

_JS_NAME_RE = re.compile(r"^(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
_SRI_RE = re.compile(r"^(sha256|sha384|sha512)-([A-Za-z0-9+/=]+)$")

SEVERITIES = ("block", "warn", "note")


class DependencyResolutionError(ValueError):
    """Raised on misuse (bad arguments) — resolution FAILURES are findings."""


@dataclass(frozen=True)
class Finding:
    severity: str  # block | warn | note
    code: str
    message: str

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise DependencyResolutionError(f"unknown severity {self.severity!r}")

    def to_payload(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class DependencyReport:
    """The SBOM + review payload for one build (dev/89 §3.4)."""

    python: tuple[dict[str, Any], ...] = ()
    js_direct: tuple[dict[str, Any], ...] = ()
    js_lock: dict[str, dict[str, Any]] = field(default_factory=dict)
    packages: tuple[dict[str, Any], ...] = ()
    findings: tuple[Finding, ...] = ()

    @property
    def blocked(self) -> bool:
        return any(f.severity == "block" for f in self.findings)

    def to_payload(self) -> dict[str, Any]:
        return {
            "python": [dict(e) for e in self.python],
            "js": {
                "direct": [dict(e) for e in self.js_direct],
                "lock": {k: dict(v) for k, v in sorted(self.js_lock.items())},
            },
            "packages": [dict(e) for e in self.packages],
            "findings": [f.to_payload() for f in self.findings],
            "blocked": self.blocked,
        }


@dataclass(frozen=True)
class DependencyPolicy:
    """Operator policy for dependency resolution (deployment-owned)."""

    js_registry_url: str | None = None
    denied_names: frozenset[str] = frozenset()
    denied_licenses: frozenset[str] = frozenset()
    block_unpinned_js: bool = False  # warn by default; operators may harden


def policy_from_env() -> DependencyPolicy:
    """The deployment's policy: registry from ``CURIO_JS_REGISTRY_URL``,
    optional comma-separated ``CURIO_JS_DENIED_NAMES`` / ``_LICENSES``."""
    def _csv(name: str) -> frozenset[str]:
        raw = os.environ.get(name) or ""
        return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())

    url = (os.environ.get("CURIO_JS_REGISTRY_URL") or "").strip() or None
    return DependencyPolicy(
        js_registry_url=url,
        denied_names=_csv("CURIO_JS_DENIED_NAMES"),
        denied_licenses=_csv("CURIO_JS_DENIED_LICENSES"),
        block_unpinned_js=(os.environ.get("CURIO_JS_BLOCK_UNPINNED") or "") == "1",
    )


# ---------------------------------------------------------------------------
# Import scanning + explicit-constraint merge
# ---------------------------------------------------------------------------

def merge_declared_and_detected(
    request: PackageBuildRequest,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[Finding]]:
    """Scan the draft's sources and merge with explicit declarations.

    Returns ``(python_entries, js_entries, findings)`` where each entry is
    ``{"constraint": str, "source": "declared"|"detected"|"both"}``. An
    explicit constraint is NEVER overwritten by the scanner; a detected
    import without a declaration defaults to ``"*"`` and is surfaced as a
    warning, never silently (dev/89 §3.4).
    """
    detected_py: set[str] = set()
    detected_js: set[str] = set()
    for path, body in request.files.items():
        filename = path.rsplit("/", 1)[-1]
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            continue  # binary asset — nothing to scan
        py_hits, js_hits = scan_imports_for_filename(filename, text)
        detected_py.update(py_hits)
        detected_js.update(js_hits)

    findings: list[Finding] = []

    def _merge(eco: str, declared: Mapping[str, str], detected: set[str]) -> dict[str, dict]:
        entries: dict[str, dict[str, Any]] = {}
        for name, constraint in declared.items():
            entries[name] = {
                "constraint": constraint,
                "source": "both" if name in detected else "declared",
            }
            if name not in detected:
                findings.append(Finding(
                    "note", f"{eco}-declared-unused",
                    f"{eco} dependency {name!r} is declared but never imported "
                    "by the draft's sources",
                ))
        for name in sorted(detected - set(declared)):
            if eco == "js" and name.lower() in RUNTIME_EXTERNALS:
                # Behavior sources IMPORT the externals — that is the contract
                # (the compiler aliases them to the host singletons). A
                # detected external is never a dependency; only an EXPLICIT
                # declaration (someone asking to bundle it) blocks.
                findings.append(Finding(
                    "note", "js-runtime-external-import",
                    f"import of {name!r} resolves to the Curio-provided host "
                    "copy at compile time and is not a dependency",
                ))
                continue
            entries[name] = {"constraint": "*", "source": "detected"}
            findings.append(Finding(
                "warn", f"{eco}-undeclared-import",
                f"detected {eco} import {name!r} has no declared constraint — "
                "defaulted to '*' (unpinned); declare a version to make the "
                "build reproducible",
            ))
        return entries

    python_entries = _merge("python", request.dependencies.get("python") or {}, detected_py)
    js_entries = _merge("js", request.dependencies.get("js") or {}, detected_js)
    return python_entries, js_entries, findings


# ---------------------------------------------------------------------------
# JS registry resolution (fetch phase)
# ---------------------------------------------------------------------------

class RegistryFetcher(Protocol):
    """The registry seam — injectable for tests and offline deployments."""

    def fetch_metadata(self, name: str) -> dict:  # pragma: no cover - protocol
        ...

    def fetch_tarball(self, url: str, max_bytes: int) -> bytes:  # pragma: no cover
        ...


class HttpRegistryFetcher:
    """Fetches from ONE operator-approved https registry — registry egress
    only (dev/89 §3.4): every URL must live under the configured base."""

    def __init__(self, registry_url: str):
        base = registry_url.rstrip("/")
        if not base.startswith("https://"):
            raise DependencyResolutionError("the JS registry URL must be https")
        self._base = base

    def _open(self, url: str, max_bytes: int) -> bytes:
        if not url.startswith(self._base + "/") and url != self._base:
            raise DependencyResolutionError(
                f"refusing non-registry egress to {url!r}"
            )
        req = urllib.request.Request(url, headers={"Accept": "application/json, */*"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:  # noqa: S310 — https + same-origin enforced above
            data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise DependencyResolutionError(f"registry response for {url!r} exceeds the size cap")
        return data

    def fetch_metadata(self, name: str) -> dict:
        quoted = name.replace("/", "%2F")
        data = self._open(f"{self._base}/{quoted}", MAX_METADATA_BYTES)
        return json.loads(data)

    def fetch_tarball(self, url: str, max_bytes: int) -> bytes:
        return self._open(url, max_bytes)


def _verify_sri(data: bytes, integrity: str) -> bool:
    m = _SRI_RE.match(integrity or "")
    if not m:
        return False
    algo, expected_b64 = m.groups()
    digest = getattr(hashlib, algo)(data).digest()
    return base64.b64encode(digest).decode("ascii") == expected_b64


def _pick_version(constraint: str, versions: list[str]) -> str | None:
    """Highest registry version satisfying *constraint* (resolver grammar)."""
    rng = parse_range(constraint)
    best: tuple[tuple[int, int, int], str] | None = None
    for raw in versions:
        try:
            v = parse_version(raw)
        except ResolverError:
            continue
        if v < rng.lo or (rng.hi is not None and v >= rng.hi):
            continue
        if best is None or v > best[0]:
            best = (v, raw)
    return best[1] if best else None


def _cache_path(cache_dir: Path, name: str, version: str) -> Path:
    safe_name = name.replace("/", "__")
    return cache_dir / "js" / safe_name / f"{version}.tgz"


def resolve_js_dependencies(
    js_entries: Mapping[str, Mapping[str, Any]],
    *,
    fetcher: RegistryFetcher | None,
    policy: DependencyPolicy,
    cache_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[Finding]]:
    """Resolve direct + transitive JS deps into a verified lockfile.

    Returns ``(direct_rows, lock, findings)``. Every locked entry carries the
    exact version, resolved URL, SRI integrity, license, and byte size; when
    *cache_dir* is given the verified tarball is written under
    ``cache/js/<name>/<version>.tgz`` for the offline compile phase.
    Failures are findings (block severity) — never a silent skip and never a
    fallback to an ambient/unpinned source (dev/89 §3.4).
    """
    findings: list[Finding] = []
    direct_rows: list[dict[str, Any]] = []
    lock: dict[str, dict[str, Any]] = {}

    requested = {name: dict(entry) for name, entry in js_entries.items()}
    for name in sorted(requested):
        if name.lower() in RUNTIME_EXTERNALS:
            findings.append(Finding(
                "block", "js-runtime-external",
                f"{name!r} is a Curio runtime external — it is provided by the "
                "host and externalized at compile time; bundling a second copy "
                "is refused",
            ))
            requested.pop(name)
    if not requested:
        return direct_rows, lock, findings

    if fetcher is None:
        findings.append(Finding(
            "block", "js-registry-missing",
            "this deployment has no approved JS registry configured "
            "(CURIO_JS_REGISTRY_URL) — JS dependencies cannot be resolved; "
            "they are never fetched from an ambient source. Author the "
            "behavior SELF-CONTAINED (zero JS dependencies — write the "
            "rendering logic in the behavior source) and resubmit the draft",
        ))
        return direct_rows, lock, findings

    cache_total = 0
    # BFS over (name, constraint, requested_by, depth).
    queue: list[tuple[str, str, str, int]] = [
        (name, str(entry.get("constraint") or "*"), "<draft>", 0)
        for name, entry in sorted(requested.items())
    ]
    while queue:
        name, constraint, requested_by, depth = queue.pop(0)
        if name in lock:
            continue
        if name.lower() in RUNTIME_EXTERNALS:
            # A transitive attempt to pull a host singleton is recorded, not
            # fetched — peer-style usage resolves against the host copy.
            findings.append(Finding(
                "note", "js-runtime-external-transitive",
                f"transitive dependency {name!r} (via {requested_by}) resolves "
                "to the Curio-provided host copy and is not bundled",
            ))
            continue
        if not _JS_NAME_RE.match(name):
            findings.append(Finding(
                "block", "js-bad-name",
                f"JS dependency name {name!r} (via {requested_by}) is not a "
                "valid registry package name",
            ))
            continue
        if name.lower() in policy.denied_names:
            findings.append(Finding(
                "block", "js-name-denied",
                f"JS dependency {name!r} is denied by deployment policy",
            ))
            continue
        if len(lock) >= MAX_JS_PACKAGES_TOTAL:
            findings.append(Finding(
                "block", "js-too-many",
                f"JS dependency closure exceeds {MAX_JS_PACKAGES_TOTAL} packages",
            ))
            break
        if depth > MAX_JS_DEPTH:
            findings.append(Finding(
                "block", "js-too-deep",
                f"JS dependency {name!r} (via {requested_by}) exceeds the "
                f"transitive depth limit ({MAX_JS_DEPTH})",
            ))
            continue

        try:
            metadata = fetcher.fetch_metadata(name)
        except Exception as exc:  # noqa: BLE001 — a fetch failure is a finding
            findings.append(Finding(
                "block", "js-resolve-failed",
                f"could not fetch registry metadata for {name!r} "
                f"(via {requested_by}): {exc} — retryable; never resolved from "
                "an ambient source",
            ))
            continue
        versions = metadata.get("versions") or {}
        try:
            chosen = _pick_version(constraint, list(versions))
        except ResolverError as exc:
            findings.append(Finding(
                "block", "js-bad-constraint",
                f"JS dependency {name!r} constraint {constraint!r} is not "
                f"supported: {exc}",
            ))
            continue
        if chosen is None:
            findings.append(Finding(
                "block", "js-no-version",
                f"no registry version of {name!r} satisfies {constraint!r}",
            ))
            continue
        if depth == 0 and constraint in ("*", ""):
            findings.append(Finding(
                "block" if policy.block_unpinned_js else "warn", "js-unpinned",
                f"JS dependency {name!r} is unpinned ({constraint!r}) — "
                f"resolved to {chosen}; the lockfile pins it for this build",
            ))

        version_meta = versions.get(chosen) or {}
        dist = version_meta.get("dist") or {}
        integrity = dist.get("integrity") or ""
        tarball_url = dist.get("tarball") or ""
        if not _SRI_RE.match(integrity):
            findings.append(Finding(
                "block", "js-no-integrity",
                f"registry entry {name}@{chosen} carries no usable SRI "
                "integrity — refused (never an unpinned ambient fallback)",
            ))
            continue
        license_name = str(version_meta.get("license") or "").strip()
        if license_name.lower() in policy.denied_licenses:
            findings.append(Finding(
                "block", "js-license-denied",
                f"{name}@{chosen} license {license_name!r} is denied by "
                "deployment policy",
            ))
            continue

        entry: dict[str, Any] = {
            "version": chosen,
            "resolved": tarball_url,
            "integrity": integrity,
            "license": license_name or "unknown",
            "requestedBy": requested_by,
            "constraint": constraint,
        }
        if cache_dir is not None:
            try:
                data = fetcher.fetch_tarball(tarball_url, MAX_TARBALL_BYTES)
            except Exception as exc:  # noqa: BLE001
                findings.append(Finding(
                    "block", "js-fetch-failed",
                    f"could not fetch {name}@{chosen}: {exc} — retryable",
                ))
                continue
            if not _verify_sri(data, integrity):
                findings.append(Finding(
                    "block", "js-integrity-mismatch",
                    f"{name}@{chosen} tarball does not match its declared "
                    "integrity — refused",
                ))
                continue
            cache_total += len(data)
            if cache_total > MAX_CACHE_TOTAL_BYTES:
                findings.append(Finding(
                    "block", "js-cache-overflow",
                    "verified JS dependency cache exceeds the total size limit",
                ))
                break
            target = _cache_path(cache_dir, name, chosen)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            entry["bytes"] = len(data)
            entry["cached"] = str(target.relative_to(cache_dir))
        lock[name] = entry
        if depth == 0:
            direct_rows.append({"name": name, "constraint": constraint,
                                "resolvedVersion": chosen,
                                "source": js_entries[name].get("source", "declared")})
        for dep_name, dep_constraint in sorted(
                (version_meta.get("dependencies") or {}).items()):
            queue.append((str(dep_name), str(dep_constraint), f"{name}@{chosen}", depth + 1))
    return direct_rows, lock, findings


# ---------------------------------------------------------------------------
# Python review (no installation) + package-to-package review
# ---------------------------------------------------------------------------

def installed_manifests(user_key: str) -> dict[str, Any]:
    """``dirName -> PackageManifest`` for every readable installed package,
    taken as ONE snapshot under the per-user seed lock (memo dev/99).

    Both review functions below consume this; :func:`resolve_dependencies`
    takes it once and hands the same snapshot to both, so a report never
    describes two different instants of the store.
    """
    out: dict[str, Any] = {}
    with package_seed_lock(user_key):
        for package_path in list_user_packageages(user_key):
            try:
                out[package_path.name] = load_packageage_manifest(package_path)
            except ManifestError:
                continue
    return out


def review_python_dependencies(
    python_entries: Mapping[str, Mapping[str, Any]],
    user_key: str,
    *,
    is_satisfied: Callable[[str, str], bool] | None = None,
    installed: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[Finding]]:
    """Validate constraints + intersect against installed packages' declared
    python deps. Reports presence via ``pip_runner.is_satisfied`` (a metadata
    check) — nothing is installed or executed here (dev/89 §3.4).

    ``installed`` is the :func:`installed_manifests` snapshot; omitted, one is
    taken here."""
    from utk_curio.backend.app.packages import pip_runner

    satisfied = is_satisfied or pip_runner.is_satisfied
    if installed is None:
        installed = installed_manifests(user_key)
    findings: list[Finding] = []
    rows: list[dict[str, Any]] = []
    parseable: dict[str, str] = {}
    for name in sorted(python_entries):
        entry = python_entries[name]
        constraint = str(entry.get("constraint") or "*")
        row = {"name": name, "constraint": constraint,
               "source": entry.get("source", "declared"),
               "pinned": constraint not in ("*", "")}
        try:
            parse_range(constraint)
            parseable[name] = constraint
        except ResolverError as exc:
            findings.append(Finding(
                "block", "py-bad-constraint",
                f"python dependency {name!r} constraint {constraint!r} is not "
                f"supported by the project resolver: {exc}",
            ))
            rows.append(row)
            continue
        if not row["pinned"]:
            findings.append(Finding(
                "warn", "py-unpinned",
                f"python dependency {name!r} is unpinned — the Apply-time "
                "installer will take the latest available version",
            ))
        try:
            row["installed"] = bool(satisfied(name, constraint))
        except Exception:  # noqa: BLE001 — presence probing must never fail review
            row["installed"] = None
        rows.append(row)

    # Conflict check against every installed package's declared python deps —
    # the same intersection the project resolver locks (one grammar, one truth).
    installed_decls: list[tuple[str, dict[str, str]]] = []
    for dir_name, m in installed.items():
        if m.python_deps:
            installed_decls.append((dir_name, dict(m.python_deps)))
    if parseable and installed_decls:
        _, conflicts = merge_python_deps(installed_decls + [("<draft>", parseable)])
        for conflict in conflicts:
            involved = dict(conflict.ranges)
            if "<draft>" not in involved:
                continue  # pre-existing conflict between installed packages
            others = ", ".join(f"{p} wants {r}" for p, r in conflict.ranges if p != "<draft>")
            findings.append(Finding(
                "block", "py-conflict",
                f"python dependency {conflict.package!r}: the draft's "
                f"constraint conflicts with installed packages ({others})",
            ))
    return rows, findings


def review_package_dependencies(
    package_deps: Mapping[str, str],
    user_key: str,
    *,
    installed: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[Finding]]:
    """Check ``dependencies.packages`` against the installed store: each dep
    must be installed at a version inside the declared range.

    ``installed`` is the :func:`installed_manifests` snapshot; omitted, one is
    taken here."""
    findings: list[Finding] = []
    rows: list[dict[str, Any]] = []
    if installed is None:
        installed = installed_manifests(user_key)
    by_package_id: dict[str, Any] = {m.package_id: m for m in installed.values()}
    for name in sorted(package_deps):
        constraint = package_deps[name]
        row: dict[str, Any] = {"name": name, "constraint": constraint}
        m = by_package_id.get(name)
        if m is None:
            row["status"] = "missing"
            findings.append(Finding(
                "block", "package-dep-missing",
                f"package dependency {name!r} is not installed — install it "
                "(the Package Recommendation flow can propose it) before this "
                "build can apply",
            ))
        else:
            try:
                rng = parse_range(constraint)
                v = parse_version(m.version)
                ok = v >= rng.lo and (rng.hi is None or v < rng.hi)
            except ResolverError as exc:
                row["status"] = "bad-constraint"
                findings.append(Finding(
                    "block", "package-dep-bad-constraint",
                    f"package dependency {name!r} constraint {constraint!r} is "
                    f"not supported: {exc}",
                ))
                rows.append(row)
                continue
            row["status"] = "installed" if ok else "version-mismatch"
            row["installedVersion"] = m.version
            if not ok:
                findings.append(Finding(
                    "block", "package-dep-version",
                    f"package dependency {name!r} requires {constraint!r} but "
                    f"{m.version} is installed",
                ))
        rows.append(row)
    return rows, findings


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def resolve_dependencies(
    user_key: str,
    request: PackageBuildRequest,
    *,
    fetcher: RegistryFetcher | None = None,
    policy: DependencyPolicy | None = None,
    cache_dir: Path | None = None,
) -> DependencyReport:
    """The resolving phase: scan+merge, JS registry resolution into the
    verified cache, python/package review — one SBOM out (dev/89 §3.4)."""
    policy = policy or policy_from_env()
    python_entries, js_entries, findings = merge_declared_and_detected(request)
    if fetcher is None and js_entries and policy.js_registry_url:
        fetcher = HttpRegistryFetcher(policy.js_registry_url)
    js_direct, js_lock, js_findings = resolve_js_dependencies(
        js_entries, fetcher=fetcher, policy=policy, cache_dir=cache_dir,
    )
    # ONE store snapshot for both reviews (memo dev/99 §4) — taken after the
    # registry work above so the seed lock is never held across network I/O.
    installed = installed_manifests(user_key)
    python_rows, py_findings = review_python_dependencies(
        python_entries, user_key, installed=installed,
    )
    package_rows, pkg_findings = review_package_dependencies(
        request.dependencies.get("packages") or {}, user_key, installed=installed,
    )
    return DependencyReport(
        python=tuple(python_rows),
        js_direct=tuple(js_direct),
        js_lock=js_lock,
        packages=tuple(package_rows),
        findings=tuple(findings + js_findings + py_findings + pkg_findings),
    )
