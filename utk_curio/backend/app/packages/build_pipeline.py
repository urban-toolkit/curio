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

The pipeline never installs anything: promotion authority lives solely in
:mod:`build_promotion` (dev/89 §3.10).
"""

from __future__ import annotations

import logging
from typing import Any

from utk_curio.backend.app.packages import build_jobs
from utk_curio.backend.app.packages.build_compiler import (
    CompilerToolchain,
    compile_behavior_bundle,
    toolchain_from_env,
)
from utk_curio.backend.app.packages.build_deps import (
    DependencyPolicy,
    RegistryFetcher,
    resolve_dependencies,
)
from utk_curio.backend.app.packages.build_extension import (
    merged_files,
    plan_create,
    plan_extension,
    snapshot_installed_package,
)
from utk_curio.backend.app.packages.build_models import PackageBuildRequest
from utk_curio.backend.app.packages.build_packager import failed_result, finalize_build
from utk_curio.backend.app.packages.build_preview import (
    PreviewRunner,
    run_preview,
    runner_from_env,
)
from utk_curio.backend.app.packages.build_workspace import (
    LIMITS_BY_TIMEOUT_CLASS,
    WorkerLimits,
    create_workspace,
    destroy_workspace,
)

log = logging.getLogger(__name__)

_ENV = object()  # sentinel: resolve the pinned tool from the environment


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

    ctx: dict[str, Any] = {
        "workspace": None, "snapshot": None, "plan": None, "report": None,
        "bundle": None, "toolchain_version": "", "preview": None,
        "backend_decl": None, "backend_findings": [], "backend_probe": None,
        "all_files": None,
    }

    def _fail(job_: build_jobs.BuildJob, reason: str, *, logs: tuple[str, ...] = ()) -> None:
        """Attach failure provenance, then raise so execute() fails the job."""
        build_jobs.attach_result(
            job_, failed_result(request, ctx["report"], reason,
                                toolchain_version=ctx["toolchain_version"], logs=logs),
        )
        raise RuntimeError(reason)

    def _resolving(job_: build_jobs.BuildJob) -> None:
        # Gate BEFORE any workspace exists or any agent-authored byte is
        # written: a build this platform cannot bound must not start on a
        # hosted instance. `limits_applied` used to be recorded into
        # provenance and never checked, so an unbounded build looked identical
        # to a bounded one.
        from utk_curio.backend.app.packages.build_workspace import (
            BuildIsolationUnavailable,
            check_build_isolation,
        )
        from utk_curio.backend.config import CURIO_NO_AUTH

        try:
            _missing, _warning = check_build_isolation(hosted=not CURIO_NO_AUTH)
        except BuildIsolationUnavailable as exc:
            _fail(job_, str(exc))
            return
        if _warning:
            log.warning("%s", _warning)

        ws = create_workspace(job_.build_id)
        ctx["workspace"] = ws
        from utk_curio.backend.app.packages.build_workspace import populate_inputs

        populate_inputs(ws, request.files)
        if request.mode == "extend":
            # Snapshot + plan first: a stale or ineligible base fails before
            # any network or compile work happens.
            ctx["snapshot"] = snapshot_installed_package(user_key, request.target)
            ctx["plan"] = plan_extension(ctx["snapshot"], request)
        else:
            ctx["plan"] = plan_create(request)
        ctx["report"] = resolve_dependencies(
            user_key, request, fetcher=fetcher, policy=policy, cache_dir=ws.cache_dir,
        )
        if ctx["report"].blocked:
            blocking = [f.message for f in ctx["report"].findings if f.severity == "block"]
            _fail(job_, "dependency policy blocked the build: " + "; ".join(blocking[:3]))
        # memo dev/91: the backend declaration + static policy scan run here —
        # a malformed declaration or an escape-hatch import fails the build
        # before any compile/probe work, with the fix named (A4/A5).
        from utk_curio.backend.app.packages import backend_policy

        try:
            decl = backend_policy.backend_declaration(request.manifest)
        except backend_policy.BackendPolicyError as exc:
            _fail(job_, f"backend declaration invalid: {exc}")
        ctx["backend_decl"] = decl
        ctx["all_files"] = (merged_files(ctx["snapshot"], request)
                            if request.mode == "extend" else dict(request.files))
        if decl is not None:
            findings = backend_policy.validate_backend_files(decl, ctx["all_files"])
            findings += backend_policy.scan_backend_sources(
                ctx["all_files"],
                net_permission_declared=backend_policy.net_declared(request.manifest),
            )
            ctx["backend_findings"] = findings
            blocked = [f.message for f in findings if f.severity == "block"]
            if blocked:
                _fail(job_, "backend policy blocked the build: " + "; ".join(blocked[:3]))
        # memo dev/91: the backend declaration + static policy scan run here —
        # a malformed declaration or an escape-hatch import fails the build
        # before any compile/probe work, with the fix named (A4/A5).
        from utk_curio.backend.app.packages import backend_policy

        try:
            decl = backend_policy.backend_declaration(request.manifest)
        except backend_policy.BackendPolicyError as exc:
            _fail(job_, f"backend declaration invalid: {exc}")
        ctx["backend_decl"] = decl
        ctx["all_files"] = (merged_files(ctx["snapshot"], request)
                            if request.mode == "extend" else dict(request.files))
        if decl is not None:
            findings = backend_policy.validate_backend_files(decl, ctx["all_files"])
            findings += backend_policy.scan_backend_sources(
                ctx["all_files"],
                net_permission_declared=backend_policy.net_declared(request.manifest),
            )
            ctx["backend_findings"] = findings
            blocked = [f.message for f in findings if f.severity == "block"]
            if blocked:
                _fail(job_, "backend policy blocked the build: " + "; ".join(blocked[:3]))

    def _compiling(job_: build_jobs.BuildJob) -> None:
        tc = toolchain_from_env() if toolchain is _ENV else toolchain
        result = compile_behavior_bundle(
            ctx["workspace"], request, ctx["report"].js_lock,
            toolchain=tc, cancel=job_.cancel_event,
        )
        ctx["toolchain_version"] = result.toolchain_version
        if result.status != "ok":
            _fail(job_, f"behavior compile failed: {result.log_tail}"[:500],
                  logs=(result.log_tail,))
        ctx["bundle"] = result.bundle

    def _probing(job_: build_jobs.BuildJob) -> None:
        # memo dev/91: every declared handler answers the synthetic probe in
        # a REAL sandbox worker (backend_runtime.invoke_from_files — the same
        # engine live invocations use). Load + resolution is the health
        # check; a failed probe blocks Apply exactly as a failed preview.
        from utk_curio.backend.app.packages import backend_contract as bc
        from utk_curio.backend.app.packages.backend_runtime import invoke_from_files

        decl = ctx["backend_decl"]
        backend_files = {p: b for p, b in ctx["all_files"].items()
                         if p.startswith("backend/")}
        net = False
        permissions = request.manifest.get("permissions")
        if isinstance(permissions, list):
            net = bc.PERMISSION_SERVER_NETWORK in permissions
        probes: list[dict[str, Any]] = []
        for handler in decl.handler_names:
            limits = probe_limits or LIMITS_BY_TIMEOUT_CLASS["quick"]
            try:
                envelope, worker = invoke_from_files(
                    backend_files, decl.entry, handler, bc.probe_payload(),
                    net_allowed=net, limits=limits, cancel=job_.cancel_event,
                    build_id=f"probe-{job_.build_id[:12]}",
                )
            except bc.BackendContractError as exc:  # pragma: no cover — probe shapes are ours
                _fail(job_, f"backend probe request invalid for {handler!r}: {exc}")
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
                # dev/97 (Option A): the probe runs BEFORE deps install (they
                # land at Apply, into the overlay) — a module-level import of
                # a DECLARED dep is a timing mistake, and the refusal must
                # name the fix (A4), not blame the import. Import-name vs
                # dist-name drift is tolerated with -/_ equivalence.
                import re as _re

                declared = {
                    str(name).lower().replace("-", "_")
                    for name in (request.dependencies.get("python") or {})
                }
                missing = _re.search(r"No module named '([^']+)'", str(detail))
                if missing:
                    module_root = missing.group(1).split(".")[0]
                    if module_root.lower().replace("-", "_") in declared:
                        detail = (
                            f"{detail} — {module_root!r} is a DECLARED python "
                            "dependency: it installs at Apply into the package's "
                            "isolated overlay and does NOT exist at build time. "
                            "Import it INSIDE your handler function (lazily), "
                            "never at module level."
                        )
                row["error"] = detail
                probes.append(row)
                ctx["backend_probe"] = probes
                _fail(job_, f"backend probe failed for handler {handler!r}: {detail}"[:500])
            probes.append(row)
        ctx["backend_probe"] = probes

    def _previewing(job_: build_jobs.BuildJob) -> None:
        runner = runner_from_env() if preview_runner is _ENV else preview_runner
        preview = run_preview(
            ctx["workspace"], request, ctx["bundle"],
            runner=runner, cancel=job_.cancel_event,
        )
        if preview.status == "failed":
            _fail(job_, "preview failed: " + "; ".join(preview.reasons[:3]))
        ctx["preview"] = preview

    def _packaging(job_: build_jobs.BuildJob) -> None:
        files = ctx["all_files"] if ctx["all_files"] is not None else dict(request.files)
        preview = ctx["preview"]
        backend_payload = None
        if ctx["backend_decl"] is not None:
            backend_payload = {
                "entry": ctx["backend_decl"].entry,
                "handlers": [
                    {"name": h.name, "timeoutClass": h.timeout_class}
                    for h in ctx["backend_decl"].handlers
                ],
                "probe": ctx["backend_probe"],
                "findings": [
                    {"severity": f.severity, "code": f.code, "message": f.message}
                    for f in ctx["backend_findings"]
                ],
            }
        result = finalize_build(
            user_key, request,
            plan=ctx["plan"], report=ctx["report"], files=files,
            bundle=ctx["bundle"], toolchain_version=ctx["toolchain_version"],
            preview=preview.to_payload() if preview is not None else None,
            backend=backend_payload,
        )
        build_jobs.attach_result(job_, result)

    steps = [("resolving", _resolving)]
    if request.behavior_entries:
        steps.append(("compiling", _compiling))
    # Phase order is forward-only (build_jobs.PHASE_ORDER): probing sits
    # after compiling, before previewing — declared-backend drafts only.
    if (request.manifest.get("backend") or None) is not None:
        steps.append(("probing", _probing))
    if request.behavior_entries:
        steps.append(("previewing", _previewing))
    steps.append(("packaging", _packaging))

    try:
        return build_jobs.execute(job, steps)
    finally:
        if ctx["workspace"] is not None:
            destroy_workspace(ctx["workspace"])
