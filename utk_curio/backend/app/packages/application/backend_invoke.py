"""One sandboxed invocation of a declared package backend handler (memo dev/91 §3) — the ONLY caller surface for package server code: the promote/install-time entry pin gates verify-on-read.

Application layer of the packages package (memo dev/143, B2-b): lifted out of ``routes.py`` so handlers
parse, call and serialize and carry no rules; every function keeps its body.
"""

from __future__ import annotations

import logging
from typing import Any

from utk_curio.backend.app.packages.infrastructure import backend_runtime as packages_backend_runtime

log = logging.getLogger(__name__)


def _owners_store(owners, dir_name: str) -> str | None:
    """The dataflow owner's store key when the dataflow uses *dir_name*
    (*owners*), else None: the caller's own store answers."""
    if owners is None:
        return None
    try:
        return owners.store_key if owners.uses(dir_name) else None
    except Exception as exc:  # noqa: BLE001 - the caller's own store still answers
        log.warning("Could not read the packages dataflow %s uses: %s", owners.project_id, exc)
        return None


def invoke_backend_handler(user_key: str, dir_name: str, handler: str, payload: Any, *, owners=None) -> dict:
    """Run *handler* of *dir_name* in a per-invocation sandboxed worker (never in
    this process), against the pinned entry digest. ``BackendRuntimeError``
    propagates with its status for the route to answer; a well-formed
    ``ok: false`` reply is a 200: the envelope IS the diagnosis.

    With *owners* (``project_packages.OwnersPackages``), the call is one of an
    editor the owner of a dataflow invited, on that dataflow: a package the
    dataflow uses runs as the owner's copy, with its pin, from her store, by
    the rule a run's modules follow; any other package from *user_key*'s."""
    package_key = _owners_store(owners, dir_name)
    pin = packages_backend_runtime.pinned_entry_digest(package_key or user_key, dir_name)
    out = packages_backend_runtime.invoke_handler(
        user_key, dir_name, handler, payload,
        expected_entry_digest=pin,
        **({"package_key": package_key} if package_key else {}),
    )
    return {
        "reply": out["reply"],
        "invocationId": out["invocationId"],
        "durationMs": out["durationMs"],
        "limitsApplied": out["limitsApplied"],
        "entryDigest": out["entryDigest"],
    }
