"""Deterministic packager + provenance for agent builds (memo dev/89 §3.8).

Assembles the final ``.curio.zip`` from the merge plan's file set, the
compiled behavior bundle, and the reviewed manifest; validates the produced
archive through the SAME extraction + manifest path the installer uses on
Apply; stages it content-addressed (build_staging); and emits the
server-authenticated :class:`PackageBuildResult` provenance: input digest,
artifact digest, base digest, builder+toolchain version, per-file integrity,
the dependency SBOM, policy findings, the normalized diff, and sanitized
logs. The result references the artifact DIGEST only — never a filesystem
path, never a model-supplied hash.

Determinism (dev/89 §3.5/§3.8): zip entries are sorted with the factory's
pinned timestamp; the manifest is serialized canonically (sorted keys); and
``createdAt`` is deliberately NOT stamped here — the installer stamps it at
Apply (``merge_missing_manifest_created_at``), keeping the staged archive
byte-identical across rebuilds of the same input. ``integrity.json`` is not
shipped either: the installer generates it over the extracted tree, exactly
as it does for every other install path.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping

from utk_curio.backend.app.packages import build_staging
from utk_curio.backend.app.packages.build_compiler import BUNDLE_ARCHIVE_PATH
from utk_curio.backend.app.packages.build_deps import DependencyReport
from utk_curio.backend.app.packages.build_extension import MergePlan
from utk_curio.backend.app.packages.build_models import (
    PackageBuildRequest,
    PackageBuildResult,
    request_digest,
)
from utk_curio.backend.app.packages.factory import _FIXED_DATE
from utk_curio.backend.app.packages.installer import (
    InstallerError,
    _extract_into,
    load_packageage_manifest_from_dir,
)
from utk_curio.backend.app.packages.manifest import PackageManifest

BUILDER_VERSION = "curio-package-builder/1"


class PackagerError(ValueError):
    """Raised when assembly or archive validation fails structurally."""


def manifest_dependencies_from_report(
    request: PackageBuildRequest, report: DependencyReport
) -> dict[str, dict[str, str]]:
    """The manifest ``dependencies`` block the reviewed artifact ships.

    Python keeps the REVIEWED constraints; JS is pinned to the LOCKED exact
    versions (the resolved, integrity-verified ones — reproducible installs,
    dev/89 §3.4); package deps ride the request verbatim.
    """
    python = {str(row["name"]): str(row["constraint"]) for row in report.python}
    js = {name: str(entry["version"]) for name, entry in report.js_lock.items()}
    return {
        "python": dict(sorted(python.items())),
        "js": dict(sorted(js.items())),
        "packages": dict(sorted((request.dependencies.get("packages") or {}).items())),
    }


def _final_manifest(
    request: PackageBuildRequest,
    dependencies: Mapping[str, Mapping[str, str]],
    *,
    has_bundle: bool,
) -> dict[str, Any]:
    manifest = dict(request.manifest)
    manifest["dependencies"] = {k: dict(v) for k, v in dependencies.items()}
    declared_script = manifest.get("behaviorScript")
    if has_bundle:
        if declared_script not in (None, BUNDLE_ARCHIVE_PATH):
            raise PackagerError(
                f"manifest.behaviorScript {declared_script!r} does not match the "
                f"builder's bundle path {BUNDLE_ARCHIVE_PATH!r}"
            )
        manifest["behaviorScript"] = BUNDLE_ARCHIVE_PATH
    elif declared_script:
        raise PackagerError(
            f"manifest declares behaviorScript {declared_script!r} but this "
            "build compiled no bundle — declare behavior entries or drop the key"
        )
    return manifest


def assemble_archive(
    request: PackageBuildRequest,
    files: Mapping[str, bytes],
    bundle: bytes | None,
    dependencies: Mapping[str, Mapping[str, str]],
) -> tuple[bytes, dict[str, str]]:
    """Build the deterministic archive; returns ``(zip_bytes, integrity_map)``.

    *files* is the merge plan's output set (create: the request's files;
    extend: every preserved base file + the draft's overrides — never
    ``manifest.json``/``integrity.json``). The integrity map is the
    provenance's per-file SHA-256 over exactly what shipped.
    """
    if "manifest.json" in files or "integrity.json" in files:
        raise PackagerError("builder-owned files may not ride the file set")
    if bundle is not None and BUNDLE_ARCHIVE_PATH in files:
        raise PackagerError(
            f"{BUNDLE_ARCHIVE_PATH} arrives from the compiler, never the file set"
        )
    manifest = _final_manifest(request, dependencies, has_bundle=bundle is not None)
    entries: dict[str, bytes] = dict(files)
    entries["manifest.json"] = json.dumps(
        manifest, indent=2, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")
    if bundle is not None:
        entries[BUNDLE_ARCHIVE_PATH] = bundle

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        for name in sorted(entries):
            info = zipfile.ZipInfo(filename=name, date_time=_FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, entries[name])
    integrity = {name: hashlib.sha256(body).hexdigest() for name, body in sorted(entries.items())}
    return buf.getvalue(), integrity


def validate_archive(archive: bytes) -> PackageManifest:
    """Prove the produced archive installs: the installer's own extraction
    guards + manifest validation, on a throwaway directory (dev/89 §3.8 —
    the same path Apply uses, so 'validated' and 'installable' cannot drift)."""
    side = Path(tempfile.mkdtemp(prefix="curio-build-validate-"))
    try:
        try:
            with zipfile.ZipFile(io.BytesIO(archive), mode="r") as zf:
                _extract_into(zf, side)
            return load_packageage_manifest_from_dir(side)
        except (InstallerError, zipfile.BadZipFile) as exc:
            raise PackagerError(f"built archive failed install validation: {exc}") from exc
    finally:
        shutil.rmtree(side, ignore_errors=True)


def _finding_strings(report: DependencyReport) -> tuple[str, ...]:
    return tuple(f"{f.severity}:{f.code}: {f.message}" for f in report.findings)


def failed_result(
    request: PackageBuildRequest,
    report: DependencyReport | None,
    reason: str,
    *,
    toolchain_version: str = "",
    logs: tuple[str, ...] = (),
) -> PackageBuildResult:
    """A failed build's provenance — findings and logs, no artifact."""
    return PackageBuildResult(
        status="failed",
        input_digest=request_digest(request),
        base_digest=request.base_digest,
        builder_version=f"{BUILDER_VERSION}+{toolchain_version}" if toolchain_version
        else BUILDER_VERSION,
        dependencies={"sbom": report.to_payload()} if report is not None else {},
        policy_findings=_finding_strings(report) if report is not None else (),
        warnings=(reason,),
        logs=logs,
    )


def finalize_build(
    user_key: str,
    request: PackageBuildRequest,
    *,
    plan: MergePlan,
    report: DependencyReport,
    files: Mapping[str, bytes],
    bundle: bytes | None,
    toolchain_version: str = "",
    preview: dict[str, Any] | None = None,
    logs: tuple[str, ...] = (),
) -> PackageBuildResult:
    """Assemble → validate → stage → provenance (dev/89 §3.8).

    Refuses to finalize a blocked dependency report (the policy gate is not
    advisory). Raises :class:`PackagerError` on structural failures; the job
    controller turns those into a failed job.
    """
    if report.blocked:
        raise PackagerError(
            "dependency policy blocked this build — resolve the blocking "
            "findings before packaging"
        )
    dependencies = manifest_dependencies_from_report(request, report)
    archive, integrity = assemble_archive(request, files, bundle, dependencies)
    manifest = validate_archive(archive)
    if manifest.dir_name != request.target:
        raise PackagerError(
            f"built archive resolves to {manifest.dir_name!r} but the request "
            f"targets {request.target!r}"
        )
    artifact_digest = build_staging.stage_artifact(user_key, archive)
    builder_version = (
        f"{BUILDER_VERSION}+{toolchain_version}" if toolchain_version else BUILDER_VERSION
    )
    return PackageBuildResult(
        status="ready",
        input_digest=request_digest(request),
        base_digest=request.base_digest,
        artifact_digest=artifact_digest,
        builder_version=builder_version,
        diff=plan.to_payload(),
        dependencies={
            "sbom": report.to_payload(),
            "manifest": dependencies,
            "filesIntegrity": integrity,
        },
        policy_findings=_finding_strings(report),
        preview=preview,
        archive_size=len(archive),
        logs=logs,
    )
