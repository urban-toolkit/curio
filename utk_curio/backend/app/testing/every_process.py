"""A test rig's change, made in every backend process of its start.

``curio.py start --backend-processes N`` runs N backend processes behind nginx
(``cli/backend_group.py``). A testing route names no dataflow, so nginx sends
it to the home process, while most of what the routes change lives in each
process's memory: the record clock, Curio's own LLM endpoints, the run hold,
pip's behaviour and settings, the import path, and the door a reset closes
(``routes.py``). Each such change is a step (:func:`step`): a function of JSON
arguments that makes the change in this process and answers JSON.

:func:`everywhere` makes a step here and, at the same time, in every other
process of the start: a POST to ``/internal/testing/<step>`` on 127.0.0.1 at
that process's port, signed with the start's secret, as a change to a
dataflow reaches its owner (``collaboration/owner_calls.post_to_process``).
Once every process was asked, it raises :class:`NotEveryProcess` naming each
process that did not make the step. With one process the step is made here
alone, and nothing is sent.

The route that takes a step makes it in its own process and sends it on to no
one. Like every testing route it exists only in a test rig, and it answers
only a call signed with the start's secret in a start of several processes;
nginx answers ``/internal/`` itself, so nothing outside the start reaches it.
A reset's door neither counts nor refuses it (``routes._count_request_in``):
the call that opens a door comes through it.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from flask import Blueprint, jsonify, request

from utk_curio.backend import config
from utk_curio.backend.app.collaboration import owner_calls
from utk_curio.common import backend_processes

log = logging.getLogger(__name__)

#: Where another process of the start sends a step, by its name.
PREFIX = "/internal/testing"

internal_bp = Blueprint("testing_internal", __name__, url_prefix=PREFIX)

_steps: dict[str, Callable[[dict], dict]] = {}


class NotEveryProcess(RuntimeError):
    """The step *name*, which some backend process of the start did not make:
    what each process that made it answered (:attr:`answers`, by number), and
    why each other did not (:attr:`problems`, by number)."""

    def __init__(self, name: str, answers: dict, problems: dict):
        self.name = name
        self.answers = answers
        self.problems = problems
        super().__init__("; ".join(problems[number] for number in sorted(problems)))


def step(name: str):
    """Make the decorated function, ``fn(arguments) -> dict``, the step
    *name*: a change a test rig makes in each backend process, made in this
    one from its JSON *arguments*, and answering JSON."""

    def register(fn):
        _steps[name] = fn
        return fn

    return register


def steps() -> list[str]:
    """The steps a process of this start makes when another sends one."""
    return sorted(_steps)


def path_of(name: str) -> str:
    """The route another process of the start sends the step *name* to."""
    return f"{PREFIX}/{name}"


def everywhere(name: str, arguments: dict | None = None) -> dict[int, dict]:
    """Make the step *name* with *arguments* in every backend process of this
    start: here, and in each other process at the same time, so a reset's
    waits in every process run together. What each process's step answered,
    by number. :class:`NotEveryProcess` once every process was asked, when
    some did not make it."""
    apply_here = _steps[name]
    arguments = dict(arguments or {})
    here = backend_processes.this_process()
    others = [number for number in range(backend_processes.process_count()) if number != here]
    answers: dict[int, dict] = {}
    problems: dict[int, str] = {}

    def ask(number: int) -> None:
        try:
            reply = owner_calls.post_to_process(number, path_of(name), {"arguments": arguments})
        except owner_calls.OwnerCallFailed as exc:
            problems[number] = f"{name}, sent to backend process {number}, {exc}"
            return
        if reply.get("ok"):
            answers[number] = reply.get("result") or {}
        else:
            problems[number] = f"{name} failed in backend process {number}: {reply.get('error') or 'no reason given'}"

    asking = [threading.Thread(target=ask, args=(number,), name=f"testing-{name}-to-{number}", daemon=True)
              for number in others]
    for thread in asking:
        thread.start()
    try:
        answers[here] = apply_here(arguments)
    except Exception as exc:  # noqa: BLE001 - named with the other processes' answers
        log.exception("[every-process] %s failed in backend process %d", name, here)
        problems[here] = f"{name} failed in backend process {here}: {type(exc).__name__}: {exc}"
    finally:
        for thread in asking:
            thread.join()
    if problems:
        raise NotEveryProcess(name, answers, problems)
    return answers


@internal_bp.before_request
def _only_in_a_test_rig():
    """404 unless this is a test rig, as every testing route answers."""
    if not config._is_dev() or not config._is_testing():
        return jsonify({"error": "not found"}), 404
    return None


@internal_bp.route("/<name>", methods=["POST"])
def made_here(name: str):
    """A step another backend process of this start sends (:func:`everywhere`):
    made here alone, and answered with what it returned or the error it
    raised, as ``{ok, result}`` or ``{ok, error}``."""
    if backend_processes.process_count() <= 1:
        return jsonify({"ok": False, "error": "a start of one backend process takes no call from another"}), 404
    if not owner_calls.signed(request.headers.get(owner_calls.TOKEN_HEADER) or ""):
        return jsonify({"ok": False, "error": "not signed with this start's secret"}), 403
    made = _steps.get(name)
    if made is None:
        return jsonify({"ok": False, "error": f"no step {name!r}"}), 404
    arguments = (request.get_json(silent=True) or {}).get("arguments") or {}
    if not isinstance(arguments, dict):
        return jsonify({"ok": False, "error": "a step's arguments are an object"}), 400
    try:
        result = made(arguments)
    except Exception as exc:  # noqa: BLE001 - the process that sent it names it
        log.exception("[every-process] %s, sent by another backend process, failed here", name)
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return jsonify({"ok": True, "result": result})
