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
from utk_curio.backend.app.packages.target_locks import target_lock

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
# dev/97: the per-package dependency overlay (§0.1 Option 2 delivered) —
# built at Apply via pip --target (wipe-before-build), handed to workers on
# PYTHONPATH, swept at uninstall. Derived state: rebuilt from the manifest
# at every promote, never edited in place.
_OVERLAY_DIRNAME = "package-backend-overlays"

#: dev/92 B-3 — the crash-loop quarantine breaker. Counted per
#: (user, package, handler): only INFRASTRUCTURE failures count
#: (worker timeout/kill/nonzero-exit, missing or contract-violating reply);
#: a well-formed ``handler-error`` reply is the handler working as designed
#: and never trips it. In-process by design — a server restart clears the
#: breaker, which is the correct semantic anyway; the ledger keeps history.
QUARANTINE_THRESHOLD = 3
QUARANTINE_SECONDS = 120.0
_now = time.monotonic  # test seam (injectable clock)
_breaker_guard = threading.Lock()
_breakers: dict[tuple[str, str, str], dict[str, Any]] = {}


def reset_breakers() -> None:
    """Test seam: drop all quarantine state."""
    with _breaker_guard:
        _breakers.clear()


def _breaker_check(key: tuple[str, str, str], pin: str) -> float | None:
    """Remaining quarantine seconds for *key*, or None when invocable.

    A changed entry pin (reinstall/promote) resets the breaker immediately —
    new code deserves a fresh start. An expired cooldown goes HALF-OPEN: the
    call proceeds, the consecutive counter is kept, and one more
    infrastructure failure re-quarantines at once."""
    with _breaker_guard:
        state = _breakers.get(key)
        if state is None:
            return None
        if state.get("pin") != pin:
            del _breakers[key]
            return None
        remaining = state.get("until", 0.0) - _now()
        return remaining if remaining > 0 else None


def _breaker_record(key: tuple[str, str, str], pin: str, *,
                    infrastructure_failure: bool) -> None:
    with _breaker_guard:
        if not infrastructure_failure:
            _breakers.pop(key, None)
            return
        state = _breakers.get(key)
        if state is None or state.get("pin") != pin:
            state = {"pin": pin, "consecutive": 0, "until": 0.0}
            _breakers[key] = state
        state["consecutive"] += 1
        if state["consecutive"] >= QUARANTINE_THRESHOLD:
            state["until"] = _now() + QUARANTINE_SECONDS


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


def overlay_dir_for(user_key: str, dir_name: str) -> Path:
    """dev/97: the package's dependency-overlay home (existence = the
    package has isolated handler deps; invocation auto-resolves it)."""
    return _user_root(user_key) / _OVERLAY_DIRNAME / dir_name


#: dev/97: overlay size cap — handler overlays are for small pure-Python
#: deps; torch-scale trees fail the promote honestly (operator-tunable).
OVERLAY_MAX_MB_ENV = "CURIO_BACKEND_OVERLAY_MAX_MB"
OVERLAY_DEFAULT_MAX_MB = 512


def overlay_max_bytes() -> int:
    raw = (os.environ.get(OVERLAY_MAX_MB_ENV) or "").strip()
    try:
        mb = int(raw) if raw else OVERLAY_DEFAULT_MAX_MB
    except ValueError:
        mb = OVERLAY_DEFAULT_MAX_MB
    return max(1, mb) * 1024 * 1024


def _dep_route(has_backend: bool, has_warm_python: bool) -> tuple[str, str]:
    """dev/97: THE routing rule, one core with two manifest adapters below —
    ``"overlay"`` for a backend-bearing package (handlers are the consumer;
    workers see PYTHONPATH), ``"both"`` when the same manifest ALSO carries a
    python-engine ``hasCode`` template (its node code runs in the warm
    sandbox, which cannot see overlays), ``"host"`` when there is no backend.
    Derived — no new schema key; ``dependencies.python`` stays the one
    declaration."""
    if not has_backend:
        return "host", "no backend surface — deps serve the warm sandbox"
    if has_warm_python:
        return "both", (
            "backend handlers use the isolated overlay; the package's python "
            "node templates also need the shared interpreter"
        )
    return "overlay", (
        "backend handlers only — the shared interpreter is not touched"
    )


def dep_destinations(manifest) -> tuple[str, str]:
    """The routing rule over a TYPED ``PackageManifest``."""
    return _dep_route(
        manifest.backend is not None,
        any(t.engine == "python" and t.has_code for t in manifest.templates),
    )


def dep_destinations_raw(manifest: Mapping[str, Any]) -> tuple[str, str]:
    """The routing rule over a RAW draft-manifest dict (the dev/96 card
    composer's input) — same core, so the card can never disagree with the
    promote (the A15 one-spelling rule)."""
    templates = manifest.get("templates") or []
    return _dep_route(
        bool(manifest.get("backend")),
        any(isinstance(t, dict) and t.get("engine") == "python"
            and bool(t.get("hasCode")) for t in templates),
    )


def build_overlay(user_key: str, dir_name: str, deps: dict,
                  on_line=None) -> dict[str, Any]:
    """dev/97: wipe-and-rebuild the package's dependency overlay via the ONE
    pip primitive. Returns ``{"libs": [specs], "bytes": n}``; raises
    :class:`~.pip_runner.PipInstallError` on pip failure and
    :class:`BackendRuntimeError` (507) when the built overlay exceeds the
    operator cap — the caller compensates (promotion rollback). The overlay
    is derived state: never edited in place, a crashed write cannot go stale
    because the next build wipes first."""
    import shutil

    from utk_curio.backend.app.packages import pip_runner

    overlay = overlay_dir_for(user_key, dir_name)
    if overlay.is_dir():
        shutil.rmtree(overlay)
    overlay.mkdir(parents=True, exist_ok=True)
    try:
        report = pip_runner.install_python_deps_to_target(
            deps, str(overlay), on_line=on_line)
    except pip_runner.PipInstallError:
        shutil.rmtree(overlay, ignore_errors=True)  # never leave a half-build
        raise
    size = _dir_size_bytes(overlay)
    cap = overlay_max_bytes()
    if size > cap:
        shutil.rmtree(overlay, ignore_errors=True)
        raise BackendRuntimeError(
            f"the built dependency overlay is {size // (1024 * 1024)} MiB — over "
            f"the {cap // (1024 * 1024)} MiB cap ({OVERLAY_MAX_MB_ENV}); "
            "torch-scale dependencies do not fit a handler overlay", 507,
        )
    return {"libs": list(report.installed), "bytes": size}


def remove_backend_residue(user_key: str, dir_name: str) -> dict[str, bool]:
    """dev/97: the uninstall sweep dev/91 §6.7 promised — overlay, data dir,
    and pin entry go; the invocation LEDGER deliberately survives (append-only
    audit history is retention's to expire, never uninstall's). Best-effort
    per item, loud on failure, returns what was actually removed."""
    import shutil

    removed = {"overlay": False, "dataDir": False, "pin": False}
    for key, path in (("overlay", overlay_dir_for(user_key, dir_name)),
                      ("dataDir", _data_dir(user_key, dir_name))):
        if path.is_dir():
            try:
                shutil.rmtree(path)
                removed[key] = True
            except OSError:
                log.warning("backend residue: could not remove %s", path, exc_info=True)
    pins_path = _pins_path(user_key)
    try:
        pins = json.loads(pins_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pins = None
    if isinstance(pins, dict) and dir_name in pins:
        pins.pop(dir_name)
        try:
            pins_path.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
            removed["pin"] = True
        except OSError:
            log.warning("backend residue: could not rewrite %s", pins_path, exc_info=True)
    return removed


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


_PINS_FILENAME = "package-backend-pins.json"


def _pins_path(user_key: str) -> Path:
    return _user_root(user_key) / _PINS_FILENAME


def record_entry_pin(user_key: str, dir_name: str) -> str | None:
    """Pin the installed package's backend entry digest (memo dev/91 §3.1) —
    called by both install authorities (build promotion and the catalog
    install) right after files land, so invocation-time verify-on-read has a
    truth to check. Returns the recorded digest, or None (and clears any
    stale pin) when the package declares no backend."""
    try:
        pkg_path = package_dir(user_key, dir_name)
        manifest = load_packageage_manifest(pkg_path)
    except Exception:  # noqa: BLE001 — pinning never breaks an install
        log.warning("backend pin: could not read %s/%s", user_key, dir_name, exc_info=True)
        return None
    pins_path = _pins_path(user_key)
    try:
        pins = json.loads(pins_path.read_text(encoding="utf-8"))
        if not isinstance(pins, dict):
            pins = {}
    except (OSError, ValueError):
        pins = {}
    digest: str | None = None
    if manifest.backend is None:
        pins.pop(dir_name, None)  # a backend-less reinstall clears stale pins
    else:
        entry_path = (pkg_path / manifest.backend.entry).resolve()
        if not is_within(entry_path, pkg_path.resolve()) or not entry_path.is_file():
            log.warning("backend pin: %s missing declared entry %s",
                        dir_name, manifest.backend.entry)
            return None
        digest = entry_digest(entry_path.read_bytes())
        pins[dir_name] = digest
    try:
        pins_path.parent.mkdir(parents=True, exist_ok=True)
        pins_path.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    except OSError:
        log.warning("backend pin: could not persist %s", pins_path, exc_info=True)
        return None
    return digest


def pinned_entry_digest(user_key: str, dir_name: str) -> str | None:
    """The promote/install-time pin for verify-on-read; None = unpinned
    (a hand-placed dev package — invocation still digests and records)."""
    try:
        pins = json.loads(_pins_path(user_key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = pins.get(dir_name) if isinstance(pins, dict) else None
    return value if isinstance(value, str) and value else None


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
    # dev/92 B-1: the whole READ phase — manifest, pin verify, entry/tree
    # copies into memory — runs under the SAME per-target lock promotes hold,
    # so an invocation never observes the installer's non-atomic rmtree+move
    # window or a files-vs-pin mismatch. Microseconds of hold time; the
    # sandbox worker always runs OUTSIDE the lock.
    with target_lock(user_key, dir_name):
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
        # dev/97: auto-resolve the package's dependency overlay INSIDE the
        # B-1 lock (a promote wiping/rebuilding it holds the same lock, so an
        # invocation never sees a half-built overlay). The explicit parameter
        # stays the test seam and always wins.
        if overlay_dir is None:
            candidate = overlay_dir_for(user_key, dir_name)
            if candidate.is_dir():
                overlay_dir = candidate
    worker_limits = limits or LIMITS_BY_TIMEOUT_CLASS.get(
        timeout_class, LIMITS_BY_TIMEOUT_CLASS["standard"]
    )

    # dev/92 B-3: the quarantine breaker gates BEFORE any slot or worker is
    # spent — a crash-looping handler stops burning wall-clock per click. The
    # check runs after pin verification so a reinstall's new digest resets it.
    breaker_key = (user_key, dir_name, handler)
    remaining = _breaker_check(breaker_key, digest)
    if remaining is not None:
        wait_s = int(remaining) + 1
        _append_ledger(user_key, dir_name, {
            "ts": datetime.now(timezone.utc).isoformat(),
            "invocationId": invocation_id,
            "handler": handler,
            "entryDigest": digest,
            "status": "quarantined",
            "cooldownRemainingSeconds": wait_s,
        })
        raise BackendRuntimeError(
            f"handler {handler!r} is quarantined after "
            f"{QUARANTINE_THRESHOLD} consecutive worker failures — retries "
            f"resume in {wait_s}s; a reinstall clears it immediately", 503,
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
        # dev/92 B-3: ONE classification, two consumers — the ledger's status
        # taxonomy drives the breaker. Infrastructure failures count; ok and
        # well-formed reply-* envelopes reset; a refused payload (413/422)
        # says nothing about the worker and touches neither.
        status_val = row.get("status")
        if isinstance(status_val, str) and status_val != "refused":
            _breaker_record(breaker_key, digest, infrastructure_failure=(
                status_val.startswith("worker-")
                or status_val in ("no-reply", "bad-reply")))
        _append_ledger(user_key, dir_name, row)
