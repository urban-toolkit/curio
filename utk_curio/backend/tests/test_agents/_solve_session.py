"""Solve sessions in the agent tests: bounded by turns, never by the clock.

A Solve session (dev/131) keeps making passes until nothing is left to do, the
user stops it, or its time budget (``CURIO_SOLVE_SESSION_DEADLINE``) is spent.
The batch also gives each node what is left of that budget as the node's repair
budget (``SolveBatch._run_verified_worker``). A test session on a one-second
budget therefore made as many passes, and gave each pass as many rounds, as the
runner's speed allowed (issues #583 and #729). ``conftest.py`` bounds every
session by turns instead, with the helpers here.
"""

from __future__ import annotations

import time

from utk_curio.backend.app.agents.application.solve import budgets

#: A session budget no runner spends, so no node's repair budget binds.
UNSPENT_SESSION_S = 900


def _bound_session_by_passes(monkeypatch, passes):
    """End every Solve session after *passes* turns of its loop, whatever the
    clock says. A turn makes a pass, finds nothing left, or waits for the user;
    the loop's own bound on turns (``budgets._SOLVE_MAX_PASSES``) ends the
    session there, with ``endedBy: budget``. The session's time budget is one
    no runner spends, so every pass gets all its rounds, and the batch's own
    check of that budget stays in place for the tests about it."""
    monkeypatch.setenv("CURIO_SOLVE_SESSION_DEADLINE", str(UNSPENT_SESSION_S))
    monkeypatch.setattr(budgets, "_SOLVE_MAX_PASSES", passes)


def _on_a_loaded_runner(monkeypatch, sandbox_run_s):
    """Issue #729: a loaded runner, on which every sandbox run takes
    *sandbox_run_s* seconds (nothing changes for 0). Call it after the test's
    setup has faked the sandbox (``execution.runner._http_exec``), which this
    slows down."""
    if not sandbox_run_s:
        return
    from utk_curio.backend.app.execution import runner as exec_runner

    run = exec_runner._http_exec

    def _slow_run(endpoint, payload):
        time.sleep(sandbox_run_s)
        return run(endpoint, payload)

    monkeypatch.setattr(exec_runner, "_http_exec", _slow_run)
