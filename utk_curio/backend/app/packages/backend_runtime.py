"""The package backend sandbox runtime (memo dev/91 §3) — on-demand,
process-isolated execution of installed packages' declared handlers.

One invocation = one short-lived worker: the installed entry is
verify-on-read (digest-pinned at promote), copied with its ``backend/``
siblings into a fresh :mod:`build_workspace` (read-only ``input/``,
scrubbed from-scratch env, rlimits, process-group kill, capped output),
where the Curio-owned :mod:`backend_harness` speaks ``curio.pkgbackend.v1``
(:mod:`backend_contract` — the single spelling). The host process NEVER
imports the package's code. Nothing is resident: an exact-digest promote is
the whole upgrade story, and rollback is the promotion journal's (dev/91's
deliberate narrowing of Follow-up B).

The §0.1 Option-3 seam: the worker interpreter is a parameter
(``CURIO_BACKEND_SANDBOX_PYTHON``, default ``sys.executable``), and
``overlay_dir`` reserves the per-package ``pip --target`` overlay slot —
future dependency isolation is new parameter values, never a redesign.

Every invocation appends one audit row (sizes and outcomes, NEVER payload
contents) to the per-package day-file ledger under
``.curio/users/<key>/package-backend-ledger/<dir_name>/`` — append-only,
archived by the dev/87 retention sweep when the operator declares it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from utk_curio.backend.app.packages import backend_contract as bc
from utk_curio.backend.app.packages.build_workspace import (
    LIMITS_BY_TIMEOUT_CLASS,
    WorkerLimits,
    WorkerResult,
    create_workspace,
    destroy_workspace,
    populate_inputs,
    run_worker,
)
from utk_curio.backend.app.packages.manifest import ManifestError, load_packageage_manifest
from utk_curio.backend.app.packages.storage import (
    is_within,
    package_dir,
    user_packageages_dir,
)

log = logging.getLogger(__name__)

#: Concurrency bound (memo dev/91 §3.3): the sandbox never multiplies load
#: unboundedly. Waiters past the slot wait are refused loudly (503).
MAX_CONCURRENT_WORKERS = 2
_SLOT_WAIT_SECONDS = 10.0
_worker_slots = threading.BoundedSemaphore(MAX_CONCURRENT_WORKERS)

#: The persistent per-package data dir's byte cap (memo dev/91 §6.7): an
#: over-cap dir refuses the NEXT invocation until the handler (or an
#: uninstall) clears it.
DATA_DIR_MAX_BYTES = 64 * 1024 * 1024

#: Bounds on the backend/ tree copied into a workspace — installer caps are
#: wider; these keep a single invocation's input assembly cheap.
_BACKEND_TREE_MAX_FILES = 64
_BACKEND_TREE_MAX_BYTES = 8 * 1024 * 1024

_LEDGER_DIRNAME = "package-backend-ledger"
_DATA_DIRNAME = "package-backend-data"


class BackendRuntimeError(ValueError):
    """An invocation refusal/failure with an HTTP-ish status. Messages are
    sanitized (worker tails come pre-sanitized from the workspace) and name
    the fix where one exists (the dev/90 A4 refusal rule)."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def entry_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sandbox_interpreter() -> str:
    """The §0.1 Option-3 seam: operator-pinnable worker interpreter."""
    return (os.environ.get("CURIO_BACKEND_SANDBOX_PYTHON") or "").strip() or sys.executable


def _user_root(user_key: str) -> Path:
    return user_packageages_dir(user_key).parent


def _data_dir(user_key: str, dir_name: str) -> Path:
    return _user_root(user_key) / _DATA_DIRNAME / dir_name


def _ledger_dir(user_key: str, dir_name: str) -> Path:
    return _user_root(user_key) / _LEDGER_DIRNAME / dir_name


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def _append_ledger(user_key: str, dir_name: str, row: Mapping[str, Any]) -> None:
    """Best-effort append-only audit row — auditing must never take an
    invocation down, but a write failure is logged loudly."""
    try:
        day_dir = _ledger_dir(user_key, dir_name)
        day_dir.mkdir(parents=True, exist_ok=True)
        day_file = day_dir / (datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".jsonl")
        with open(day_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
    except OSError:
        log.warning("package-backend ledger append failed for %s/%s",
                    user_key, dir_name, exc_info=True)


def _harness_files() -> dict[str, bytes]:
    """The Curio-owned files every worker gets: harness + the ONE contract
    module (copied fresh per invocation — never taken from the package)."""
    here = Path(__file__).resolve().parent
    return {
        bc.HARNESS_FILENAME: (here / "backend_harness.py").read_bytes(),
        "backend_contract.py": (here / "backend_contract.py").read_bytes(),
    }


def invoke_from_files(
    files: Mapping[str, bytes],
    entry_rel: str,
    handler: str,
    payload: Any,
    *,
    net_allowed: bool,
    limits: WorkerLimits,
    data_dir: Path | None = None,
    overlay_dir: Path | None = None,
    cancel: threading.Event | None = None,
    build_id: str = "pkgbackend",
) -> tuple[dict[str, Any] | None, WorkerResult]:
    """Run ONE harness invocation over an explicit file map.

    The shared engine under both consumers: :func:`invoke_handler` (installed
    packages) and the build pipeline's probing phase (draft files — memo
    dev/91 §3, commit 3). Returns ``(reply_envelope_or_None, worker_result)``
    — the reply is ``None`` when the worker died without writing one; envelope
    validation errors raise :class:`~.backend_contract.BackendContractError`.
    """
    request = bc.build_request(handler, payload)  # BackendContractError → caller
    workspace = create_workspace(build_id)
    try:
        inputs: dict[str, bytes] = dict(_harness_files())
        inputs.update(files)
        inputs[bc.REQUEST_FILENAME] = request
        populate_inputs(workspace, inputs)
        extra_env = {
            "CURIO_PKG_ENTRY": entry_rel,
            "CURIO_PKG_NET_ALLOWED": "1" if net_allowed else "0",
        }
        if data_dir is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            extra_env["CURIO_PKG_DATA_DIR"] = str(data_dir)
        if overlay_dir is not None:
            # The reserved §0.1 Option-2 slot: a per-package pip --target
            # overlay rides PYTHONPATH — parameter values, not a redesign.
            extra_env["PYTHONPATH"] = str(overlay_dir)
        result = run_worker(
            workspace,
            [sandbox_interpreter(), str(workspace.input_dir / bc.HARNESS_FILENAME)],
            limits=limits,
            cancel=cancel,
            extra_env=extra_env,
        )
        reply_path = workspace.output_dir / bc.REPLY_FILENAME
        if not reply_path.is_file():
            return None, result
        envelope = bc.parse_reply(reply_path.read_bytes())
        return envelope, result
    finally:
        destroy_workspace(workspace)


def _backend_tree(pkg_path: Path) -> dict[str, bytes]:
    """The package's ``backend/`` files as workspace inputs, bounds-checked."""
    base = (pkg_path / "backend").resolve()
    files: dict[str, bytes] = {}
    total = 0
    if not base.is_dir():
        return files
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if not is_within(p.resolve(), base):
            raise BackendRuntimeError(
                "the package's backend/ tree escapes its directory — reinstall the package",
                409,
            )
        data = p.read_bytes()
        total += len(data)
        files[f"backend/{p.relative_to(base).as_posix()}"] = data
        if len(files) > _BACKEND_TREE_MAX_FILES or total > _BACKEND_TREE_MAX_BYTES:
            raise BackendRuntimeError(
                "the package's backend/ tree exceeds the invocation bounds "
                f"({_BACKEND_TREE_MAX_FILES} files / "
                f"{_BACKEND_TREE_MAX_BYTES // (1024 * 1024)} MiB)",
                502,
            )
    return files


def invoke_handler(
    user_key: str,
    dir_name: str,
    handler: str,
    payload: Any,
    *,
    expected_entry_digest: str | None = None,
    limits: WorkerLimits | None = None,
    overlay_dir: Path | None = None,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    """Invoke one declared handler of an installed package — the ONLY way
    package server code runs (memo dev/91 §8.1).

    Returns ``{"reply": <curio.pkgbackend.v1 envelope>, "invocationId",
    "durationMs", "limitsApplied", "entryDigest", "workerStatus"}``. Raises
    :class:`BackendRuntimeError` with the memo's status matrix: 404 unknown
    package/backend/handler, 409 digest drift, 413/422 payload bounds,
    503 no worker slot, 507 data dir over cap, 502 worker/contract failure.
    """
    invocation_id = uuid.uuid4().hex
    try:
        pkg_path = package_dir(user_key, dir_name)
    except Exception as exc:  # PackageIdError/PathTraversalError — bad name
        raise BackendRuntimeError(f"invalid package directory name: {exc}", 404) from exc
    if not pkg_path.is_dir():
        raise BackendRuntimeError(f"package {dir_name!r} is not installed", 404)
    try:
        manifest = load_packageage_manifest(pkg_path)
    except ManifestError as exc:
        raise BackendRuntimeError(
            f"package {dir_name!r} has an unreadable manifest — reinstall it ({exc})", 409
        ) from exc
    backend = manifest.backend
    if backend is None:
        raise BackendRuntimeError(
            f"package {dir_name!r} declares no backend surface", 404
        )
    timeout_class = backend.timeout_class_for(handler)
    if timeout_class is None:
        raise BackendRuntimeError(
            f"handler {handler!r} is not declared by {dir_name!r} "
            f"(declared: {backend.handler_names})", 404,
        )

    entry_path = (pkg_path / backend.entry).resolve()
    if not is_within(entry_path, pkg_path.resolve()) or not entry_path.is_file():
        raise BackendRuntimeError(
            f"the backend entry {backend.entry!r} is missing from the installed "
            "package — reinstall it", 409,
        )
    entry_bytes = entry_path.read_bytes()
    digest = entry_digest(entry_bytes)
    if expected_entry_digest and digest != expected_entry_digest:
        raise BackendRuntimeError(
            "the backend entry changed on disk since install (digest mismatch) — "
            "reinstall the package before invoking it", 409,
        )

    data_dir = _data_dir(user_key, dir_name)
    data_bytes = _dir_size_bytes(data_dir)
    if data_bytes > DATA_DIR_MAX_BYTES:
        raise BackendRuntimeError(
            f"the package's persistent data dir holds {data_bytes} bytes — over "
            f"the {DATA_DIR_MAX_BYTES // (1024 * 1024)} MiB cap; the handler (or an "
            "uninstall) must clear it before the next invocation", 507,
        )

    files = _backend_tree(pkg_path)
    net_allowed = bc.PERMISSION_SERVER_NETWORK in manifest.permissions
    worker_limits = limits or LIMITS_BY_TIMEOUT_CLASS.get(
        timeout_class, LIMITS_BY_TIMEOUT_CLASS["standard"]
    )

    if not _worker_slots.acquire(timeout=_SLOT_WAIT_SECONDS):
        raise BackendRuntimeError(
            "no backend worker slot became available — the sandbox runs at most "
            f"{MAX_CONCURRENT_WORKERS} workers; retry shortly", 503,
        )
    started = time.monotonic()
    row: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "invocationId": invocation_id,
        "handler": handler,
        "entryDigest": digest,
        "payloadBytes": None,
        "resultBytes": None,
        "dataDirBytes": data_bytes,
    }
    try:
        try:
            row["payloadBytes"] = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError):
            pass  # build_request refuses it below with the honest 422
        try:
            envelope, result = invoke_from_files(
                files, backend.entry, handler, payload,
                net_allowed=net_allowed, limits=worker_limits,
                data_dir=data_dir, overlay_dir=overlay_dir, cancel=cancel,
                build_id=f"pkgbackend-{invocation_id[:8]}",
            )
        except bc.BackendContractError as exc:
            status = 413 if "bound" in str(exc) else 422
            row.update(status="refused", error=str(exc))
            raise BackendRuntimeError(str(exc), status) from exc
        row["workerStatus"] = result.status
        row["durationMs"] = int(result.duration_seconds * 1000)
        row["limitsApplied"] = list(result.limits_applied)
        if result.status != "ok":
            row["status"] = "worker-" + result.status
            detail = result.stderr_tail or result.stdout_tail
            raise BackendRuntimeError(
                f"the backend worker did not complete ({result.status})"
                + (f": {detail}" if detail else ""), 502,
            )
        if envelope is None:
            row["status"] = "no-reply"
            detail = result.stderr_tail or result.stdout_tail
            raise BackendRuntimeError(
                "the backend worker exited without a reply envelope"
                + (f": {detail}" if detail else ""), 502,
            )
        row["status"] = "ok" if envelope["ok"] else f"reply-{envelope.get('kind')}"
        row["resultBytes"] = len(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
        return {
            "reply": envelope,
            "invocationId": invocation_id,
            "durationMs": row["durationMs"],
            "limitsApplied": row["limitsApplied"],
            "entryDigest": digest,
            "workerStatus": result.status,
        }
    except bc.BackendContractError as exc:
        # parse_reply on the worker's reply file — raw bytes never pass.
        row["status"] = "bad-reply"
        row["error"] = str(exc)
        raise BackendRuntimeError(f"the backend reply violated the contract: {exc}", 502) from exc
    finally:
        _worker_slots.release()
        row.setdefault("durationMs", int((time.monotonic() - started) * 1000))
        _append_ledger(user_key, dir_name, row)
