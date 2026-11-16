"""The monitor across the backend processes of a start.

``curio.py start --backend-processes N`` runs N backend processes behind nginx,
which sends every monitor route to the home process (``cli/backend_group.py``),
while each process holds its own part of what the monitor shows: its node runs
and its memory, its error log, the LLM tokens its agents spent and its open
files. So each such route of the home process asks every other process for its
part (:func:`ask`) and merges the parts with its own: a POST to
``/internal/monitor/<part>`` on 127.0.0.1 at that process's port, signed with
the start's secret, as a change to a dataflow reaches its owner
(``collaboration/owner_calls.post_to_process``). The asks go out at once, and
the route waits at most :data:`ASK_TIMEOUT_S` for them, beside its own work.

A process that does not answer in time, or answers without its part, is left
out: the route names it in its ``backendProcesses`` by its number, and why goes
to the error log, raw by decision (``errors.py``), one entry a process however
often it is asked. A route never fails over another process. With one process
nothing is asked, and no route carries ``backendProcesses``.

A process answers for its part at ``/internal/monitor/<part>`` (:func:`part`):
only a call signed with the start's secret, in a start of several processes.
The site's proxy sends only ``/api`` to the backend, and nginx answers
``/internal/`` itself, so nothing outside the start reaches it.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from flask import Blueprint, jsonify, request

from utk_curio.backend.app.monitor import errors
from utk_curio.common import backend_processes

log = logging.getLogger(__name__)

#: How long a route waits for the other processes' parts: under the page's
#: 5 s poll, as the sandbox's own call is (``routes.SANDBOX_MONITOR_TIMEOUT``).
ASK_TIMEOUT_S = 3.0
#: Where a process answers for its part, by the part's name.
PREFIX = "/internal/monitor"

internal_bp = Blueprint("monitor_processes", __name__, url_prefix=PREFIX)

_parts: dict[str, Callable[[dict], dict]] = {}


def part(name: str):
    """Make the decorated function, ``fn(arguments) -> dict``, this process's
    part *name*: what it answers the home process that asks for it, from the
    JSON *arguments* of the ask."""

    def register(fn):
        _parts[name] = fn
        return fn

    return register


@dataclass
class Asked:
    """What the other processes of the start answered for a part: each one's
    part by its number (:attr:`parts`), and the numbers of those that did not
    answer (:attr:`missing`)."""

    count: int
    here: int
    parts: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)

    def line(self) -> dict:
        """The route's ``backendProcesses``: how many processes the start runs,
        those whose part the route holds, this one's among them, and those it
        left out. Numbers only."""
        return {"count": self.count, "answered": sorted([self.here, *self.parts]), "missing": sorted(self.missing)}


class Asking:
    """The asks for the part *name* of every other process, under way, each on
    a thread of its own; :meth:`wait` gathers them."""

    def __init__(self, name: str, arguments: dict, count: int, here: int) -> None:
        self.name = name
        self.count = count
        self.here = here
        self._arguments = dict(arguments)
        self._others = [number for number in range(count) if number != here]
        self._lock = threading.Lock()
        self._answers: dict[int, dict] = {}
        self._problems: dict[int, str] = {}
        self._closed = False
        self._started = time.monotonic()
        self._threads = [
            threading.Thread(target=self._ask, args=(number,), name=f"monitor-{name}-of-{number}", daemon=True)
            for number in self._others
        ]
        for thread in self._threads:
            thread.start()

    def _ask(self, number: int) -> None:
        from utk_curio.backend.app.collaboration import owner_calls

        try:
            reply = owner_calls.post_to_process(number, f"{PREFIX}/{self.name}", {"arguments": self._arguments},
                                                timeout=ASK_TIMEOUT_S)
        except owner_calls.OwnerCallFailed as exc:
            self._settle(number, problem=str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - a route never fails over another process
            self._settle(number, problem=f"failed: {type(exc).__name__}: {exc}")
            return
        result = reply.get("result") if isinstance(reply, dict) else None
        if isinstance(reply, dict) and reply.get("ok") and isinstance(result, dict):
            self._settle(number, answer=result)
        else:
            reason = reply.get("error") if isinstance(reply, dict) else None
            self._settle(number, problem=f"got an answer without its part: {reason or 'no reason given'}")

    def _settle(self, number: int, *, answer: dict | None = None, problem: str | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            if answer is not None:
                self._answers[number] = answer
            else:
                self._problems[number] = problem or "failed"

    def wait(self) -> Asked:
        """Every other process's part that came within :data:`ASK_TIMEOUT_S`,
        and those that did not, each recorded in the error log."""
        deadline = self._started + ASK_TIMEOUT_S + 1.0
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        with self._lock:
            self._closed = True
            answers = dict(self._answers)
            problems = dict(self._problems)
        for number in self._others:
            if number not in answers and number not in problems:
                problems[number] = f"got no answer within {ASK_TIMEOUT_S:g} s"
        for number in sorted(problems):
            errors.record(
                "backend",
                summary=f"Backend process {number} did not answer the monitor",
                detail=f"The monitor's call to backend process {number} {problems[number]}.",
            )
        return Asked(count=self.count, here=self.here, parts=answers, missing=sorted(problems))


def ask(name: str, arguments: dict | None = None) -> Asking | None:
    """Ask every other backend process of this start for its part *name*,
    with *arguments*: the asks under way, which :meth:`Asking.wait` gathers.
    None with one process, which asks no one."""
    try:
        count = backend_processes.process_count()
        here = backend_processes.this_process()
    except ValueError:  # the launcher's variables do not say: this process alone
        return None
    if count <= 1:
        return None
    return Asking(name, arguments or {}, count, here)


@internal_bp.route("/<name>", methods=["POST"])
def answered_here(name: str):
    """This process's part *name*, which the home process of its start asks
    for (:func:`ask`): ``{ok, result}``, or ``{ok, error}`` with why not."""
    from utk_curio.backend.app.collaboration import owner_calls

    if backend_processes.process_count() <= 1:
        return jsonify({"ok": False, "error": "a start of one backend process takes no call from another"}), 404
    if not owner_calls.signed(request.headers.get(owner_calls.TOKEN_HEADER) or ""):
        return jsonify({"ok": False, "error": "not signed with this start's secret"}), 403
    made = _parts.get(name)
    if made is None:
        return jsonify({"ok": False, "error": f"no part {name!r}"}), 404
    body = request.get_json(silent=True)
    arguments = body.get("arguments") if isinstance(body, dict) else None
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return jsonify({"ok": False, "error": "a part's arguments are an object"}), 400
    try:
        result = made(arguments)
    except Exception as exc:  # noqa: BLE001 - the home process names it in its error log
        log.exception("[monitor] the %s part failed here", name)
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return jsonify({"ok": True, "result": result})
