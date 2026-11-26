"""What runs on a plan's nodes now, as the server says: one rule for a Build &
validate and for a plan row's Solve, which the agents' listing, every refusal
and every pick read.

A Build & validate and a row's Solve are streams their backend process drives.
Each one's record on the plan's agent says when it began and in which start
(``shared_budgets.BOOT_ID``, one for every backend process of a start): one
begun in an earlier start, or longer ago than its bound, runs no more, and
holds nothing. A tab never weighs its own clock against the server's: it reads
the listing's ``buildRunning`` and ``validating``.

While a build runs on a plan, no row's Solve and no Solve this node of one of
its nodes starts; while a row's Solve runs on a node, no Build & validate of
its plan and no Solve this node of that node starts; while Solve this node
runs on a node, no row's Solve of it starts. Each refusal is a 409 that says
why.
"""

from __future__ import annotations

import time as _time

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.infrastructure import agent_jobs
from utk_curio.backend.app.common import shared_budgets

#: Why a row's Solve or Solve this node does not start while a build runs.
BUILD_RUNNING = "the plan is being built: Stop the build to Solve"
#: Why a Build & validate does not start while a row's Solve runs on its plan.
ROW_SOLVING = "a node of this plan is being solved: wait for its Solve to end"
#: Why a second Solve of a node does not start while one runs on it.
NODE_SOLVING = "this node is being solved: wait for its Solve to end"

#: What a row's Solve stamps as who runs a validation (``validatingBy``); a
#: build's own validations stamp its mode, ``auto`` or ``step``.
BY_ROW = "node"


def this_start() -> str:
    """The boot id of the start this process belongs to."""
    return shared_budgets.BOOT_ID


def build_running(session: object) -> str | None:
    """The mode of the Build & validate running on the plan of *session* (a
    plan agent's ``builderSession``), or None when none runs: one whose start
    is older than ``SIMULATE_STALE_SECONDS``, or that an earlier start began
    (its ``simulateBootId`` is not this start's, or it has none), is gone."""
    if not isinstance(session, dict):
        return None
    since = float(session.get("simulatingSince") or 0)
    if not since or _time.time() - since >= agents_budgets.SIMULATE_STALE_SECONDS:
        return None
    if session.get("simulateBootId") != this_start():
        return None
    return str(session.get("simulateMode") or "auto")


def validation_running(session: object) -> bool:
    """Whether a validation of a node of the plan of *session* runs: a row's
    Solve, or a build's own validation. One older than
    ``VALIDATE_STALE_SECONDS``, or that an earlier start began, is gone."""
    if not isinstance(session, dict):
        return False
    since = float(session.get("validatingSince") or 0)
    if not since or _time.time() - since >= agents_budgets.VALIDATE_STALE_SECONDS:
        return False
    return session.get("validatingBootId") == this_start()


def row_solve_running(session: object) -> dict | None:
    """The plan row's Solve running on the plan of *session*, as the listing
    names it (``validating``): ``{"ref", "nodeId"}``, or None. A build's own
    validation is no row's Solve: the build holds the plan already."""
    if not isinstance(session, dict) or not validation_running(session) or session.get("validatingBy") != BY_ROW:
        return None
    return {"ref": session.get("validatingRef"), "nodeId": session.get("validatingNodeId")}


def _plan_sessions(spec: dict | None):
    for record in attachments.list_attachments(spec or {}):
        session = record.get("builderSession")
        if isinstance(session, dict):
            yield record, session


def build_over(spec: dict | None, node_id: str) -> bool:
    """Whether a Build & validate runs on a plan that holds the node *node_id*."""
    return any(
        node_id in (session.get("nodeIds") or {}).values() and build_running(session)
        for _record, session in _plan_sessions(spec)
    )


def row_solve_over(spec: dict | None, node_id: str) -> bool:
    """Whether a plan row's Solve runs on the node *node_id*."""
    return any(
        (row_solve_running(session) or {}).get("nodeId") == node_id
        for _record, session in _plan_sessions(spec)
    )


def solve_this_node_over(user_key: str, spec: dict | None, node_id: str) -> bool:
    """Whether Solve this node runs on the node *node_id*: a live ``solve-node``
    job of an agent attached to it, in this process, which runs the dataflow's
    Solves."""
    for record in attachments.list_attachments(spec or {}):
        target = record.get("target") or {}
        if target.get("kind") != "node" or target.get("targetId") != node_id:
            continue
        job = agent_jobs.live_job(user_key, str(record.get("attachmentId") or ""))
        if job is not None and getattr(job, "kind", None) == "solve-node":
            return True
    return False
