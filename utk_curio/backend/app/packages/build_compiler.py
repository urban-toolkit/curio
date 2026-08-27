"""Pinned deterministic behavior compiler (memo dev/89 §3.5).

Compiles a draft's JS/TS/TSX behavior entries into ONE
``scripts/behaviors.js`` inside a restricted build workspace, offline, using
the deployment-pinned toolchain — never the repository's ambient Node.

**Toolchain pinning.** ``CURIO_BUILD_ESBUILD`` names the pinned esbuild
binary for this deployment; its probed version is recorded in the build
provenance. No toolchain configured = an honest failed compile ("toolchain
not configured"), the same fail-closed posture as the JS registry
(build_deps) — never a fallback to whatever ``node`` happens to be on PATH.

**Runtime externals contract** (docs/EXTENDING.md §5, one truth with
``webpack.packages.config.js``): ``react`` / ``react-dom`` / ``reactflow``
resolve to the HOST's ``window.React`` / ``window.ReactDOM`` /
``window.ReactFlow``, and ``@curio/package-runtime`` resolves to
``window.curio`` — via generated shim modules aliased into the bundle, so a
package can never ship a second React copy (the rules-of-hooks failure the
contract exists to prevent). A lockfile that somehow carries an external is
refused here again (defence in depth over build_deps' block).

**Determinism.** Fixed flags (iife, es2020, utf8 charset, no sourcemap, no
legal comments, production define), entry ordering = the request's declared
``behaviorEntries`` order, and dependencies materialized ONLY from the
resolver's SRI-verified tarball cache. Identical inputs + identical
toolchain version → byte-identical bundles.
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import tarfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from utk_curio.backend.app.packages.build_deps import RUNTIME_EXTERNALS
from utk_curio.backend.app.packages.build_workspace import system_path_env
from utk_curio.backend.app.packages.build_models import PackageBuildRequest
from utk_curio.backend.app.packages.build_workspace import (
    BuildWorkspace,
    WorkerLimits,
    collect_outputs,
    run_worker,
)

log = logging.getLogger(__name__)

BUNDLE_ARCHIVE_PATH = "scripts/behaviors.js"

# Host-global shims (the EXTENDING.md §5 contract). Aliased into the bundle
# so bare imports of the externals resolve to the host singletons at runtime.
_EXTERNAL_SHIMS: dict[str, str] = {
    "react": "module.exports = window.React;\n",
    "react-dom": "module.exports = window.ReactDOM;\n",
    "reactflow": "module.exports = window.ReactFlow;\n",
    "@curio/package-runtime": "module.exports = window.curio;\n",
}

# Extraction bounds for cached dependency tarballs (mirrors the installer's
# per-file/total posture; a dependency is code + small assets, never data).
_MAX_TAR_MEMBER_BYTES = 8 * 1024 * 1024
_MAX_TAR_TOTAL_BYTES = 64 * 1024 * 1024


class CompileError(ValueError):
    """Raised on compiler misuse or unsafe dependency materialization."""


@dataclass(frozen=True)
class CompilerToolchain:
    """The deployment-pinned compiler (dev/89 §3.5)."""

    esbuild_path: str
    version: str


@dataclass(frozen=True)
class CompileResult:
    status: str  # "ok" | "failed"
    bundle: bytes | None
    toolchain_version: str
    log_tail: str = ""
    warnings: tuple[str, ...] = ()


def toolchain_from_env() -> CompilerToolchain | None:
    """Resolve the pinned toolchain from ``CURIO_BUILD_ESBUILD``, probing its
    version for provenance. Returns None when unconfigured or unusable."""
    path = (os.environ.get("CURIO_BUILD_ESBUILD") or "").strip()
    if not path:
        return None
    try:
        probe = subprocess.run(  # noqa: S603 — operator-pinned binary, fixed argv
            [path, "--version"],
            capture_output=True, text=True, timeout=10,
            env=system_path_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("CURIO_BUILD_ESBUILD %r is not runnable: %s", path, exc)
        return None
    version = (probe.stdout or probe.stderr or "").strip().splitlines()[:1]
    if probe.returncode != 0 or not version:
        log.warning("CURIO_BUILD_ESBUILD %r failed the version probe", path)
        return None
    return CompilerToolchain(esbuild_path=path, version=f"esbuild/{version[0]}")


# ---------------------------------------------------------------------------
# Dependency materialization (offline, from the verified cache)
# ---------------------------------------------------------------------------

def _module_dir(node_modules: Path, name: str) -> Path:
    target = node_modules.joinpath(*name.split("/"))
    resolved_base = node_modules.resolve()
    if not str(target.resolve()).startswith(str(resolved_base) + os.sep):
        raise CompileError(f"dependency name {name!r} escapes node_modules")
    return target


def _extract_tarball(data: bytes, dest: Path) -> None:
    """Extract one npm tarball safely: regular files only, no links, no
    traversal, the conventional ``package/`` prefix stripped, size caps."""
    total = 0
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError as exc:
        raise CompileError(f"cached dependency tarball is unreadable: {exc}") from exc
    with tf:
        for member in tf.getmembers():
            if member.isdir():
                continue
            if not member.isfile():
                raise CompileError(
                    f"dependency tarball member {member.name!r} is not a regular "
                    "file (links/devices refused)"
                )
            name = member.name
            parts = [p for p in name.split("/") if p]
            if not parts or any(p in (".", "..") for p in parts) or name.startswith("/"):
                raise CompileError(f"dependency tarball member {name!r} is unsafe")
            if parts[0] == "package":
                parts = parts[1:]  # npm convention
            if not parts:
                continue
            if member.size > _MAX_TAR_MEMBER_BYTES:
                raise CompileError(f"dependency tarball member {name!r} exceeds the size cap")
            total += member.size
            if total > _MAX_TAR_TOTAL_BYTES:
                raise CompileError("dependency tarball exceeds the total size cap")
            out = dest.joinpath(*parts)
            resolved_dest = dest.resolve()
            if not str(out.resolve()).startswith(str(resolved_dest) + os.sep):
                raise CompileError(f"dependency tarball member {name!r} escapes its module dir")
            out.parent.mkdir(parents=True, exist_ok=True)
            extracted = tf.extractfile(member)
            if extracted is None:
                continue
            out.write_bytes(extracted.read())


def materialize_node_modules(
    workspace: BuildWorkspace, js_lock: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Extract every SRI-verified cached tarball into ``work/node_modules/``.

    Only entries the resolver cached are materialized; an entry without a
    ``cached`` path is a resolver-phase bug surfaced loudly, and a runtime
    external in the lock is refused outright (defence in depth).
    """
    node_modules = workspace.work_dir / "node_modules"
    materialized: list[str] = []
    for name in sorted(js_lock):
        if name.lower() in RUNTIME_EXTERNALS:
            raise CompileError(
                f"lockfile carries runtime external {name!r} — refused; host "
                "singletons are never bundled"
            )
        entry = js_lock[name]
        cached_rel = entry.get("cached")
        if not isinstance(cached_rel, str) or not cached_rel:
            raise CompileError(
                f"lock entry {name!r} has no verified cached tarball — the "
                "resolve phase must run (with a cache dir) before compiling"
            )
        cached = (workspace.cache_dir / cached_rel).resolve()
        if not str(cached).startswith(str(workspace.cache_dir.resolve()) + os.sep):
            raise CompileError(f"lock entry {name!r} cache path escapes the cache dir")
        if not cached.is_file():
            raise CompileError(f"lock entry {name!r} cached tarball is missing")
        dest = _module_dir(node_modules, name)
        dest.mkdir(parents=True, exist_ok=True)
        _extract_tarball(cached.read_bytes(), dest)
        materialized.append(name)
    return materialized


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------

def _write_shims(workspace: BuildWorkspace) -> dict[str, Path]:
    shim_dir = workspace.work_dir / "__shims__"
    shim_dir.mkdir(exist_ok=True)
    out: dict[str, Path] = {}
    for name, body in _EXTERNAL_SHIMS.items():
        path = shim_dir / (name.replace("/", "__") + ".js")
        path.write_text(body, encoding="utf-8")
        out[name] = path
    return out


def _write_generated_entry(workspace: BuildWorkspace, request: PackageBuildRequest) -> Path:
    """One generated entry importing each behavior entry in DECLARED order —
    the fixed source ordering the determinism contract requires."""
    lines = [
        "// generated by the Curio package builder — imports each behavior",
        "// entry in the request's declared order (deterministic).",
    ]
    for rel in request.behavior_entries:
        source = workspace.input_dir / rel
        lines.append(f"import {json_string(str(source))};")
    entry = workspace.work_dir / "__entry__.gen.js"
    entry.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return entry


def json_string(value: str) -> str:
    import json

    return json.dumps(value)


def compile_behavior_bundle(
    workspace: BuildWorkspace,
    request: PackageBuildRequest,
    js_lock: Mapping[str, Mapping[str, Any]],
    *,
    toolchain: CompilerToolchain | None,
    limits: WorkerLimits | None = None,
    cancel: threading.Event | None = None,
) -> CompileResult:
    """Compile the request's behavior entries into one deterministic bundle.

    Returns a :class:`CompileResult` — a compile failure is data for the job
    record, never an exception (misuse and unsafe materialization DO raise
    :class:`CompileError`). The workspace's inputs must already be populated
    and the resolver's verified cache in place.
    """
    if not request.behavior_entries:
        raise CompileError("request has no behavior entries — nothing to compile")
    if toolchain is None:
        return CompileResult(
            status="failed", bundle=None, toolchain_version="unconfigured",
            log_tail=(
                "no pinned compiler toolchain is configured for this deployment "
                "(CURIO_BUILD_ESBUILD) — custom behavior cannot be built; the "
                "ambient Node installation is never used"
            ),
        )

    materialize_node_modules(workspace, js_lock)
    shims = _write_shims(workspace)
    entry = _write_generated_entry(workspace, request)
    outfile = workspace.output_dir / "scripts" / "behaviors.js"
    outfile.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        toolchain.esbuild_path,
        str(entry),
        "--bundle",
        "--format=iife",
        "--platform=browser",
        "--target=es2020",
        "--charset=utf8",
        "--legal-comments=none",
        # No --sourcemap flag AT ALL = no sourcemap (the fixed policy);
        # "--sourcemap=false" is not a valid esbuild value (found against
        # the real 0.28 binary — the fake toolchain could never catch it).
        "--log-level=warning",
        '--define:process.env.NODE_ENV="production"',
        f"--outfile={outfile}",
    ]
    for name, shim_path in sorted(shims.items()):
        argv.append(f"--alias:{name}={shim_path}")

    worker = run_worker(
        workspace, argv,
        limits=limits or WorkerLimits(),
        cancel=cancel,
        extra_env={"NODE_ENV": "production"},
    )
    log_tail = (worker.stderr_tail or "") + (worker.stdout_tail or "")
    if worker.status != "ok":
        return CompileResult(
            status="failed", bundle=None, toolchain_version=toolchain.version,
            log_tail=f"compiler {worker.status} (exit {worker.exit_code}): {log_tail}",
        )

    outputs = collect_outputs(workspace)
    bundle = outputs.pop(BUNDLE_ARCHIVE_PATH, None)
    if bundle is None or not bundle.strip():
        return CompileResult(
            status="failed", bundle=None, toolchain_version=toolchain.version,
            log_tail=f"compiler exited 0 but produced no {BUNDLE_ARCHIVE_PATH}: {log_tail}",
        )
    if outputs:
        # A pinned compiler with fixed flags writes exactly one file; anything
        # else is refused rather than silently packaged (dev/89 §3.6).
        return CompileResult(
            status="failed", bundle=None, toolchain_version=toolchain.version,
            log_tail=(
                "compiler produced unexpected outputs "
                f"{sorted(outputs)} alongside {BUNDLE_ARCHIVE_PATH} — refused"
            ),
        )
    warnings = tuple(
        line for line in (worker.stderr_tail or "").splitlines() if line.strip()
    )[:20]
    return CompileResult(
        status="ok", bundle=bundle, toolchain_version=toolchain.version,
        log_tail=log_tail, warnings=warnings,
    )
