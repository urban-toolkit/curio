"""Reviewed promotion coordinator — the ONLY install authority for built
packages (memo dev/89 §3.10).

The builder stages artifacts and reports; it never mutates installed
packages, lockfiles, or graphs. :func:`promote` is what the authenticated
Apply endpoint calls after the user reviews a ``ready`` build:

1. **Exact digest** — the artifact is read back from content-addressed
   staging (verify-on-read) and re-validated through the installer path;
   the manifest must resolve to the promoted target. No path, no
   model-supplied hash, no substitution between review and Apply.
2. **Stale protection** — an extension's pinned ``baseDigest`` must still
   match the installed package (409 otherwise); a create must not collide
   with an existing install (extension requires a pinned base).
3. **Compensation held** — the prior editable package is exported to a
   backup BEFORE the replace, and kept until registry activation and node
   insertion complete; :func:`rollback` restores it and honestly reports
   ``rolled-back`` vs ``rollback-failed`` (the UI must show which).
4. **Journal** — every step (`verified → backed-up → installed →
   lockfile-updated → registry-ready → nodes-created`) is persisted under
   ``.curio/users/<u>/.package-promotions/``, so a client disconnect
   resumes: repeated Apply returns the journal instead of reinstalling
   blindly.
5. **Order** — python deps install at Apply (the reviewed installer step);
   the project lockfile updates only after the package install succeeded;
   registry refresh (frontend) is confirmed before node creation
   (:func:`confirm_registry_ready` → :func:`confirm_nodes_created`, which
   completes the journal, drops the backup, and discards the staged
   artifact).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from utk_curio.backend.app.packages.repositories import seed_state
from utk_curio.backend.app.packages.repositories import staging as build_staging
from utk_curio.backend.app.packages.builder.extension import installed_package_digest
from utk_curio.backend.app.packages.builder.packager import PackagerError, validate_archive
from utk_curio.backend.app.packages.repositories.staging import StagingError
from utk_curio.backend.app.packages.application.store_install import (
    export_package_archive,
    install_package_from_archive,
    uninstall_package,
)
from utk_curio.backend.app.packages.repositories.archive import InstallerError
from utk_curio.backend.app.packages.repositories.store import (
    _user_key_segment,
    _users_base,
)
from utk_curio.backend.app.packages.domain import backend_contract as bc
from utk_curio.backend.app.packages.infrastructure import backend_runtime, pip_runner
from utk_curio.backend.app.packages.infrastructure.target_locks import target_lock as _target_lock
from utk_curio.backend.app.packages.infrastructure.workspace import LIMITS_BY_TIMEOUT_CLASS
from utk_curio.backend.app.packages.repositories.store import package_dir
from utk_curio.backend.app.packages.application import (
    project_packages as packages_project_packages,
    provisioning as packages_provisioning,
)
from utk_curio.backend.app.packages.domain.errors import PackageServiceError

log = logging.getLogger(__name__)

PROMOTION_CONTRACT_VERSION = "1"

# Journal statuses. ``awaiting-activation`` = installed (+ lockfile) but the
# frontend has not yet confirmed registry refresh + node insertion.
_ACTIVE_STATUSES = ("awaiting-activation",)
_TERMINAL_STATUSES = ("completed", "rolled-back", "rollback-failed", "failed")


class PromotionError(ValueError):
    """Raised on refused promotions. ``status`` is the suggested HTTP code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _promotions_dir(user_key: str) -> Path:
    return _users_base() / _user_key_segment(user_key) / ".package-promotions"


def _journal_path(user_key: str, artifact_digest: str) -> Path:
    return _promotions_dir(user_key) / f"{artifact_digest}.json"


def _backup_path(user_key: str, artifact_digest: str) -> Path:
    return _promotions_dir(user_key) / f"{artifact_digest}.backup.zip"


def load_journal(user_key: str, artifact_digest: str) -> dict[str, Any] | None:
    path = _journal_path(user_key, artifact_digest)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        log.warning("Corrupt promotion journal %s — ignoring", path)
        return None


def _save_journal(user_key: str, journal: dict[str, Any]) -> dict[str, Any]:
    base = _promotions_dir(user_key)
    base.mkdir(parents=True, exist_ok=True)
    path = _journal_path(user_key, journal["artifactDigest"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(journal, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return journal


def _record_step(journal: dict[str, Any], step: str) -> None:
    journal["steps"].append({"step": step, "at": time.time()})


def _has_step(journal: dict[str, Any], step: str) -> bool:
    return any(s.get("step") == step for s in journal.get("steps") or [])


# In-process serialization per (user, target) — dev/92 B-1: the lock LIVES in
# target_locks now, shared with backend_runtime's invocation READ phase, so an
# invocation can no longer observe the installer's non-atomic rmtree+move
# window or a files-vs-pin mismatch; promotes behave exactly as before.


def promote(
    user_key: str,
    *,
    target: str,
    artifact_digest: str,
    base_digest: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Promote the exact reviewed artifact into the user's package store.

    Returns the journal payload (status ``awaiting-activation``). Idempotent:
    an existing active/completed journal for the same artifact is returned
    as-is — a disconnect + retry never reinstalls blindly.

    The steps, in order (memo dev/143 B3): the journal check, the exact-digest
    verification, the stale/collision check on the base, the journal opened,
    the prior package backed up, the artifact installed, the backend entry
    pinned, dependencies provisioned, the post-apply probe, the project
    lockfile — each a function below; every failure past the install
    compensates through :func:`_compensate` before it is raised.
    """
    # Gated like every other path that ends in pip. This one is the reason the
    # gate exists: an agent proposal the user accepts installs whatever
    # dependencies the model wrote, into the interpreter that runs everyone's
    # node code. Checked before the lock, so a refusal costs nothing.
    try:
        packages_provisioning.assert_may_install()
    except PackageServiceError as exc:
        raise PromotionError(str(exc), exc.status) from exc

    with _target_lock(user_key, target):
        existing = _existing_journal(user_key, target, artifact_digest)
        if existing is not None:
            return existing
        archive, manifest = _verified_artifact(user_key, target, artifact_digest)
        installed_digest = _checked_base(user_key, target, base_digest)
        journal = _open_journal(target, artifact_digest, base_digest, project_id)
        _save_journal(user_key, journal)
        if installed_digest is not None:
            _back_up_prior(user_key, journal, installed_digest)
        _install_artifact(user_key, journal, archive, replace=installed_digest is not None)
        _pin_backend_entry(user_key, journal)
        _provision_dependencies(user_key, journal, manifest)
        _post_apply_probe(user_key, journal, manifest)
        if project_id is not None:
            _enlist_in_project(user_key, journal, project_id)
        journal["status"] = "awaiting-activation"
        _save_journal(user_key, journal)
        return journal


def _existing_journal(user_key: str, target: str, artifact_digest: str) -> dict[str, Any] | None:
    """An active or completed journal for this artifact is the answer; a failed
    or rolled-back one is superseded by a fresh attempt."""
    existing = load_journal(user_key, artifact_digest)
    if existing is None:
        return None
    if existing.get("status") in _ACTIVE_STATUSES + ("completed",):
        if existing.get("target") != target:
            raise PromotionError(
                f"artifact {artifact_digest[:12]}… was promoted for "
                f"{existing.get('target')!r}, not {target!r}", 409)
        return existing
    return None


def _verified_artifact(user_key: str, target: str, artifact_digest: str):
    """Exact digest: read back from content-addressed staging (verify-on-read),
    re-validated through the installer path, resolving to the promoted target."""
    try:
        archive = build_staging.read_artifact(user_key, artifact_digest)
    except StagingError as exc:
        raise PromotionError(
            f"staged artifact unavailable: {exc}", 410) from exc
    try:
        manifest = validate_archive(archive)
    except PackagerError as exc:
        raise PromotionError(str(exc), 422) from exc
    if manifest.dir_name != target:
        raise PromotionError(
            f"reviewed artifact resolves to {manifest.dir_name!r} but the "
            f"proposal targets {target!r} — refused", 409)
    return archive, manifest


def _checked_base(user_key: str, target: str, base_digest: str | None) -> str | None:
    """Stale protection: an extension's pinned base must still be installed and
    unchanged; a create must not collide with an existing install. Returns the
    installed digest (``None`` for a fresh create)."""
    installed_digest = installed_package_digest(user_key, target)
    if base_digest is not None:
        if installed_digest is None:
            raise PromotionError(
                f"extension base {target} is no longer installed — "
                "regenerate the draft", 409)
        if installed_digest != base_digest:
            raise PromotionError(
                f"stale base: {target} changed since this draft was built "
                "— regenerate against the current package", 409)
    elif installed_digest is not None:
        raise PromotionError(
            f"{target} is already installed — extending it requires a "
            "draft pinned to its current digest", 409)
    return installed_digest


def _open_journal(
    target: str, artifact_digest: str, base_digest: str | None, project_id: str | None,
) -> dict[str, Any]:
    journal: dict[str, Any] = {
        "contract": PROMOTION_CONTRACT_VERSION,
        "artifactDigest": artifact_digest,
        "baseDigest": base_digest,
        "target": target,
        "projectId": project_id,
        "status": "in-progress",
        "steps": [],
        "backupHeld": False,
        "lockfileAdded": False,
        "error": None,
        "rollback": None,
    }
    _record_step(journal, "verified")
    return journal


def _back_up_prior(user_key: str, journal: dict[str, Any], installed_digest: str) -> None:
    """Compensation held: the prior editable package is exported BEFORE the replace."""
    backup = export_package_archive(user_key, journal["target"])
    _backup_path(user_key, journal["artifactDigest"]).write_bytes(backup)
    journal["backupHeld"] = True
    journal["priorDigest"] = installed_digest
    # Where the prior copy came from goes back with it: restoring a catalog
    # copy as if it were the user's own would take it off the catalog's
    # refresh track (#564).
    prior_record = seed_state.load(user_key).get(journal["target"])
    journal["priorSeedRecord"] = prior_record.to_json() if prior_record else {}
    _record_step(journal, "backed-up")
    _save_journal(user_key, journal)


def _install_artifact(user_key: str, journal: dict[str, Any], archive: bytes, *, replace: bool) -> None:
    try:
        install_package_from_archive(user_key, archive, replace=replace)
    except InstallerError as exc:
        journal["status"] = "failed"
        journal["error"] = f"install failed: {exc}"
        _save_journal(user_key, journal)
        raise PromotionError(f"install failed: {exc}", 422) from exc
    _record_step(journal, "installed")
    _save_journal(user_key, journal)


def _pin_backend_entry(user_key: str, journal: dict[str, Any]) -> None:
    # memo dev/91: pin the backend entry digest at the install authority —
    # invocation-time verify-on-read checks THIS truth (409 + reinstall on
    # drift). A backend-less install clears any stale pin.
    pinned = backend_runtime.record_entry_pin(user_key, journal["target"])
    if pinned is not None:
        journal["backendEntryDigest"] = pinned
        _save_journal(user_key, journal)


def _compensate(user_key: str, journal: dict[str, Any], reason: str) -> str:
    """Record *reason*, roll the promotion back under the held lock, and say
    honestly whether the prior state came back — the phrase the refusal carries."""
    journal["error"] = reason
    _save_journal(user_key, journal)
    _rollback_locked(user_key, journal, reason)
    return ("restored" if journal["rollback"]["status"] == "rolled-back"
            else "NOT fully restored — manual repair required")


def _provision_dependencies(user_key: str, journal: dict[str, Any], manifest) -> None:
    """Python deps install at Apply — the reviewed installer step the build
    phase deliberately never ran (dev/89 §3.4). dev/97: ONE routing decision
    (dep_destinations) sends a backend-bearing package's deps to its isolated
    OVERLAY (wipe-and-rebuild under this lock — invocations wait, B-1); the
    shared interpreter is touched only when the manifest also carries
    warm-sandbox python templates. Any failure compensates immediately."""
    target = journal["target"]
    py_deps = dict(manifest.python_deps or {})
    if not py_deps:
        return
    destination, dest_reason = backend_runtime.dep_destinations(manifest)
    if destination in ("overlay", "both"):
        _build_overlay_or_compensate(user_key, journal, py_deps, dest_reason)
    if destination in ("host", "both"):
        _install_host_deps_or_compensate(user_key, journal, py_deps)

    # pip is satisfied by metadata alone, so a wheel whose native
    # extension cannot load installs without complaint and the
    # promotion reports success. Record it instead: the applied turn
    # says "built and installed", which is the last moment this is
    # connectable to the package that caused it. Not a rollback - the
    # package itself is sound, and the repair (a matching GDAL, a
    # different wheel) is the user's.
    #
    # Outside the host branch, and asked through the install seam, so
    # the question follows the deps to wherever `dep_destinations` just
    # sent them. Inside it, a backend-bearing package - whose deps went
    # to the overlay - was never probed at all, and a "both" package was
    # vouched for by the host copy alone.
    broken = packages_provisioning._declared_import_failures(user_key, target, manifest)
    if broken:
        journal["importErrors"] = broken
        _save_journal(user_key, journal)


def _build_overlay_or_compensate(
    user_key: str, journal: dict[str, Any], py_deps: dict[str, str], dest_reason: str,
) -> None:
    try:
        overlay_info = backend_runtime.build_overlay(user_key, journal["target"], py_deps)
    except (pip_runner.PipInstallError, backend_runtime.BackendRuntimeError) as exc:
        outcome = _compensate(user_key, journal, f"overlay build failed: {exc}")
        raise PromotionError(
            "dependency overlay build failed and the prior state was "
            f"{outcome}: {exc}",
            502) from exc
    journal["overlay"] = {**overlay_info, "reason": dest_reason}
    _save_journal(user_key, journal)


def _install_host_deps_or_compensate(
    user_key: str, journal: dict[str, Any], py_deps: dict[str, str],
) -> None:
    try:
        pip_report = pip_runner.install_python_deps(py_deps)
        # dev/92 B-2, narrowed by dev/97: the restart signal fires
        # for the SHARED interpreter only — overlay changes never
        # split-brain anything (workers are freshly spawned).
        if pip_report.installed:
            journal["restartRecommended"] = {
                "libs": sorted(pip_report.installed)}
            _save_journal(user_key, journal)
    except pip_runner.PipInstallError as exc:
        outcome = _compensate(user_key, journal, f"pip install failed: {exc}")
        raise PromotionError(
            "python dependency install failed and the prior state was "
            f"{outcome}: {exc}",
            502) from exc


def _post_apply_probe(user_key: str, journal: dict[str, Any], manifest) -> None:
    """dev/97: the post-Apply probe — ONE invocation of the INSTALLED entry with
    the real overlay on PYTHONPATH, catching the overlay shadowing edge at Apply
    (rollback compensation) instead of at the user's first Run. Load +
    resolution is the health check (dev/91)."""
    if manifest.backend is None or not manifest.backend.handlers:
        return
    probe_error = _probe_installed_backend(user_key, journal, manifest)
    if probe_error:
        outcome = _compensate(user_key, journal, f"post-apply probe failed: {probe_error}")
        raise PromotionError(
            "the installed backend failed its post-apply probe and the "
            f"prior state was {outcome}: "
            f"{probe_error}", 422) from None


def _probe_installed_backend(user_key: str, journal: dict[str, Any], manifest) -> str | None:
    """The first declared handler's probe against the installed ``backend/``
    tree; ``None`` when it answered ok. A broken probe is data, never a raise."""
    target = journal["target"]
    try:
        pkg_path = package_dir(user_key, target)
        files = {
            f"backend/{p.relative_to(pkg_path / 'backend').as_posix()}":
                p.read_bytes()
            for p in sorted((pkg_path / "backend").rglob("*"))
            if p.is_file()
        }
        overlay_path = backend_runtime.overlay_dir_for(user_key, target)
        envelope, worker = backend_runtime.invoke_from_files(
            files, manifest.backend.entry,
            manifest.backend.handlers[0].name, bc.probe_payload(),
            net_allowed=bc.PERMISSION_SERVER_NETWORK in manifest.permissions,
            limits=LIMITS_BY_TIMEOUT_CLASS["quick"],
            overlay_dir=overlay_path if overlay_path.is_dir() else None,
            build_id=f"apply-probe-{journal['artifactDigest'][:12]}",
        )
        if worker.status != "ok" or not (envelope and envelope.get("ok")):
            return ((envelope or {}).get("error")
                    or worker.stderr_tail or worker.status)
    except Exception as exc:  # noqa: BLE001 — a broken probe is data
        return str(exc)
    return None


def _enlist_in_project(user_key: str, journal: dict[str, Any], project_id: str) -> None:
    """The project lockfile updates only after the package install succeeded."""
    target = journal["target"]
    already = target in packages_project_packages.get_project_lockfile(user_key, project_id)
    try:
        packages_project_packages.install_to_project(user_key, project_id, target)
    except PackageServiceError as exc:
        _compensate(user_key, journal, f"lockfile update failed: {exc}")
        raise PromotionError(
            f"project lockfile update failed: {exc}", exc.status) from exc
    journal["lockfileAdded"] = not already
    _record_step(journal, "lockfile-updated")


def confirm_registry_ready(user_key: str, artifact_digest: str) -> dict[str, Any]:
    """The frontend confirms the package/behavior/template registries
    refreshed with the promoted package — the precondition for node creation."""
    journal = _require_journal(user_key, artifact_digest, expect_status="awaiting-activation")
    if not _has_step(journal, "registry-ready"):
        _record_step(journal, "registry-ready")
        _save_journal(user_key, journal)
    return journal


def confirm_nodes_created(user_key: str, artifact_digest: str) -> dict[str, Any]:
    """Complete the promotion: requested nodes exist on the canvas. Drops the
    compensation backup and discards the staged artifact (it is installed)."""
    journal = _require_journal(user_key, artifact_digest, expect_status="awaiting-activation")
    if not _has_step(journal, "registry-ready"):
        raise PromotionError(
            "registry refresh has not been confirmed — nodes are never created "
            "before the registries can resolve them", 409)
    _record_step(journal, "nodes-created")
    journal["status"] = "completed"
    journal["backupHeld"] = False
    _save_journal(user_key, journal)
    _backup_path(user_key, artifact_digest).unlink(missing_ok=True)
    build_staging.discard_artifact(user_key, artifact_digest)
    return journal


def rollback(user_key: str, artifact_digest: str, reason: str) -> dict[str, Any]:
    """Compensate a promotion whose activation failed (dev/89 §3.10).

    Restores the held backup (extension) or uninstalls the fresh package
    (create), and removes a lockfile entry this promotion added. The outcome
    is honest: ``rolled-back`` when the prior state is restored,
    ``rollback-failed`` (with the error) when it is not — the caller's UI
    must tell the user which happened.
    """
    journal = _require_journal(user_key, artifact_digest, expect_status=None)
    if journal.get("status") == "completed":
        raise PromotionError(
            "promotion already completed — uninstall/extend it instead of "
            "rolling back", 409)
    with _target_lock(user_key, journal["target"]):
        _rollback_locked(user_key, journal, reason)
    return journal


def _rollback_locked(user_key: str, journal: dict[str, Any], reason: str) -> None:
    target = journal["target"]
    try:
        if journal.get("backupHeld"):
            backup_file = _backup_path(user_key, journal["artifactDigest"])
            if not backup_file.is_file():
                raise PromotionError(f"backup for {target} is missing", 500)
            install_package_from_archive(user_key, backup_file.read_bytes(), replace=True)
            if "priorSeedRecord" in journal:
                seed_state.put(user_key, target, journal["priorSeedRecord"])
        elif _has_step(journal, "installed"):
            uninstall_package(user_key, target)
        if journal.get("lockfileAdded") and journal.get("projectId"):
            current = packages_project_packages.get_project_lockfile(
                user_key, journal["projectId"])
            if target in current:
                current.discard(target)
                packages_project_packages._write_lockfile(user_key, journal["projectId"], current)
            journal["lockfileAdded"] = False
        journal["status"] = "rolled-back"
        journal["rollback"] = {"status": "rolled-back", "reason": reason}
    except Exception as exc:  # noqa: BLE001 — the outcome must be reported, not raised away
        journal["status"] = "rollback-failed"
        journal["rollback"] = {
            "status": "rollback-failed", "reason": reason,
            "error": str(exc)[:300],
        }
        log.exception("Promotion rollback failed for %s/%s", user_key, target)
    _save_journal(user_key, journal)


def _require_journal(
    user_key: str, artifact_digest: str, *, expect_status: str | None
) -> dict[str, Any]:
    journal = load_journal(user_key, artifact_digest)
    if journal is None:
        raise PromotionError(
            f"no promotion journal for artifact {artifact_digest[:12]}…", 404)
    if expect_status is not None and journal.get("status") != expect_status:
        raise PromotionError(
            f"promotion is {journal.get('status')!r}, expected {expect_status!r}",
            409)
    return journal
