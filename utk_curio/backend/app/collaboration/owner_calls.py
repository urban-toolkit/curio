"""A change to a dataflow, made by the backend process that owns it
(``owner_guard.py``), whichever process was asked for it.

Most requests name one dataflow, and the router sends them to its owner. A
change made for an account names none: an agent, a package or a dataset added
to all projects or removed from the account, a dataset's id migrated, a
dataflow made. Its request reaches any process, and it writes dataflows any
process may own. Each such change is an operation on one dataflow
(:func:`operation`), which :func:`run` makes here when this process owns the
dataflow, and otherwise sends to the owner: a POST to
``/internal/dataflows/<dataflow>/<operation>`` on 127.0.0.1 at the owner's port
(``backend_processes.port_of``), signed with the start's secret
(``backend_processes.token``). The owner makes it and answers with what the
operation returned, or with the error it raised, which is raised again here
as the operation's own error.

The route lies outside ``/api``, which is all the site's proxy sends the
backend. It refuses a call without the secret, an operation it does not know,
and a dataflow it does not own: an owner never sends a change on.

A call is never made while this thread holds the dataflow's spec lock, which
the owner takes to make the change across processes, nor while it holds a
database write not committed, which the owner's own write would wait for
(#909): either would wait until the call gave up.
"""

from __future__ import annotations

import hmac
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from flask import Blueprint, jsonify, request

from utk_curio.backend.app.collaboration import owner_guard
from utk_curio.common import backend_processes

logger = logging.getLogger(__name__)

#: The header the start's secret travels in.
TOKEN_HEADER = "X-Curio-Backend-Token"
#: How long a call waits for the owner to make its change.
CALL_TIMEOUT_S = 300.0

owner_calls_bp = Blueprint("owner_calls", __name__)

#: Never through a proxy the environment names: the owner is on 127.0.0.1.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OwnerCallFailed(RuntimeError):
    """A change its owner could not be reached for, refused, or failed with
    an error of no feature's: its message, and the status a route answers."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class _Operation:
    name: str
    run: Callable
    error: Optional[Callable]


_operations: dict[str, _Operation] = {}


def operation(name: str, *, error: Optional[Callable] = None):
    """Make the decorated function, ``fn(user_key, dataflow_id, **arguments)``,
    the operation *name*: a change to one dataflow of the store *user_key*
    that the dataflow's owner makes, whichever process :func:`run` is asked
    in. Its arguments and what it returns travel as JSON. *error*, a feature's
    error made from a message and a status, is raised again in the sender
    with what the owner's raised."""

    def register(fn):
        _operations[name] = _Operation(name, fn, error)
        fn.owner_operation = name
        return fn

    return register


def operations() -> list[str]:
    """The operations this process makes when another sends one."""
    return sorted(_operations)


def path_of(dataflow_id: str, name: str) -> str:
    """The owner's route for the operation *name* on *dataflow_id*."""
    return f"/internal/dataflows/{dataflow_id}/{name}"


def run(fn, user_key, dataflow_id: str, **arguments):
    """Make the operation *fn* (:func:`operation`) on the dataflow
    *dataflow_id* of the store *user_key*: here when this process owns it,
    else by its owner. What it returned, or its error."""
    known = _operations.get(getattr(fn, "owner_operation", None) or "")
    if known is None or known.run is not fn:
        raise TypeError(f"{fn!r} is no operation a dataflow's owner makes")
    owner = owner_guard.elsewhere(dataflow_id, user_key)
    if owner is None:
        return fn(user_key, dataflow_id, **arguments)
    return _sent(owner, known, str(user_key), dataflow_id, arguments)


def _sent(owner: int, op: _Operation, user_key: str, dataflow_id: str, arguments: dict):
    """The operation *op* made by the process *owner*: its answer, or its
    error raised again."""
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.extensions import session_holds_write_lock

    asked = f"{op.name} of dataflow {dataflow_id}, which process {owner} owns,"
    if storage.holds_spec_lock(user_key, dataflow_id):
        raise OwnerCallFailed(f"{asked} was asked while this thread holds the dataflow's spec lock, "
                              "which its owner takes to make it", 500)
    if session_holds_write_lock():
        raise OwnerCallFailed(f"{asked} was asked while this thread holds a database write not committed, "
                              "which its owner's write would wait for", 500)
    secret = backend_processes.token()
    if not secret:
        raise OwnerCallFailed(f"{asked} cannot be sent: {backend_processes.TOKEN_VARIABLE} is not set", 500)
    try:
        port = backend_processes.port_of(owner)
    except ValueError as exc:
        raise OwnerCallFailed(f"{asked} cannot be sent: {exc}", 500) from None
    owner_guard.sent(op.name, dataflow_id, owner)
    call = urllib.request.Request(
        f"http://127.0.0.1:{port}{path_of(dataflow_id, op.name)}", method="POST",
        data=json.dumps({"account": user_key, "arguments": arguments}).encode("utf-8"),
        headers={"Content-Type": "application/json", TOKEN_HEADER: secret},
    )
    try:
        with _OPENER.open(call, timeout=CALL_TIMEOUT_S) as reply:
            answer = json.loads(reply.read() or b"{}")
    except urllib.error.HTTPError as exc:
        refusal = _error_of(exc)
        raise OwnerCallFailed(f"{asked} was refused there: {refusal}", exc.code) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise OwnerCallFailed(f"{asked} got no answer from it: {exc}", 503) from None
    if answer.get("ok"):
        return answer.get("result")
    message, status = str(answer.get("error") or "the change failed"), int(answer.get("status") or 500)
    if op.error is not None:
        raise op.error(message, status)
    raise OwnerCallFailed(message, status)


def _error_of(exc: urllib.error.HTTPError) -> str:
    try:
        return str(json.loads(exc.read() or b"{}").get("error") or exc.reason)
    except (OSError, ValueError, AttributeError):
        return str(exc.reason)


def _status_of(exc: BaseException) -> int:
    for name in ("status", "status_code", "code"):
        value = getattr(exc, name, None)
        if isinstance(value, int) and 400 <= value <= 599:
            return value
    return 500


@owner_calls_bp.route("/internal/dataflows/<dataflow_id>/<name>", methods=["POST"])
def made_here(dataflow_id: str, name: str):
    """An operation another backend process of this start sends the owner of
    *dataflow_id* (:func:`run`): made here, and answered with what it returned
    or the error it raised, as ``{ok, result}`` or ``{ok, error, status}``."""
    if backend_processes.process_count() <= 1:
        return jsonify({"ok": False, "error": "a start of one backend process takes no call from another"}), 404
    secret = backend_processes.token()
    given = request.headers.get(TOKEN_HEADER) or ""
    if not secret or not hmac.compare_digest(given.encode("utf-8"), secret.encode("utf-8")):
        return jsonify({"ok": False, "error": "not signed with this start's secret"}), 403
    op = _operations.get(name)
    if op is None:
        return jsonify({"ok": False, "error": f"no operation {name!r}"}), 404
    body = request.get_json(silent=True) or {}
    user_key, arguments = body.get("account"), body.get("arguments") or {}
    if not isinstance(user_key, str) or not user_key or not isinstance(arguments, dict):
        return jsonify({"ok": False, "error": "a call names its account and its arguments"}), 400
    try:
        owner_guard.refuse(dataflow_id, user_key, what=f"{name}, sent by another process,")
    except owner_guard.NotTheOwner as exc:
        return jsonify({"ok": False, "error": exc.description}), 421
    try:
        result = op.run(user_key, dataflow_id, **arguments)
    except Exception as exc:  # noqa: BLE001 - the sender raises it again
        status = _status_of(exc)
        if status >= 500:
            logger.exception("[owner-guard] %s of dataflow %s, sent by another process, failed", name, dataflow_id)
        return jsonify({"ok": False, "error": str(exc), "status": status})
    return jsonify({"ok": True, "result": result})
