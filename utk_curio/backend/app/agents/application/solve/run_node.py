"""Run one node from chat: the stream and its events.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import queue as _queue
import threading
import time as _time
import uuid

from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import validate as agents_validate
from utk_curio.backend.app.projects import storage as projects_storage


def _validate_node_inline(
    user_key: str, project_id: str, attachment_id: str, config: ProviderConfig,
    ref: str, exec_fn,
):
    """The 67-7 validation loop, driven inline by the simulator — its
    ``done`` payload is consumed (transformed into an ``action_result``),
    everything else re-yields verbatim."""
    yield from agents_validate.validate_node_stream(
        user_key, project_id, attachment_id, config, ref=ref, exec_fn=exec_fn
    )


def run_node_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    *,
    ref: str | None = None,
    node_id: str | None = None,
    exec_fn=None,
):
    """Run the dataflow THROUGH one node (memo dev/71): the 67-7 runner
    WITHOUT a candidate — the SAVED content executes through its upstream
    chain, every execution journals as a REAL run (``validation: false``), and
    the outcome (outputs, schema metadata, logs, warnings, errors) lands in
    the runtime journal where the Node Builder, debug agent, and explainer
    read it (67-2 ``node.runtime.read``). The saved spec is never mutated.

    Streams ``run_started`` → ``node_executed`` per upstream execution →
    ``done {ok, nodes, blocker, error}``; a result card joins the transcript.
    """

    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    if ref and not node_id:
        node_id = (session.get("nodeIds") or {}).get(ref)
        if not node_id:
            raise AgentServiceError(f"ref {ref!r} has no created node yet", 409)
    if not node_id:
        raise AgentServiceError("a ref or nodeId is required", 422)
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    if node is None:
        raise AgentServiceError(f"node {node_id!r} not found in the saved spec", 404)
    now = _time.time()
    if session.get("runningSince") and now - float(session.get("runningSince") or 0) < agents_budgets._VALIDATE_STALE_SECONDS:
        raise AgentServiceError("a run is already in progress for this attachment", 409)
    session["runningSince"] = now
    record["builderSession"] = session
    projects_storage.write_spec(user_key, project_id, spec)
    session_id = record.get("sessionId")
    return _run_node_events(
        user_key, project_id, attachment_id, spec, node, session_id, exec_fn
    )


def _run_node_events(
    user_key: str,
    project_id: str,
    attachment_id: str,
    spec: dict,
    node: dict,
    session_id,
    exec_fn,
):
    """The run-node body: a threaded runner drains a queue so upstream
    executions stream live (the dev/63 pattern); the finally clears the
    in-flight guard on every exit, disconnect included."""

    from utk_curio.backend.app.execution import runner

    from utk_curio.backend.app.discovery.application.exec_collections import (
        resolve_spec_collections,
    )

    node_id = node.get("id")
    execution_id = uuid.uuid4().hex
    try:
        yield "run_started", {"nodeId": node_id, "executionId": execution_id}
        progress_queue: _queue.Queue = _queue.Queue()
        # Resolved here, in the request context the stream carries, before
        # the worker thread starts.
        collections, media_dir = resolve_spec_collections(spec, user_key)

        def _run():
            try:
                report = runner.run_through_node(
                    user_key, project_id, spec, node_id,
                    candidate_content=None,
                    exec_fn=exec_fn,
                    collections=collections, media_dir=media_dir,
                    as_validation=False,  # a REAL run, journaled as one
                    progress=lambda nid, i, total: progress_queue.put(
                        ("progress", nid, i, total)
                    ),
                )
            except Exception as exc:  # the runner must never kill the stream
                report = {
                    "ok": False, "target": node_id, "order": [], "nodes": {},
                    "blocker": None, "infrastructure": str(exc)[:300],
                    "error": f"run failed: {str(exc)[:300]}",
                }
            progress_queue.put(("done", report))

        thread = threading.Thread(target=_run)
        thread.start()
        report: dict = {}
        while True:
            item = progress_queue.get()
            if item[0] == "progress":
                _, nid, index, total = item
                yield "node_executed", {"nodeId": nid, "index": index, "total": total}
                continue
            report = item[1]
            break
        thread.join(timeout=5)
        target_record = (report.get("nodes") or {}).get(node_id) or {}
        label = (node.get("goal") or node_id)[:60]
        if isinstance(session_id, str):
            if report.get("ok"):
                lines = [
                    f"{label} · ok",
                    f"output: {(target_record.get('output') or {}).get('dataType') or '?'}",
                    f"{len(report.get('order') or [])} node(s) in the chain",
                ]
                if target_record.get("stderrTail"):
                    lines.append("warnings captured — see node.runtime.read")
                text = f"Ran through {label!r}: ok."
            else:
                blocker = report.get("blocker")
                failed_record = (report.get("nodes") or {}).get(blocker) or {}
                lines = [
                    f"{label} · failed",
                    (report.get("error") or "")[:300],
                ]
                tail = failed_record.get("stderrTail") or ""
                if tail:
                    lines.append(tail[-300:])
                text = f"Ran through {label!r}: FAILED — {report.get('error')}"
            sessions.append_turns(
                user_key, project_id, session_id, attachment_id,
                [sessions.make_turn(
                    "agent", text,
                    content=[{
                        "type": "card", "kind": "result",
                        "title": "Run through node", "lines": lines[:10],
                    }],
                )],
            )
        yield "done", {
            "nodeId": node_id,
            "executionId": execution_id,
            "ok": bool(report.get("ok")),
            "order": report.get("order") or [],
            "nodes": report.get("nodes") or {},
            "blocker": report.get("blocker"),
            "error": report.get("error"),
        }
    finally:
        # Disconnect-safe: the in-flight guard never wedges the attachment.
        try:
            cleanup_spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
            cleanup_record = agents_spec_reads._record_or_404(cleanup_spec, attachment_id)
            cleanup_session = cleanup_record.get("builderSession") or {}
            if cleanup_session.pop("runningSince", None) is not None:
                cleanup_record["builderSession"] = cleanup_session
                projects_storage.write_spec(user_key, project_id, cleanup_spec)
        except Exception:
            pass
