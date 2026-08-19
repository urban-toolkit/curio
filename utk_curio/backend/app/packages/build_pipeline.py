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
    }

    def _fail(job_: build_jobs.BuildJob, reason: str, *, logs: tuple[str, ...] = ()) -> None:
        """Attach failure provenance, then raise so execute() fails the job."""
        build_jobs.attach_result(
            job_, failed_result(request, ctx["report"], reason,
                                toolchain_version=ctx["toolchain_version"], logs=logs),
        )
        raise RuntimeError(reason)

    def _resolving(job_: build_jobs.BuildJob) -> None:
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
        files = (merged_files(ctx["snapshot"], request)
                 if request.mode == "extend" else dict(request.files))
        preview = ctx["preview"]
        result = finalize_build(
            user_key, request,
            plan=ctx["plan"], report=ctx["report"], files=files,
            bundle=ctx["bundle"], toolchain_version=ctx["toolchain_version"],
            preview=preview.to_payload() if preview is not None else None,
        )
        build_jobs.attach_result(job_, result)

    steps = [("resolving", _resolving)]
    if request.behavior_entries:
        steps.append(("compiling", _compiling))
        steps.append(("previewing", _previewing))
    steps.append(("packaging", _packaging))

    try:
        return build_jobs.execute(job, steps)
    finally:
        if ctx["workspace"] is not None:
            destroy_workspace(ctx["workspace"])
