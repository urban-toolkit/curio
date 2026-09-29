"""Validate one node from chat: the stream and its events.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import time as _time
import uuid

from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import rounds as agents_rounds
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.projects import storage as projects_storage


def validate_node_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    *,
    ref: str | None = None,
    node_id: str | None = None,
    exec_fn=None,
):
    """Generate → execute-through → validate → self-correct → propose, for
    ONE node (memo dev/67-7 — Simulation Mode: validate).

    Eager validation (409s stay JSON); the returned generator yields
    ``validation_started`` → per round: ``generation_round`` →
    ``node_executed`` per upstream execution → ``round_verdict`` → … →
    ``done {verdict, evidence, rounds, proposalId?, builderSession}``.
    The saved spec is never mutated: the candidate runs as an overlay and
    lands as a reviewed ``node.content.write`` proposal carrying the
    validation block — PASS or FAIL, the user decides ("Apply anyway" is a
    labeled choice, never a hidden one). An ``infrastructure`` verdict mints
    nothing and leaves the node's state untouched.
    """

    agents_acquire._settle_lake_acquisitions(user_key, project_id)
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
    if session.get("validatingSince") and now - float(session.get("validatingSince") or 0) < agents_budgets._VALIDATE_STALE_SECONDS:
        raise AgentServiceError("a validation is already running for this attachment", 409)
    manifest = agents_catalog._resolve_definition(user_key, record.get("coord", ""))
    resolution = delegation.resolve(
        user_key, project_id, manifest, "node.content.generate"
    ) if manifest is not None else delegation.Resolution("unresolvable")
    if resolution.outcome != "ok":
        raise AgentServiceError(
            "no installed agent declares node.content.generate — install the "
            "Node Content Builder first",
            409,
        )
    agents_session._check_delegate_llms(user_key, project_id, manifest, config, agents_session._delegate_capabilities([node]))
    session_id = record.get("sessionId")
    coord = record.get("coord", "")
    if ref is None:
        ref = next(
            (r for r, nid in (session.get("nodeIds") or {}).items() if nid == node_id),
            None,
        )
    # dev/72: the node's Node Builder attachment is the Solve trace's home —
    # the content review and the consolidated trace live with the agent
    # responsible for THIS node (best-effort created; fallback: parent-only).
    home, _created = agents_delegates._delegation_home(
        spec, "agent.node-builder", "node.content.generate", {},
        node_id=node_id, create=True,
    )
    home_attachment_id = (home or {}).get("attachmentId")
    home_session_id = (home or {}).get("sessionId")
    session["validatingSince"] = now
    record["builderSession"] = session
    projects_storage.write_spec(user_key, project_id, spec)
    return _validate_events(
        user_key, project_id, attachment_id, config, spec, node, ref,
        resolution, coord, session_id, exec_fn,
        home_attachment_id=home_attachment_id,
        home_session_id=home_session_id,
    )


def _validate_events(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    spec: dict,
    node: dict,
    ref: str | None,
    resolution,
    coord: str,
    session_id,
    exec_fn,
    *,
    home_attachment_id: str | None = None,
    home_session_id: str | None = None,
):
    """The validate-node body over the ONE verified-content loop (dev/115):
    the loop streams its rounds live; this body owns the framing turns, the
    reviewed mint with the validation block, the per-node ledger, and the
    finally that clears the in-flight guard on every exit, disconnect
    included."""
    node_id = node.get("id")
    execution_id = uuid.uuid4().hex
    label = (node.get("goal") or node_id)[:60]
    if isinstance(home_session_id, str):
        try:
            sessions.append_turns(
                user_key, project_id, home_session_id, home_attachment_id,
                [sessions.make_turn(
                    "user",
                    f"[Delegated by Dataflow Builder] Solve {label!r}: generate, "
                    "execute through the dataflow, validate, self-correct.",
                )],
            )
        except Exception:
            pass
    try:
        yield "validation_started", {"nodeId": node_id, "executionId": execution_id}
        outcome = yield from agents_rounds._verified_content_rounds(
            user_key, project_id,
            spec=spec, node=node, resolution=resolution, config=config,
            parent_execution_id=execution_id, parent_coord=coord,
            attachment_id=attachment_id, exec_fn=exec_fn,
            grounding_loop_ctx={
                "attachment_id": attachment_id, "session_id": session_id,
                "granted": [], "manifest": None,
            },
            dataset_paths_fn=lambda codes: agents_grounding._exec_dataset_paths(project_id, *codes),
            exec_user_key=user_key,
            secrets_fn=agents_grounding._exec_secrets_resolver(user_key),
            resolve_source=agents_grounding._source_resolver(
                user_key, project_id, coord=coord, attachment_id=attachment_id,
                execution_id=execution_id, config=config,
                extra_texts=(str((spec.get("dataflow") or {}).get("task") or ""),),
            ),
        )
        rounds_used = outcome["rounds"]
        candidate = outcome["candidate"]
        rounds_trace = outcome["roundsTrace"]
        done: dict = {
            "verdict": outcome["verdict"],
            "evidence": outcome["evidence"],
            "rounds": rounds_used,
            "nodeId": node_id,
            "attempts": outcome["attempts"],
        }
        if done["verdict"] in ("pass", "fail", "not-executable") and candidate:
            # PASS or FAIL, the user decides — the proposal carries the
            # validation block so the review is informed, never gatekept.
            # dev/118: NOT-EXECUTABLE (a browser-rendered kind) is proposed
            # too, labeled — nothing ran, and the block says so.
            # dev/72: the review lives with the NODE's agent when it exists —
            # per-node proposals stop contending for the builder's one slot.
            mint_attachment = home_attachment_id or attachment_id
            mint_session = home_session_id or session_id
            p_status, p_error, part = agents_mint._mint_node_content_write(
                user_key, project_id,
                {"attachment_id": mint_attachment, "session_id": mint_session},
                {"tool": "node.content.write",
                 "params": {"nodeId": node_id, "content": candidate}},
            )
            if part is not None:
                part["validation"] = {
                    "verdict": done["verdict"],
                    "rounds": rounds_used,
                    "evidence": done["evidence"],
                    # dev/115: the attempt trail — every round's error and
                    # fix, rendered as a collapsed list on the card.
                    "attempts": done["attempts"],
                }
                done["proposalId"] = part["proposalId"]
                done["proposalAttachmentId"] = mint_attachment
                trace_card = {
                    "type": "card",
                    "kind": "result" if done["verdict"] in ("pass", "not-executable") else "error",
                    "title": f"Solve trace · {done['verdict'].upper()}",
                    "lines": (
                        [f"dependencies executed: {len(done['evidence'].get('executedNodes') or [])} node(s)"]
                        + rounds_trace
                        + [f"outcome: {done['verdict']} after {rounds_used} round{'s' if rounds_used != 1 else ''}"]
                    )[:10],
                }
                if isinstance(mint_session, str):
                    sessions.append_turns(
                        user_key, project_id, mint_session, mint_attachment,
                        [sessions.make_turn(
                            "agent",
                            f"Validated content for {label!r}: "
                            f"{done['verdict'].upper()} after {rounds_used} "
                            f"round{'s' if rounds_used != 1 else ''} — review below.",
                            content=[trace_card, part],
                        )],
                    )
                if (
                    home_attachment_id
                    and home_attachment_id != attachment_id
                    and isinstance(session_id, str)
                ):
                    # The parent references and LINKS; the story lives at home.
                    sessions.append_turns(
                        user_key, project_id, session_id, attachment_id,
                        [sessions.make_turn(
                            "agent",
                            f"Solved {label!r}: {done['verdict'].upper()} after "
                            f"{rounds_used} round{'s' if rounds_used != 1 else ''} — "
                            "the trace and content review live in the node's "
                            "Node Builder.",
                            content=[content.make_delegation_part(
                                capability="node.content.generate",
                                coord="agent.node-builder",
                                name="Node Builder",
                                category="node",
                                attachment_id=home_attachment_id,
                                status="ok" if done["verdict"] in ("pass", "not-executable") else "failed",
                                summary=f"Solve {label!r}: {done['verdict']} "
                                f"({rounds_used} round{'s' if rounds_used != 1 else ''})",
                            )],
                        )],
                    )
            else:
                done["evidence"] = {
                    **done["evidence"],
                    "mintError": (p_error or "")[:300],
                }
        # The per-node ledger: validated / failed; infrastructure untouched.
        fresh = agents_spec_reads._read_spec_or_404(user_key, project_id)
        fresh_record = agents_spec_reads._record_or_404(fresh, attachment_id)
        fresh_session = fresh_record.get("builderSession") or {}
        if ref and isinstance(fresh_session.get("nodeStates"), dict):
            if done["verdict"] in ("pass", "not-executable"):
                # dev/118: a browser-rendered kind proceeds like a pass in the
                # plan's ledger (Simulation Mode auto-approves it); the
                # proposal's validation block carries the honest label.
                fresh_session["nodeStates"][ref] = "validated"
            elif done["verdict"] == "fail":
                fresh_session["nodeStates"][ref] = "failed"
        fresh_session.pop("validatingSince", None)
        fresh_record["builderSession"] = fresh_session
        projects_storage.write_spec(user_key, project_id, fresh)
        done["builderSession"] = fresh_session
        yield "done", done
    finally:
        # Disconnect-safe: the in-flight guard never wedges the attachment.
        try:
            cleanup_spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
            cleanup_record = agents_spec_reads._record_or_404(cleanup_spec, attachment_id)
            cleanup_session = cleanup_record.get("builderSession") or {}
            if cleanup_session.pop("validatingSince", None) is not None:
                cleanup_record["builderSession"] = cleanup_session
                projects_storage.write_spec(user_key, project_id, cleanup_spec)
        except Exception:
            pass
