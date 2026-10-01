"""One sandboxed invocation of a declared package backend handler (memo dev/91 §3) — the ONLY caller surface for package server code: the promote/install-time entry pin gates verify-on-read.

Application layer of the packages package (memo dev/143, B2-b): lifted out of ``routes.py`` so handlers
parse, call and serialize and carry no rules; every function keeps its body.
"""

from __future__ import annotations

from typing import Any

from utk_curio.backend.app.packages.infrastructure import backend_runtime as packages_backend_runtime


def invoke_backend_handler(user_key: str, dir_name: str, handler: str, payload: Any) -> dict:
    """Run *handler* of *dir_name* in a per-invocation sandboxed worker (never in
    this process), against the pinned entry digest. ``BackendRuntimeError``
    propagates with its status for the route to answer; a well-formed
    ``ok: false`` reply is a 200 — the envelope IS the diagnosis."""
    pin = packages_backend_runtime.pinned_entry_digest(user_key, dir_name)
    out = packages_backend_runtime.invoke_handler(
        user_key, dir_name, handler, payload,
        expected_entry_digest=pin,
    )
    return {
        "reply": out["reply"],
        "invocationId": out["invocationId"],
        "durationMs": out["durationMs"],
        "limitsApplied": out["limitsApplied"],
        "entryDigest": out["entryDigest"],
    }
