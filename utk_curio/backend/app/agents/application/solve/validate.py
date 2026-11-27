"""Validate one node from chat: the stream and its events.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import contextlib
import time as _time
import uuid

from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import labels
from utk_curio.backend.app.agents.domain.counts import count_label
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import dataset_resolution as agents_dataset_resolution
from utk_curio.backend.app.agents.application import in_the_room as agents_room
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.proposals import changes as agents_changes
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.solve import node_solve as agents_node_solve
from utk_curio.backend.app.agents.application.solve import node_work as agents_node_work
from utk_curio.backend.app.agents.application.solve import rounds as agents_rounds
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.execution import node_names
from utk_curio.backend.app.projects import storage as projects_storage

#: A plan node's state while it waits for the user to pick its source in its
#: Dataset Finder's chat, as the verdict of its validation names it: its row
#: needs a source, and Build & validate goes on past it.
AWAITING_SOURCE = "awaiting-source"
#: A plan node's state while the source picked for it downloads into the
#: Data Catalog, and while the dataset picked for it waits for its install.
AWAITING_DOWNLOAD = "awaiting-download"
AWAITING_INSTALL = "awaiting-install"
#: The states of a plan node that waits for its source: Build & validate goes
#: on past it, and its row keeps its Solve.
SOURCE_WAITS = (AWAITING_SOURCE, AWAITING_DOWNLOAD, AWAITING_INSTALL)


def plan_wait_state(spec: dict, node_id: str | None, user_key: str) -> str:
    """The state a plan node whose source waited is in now, as its Dataset
    Finder's record in *spec* says (``dataset_resolution.source_wait``): it
    waits for the user, for a download or for an install, or, when its
    source waits for nothing more, it is placed again (``created``): the pick
    resolved it, the download landed, the install was applied, or the record
    went and the next validation asks the Finder again."""
    record = agents_dataset_resolution.source_record(spec, node_id, user_key=user_key) if node_id else None
    return {
        agents_dataset_resolution.WAITS_FOR_PICK: AWAITING_SOURCE,
        agents_dataset_resolution.WAITS_FOR_DOWNLOAD: AWAITING_DOWNLOAD,
        agents_dataset_resolution.WAITS_FOR_INSTALL: AWAITING_INSTALL,
    }.get(agents_dataset_resolution.source_wait(record), "created")


def validate_node_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    *,
    ref: str | None = None,
    node_id: str | None = None,
    exec_fn=None,
    by: str = agents_node_work.BY_ROW,
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

    *by* says who runs it: a row's Solve (``node``, the route's), or a Build &
    validate (its mode, ``auto`` or ``step``). A row's Solve is work on its
    node (``node_work``): it does not start while a build runs on the plan, or
    while Solve this node runs on the node, and the listing names it while it
    runs. One validation runs on a plan at a time.
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
    if by == agents_node_work.BY_ROW:
        # A row's Solve: never over a build of its plan, nor over Solve this
        # node running on the same node.
        if agents_node_work.build_running(session):
            raise AgentServiceError(agents_node_work.BUILD_RUNNING, 409)
        if agents_node_work.solve_this_node_over(user_key, spec, node_id):
            raise AgentServiceError(agents_node_work.NODE_SOLVING, 409)
    if agents_node_work.validation_running(session):
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
    # change and the consolidated trace live with the agent responsible for
    # THIS node (best-effort created; fallback: parent-only).
    home, created = agents_delegates._delegation_home(
        spec, resolution.coord, "node.content.generate", {},
        node_id=node_id, create=True, user_key=user_key, project_id=project_id,
    )
    home_attachment_id = (home or {}).get("attachmentId")
    home_session_id = (home or {}).get("sessionId")
    if created:
        # The home this validation attached is written alone: the plan's
        # record, as this read holds it, is left as the dataflow holds it.
        dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._agent_actor(user_key, spec, attachment_id, "validate"))
    _mark_validating(user_key, project_id, attachment_id, now, ref=ref, node_id=node_id, by=by)
    return _validate_events(
        user_key, project_id, attachment_id, config, spec, node, ref,
        resolution, coord, session_id, exec_fn,
        home_attachment_id=home_attachment_id,
        home_session_id=home_session_id,
        # Captured here, in the request: the rounds validate on a thread.
        acting_user=agents_spec_reads._acting_user(),
        room_asker=agents_room.asker(),
        by=by,
    )


#: The fields a running validation keeps on the plan's record, which its end
#: clears: when it began, its ref and node, who runs it (``node`` for a row's
#: Solve, the build's mode for a build's) and the start it began in.
_VALIDATING = ("validatingSince", "validatingRef", "validatingNodeId", "validatingBy", "validatingBootId")


def _mark_validating(user_key: str, project_id: str, attachment_id: str, now: float, *,
                     ref: str | None = None, node_id: str | None = None, by: str = agents_node_work.BY_ROW) -> None:
    """Set the in-flight guard on the plan's record as the dataflow holds it
    now, under its spec lock, as every writer of a node's source does: a pick
    that moved the plan's ledger since this validation read it keeps its
    move. The guard names the node and who runs it, and the start it runs in,
    so the listing names a row's Solve while it runs (``validating``). A
    validation already running refuses this one (409), and so does a build
    running on the plan for a row's Solve."""
    with projects_storage.spec_write_lock(user_key, project_id):
        spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
        record = agents_spec_reads._record_or_404(spec, attachment_id)
        session = record.get("builderSession") or {}
        if by == agents_node_work.BY_ROW and agents_node_work.build_running(session):
            raise AgentServiceError(agents_node_work.BUILD_RUNNING, 409)
        if agents_node_work.validation_running(session):
            raise AgentServiceError("a validation is already running for this attachment", 409)
        session["validatingSince"] = now
        session["validatingRef"] = ref
        session["validatingNodeId"] = node_id
        session["validatingBy"] = by
        session["validatingBootId"] = agents_node_work.this_start()
        record["builderSession"] = session
        dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._agent_actor(user_key, spec, attachment_id, "validate"))


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
    by: str = agents_node_work.BY_ROW,
):
    """The validate-node body over the ONE verified-content loop (dev/115):
    the loop streams its rounds live; this body owns the framing turns, the
    change that lands with its validation block, the per-node ledger, and the
    finally that clears the in-flight guard on every exit, disconnect
    included. Its agent is at work in the dataflow's room until the node's
    state is settled, before ``done`` (``in_the_room``). *by* is who runs it,
    which the ledger keeps for a node left waiting for its source."""
    node_id = node.get("id")
    execution_id = uuid.uuid4().hex
    label = agents_node_solve.solve_label(node, templates=node_names.template_labels(user_key, project_id))
    try:
        with agents_room.at_work(user_key, project_id, attachment_id, spec=spec, coord=coord, who=room_asker):
            yield "validation_started", {"nodeId": node_id, "executionId": execution_id}
            rounds = agents_rounds._verified_content_rounds(
                user_key, project_id,
                spec=spec, node=node, resolution=resolution, config=config,
                parent_execution_id=execution_id, parent_coord=coord,
                attachment_id=attachment_id, exec_fn=exec_fn,
                grounding_loop_ctx={
                    "attachment_id": attachment_id, "session_id": session_id,
                    "granted": [], "manifest": None,
                },
                # Looked up as the account the request took, on the thread the
                # attempt runs on, where a download of one says how far it has
                # come: that thread holds no request.
                dataset_paths_fn=lambda codes, formats, unavailable=None: agents_grounding._exec_dataset_paths(
                    project_id, *codes, formats=formats, unavailable=unavailable, user=acting_user,
                ),
                # Looked up in the request the stream holds, and handed to the
                # thread each attempt runs on.
                collections_fn=lambda codes: agents_grounding._exec_collections(project_id, user_key, *codes),
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
            outcome = yield from _handed_to_the_builder(rounds, lambda: _announce_delegated_solve(
                user_key, project_id, home_attachment_id, home_session_id, label,
                parent_name=agents_spec_reads._agent_name(user_key, coord) or coord,
            ))
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
                                           resolution=resolution, asker=acting_user, room_asker=room_asker,
                                           intent_texts=(str(node.get("goal") or ""),
                                                         str((spec.get("dataflow") or {}).get("task") or "")))
            elif candidate and done["verdict"] in ("fail", "not-executable"):
                # Code that failed its check is not written: its attempts, each
                # with the code it ran, stay in the node's agent chat.
                done["verdict"] = "fail"
                _say_it_failed(user_key, project_id, attachment_id, session_id, home_attachment_id, home_session_id,
                               spec, node, label, outcome, rounds_trace)
            done["builderSession"] = _settle_node_state(user_key, project_id, attachment_id, ref, done["verdict"], by=by,
                                                        check=check_of(done))
        yield "done", done
    finally:
        # Disconnect-safe: the in-flight guard never wedges the attachment.
        _clear_validating_guard(user_key, project_id, attachment_id)


def _handed_to_the_builder(rounds, announce):
    """The content loop's events, with *announce* called as the first of them
    comes: the first round's, just before the node's builder is asked. A node
    whose source still waits for the user is never handed to its builder: the
    loop ends with no event, and no chat gains a turn. Returns the loop's
    outcome; a stream closed early closes the loop, as ``yield from`` does."""
    announced = False
    try:
        while True:
            try:
                event = next(rounds)
            except StopIteration as stop:
                return stop.value
            if not announced:
                announced = True
                announce()
            yield event
    finally:
        rounds.close()


def _announce_delegated_solve(user_key, project_id, home_attachment_id, home_session_id, label,
                              *, parent_name: str) -> None:
    """The framing user turn at HOME: the agent named *parent_name* delegated
    this Solve. The chat draws it as one quiet line, "Asked by the Dataflow
    Builder: solve CPL branches." (``asked``)."""
    if isinstance(home_session_id, str):
        with contextlib.suppress(Exception):
            sessions.append_turns(
                user_key, project_id, home_session_id, home_attachment_id,
                [sessions.make_turn(
                    "user",
                    f"{sessions.DELEGATED_TURN_PREFIX}{parent_name}] Solve {label!r}: generate, "
                    "execute through the dataflow, validate, self-correct.",
                    asked={"by": parent_name, "task": f"solve {label}"},
                )],
            )


def _say_the_answer(user_key, project_id, attachment_id, session_id, home_attachment_id, home_session_id,
                    spec, node, label, outcome: dict) -> None:
    """The builder answered in one line instead of writing code, or a loader's
    builder declined. That line is no content, so nothing is written into the
    node. The node's agent says it the way Solve this node does, with every
    attempt below it, and the agent the Solve was asked of says it too."""
    text = agents_node_solve._not_fixed(label, outcome, {})
    trail = agents_rounds._solve_attempts_part(
        spec, node.get("id"), label,
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
    """The Solve's trace, a line a round: a run detail (``runDetails``), its
    rounds being the change card's Verification, each with its code."""
    executed = count_label(len(done["evidence"].get("executedNodes") or []), "node")
    outcome = f"{labels.verdict_words(done['verdict'], done['evidence'])} after {count_label(rounds_used, 'round')}"
    lines = [f"dependencies executed: {executed}", *rounds_trace, f"outcome: {outcome}"]
    return {
        "type": "card",
        "kind": "result" if done["verdict"] in ("pass", "not-executable") else "error",
        "title": f"Solve trace · {labels.verdict_words(done['verdict'], done['evidence'], capitals=True)}",
        "lines": lines[:10],
        "runDetails": True,
    }


def _land_validated(user_key, project_id, attachment_id, session_id, home_attachment_id, home_session_id,
                    node_id, label, candidate, done: dict, rounds_used: int, rounds_trace: list,
                    *, resolution=None, asker=None, room_asker=None, intent_texts=()):
    """Write the code that passed its check into its node, as the agent's
    change with its Undo, through the ``node.content.write`` mint and its
    checks, at the NODE's agent when it exists (dev/72). Those checks read
    what the round's did: the user's words in the chat that asked,
    *session_id*, and *intent_texts*, the node's goal and the dataflow's
    task. So the code lands as it passed: values the user typed there, a
    path the goal names, synthetic data the goal asks for. Its card carries
    the validation block (verdict, rounds, attempts). Yields its ``change``
    event; writes the change's id, or why it did not land, into *done*.
    *asker*: the person the job took when it started, whom the change names
    and whose own focus in the node never holds it back; *room_asker*, the
    same as the room names them, whom the node's agent at work for the write
    says asked it."""
    change_attachment = home_attachment_id or attachment_id
    change_session = home_session_id or session_id
    ctx = {"attachment_id": change_attachment, "session_id": change_session,
           "asker_id": getattr(asker, "id", None), "asker": asker, "room_asker": room_asker,
           "_intent_texts": tuple(text for text in intent_texts if text)}
    if isinstance(session_id, str):
        # The change lands in the node's agent's chat, but the user's words are
        # in the chat that asked for the validation, which the round's source
        # check read: the landing's check reads the same chat.
        ctx["asked_in_session_id"] = session_id
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
    rounds = count_label(rounds_used, "round")
    # A chart's or a map's document the sandbox does not run: its grammar's
    # schema validated it, and nothing failed.
    validated = labels.document_validated(done["verdict"], done["evidence"])
    if isinstance(change_session, str):
        sessions.append_turns(
            user_key, project_id, change_session, change_attachment,
            [sessions.make_turn(
                "agent",
                f"Validated {label!r} against its grammar after {rounds}, written into the node." if validated
                else f"Validated {label}: its code ran after {rounds} and is written into the node."
                if done["verdict"] == "pass"
                else f"Validated content for {label!r}: {done['verdict'].upper()} after {rounds}, written into the node.",
                content=[_trace_card(done, rounds_used, rounds_trace), part],
            )],
        )
    if home_attachment_id and home_attachment_id != attachment_id and isinstance(session_id, str):
        # The parent references and LINKS; the story lives at home. The agent
        # that wrote it is named as its manifest names it. Its chat does not
        # draw the turn: the node's row on the plan's card says it is built,
        # and its name opens that chat. The agents read it.
        delegate = getattr(resolution, "manifest", None)
        delegate_coord = getattr(resolution, "coord", None) or ""
        delegate_name = getattr(delegate, "name", None) or delegate_coord
        said = (f"Validated {label!r} against its grammar after {rounds}" if validated
                else f"Solved {label!r}: {done['verdict'].upper()} after {rounds}")
        sessions.append_turns(
            user_key, project_id, session_id, attachment_id,
            [sessions.make_turn(
                "agent",
                f"{said}: the trace and the change live in the node's {delegate_name}.",
                for_agents=True,
                content=[content.make_delegation_part(
                    capability="node.content.generate",
                    coord=delegate_coord,
                    name=delegate_name,
                    category=getattr(delegate, "category", "") or "",
                    attachment_id=home_attachment_id,
                    status="ok",
                    summary=(f"Validated {label!r} against its grammar ({rounds})" if validated
                             else f"Solve {label!r}: {done['verdict']} ({rounds})"),
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
        spec, node.get("id"), label,
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


#: How a node's code that landed was checked, as its row on the plan's card
#: says it (``nodeChecks``): it ran in the sandbox, its document is valid
#: against its grammar, or it was written with no code to run.
CHECK_RAN, CHECK_VALID, CHECK_WRITTEN = "ran", "valid", "written"

#: The plan's ledger of checks: how each node's code was checked, by ref, and
#: the digest of the code each check was made on.
CHECKS, CHECKED_CODE = "nodeChecks", "nodeCheckedCode"


def check_of(done: dict) -> str | None:
    """How the code a validation landed was checked (``CHECK_*``), from its
    verdict and evidence; None for code that did not pass."""
    if done.get("verdict") == "pass":
        return CHECK_RAN
    if done.get("verdict") == "not-executable":
        return CHECK_VALID if labels.document_validated("not-executable", done.get("evidence") or {}) else CHECK_WRITTEN
    return None


def node_code(spec: dict, node_id: object) -> str | None:
    """The code the node *node_id* holds in *spec*; None when *spec* holds no
    such node."""
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    return None if node is None else str(node.get("content") or "")


def keep_check(session: dict, ref: str, check: str | None, code: str | None) -> None:
    """Keep in the plan's ledger (*session*) how the code of its node *ref*
    was checked, *check*, with the digest of *code*, the code that check was
    made on. With no check, or no code, the ledger keeps none for *ref*: no
    row claims a check that did not run on the code its node holds."""
    if check and code is not None:
        session.setdefault(CHECKS, {})[ref] = check
        session.setdefault(CHECKED_CODE, {})[ref] = agents_rounds._content_sha(code)
        return
    for key in (CHECKS, CHECKED_CODE):
        held = session.get(key)
        if isinstance(held, dict):
            held.pop(ref, None)


def checks_that_hold(spec: dict, session: dict | None) -> dict[str, str]:
    """The checks of *session*'s plan nodes that still hold in *spec*: each
    ``nodeChecks`` entry whose node holds the code the check was made on. A
    change to a node's code after its check, by anyone, drops the check, and
    so does a node no longer there."""
    session = session if isinstance(session, dict) else {}
    digests = session.get(CHECKED_CODE) or {}
    node_ids = session.get("nodeIds") or {}
    held: dict[str, str] = {}
    for ref, check in (session.get(CHECKS) or {}).items():
        code = node_code(spec, node_ids.get(ref))
        if code is not None and digests.get(ref) == agents_rounds._content_sha(code):
            held[ref] = check
    return held


def session_as_it_holds(spec: dict, session: dict | None) -> dict | None:
    """A copy of the plan's ledger *session* as a reader of *spec* is told it:
    its checks those that still hold (:func:`checks_that_hold`). The ledger
    kept is never changed by a read."""
    if not isinstance(session, dict):
        return session
    shown = dict(session)
    if CHECKS in shown:
        shown[CHECKS] = checks_that_hold(spec, session)
    return shown


#: Why a build paused when a node's check failed (``pauseReason.kind``).
PAUSED_ON_A_FAILURE = "validation-failed"


def end_pause_on(session: dict, ref: str | None) -> None:
    """A build's pause on a node whose check failed is about that node
    alone: once something builds the node, the plan is paused on nothing,
    and its line says where it stands."""
    pause = session.get("pauseReason")
    if ref and isinstance(pause, dict) and pause.get("kind") == PAUSED_ON_A_FAILURE and pause.get("ref") == ref:
        session.pop("pauseReason", None)


def _settle_node_state(user_key, project_id, attachment_id, ref, verdict: str, *,
                       by: str = agents_node_work.BY_ROW, check: str | None = None) -> dict:
    """The per-node ledger: validated / failed / waiting for its source;
    infrastructure untouched. Written on the plan's record as the dataflow
    holds it now, under its spec lock, so a pick that landed meanwhile keeps
    its move. A node left waiting for its source keeps who left it so
    (``sourceWaitBy``: *by*, the build's mode or ``node`` for a row's Solve),
    which says how the plan goes on after the pick. A node validated keeps
    how its code was checked (``nodeChecks``: *check*, :func:`check_of`),
    with the code it was checked on, which its row's tick says, and a build's
    pause on its failure ends; one that did not lose its check. Returns the
    builder session."""
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = agents_spec_reads._live_spec_or_404(user_key, project_id)
        fresh_record = agents_spec_reads._record_or_404(fresh, attachment_id)
        fresh_session = fresh_record.get("builderSession") or {}
        if ref and isinstance(fresh_session.get("nodeStates"), dict):
            if verdict in ("pass", "not-executable"):
                # dev/118: a browser-rendered kind proceeds like a pass in the
                # plan's ledger (Simulation Mode auto-approves it); the
                # change's validation block carries the honest label.
                fresh_session["nodeStates"][ref] = "validated"
                keep_check(fresh_session, ref, check,
                           node_code(fresh, (fresh_session.get("nodeIds") or {}).get(ref)))
                end_pause_on(fresh_session, ref)
            elif verdict != "infrastructure":
                keep_check(fresh_session, ref, None, None)
            if verdict == "fail":
                fresh_session["nodeStates"][ref] = "failed"
            elif verdict == AWAITING_SOURCE:
                # The node waits for its source, for what its Dataset Finder's
                # record says now: its row says so, and Build & validate goes
                # on past it with every node that does not read from it. A
                # source picked while it was checked places it again, so the
                # run builds it.
                node_id = (fresh_session.get("nodeIds") or {}).get(ref)
                fresh_session["nodeStates"][ref] = plan_wait_state(fresh, node_id, user_key)
            if fresh_session["nodeStates"].get(ref) in SOURCE_WAITS:
                fresh_session.setdefault("sourceWaitBy", {})[ref] = by
            elif verdict != "infrastructure":
                (fresh_session.get("sourceWaitBy") or {}).pop(ref, None)
        for key in _VALIDATING:
            fresh_session.pop(key, None)
        fresh_record["builderSession"] = fresh_session
        dataflow_docs.write(user_key, project_id, fresh, agents_spec_reads._agent_actor(user_key, fresh, attachment_id, "validate"))
    return fresh_session


def _clear_validating_guard(user_key, project_id, attachment_id) -> None:
    """Disconnect-safe: the in-flight guard never wedges the attachment.
    Cleared on the record as the dataflow holds it now, under its spec lock."""
    with contextlib.suppress(Exception), projects_storage.spec_write_lock(user_key, project_id):
        cleanup_spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
        cleanup_record = agents_spec_reads._record_or_404(cleanup_spec, attachment_id)
        cleanup_session = cleanup_record.get("builderSession") or {}
        popped = [cleanup_session.pop(key, None) for key in _VALIDATING]
        if any(value is not None for value in popped):
            cleanup_record["builderSession"] = cleanup_session
            dataflow_docs.write(
                user_key, project_id, cleanup_spec,
                agents_spec_reads._agent_actor(user_key, cleanup_spec, attachment_id, "validate"),
            )
