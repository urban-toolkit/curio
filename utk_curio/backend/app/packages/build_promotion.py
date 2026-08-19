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
import threading
import time
from pathlib import Path
from typing import Any

from utk_curio.backend.app.packages import build_staging
from utk_curio.backend.app.packages.build_extension import installed_package_digest
from utk_curio.backend.app.packages.build_packager import PackagerError, validate_archive
from utk_curio.backend.app.packages.build_staging import StagingError
from utk_curio.backend.app.packages.installer import (
    InstallerError,
    export_packageage_archive,
    install_packageage_from_archive,
    uninstall_packageage,
)
from utk_curio.backend.app.packages.storage import _user_key_segment, _users_base

log = logging.getLogger(__name__)

PROMOTION_CONTRACT_VERSION = "1"

STEP_ORDER = (
    "verified", "backed-up", "installed", "lockfile-updated",
    "registry-ready", "nodes-created",
)

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


# In-process serialization per (user, target): two promotions racing the same
# coordinate run one at a time; the base-digest check keeps cross-process
# races correct (the loser sees a stale base).
_LOCKS_GUARD = threading.Lock()
_TARGET_LOCKS: dict[tuple[str, str], threading.Lock] = {}


def _target_lock(user_key: str, target: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _TARGET_LOCKS.setdefault((user_key, target), threading.Lock())


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
    """
    with _target_lock(user_key, target):
        existing = load_journal(user_key, artifact_digest)
        if existing is not None:
            if existing.get("status") in _ACTIVE_STATUSES + ("completed",):
                if existing.get("target") != target:
                    raise PromotionError(
                        f"artifact {artifact_digest[:12]}… was promoted for "
                        f"{existing.get('target')!r}, not {target!r}", 409)
                return existing
            # failed / rolled-back journals are superseded by a fresh attempt.

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
        _save_journal(user_key, journal)

        if installed_digest is not None:
            backup = export_packageage_archive(user_key, target)
            _backup_path(user_key, artifact_digest).write_bytes(backup)
            journal["backupHeld"] = True
            journal["priorDigest"] = installed_digest
            _record_step(journal, "backed-up")
            _save_journal(user_key, journal)

        try:
            install_packageage_from_archive(
                user_key, archive, replace=installed_digest is not None)
        except InstallerError as exc:
            journal["status"] = "failed"
            journal["error"] = f"install failed: {exc}"
            _save_journal(user_key, journal)
            raise PromotionError(f"install failed: {exc}", 422) from exc
        _record_step(journal, "installed")
        _save_journal(user_key, journal)

        # Python deps install at Apply — the reviewed installer step the
        # build phase deliberately never ran (dev/89 §3.4). A pip failure
        # compensates immediately.
        py_deps = dict(manifest.python_deps or {})
        if py_deps:
            from utk_curio.backend.app.packages import pip_runner

            try:
                pip_runner.install_python_deps(py_deps)
            except pip_runner.PipInstallError as exc:
                journal["error"] = f"pip install failed: {exc}"
                _save_journal(user_key, journal)
                _rollback_locked(user_key, journal, f"pip install failed: {exc}")
                raise PromotionError(
                    "python dependency install failed and the prior state was "
                    f"{'restored' if journal['rollback']['status'] == 'rolled-back' else 'NOT fully restored — manual repair required'}: {exc}",
                    502) from exc

        if project_id is not None:
            from utk_curio.backend.app.packages import services as packages_services

            already = target in packages_services.get_project_lockfile(user_key, project_id)
            try:
                packages_services.install_to_project(user_key, project_id, target)
            except packages_services.PackageServiceError as exc:
                journal["error"] = f"lockfile update failed: {exc}"
                _save_journal(user_key, journal)
                _rollback_locked(user_key, journal, f"lockfile update failed: {exc}")
                raise PromotionError(
                    f"project lockfile update failed: {exc}", exc.status) from exc
            journal["lockfileAdded"] = not already
            _record_step(journal, "lockfile-updated")

        journal["status"] = "awaiting-activation"
        _save_journal(user_key, journal)
        return journal


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
            install_packageage_from_archive(user_key, backup_file.read_bytes(), replace=True)
        elif _has_step(journal, "installed"):
            uninstall_packageage(user_key, target)
        if journal.get("lockfileAdded") and journal.get("projectId"):
            from utk_curio.backend.app.packages import services as packages_services
            from utk_curio.backend.app.packages.services import _write_lockfile

            current = packages_services.get_project_lockfile(
                user_key, journal["projectId"])
            if target in current:
                current.discard(target)
                _write_lockfile(user_key, journal["projectId"], current)
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
