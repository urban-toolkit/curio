"""The build pipeline — one job through resolve → compile → preview → package
(memo dev/89 §3, the phase composition of commits 2–6).

:func:`run_build` is the single entry the reviewed proposal flow calls: it
creates (or re-attaches to, by input digest) the observable job, runs the
phase steps under :func:`build_jobs.execute` with cancellation checkpoints,
and always destroys the workspace afterwards. Every failure attaches a
``failed`` :class:`PackageBuildResult` (findings, sanitized logs) BEFORE
failing the job, so the job record carries reviewable provenance either way.

Phase mapping (phases may be skipped, never reordered — build_jobs):

* ``resolving`` — workspace + inputs; extension snapshot + merge plan
  (stale bases fail here, before any expensive work); dependency resolution
  into the verified cache. A blocked SBOM fails the build — the policy gate
  is not advisory.
* ``compiling`` — only when the draft declares behavior entries; the pinned
  toolchain compiles offline against the verified cache.
* ``probing`` — only when the draft declares a ``backend`` (memo dev/91):
  the static policy scan's blocking findings fail the build first (declared
  in ``resolving``, enforced here), then every declared handler answers the
  synthetic ``curio.pkgbackend.v1`` probe in a REAL sandbox worker — load +
  resolution is the health check, and a failed probe blocks Apply exactly
  as a failed preview does.
* ``previewing`` — only when a bundle exists; the pinned runner renders the
  five contract states, and a failed preview fails the build.
* ``packaging`` — deterministic assembly, installer-path validation,
  content-addressed staging, provenance (build_packager.finalize_build).

Each phase is a module-level function over a :class:`BuildContext` (memo
dev/143 B3): what one phase produces and the next consumes is a named field,
not a dict key, and every step reads in isolation.

The pipeline never installs anything: promotion authority lives solely in
:mod:`build_promotion` (dev/89 §3.10).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from utk_curio.backend import config as backend_config
from utk_curio.backend.app.packages.builder import jobs as build_jobs
from utk_curio.backend.app.packages.builder import policy as backend_policy
from utk_curio.backend.app.packages.builder.compiler import (
    CompilerToolchain,
    compile_behavior_bundle,
    toolchain_from_env,
)
from utk_curio.backend.app.packages.builder.deps import (
    DependencyPolicy,
    DependencyReport,
    RegistryFetcher,
    resolve_dependencies,
)
from utk_curio.backend.app.packages.builder.extension import (
    merged_files,
    plan_create,
    plan_extension,
    snapshot_installed_package,
)
from utk_curio.backend.app.packages.builder.models import PackageBuildRequest
from utk_curio.backend.app.packages.builder.packager import failed_result, finalize_build
from utk_curio.backend.app.packages.builder.preview import (
    PreviewRunner,
    run_preview,
    runner_from_env,
)
from utk_curio.backend.app.packages.domain import backend_contract as bc
from utk_curio.backend.app.packages.infrastructure import backend_runtime as packages_backend_runtime
from utk_curio.backend.app.packages.infrastructure.workspace import (
    LIMITS_BY_TIMEOUT_CLASS,
    BuildIsolationUnavailable,
    BuildWorkspace,
    WorkerLimits,
    check_build_isolation,
    create_workspace,
    destroy_workspace,
    populate_inputs,
)

log = logging.getLogger(__name__)

_ENV = object()  # sentinel: resolve the pinned tool from the environment
_MISSING_MODULE_RE = re.compile(r"No module named '([^']+)'")


@dataclass
class BuildContext:
    """Everything one build carries between its phases.

    The request and the injected seams are fixed at creation; the phase
    outputs start empty and are filled in ``PHASE_ORDER``. A field is written
    by exactly one phase and read by the ones after it.
    """

    user_key: str
    request: PackageBuildRequest
    fetcher: RegistryFetcher | None
    policy: DependencyPolicy | None
    toolchain: CompilerToolchain | None | Any
    preview_runner: PreviewRunner | None | Any
    probe_limits: WorkerLimits | None
    # phase outputs
    workspace: BuildWorkspace | None = None
    snapshot: Any = None
    plan: Any = None
    report: DependencyReport | None = None
    bundle: Any = None
    toolchain_version: str = ""
    preview: Any = None
    backend_decl: Any = None
    backend_findings: list = field(default_factory=list)
    backend_probe: list[dict[str, Any]] | None = None
    all_files: dict[str, bytes] | None = None


def run_build(
    user_key: str,
    request: PackageBuildRequest,
    *,
    fetcher: RegistryFetcher | None = None,
    policy: DependencyPolicy | None = None,
    toolchain: CompilerToolchain | None | Any = _ENV,
    preview_runner: PreviewRunner | None | Any = _ENV,
    probe_limits: WorkerLimits | None = None,
) -> build_jobs.BuildJob:
    """Run (or re-attach to) the build for *request*; returns its job.

    Idempotent by input digest: an in-flight job is returned untouched and a
    cached ``ready`` job is returned without rebuilding (dev/89 §3.9). The
    returned job is terminal unless it was already running elsewhere.
    """
    job, created = build_jobs.create_job(user_key, request)
    if not created:
        return job
    ctx = BuildContext(
        user_key=user_key, request=request, fetcher=fetcher, policy=policy,
        toolchain=toolchain, preview_runner=preview_runner, probe_limits=probe_limits,
    )
    try:
        return build_jobs.execute(job, _steps_for(ctx))
    finally:
        if ctx.workspace is not None:
            destroy_workspace(ctx.workspace)


def _steps_for(ctx: BuildContext) -> list[tuple[str, Any]]:
    """The phases this request needs, in ``build_jobs.PHASE_ORDER``.

    Phases may be skipped, never reordered: compiling and previewing only when
    the draft declares behavior entries; probing — after compiling, before
    previewing — only when it declares a ``backend``.
    """
    request = ctx.request
    steps: list[tuple[str, Any]] = [("resolving", lambda job: _resolving(ctx, job))]
    if request.behavior_entries:
        steps.append(("compiling", lambda job: _compiling(ctx, job)))
    if (request.manifest.get("backend") or None) is not None:
        steps.append(("probing", lambda job: _probing(ctx, job)))
    if request.behavior_entries:
        steps.append(("previewing", lambda job: _previewing(ctx, job)))
    steps.append(("packaging", lambda job: _packaging(ctx, job)))
    return steps


def _fail(ctx: BuildContext, job: build_jobs.BuildJob, reason: str, *, logs: tuple[str, ...] = ()) -> None:
    """Attach failure provenance, then raise so execute() fails the job."""
    build_jobs.attach_result(
        job, failed_result(ctx.request, ctx.report, reason,
                           toolchain_version=ctx.toolchain_version, logs=logs),
    )
    raise RuntimeError(reason)


# ── resolving ────────────────────────────────────────────────────────────────

def _resolving(ctx: BuildContext, job: build_jobs.BuildJob) -> None:
    """Workspace + inputs, the extension plan, dependency resolution, the backend scan."""
    _check_isolation(ctx, job)
    _prepare_workspace(ctx, job)
    _plan_inputs(ctx)
    _resolve_dependencies(ctx, job)
    _scan_backend(ctx, job)


def _check_isolation(ctx: BuildContext, job: build_jobs.BuildJob) -> None:
    # Gate BEFORE any workspace exists or any agent-authored byte is
    # written: a build this platform cannot bound must not start on a
    # hosted instance. `limits_applied` used to be recorded into
    # provenance and never checked, so an unbounded build looked identical
    # to a bounded one.
    try:
        _missing, warning = check_build_isolation(hosted=not backend_config.CURIO_NO_AUTH)
    except BuildIsolationUnavailable as exc:
        _fail(ctx, job, str(exc))
        return
    if warning:
        log.warning("%s", warning)


def _prepare_workspace(ctx: BuildContext, job: build_jobs.BuildJob) -> None:
    ctx.workspace = create_workspace(job.build_id)
    populate_inputs(ctx.workspace, ctx.request.files)


def _plan_inputs(ctx: BuildContext) -> None:
    if ctx.request.mode == "extend":
        # Snapshot + plan first: a stale or ineligible base fails before
        # any network or compile work happens.
        ctx.snapshot = snapshot_installed_package(ctx.user_key, ctx.request.target)
        ctx.plan = plan_extension(ctx.snapshot, ctx.request)
    else:
        ctx.plan = plan_create(ctx.request)


def _resolve_dependencies(ctx: BuildContext, job: build_jobs.BuildJob) -> None:
    ctx.report = resolve_dependencies(
        ctx.user_key, ctx.request, fetcher=ctx.fetcher, policy=ctx.policy,
        cache_dir=ctx.workspace.cache_dir,
    )
    if ctx.report.blocked:
        blocking = [f.message for f in ctx.report.findings if f.severity == "block"]
        _fail(ctx, job, "dependency policy blocked the build: " + "; ".join(blocking[:3]))


def _scan_backend(ctx: BuildContext, job: build_jobs.BuildJob) -> None:
    # memo dev/91: the backend declaration + static policy scan run here —
    # a malformed declaration or an escape-hatch import fails the build
    # before any compile/probe work, with the fix named (A4/A5).
    request = ctx.request
    try:
        decl = backend_policy.backend_declaration(request.manifest)
    except backend_policy.BackendPolicyError as exc:
        _fail(ctx, job, f"backend declaration invalid: {exc}")
    ctx.backend_decl = decl
    ctx.all_files = (merged_files(ctx.snapshot, request)
                     if request.mode == "extend" else dict(request.files))
    if decl is None:
        return
    findings = backend_policy.validate_backend_files(decl, ctx.all_files)
    findings += backend_policy.scan_backend_sources(
        ctx.all_files,
        net_permission_declared=backend_policy.net_declared(request.manifest),
    )
    ctx.backend_findings = findings
    blocked = [f.message for f in findings if f.severity == "block"]
    if blocked:
        _fail(ctx, job, "backend policy blocked the build: " + "; ".join(blocked[:3]))


# ── compiling ────────────────────────────────────────────────────────────────

def _compiling(ctx: BuildContext, job: build_jobs.BuildJob) -> None:
    tc = toolchain_from_env() if ctx.toolchain is _ENV else ctx.toolchain
    result = compile_behavior_bundle(
        ctx.workspace, ctx.request, ctx.report.js_lock,
        toolchain=tc, cancel=job.cancel_event,
    )
    ctx.toolchain_version = result.toolchain_version
    if result.status != "ok":
        _fail(ctx, job, f"behavior compile failed: {result.log_tail}"[:500],
              logs=(result.log_tail,))
    ctx.bundle = result.bundle


# ── probing ──────────────────────────────────────────────────────────────────

def _probing(ctx: BuildContext, job: build_jobs.BuildJob) -> None:
    # memo dev/91: every declared handler answers the synthetic probe in
    # a REAL sandbox worker (backend_runtime.invoke_from_files — the same
    # engine live invocations use). Load + resolution is the health
    # check; a failed probe blocks Apply exactly as a failed preview.
    decl = ctx.backend_decl
    backend_files = {p: b for p, b in ctx.all_files.items() if p.startswith("backend/")}
    net = False
    permissions = ctx.request.manifest.get("permissions")
    if isinstance(permissions, list):
        net = bc.PERMISSION_SERVER_NETWORK in permissions
    probes: list[dict[str, Any]] = []
    for handler in decl.handler_names:
        row = _probe_handler(ctx, job, handler, backend_files, net_allowed=net)
        probes.append(row)
        if not row["ok"]:
            ctx.backend_probe = probes
            _fail(ctx, job, f"backend probe failed for handler {handler!r}: {row['error']}"[:500])
    ctx.backend_probe = probes


def _probe_handler(
    ctx: BuildContext, job: build_jobs.BuildJob, handler: str,
    backend_files: dict[str, bytes], *, net_allowed: bool,
) -> dict[str, Any]:
    """One handler's probe row; ``error`` names the fix when it did not answer ok."""
    limits = ctx.probe_limits or LIMITS_BY_TIMEOUT_CLASS["quick"]
    try:
        envelope, worker = packages_backend_runtime.invoke_from_files(
            backend_files, ctx.backend_decl.entry, handler, bc.probe_payload(),
            net_allowed=net_allowed, limits=limits, cancel=job.cancel_event,
            build_id=f"probe-{job.build_id[:12]}",
        )
    except bc.BackendContractError as exc:  # pragma: no cover — probe shapes are ours
        _fail(ctx, job, f"backend probe request invalid for {handler!r}: {exc}")
    row: dict[str, Any] = {
        "handler": handler,
        "workerStatus": worker.status,
        "durationMs": int(worker.duration_seconds * 1000),
        "limitsApplied": list(worker.limits_applied),
        "ok": bool(envelope and envelope.get("ok")),
    }
    if not row["ok"]:
        detail = (envelope or {}).get("error") or worker.stderr_tail \
            or worker.stdout_tail or worker.status
        row["error"] = _explain_probe_failure(ctx.request, detail)
    return row


def _explain_probe_failure(request: PackageBuildRequest, detail: Any) -> Any:
    """dev/97 (Option A): the probe runs BEFORE deps install (they land at
    Apply, into the overlay) — a module-level import of a DECLARED dep is a
    timing mistake, and the refusal must name the fix (A4), not blame the
    import. Import-name vs dist-name drift is tolerated with -/_ equivalence."""
    declared = {
        str(name).lower().replace("-", "_")
        for name in (request.dependencies.get("python") or {})
    }
    missing = _MISSING_MODULE_RE.search(str(detail))
    if missing:
        module_root = missing.group(1).split(".")[0]
        if module_root.lower().replace("-", "_") in declared:
            return (
                f"{detail} — {module_root!r} is a DECLARED python "
                "dependency: it installs at Apply into the package's "
                "isolated overlay and does NOT exist at build time. "
                "Import it INSIDE your handler function (lazily), "
                "never at module level."
            )
    return detail


# ── previewing ───────────────────────────────────────────────────────────────

def _previewing(ctx: BuildContext, job: build_jobs.BuildJob) -> None:
    runner = runner_from_env() if ctx.preview_runner is _ENV else ctx.preview_runner
    preview = run_preview(
        ctx.workspace, ctx.request, ctx.bundle,
        runner=runner, cancel=job.cancel_event,
    )
    if preview.status == "failed":
        _fail(ctx, job, "preview failed: " + "; ".join(preview.reasons[:3]))
    ctx.preview = preview


# ── packaging ────────────────────────────────────────────────────────────────

def _packaging(ctx: BuildContext, job: build_jobs.BuildJob) -> None:
    files = ctx.all_files if ctx.all_files is not None else dict(ctx.request.files)
    result = finalize_build(
        ctx.user_key, ctx.request,
        plan=ctx.plan, report=ctx.report, files=files,
        bundle=ctx.bundle, toolchain_version=ctx.toolchain_version,
        preview=ctx.preview.to_payload() if ctx.preview is not None else None,
        backend=_backend_payload(ctx),
    )
    build_jobs.attach_result(job, result)


def _backend_payload(ctx: BuildContext) -> dict[str, Any] | None:
    """The backend provenance the result carries: declaration, probe rows, findings."""
    if ctx.backend_decl is None:
        return None
    return {
        "entry": ctx.backend_decl.entry,
        "handlers": [
            {"name": h.name, "timeoutClass": h.timeout_class}
            for h in ctx.backend_decl.handlers
        ],
        "probe": ctx.backend_probe,
        "findings": [
            {"severity": f.severity, "code": f.code, "message": f.message}
            for f in ctx.backend_findings
        ],
    }
