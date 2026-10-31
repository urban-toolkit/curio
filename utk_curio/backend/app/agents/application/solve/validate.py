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
from utk_curio.backend.app.agents.application import in_the_room as agents_room
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.proposals import changes as agents_changes
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import node_solve as agents_node_solve
from utk_curio.backend.app.agents.application.solve import rounds as agents_rounds
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.collaboration import dataflow_docs


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
    """Generate, execute through, validate, self-correct, and write, for ONE
    node of a plan (memo dev/67-7: a row's Solve, and Build & validate's
    validate step).

    Eager validation (409s stay JSON); the returned generator yields
    ``validation_started``, then per round ``generation_round``,
    ``node_executed`` per upstream execution and ``round_verdict``, then a
    ``change`` when the code lands, and ``done {verdict, evidence, rounds,
    changeId?, builderSession}``. The candidate runs as an overlay, and code
    that passed its check lands in the node as the agent's change, carrying
    the validation block, with its Undo. Code that failed it is not written:
    its attempts, each with its code, stay in the node's agent chat. An
    ``infrastructure`` verdict writes nothing and leaves the node's state
    untouched.
    """

    agents_acquire._settle_discovery_acquisitions(user_key, project_id)
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
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
        raise AgentServiceError(agents_rounds._no_content_agent(resolution), 409)
    agents_session._check_delegate_llms(
        user_key, project_id, manifest, config,
        agents_session._delegate_capabilities([node], agents_roster._roster_templates(user_key, project_id)),
    )
    session_id = record.get("sessionId")
    coord = record.get("coord", "")
    if ref is None:
        ref = next(
            (r for r, nid in (session.get("nodeIds") or {}).items() if nid == node_id),
            None,
        )
    # dev/72: the node's content agent is the Solve trace's home: the content
    # review and the consolidated trace live with the agent responsible for
    # THIS node (best-effort created; fallback: parent-only).
    home, _created = agents_delegates._delegation_home(
        spec, resolution.coord, "node.content.generate", {},
        node_id=node_id, create=True, user_key=user_key, project_id=project_id,
    )
    home_attachment_id = (home or {}).get("attachmentId")
    home_session_id = (home or {}).get("sessionId")
    session["validatingSince"] = now
    record["builderSession"] = session
    dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._agent_actor(user_key, spec, attachment_id, "validate"))
    return _validate_events(
        user_key, project_id, attachment_id, config, spec, node, ref,
        resolution, coord, session_id, exec_fn,
        home_attachment_id=home_attachment_id,
        home_session_id=home_session_id,
        # Captured here, in the request: the rounds validate on a thread.
        acting_user=agents_spec_reads._acting_user(),
        room_asker=agents_room.asker(),
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
    acting_user=None,
    room_asker: agents_room.Asker | None = None,
):
    """The validate-node body over the ONE verified-content loop (dev/115):
    the loop streams its rounds live; this body owns the framing turns, the
    reviewed mint with the validation block, the per-node ledger, and the
    finally that clears the in-flight guard on every exit, disconnect
    included. Its agent is at work in the dataflow's room until the node's
    state is settled, before ``done`` (``in_the_room``)."""
    node_id = node.get("id")
    execution_id = uuid.uuid4().hex
    label = (node.get("goal") or node_id)[:60]
    _announce_delegated_solve(
        user_key, project_id, home_attachment_id, home_session_id, label,
        parent_name=agents_spec_reads._agent_name(user_key, coord) or coord,
    )
    try:
        with agents_room.at_work(user_key, project_id, attachment_id, spec=spec, coord=coord, who=room_asker):
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
                dataset_paths_fn=lambda codes, formats: agents_grounding._exec_dataset_paths(
                    project_id, *codes, formats=formats,
                ),
                exec_user_key=user_key,
                acting_user=acting_user,
                secrets_fn=agents_grounding._exec_secrets_resolver(
                    agents_grounding._keys_of(None, user_key, acting_user)),
                resolve_source=agents_grounding._source_resolver(
                    user_key, project_id, coord=coord, attachment_id=attachment_id,
                    execution_id=execution_id, config=config,
                    extra_texts=(str((spec.get("dataflow") or {}).get("task") or ""),),
                    asker=acting_user,
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
            if agents_rounds._ended_on_an_answer(outcome):
                # The builder's one-line answer is no content: nothing is written
                # into the node.
                _say_the_answer(user_key, project_id, attachment_id, session_id,
                                home_attachment_id, home_session_id, spec, node, label, outcome)
            elif candidate and _writes(done):
                yield from _land_validated(user_key, project_id, attachment_id, session_id,
                                           home_attachment_id, home_session_id,
                                           node_id, label, candidate, done, rounds_used, rounds_trace,
                                           resolution=resolution, asker=acting_user, room_asker=room_asker)
            elif candidate and done["verdict"] in ("fail", "not-executable"):
                # Code that failed its check is not written: its attempts, each
                # with the code it ran, stay in the node's agent chat.
                done["verdict"] = "fail"
                _say_it_failed(user_key, project_id, attachment_id, session_id, home_attachment_id, home_session_id,
                               spec, node, label, outcome, rounds_trace)
            done["builderSession"] = _settle_node_state(user_key, project_id, attachment_id, ref, done["verdict"])
        yield "done", done
    finally:
        # Disconnect-safe: the in-flight guard never wedges the attachment.
        _clear_validating_guard(user_key, project_id, attachment_id)


def _announce_delegated_solve(user_key, project_id, home_attachment_id, home_session_id, label,
                              *, parent_name: str) -> None:
    """The framing user turn at HOME: the agent named *parent_name* delegated this Solve."""
    if isinstance(home_session_id, str):
        try:
            sessions.append_turns(
                user_key, project_id, home_session_id, home_attachment_id,
                [sessions.make_turn(
                    "user",
                    f"{sessions.DELEGATED_TURN_PREFIX}{parent_name}] Solve {label!r}: generate, "
                    "execute through the dataflow, validate, self-correct.",
                )],
            )
        except Exception:
            pass


def _say_the_answer(user_key, project_id, attachment_id, session_id, home_attachment_id, home_session_id,
                    spec, node, label, outcome: dict) -> None:
    """The builder answered in one line instead of writing code, or a loader's
    builder declined. That line is no content, so nothing is written into the
    node. The node's agent says it the way Solve this node does, with every
    attempt below it, and the agent the Solve was asked of says it too."""
    text = agents_node_solve._not_fixed(label, outcome, {})
    trail = agents_rounds._solve_attempts_part(
        spec, node.get("id"), str(node.get("goal") or node.get("id"))[:120],
        {"attempts": outcome["attempts"], "rounds": outcome["rounds"],
         "verdict": outcome["verdict"], "stoppedBy": outcome.get("stoppedBy")},
        user_key=user_key,
    )
    home_attachment = home_attachment_id or attachment_id
    home_session = home_session_id or session_id
    if isinstance(home_session, str):
        sessions.append_turns(
            user_key, project_id, home_session, home_attachment,
            [sessions.make_turn("agent", text, error=True, content=[trail] if trail is not None else [])],
        )
    if home_attachment != attachment_id and isinstance(session_id, str):
        sessions.append_turns(
            user_key, project_id, session_id, attachment_id,
            [sessions.make_turn("agent", text, error=True)],
        )


def _writes(done: dict) -> bool:
    """Whether a validation's code is written into its node: code that
    passed its check, and a browser-rendered kind's document that its check
    could read (dev/118, dev/129: the rule Solve writes by)."""
    if done["verdict"] == "pass":
        return True
    evidence = done.get("evidence") or {}
    return done["verdict"] == "not-executable" and not (
        evidence.get("documentUnchecked") and not evidence.get("documentPassive")
    )


def _trace_card(done: dict, rounds_used: int, rounds_trace: list) -> dict:
    return {
        "type": "card",
        "kind": "result" if done["verdict"] in ("pass", "not-executable") else "error",
        "title": f"Solve trace · {done['verdict'].upper()}",
        "lines": (
            [f"dependencies executed: {len(done['evidence'].get('executedNodes') or [])} node(s)"]
            + rounds_trace
            + [f"outcome: {done['verdict']} after {rounds_used} round{'s' if rounds_used != 1 else ''}"]
        )[:10],
    }


def _land_validated(user_key, project_id, attachment_id, session_id, home_attachment_id, home_session_id,
                    node_id, label, candidate, done: dict, rounds_used: int, rounds_trace: list,
                    *, resolution=None, asker=None, room_asker=None):
    """Write the code that passed its check into its node, as the agent's
    change with its Undo, through the ``node.content.write`` mint and its
    checks, at the NODE's agent when it exists (dev/72). Its card carries the
    validation block (verdict, rounds, attempts). Yields its ``change``
    event; writes the change's id, or why it did not land, into *done*.
    *asker*: the person the job took when it started, whom the change names
    and whose own focus in the node never holds it back; *room_asker*, the
    same as the room names them, whom the node's agent at work for the write
    says asked it."""
    change_attachment = home_attachment_id or attachment_id
    change_session = home_session_id or session_id
    ctx = {"attachment_id": change_attachment, "session_id": change_session,
           "asker_id": getattr(asker, "id", None), "asker": asker, "room_asker": room_asker}
    status, text, part = agents_mint._mint_node_content_write(
        user_key, project_id, ctx,
        {"tool": "node.content.write", "params": {"nodeId": node_id, "content": candidate}},
    )
    for landed in agents_changes.take_landed(ctx):
        yield "change", landed
    if part is None:
        done["verdict"] = "fail"
        done["evidence"] = {**done["evidence"], "mintError": (text or "")[:300]}
        return
    part["validation"] = {
        "verdict": done["verdict"],
        "rounds": rounds_used,
        "evidence": done["evidence"],
        # dev/115: the attempt trail, every round's error and fix, rendered
        # as a collapsed list on the card.
        "attempts": done["attempts"],
    }
    done["changeId"] = part["changeId"]
    done["changeAttachmentId"] = change_attachment
    if isinstance(change_session, str):
        sessions.append_turns(
            user_key, project_id, change_session, change_attachment,
            [sessions.make_turn(
                "agent",
                f"Validated content for {label!r}: {done['verdict'].upper()} after {rounds_used} "
                f"round{'s' if rounds_used != 1 else ''}, written into the node.",
                content=[_trace_card(done, rounds_used, rounds_trace), part],
            )],
        )
    if home_attachment_id and home_attachment_id != attachment_id and isinstance(session_id, str):
        # The parent references and LINKS; the story lives at home. The agent
        # that wrote it is named as its manifest names it.
        delegate = getattr(resolution, "manifest", None)
        delegate_coord = getattr(resolution, "coord", None) or ""
        delegate_name = getattr(delegate, "name", None) or delegate_coord
        sessions.append_turns(
            user_key, project_id, session_id, attachment_id,
            [sessions.make_turn(
                "agent",
                f"Solved {label!r}: {done['verdict'].upper()} after "
                f"{rounds_used} round{'s' if rounds_used != 1 else ''}: "
                f"the trace and the change live in the node's {delegate_name}.",
                content=[content.make_delegation_part(
                    capability="node.content.generate",
                    coord=delegate_coord,
                    name=delegate_name,
                    category=getattr(delegate, "category", "") or "",
                    attachment_id=home_attachment_id,
                    status="ok",
                    summary=f"Solve {label!r}: {done['verdict']} "
                    f"({rounds_used} round{'s' if rounds_used != 1 else ''})",
                )],
            )],
        )


def _say_it_failed(user_key, project_id, attachment_id, session_id, home_attachment_id, home_session_id,
                   spec, node, label, outcome: dict, rounds_trace: list) -> None:
    """Code that failed its check is not written. The node's agent says so,
    with the trace and every attempt below it, each with the code it ran, so
    a person can take one from there; the agent the Solve was asked of says
    it too."""
    done = {"verdict": "fail", "evidence": outcome.get("evidence") or {}}
    rounds_used = outcome["rounds"]
    text = (f"Validated content for {label!r}: FAIL after {rounds_used} "
            f"round{'s' if rounds_used != 1 else ''}; nothing was written. Each attempt's code is below.")
    trail = agents_rounds._solve_attempts_part(
        spec, node.get("id"), str(node.get("goal") or node.get("id"))[:120],
        {"attempts": outcome["attempts"], "rounds": rounds_used,
         "verdict": "fail", "stoppedBy": outcome.get("stoppedBy")},
        user_key=user_key,
    )
    home_attachment = home_attachment_id or attachment_id
    home_session = home_session_id or session_id
    if isinstance(home_session, str):
        sessions.append_turns(
            user_key, project_id, home_session, home_attachment,
            [sessions.make_turn("agent", text, error=True,
                                content=[_trace_card(done, rounds_used, rounds_trace)]
                                + ([trail] if trail is not None else []))],
        )
    if home_attachment != attachment_id and isinstance(session_id, str):
        sessions.append_turns(
            user_key, project_id, session_id, attachment_id,
            [sessions.make_turn("agent", text, error=True)],
        )


def _settle_node_state(user_key, project_id, attachment_id, ref, verdict: str) -> dict:
    """The per-node ledger: validated / failed; infrastructure untouched. Returns the builder session."""
    fresh = agents_spec_reads._live_spec_or_404(user_key, project_id)
    fresh_record = agents_spec_reads._record_or_404(fresh, attachment_id)
    fresh_session = fresh_record.get("builderSession") or {}
    if ref and isinstance(fresh_session.get("nodeStates"), dict):
        if verdict in ("pass", "not-executable"):
            # dev/118: a browser-rendered kind proceeds like a pass in the
            # plan's ledger (Simulation Mode auto-approves it); the
            # proposal's validation block carries the honest label.
            fresh_session["nodeStates"][ref] = "validated"
        elif verdict == "fail":
            fresh_session["nodeStates"][ref] = "failed"
    fresh_session.pop("validatingSince", None)
    fresh_record["builderSession"] = fresh_session
    dataflow_docs.write(user_key, project_id, fresh, agents_spec_reads._agent_actor(user_key, fresh, attachment_id, "validate"))
    return fresh_session


def _clear_validating_guard(user_key, project_id, attachment_id) -> None:
    """Disconnect-safe: the in-flight guard never wedges the attachment."""
    try:
        cleanup_spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
        cleanup_record = agents_spec_reads._record_or_404(cleanup_spec, attachment_id)
        cleanup_session = cleanup_record.get("builderSession") or {}
        if cleanup_session.pop("validatingSince", None) is not None:
            cleanup_record["builderSession"] = cleanup_session
            dataflow_docs.write(
                user_key, project_id, cleanup_spec,
                agents_spec_reads._agent_actor(user_key, cleanup_spec, attachment_id, "validate"),
            )
    except Exception:
        pass
