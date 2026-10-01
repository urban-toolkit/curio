"""The ``curio.pkgbackend.v1`` envelope — ONE contract module (memo dev/91).

Generated server-side package code never runs in the Curio host process:
each invocation spawns a short-lived, resource-limited worker (memo dev/91
§3) that receives a request envelope and writes a reply envelope. Every
party — the HTTP route, the runtime, the child-side harness, the build-time
probe, and the Package Builder's prompt contract — speaks the shapes defined
HERE and nowhere else (the dev/90 A15 lesson: a contract stated in two
places WILL drift; this module is the single spelling).

Request (written to the worker's ``input/payload.json``)::

    {"contract": "curio.pkgbackend.v1", "handler": "<name>", "payload": <JSON>}

Reply (written by the harness to ``output/reply.json``)::

    {"contract": "curio.pkgbackend.v1", "ok": true,  "result": <JSON>}
    {"contract": "curio.pkgbackend.v1", "ok": false, "error": "<text>",
     "kind": "handler-error" | "contract-error"}

Runner-level failures (timeout, output-limit, kill) are reported by the
runtime from ``WorkerResult.status`` — a handler can never invent them.

The probe: every declared handler must answer the synthetic probe payload
(``{"__probe__": true}``) with ``ok: true``. The build pipeline's probing
phase sends it before a draft may reach review, and Apply-time health checks
reuse the same request.
"""

from __future__ import annotations

import json
import re
from typing import Any

PKGBACKEND_CONTRACT_VERSION = "curio.pkgbackend.v1"

#: Handler names are template-id-shaped: short, lowercase, hyphenated.
HANDLER_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

#: The worker-limit tiers a handler may declare (mapped onto the build
#: workspace's ``LIMITS_BY_TIMEOUT_CLASS`` — no new limit vocabulary).
TIMEOUT_CLASSES = ("quick", "standard")
DEFAULT_TIMEOUT_CLASS = "standard"

#: Manifest permission strings a backend-bearing package must declare
#: (surfaced in the install review — memo dev/91 §5).
PERMISSION_SERVER_CODE = "server-code"
PERMISSION_SERVER_NETWORK = "server-network"

#: Size bounds (memo dev/91 §3/§6): checked at the route before any worker
#: spawns, and on the reply before anything reaches the client.
PAYLOAD_MAX_BYTES = 2 * 1024 * 1024
RESULT_MAX_BYTES = 8 * 1024 * 1024
ERROR_TEXT_MAX_CHARS = 4000

#: A payload nested deeper than this is refused up front (json.loads happily
#: builds it; handlers and audits should never see pathological shapes).
PAYLOAD_MAX_DEPTH = 32

#: The synthetic health-check payload every handler must accept.
PROBE_KEY = "__probe__"

REPLY_KINDS = ("handler-error", "contract-error")

#: The workers' filenames — shared by runtime, harness, and probe.
REQUEST_FILENAME = "payload.json"
REPLY_FILENAME = "reply.json"
HARNESS_FILENAME = "backend_harness.py"


class BackendContractError(ValueError):
    """An envelope violated ``curio.pkgbackend.v1``. Messages are safe to
    surface: they describe the contract, never worker internals."""


def probe_payload() -> dict[str, Any]:
    return {PROBE_KEY: True}


def is_probe(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get(PROBE_KEY) is True


def json_depth(value: object, _depth: int = 1) -> int:
    """Depth of a decoded JSON value (scalars = 1)."""
    if isinstance(value, dict):
        return _depth if not value else max(json_depth(v, _depth + 1) for v in value.values())
    if isinstance(value, list):
        return _depth if not value else max(json_depth(v, _depth + 1) for v in value)
    return _depth


def build_request(handler: str, payload: Any) -> bytes:
    """Serialize a request envelope, enforcing the payload bounds.

    Raises :class:`BackendContractError` on an invalid handler name, an
    unserializable/oversized payload, or pathological nesting — the caller
    turns these into the 413/422 route responses (memo dev/91 §6.11).
    """
    if not isinstance(handler, str) or not HANDLER_NAME_RE.match(handler):
        raise BackendContractError(
            f"handler name must match {HANDLER_NAME_RE.pattern}"
        )
    try:
        payload_text = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise BackendContractError(f"payload is not JSON-serializable: {exc}") from exc
    if len(payload_text.encode("utf-8")) > PAYLOAD_MAX_BYTES:
        raise BackendContractError(
            f"payload exceeds the {PAYLOAD_MAX_BYTES // (1024 * 1024)} MiB request bound"
        )
    if json_depth(payload) > PAYLOAD_MAX_DEPTH:
        raise BackendContractError(
            f"payload nests deeper than {PAYLOAD_MAX_DEPTH} levels"
        )
    envelope = {
        "contract": PKGBACKEND_CONTRACT_VERSION,
        "handler": handler,
        "payload": payload,
    }
    return json.dumps(envelope, ensure_ascii=False).encode("utf-8")


def error_reply(kind: str, error: str) -> dict[str, Any]:
    """A well-formed failure reply (used by the harness and the runtime)."""
    if kind not in REPLY_KINDS:
        raise BackendContractError(f"reply kind must be one of {REPLY_KINDS}")
    return {
        "contract": PKGBACKEND_CONTRACT_VERSION,
        "ok": False,
        "error": str(error)[:ERROR_TEXT_MAX_CHARS],
        "kind": kind,
    }


def parse_reply(raw: bytes) -> dict[str, Any]:
    """Validate a reply envelope from a worker.

    Returns the decoded envelope. Raises :class:`BackendContractError` for
    every violation — the raw worker bytes NEVER reach a client on failure.
    """
    if len(raw) > RESULT_MAX_BYTES:
        raise BackendContractError(
            f"reply exceeds the {RESULT_MAX_BYTES // (1024 * 1024)} MiB result bound"
        )
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackendContractError(f"reply is not valid JSON: {exc}") from exc
    if not isinstance(envelope, dict):
        raise BackendContractError("reply must be a JSON object")
    if envelope.get("contract") != PKGBACKEND_CONTRACT_VERSION:
        raise BackendContractError(
            f"reply.contract must be {PKGBACKEND_CONTRACT_VERSION!r}"
        )
    ok = envelope.get("ok")
    if not isinstance(ok, bool):
        raise BackendContractError("reply.ok must be a boolean")
    if ok:
        if "result" not in envelope:
            raise BackendContractError("a successful reply must carry 'result'")
        return {"contract": PKGBACKEND_CONTRACT_VERSION, "ok": True,
                "result": envelope["result"]}
    error = envelope.get("error")
    kind = envelope.get("kind")
    if not isinstance(error, str) or not error:
        raise BackendContractError("a failure reply must carry a non-empty 'error'")
    if kind not in REPLY_KINDS:
        raise BackendContractError(f"reply.kind must be one of {REPLY_KINDS}")
    return {"contract": PKGBACKEND_CONTRACT_VERSION, "ok": False,
            "error": error[:ERROR_TEXT_MAX_CHARS], "kind": kind}
