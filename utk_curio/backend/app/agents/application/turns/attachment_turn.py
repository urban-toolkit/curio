"""One chat turn on an attachment: ``run_attachment`` and its streaming twin.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import time
import uuid

from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.application.tool_rounds import ParamRefusal
from utk_curio.backend.app.agents.application.tool_rounds import _RunConversation
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.infrastructure import provider_config
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn
from utk_curio.backend.app.agents.infrastructure.providers import NativeToolsRefused
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.infrastructure.providers import ToolCall
from utk_curio.backend.app.agents.repositories import ledger
from utk_curio.backend.app.agents.application import tool_rounds as agents_tool_rounds
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import policy as agents_policy
from utk_curio.backend.app.agents.application.turns import prepare as agents_prepare
from utk_curio.backend.app.agents.application.turns import titles as agents_titles
from utk_curio.backend.app.agents.infrastructure import providers as agents_providers


def run_attachment(
    user_key: str,
    project_id: str,
    attachment_id: str,
    message: str,
    config: ProviderConfig,
    run_context: str | None = None,
) -> dict:
    """Run one turn of an attached agent through the provider port.

    Session-aware (dev/20): the system turn is the attachment's intent override
    (dev/19) or the resolved instruction prompt, followed by a bounded window of
    the session's prior turns, then the new user message. Both sides of the
    exchange persist to the session file so a reload restores the conversation;
    a provider failure persists the user turn plus a display-only error marker
    (excluded from future context) so history matches what the user saw.
    """
    coord, session_id, messages, run_policy, wants_title, pins, loop_ctx = agents_prepare._prepare_run(
        user_key, project_id, attachment_id, message, config, run_context
    )
    # dev/114: the current user text — turns persist AFTER the run, so the
    # grounding gate cannot read it from the session; a path the user typed
    # is the one human-trusted source of a local path.
    loop_ctx["message"] = message
    execution_id = uuid.uuid4().hex
    # Atomic admission (dev/40): after validation (an invalid request never
    # consumes quota), before provider dispatch (a denied run never reaches a
    # provider). The reservation IS this execution (one id), and the price
    # snapshot pinned here is what settlement charges.
    reservation = ledger.reserve(
        user_key,
        reservation_id=execution_id,
        llm_config_id=config.config_id,
        **run_policy["admit"],
    )
    usage_total: dict = {}
    tool_calls: list = []
    delegations: list = []
    minted: list = []
    folded: list[str] = []
    final_parts: list = []
    conversation = _RunConversation(messages, loop_ctx)
    rounds_used = 0
    refusals_used = 0  # dev/105 D2: free parameter corrections taken
    started = time.monotonic()
    try:
        # The bounded tool loop (memos dev/41/48): parse → execute granted
        # read tool / mint proposal / run depth-1 delegate → re-prompt, at
        # most MAX_TOOL_ROUNDS request executions per run (one shared budget).
        while True:
            usage_sink: dict = {}
            try:
                turn = ChatTurn.of(agents_providers.run_chat_turn(
                    config,
                    conversation.messages,
                    max_output_tokens=run_policy["max_output_tokens"],
                    usage_out=usage_sink,
                    **conversation.offer(rounds_used),
                ))
            except NativeToolsRefused as refusal:
                # The endpoint takes no native tools after all: the same round
                # again, on the fenced protocol.
                conversation.fall_back(refusal, pins)
                continue
            conversation.answered(config, user_key)
            reply = turn.text
            agents_policy._add_usage(usage_total, usage_sink)
            visible, parts = content.extract_content(reply)
            agents_grounding._verify_candidate_parts(parts, loop_ctx)  # dev/67-4: no unverified laundering
            req = (
                parts[0]
                if parts and parts[0].get("type") in ("toolRequest", "delegateRequest")
                else None
            )
            native_calls = conversation.native_calls(turn)
            if native_calls:
                # A native call is the round's request, whatever the text says.
                req, call_errors = agents_tool_rounds._native_request(native_calls[0])
                if req is None:
                    if rounds_used < agents_tool_rounds.MAX_TOOL_ROUNDS:
                        rounds_used += 1
                        conversation.add_unreadable_call_round(
                            turn, call_errors, final=rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS
                        )
                        continue
                    # Past the cap: the text stays, and a proposal that could
                    # not be made says why.
                    if visible:
                        folded.append(visible)
                    if agents_tool_rounds._is_mutate_call(native_calls[0]):
                        final_parts = [agents_tool_rounds._tool_cap_card(call_errors)]
                    break
            if req is None:
                # Plan handling (dev/52 mint; dev/54 correction rounds).
                kind, payload, visible_override = agents_tool_rounds._handle_plan_reply(
                    user_key, project_id, loop_ctx, reply, parts, minted, rounds_used
                )
                if kind == "correct":
                    # Corrective prose is not folded: the invalid attempt never
                    # reaches the user; the final round's text is the truth.
                    rounds_used += 1
                    conversation.add_text_round(
                        reply, agents_tool_rounds._plan_correction_message(payload),
                        agents_tool_rounds._plan_correction_message(payload, native=True),
                    )
                    continue
                if kind == "none":
                    # #245: only once the plan handler has declined — a
                    # toolRequest the parser could not take (wrong fence,
                    # trailing prose, correctable params) must never fold into
                    # the chat as raw JSON.
                    kind, payload, visible_override, req = agents_tool_rounds._handle_tool_reply(
                        loop_ctx, reply, parts, rounds_used
                    )
                    if kind == "correct":
                        rounds_used += 1
                        conversation.add_text_round(
                            reply, agents_tool_rounds._tool_correction_message(payload),
                            agents_tool_rounds._tool_correction_message(payload, native=True),
                        )
                        continue
                if req is None:
                    effective_visible = (
                        visible_override if visible_override is not None else visible
                    )
                    if effective_visible:
                        folded.append(effective_visible)
                    final_parts = payload
                    break
                # A RECOVERED request falls through to the shared request path
                # below, so grant re-check, mint, cap card and the dev/105 D2
                # free-refusal accounting all apply to it unchanged.
                visible = visible_override if visible_override is not None else visible
            if visible:
                folded.append(visible)
            if rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS:
                # dev/73: a mutate request cut off at the cap is a visible
                # outcome — never a silent drop under confident prose.
                if req["type"] == "toolRequest" and req.get("tool") in agents_tool_rounds.MUTATE_PROPOSAL_TOOLS:
                    minted.append(agents_tool_rounds._round_cap_cutoff_card(req["tool"]))
                break  # dangling read request at the cap: dropped, text kept
            if req["type"] == "delegateRequest":
                rounds_used += 1
                final = rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS
                status, text, resolution = agents_delegates._resolve_delegate_request(
                    user_key, project_id, loop_ctx, req, minted
                )
                if resolution is not None:
                    # dev/73: node-scoped content generation homes its trace
                    # AND its minted review at the node's own agent.
                    gen_node_id = (
                        agents_delegates._delegate_target_node_id(loop_ctx, req.get("inputs") or {})
                        if req["capability"] == "node.content.generate"
                        else None
                    )
                    status, text, child, home_att = agents_delegates._run_delegate_traced(
                        user_key,
                        project_id,
                        resolution.coord,
                        req["capability"],
                        agents_delegates._enriched_delegate_inputs(
                            user_key, project_id, loop_ctx,
                            req["capability"], req.get("inputs") or {},
                        ),
                        config,
                        parent_execution_id=execution_id,
                        parent_coord=loop_ctx["coord"],
                        attachment_id=loop_ctx.get("attachment_id"),
                        parent_name=getattr(loop_ctx.get("manifest"), "name", None),
                        node_id=gen_node_id,
                    )
                    delegations.append(child)
                    delegate_summary = text
                    if status == "ok" and gen_node_id:
                        # dev/73: generation success ⇒ the review EXISTS —
                        # runtime-minted, never the model's second step.
                        review_part, review_home, text = agents_delegates._mint_content_review_from_delegate(
                            user_key, project_id,
                            node_id=gen_node_id,
                            generated_text=text,
                            parent_attachment_id=loop_ctx.get("attachment_id"),
                            parent_session_id=loop_ctx.get("session_id"),
                            parent_loop_ctx=loop_ctx,
                        )
                        delegate_summary = text
                        if review_part is not None:
                            delegate_summary = (
                                f"reviewed content change proposed for node "
                                f"{gen_node_id!r} — awaits Apply"
                            )
                            if review_home == loop_ctx.get("attachment_id"):
                                minted.append(review_part)
                    elif status == "ok" and req["capability"] in agents_delegates.PACKAGE_AUTHORING_CAPABILITIES:
                        # dev/90: authoring success ⇒ the reviewed draft
                        # EXISTS — runtime-minted from the child's payload,
                        # never the model's second step.
                        draft_part, text, draft_outcome = agents_delegates._mint_package_draft_from_delegate(
                            user_key, project_id, loop_ctx, text,
                            delegate_inputs=req.get("inputs") or {},
                            redelegate=agents_delegates._draft_corrector(
                                user_key, project_id, loop_ctx, req, resolution,
                                config, execution_id, delegations,
                            ),
                        )
                        delegate_summary = text
                        if draft_part is not None:
                            minted.append(draft_part)
                            delegate_summary = (
                                "reviewed package draft proposed — awaits Apply"
                            )
                        # dev/93 D5: the delegation card reports the OUTCOME,
                        # not merely that the child ran — "ok" beside "returned
                        # no parseable draft" is how the parent learned nothing.
                        status = draft_outcome
                    elif status == "ok" and req["capability"] == "dataset.discover":
                        # dev/114: discovery success ⇒ the two-lane candidates part
                        # EXISTS on this turn — runtime-minted (catalog rows tool-
                        # grounded, external rows probed), never the model's claim.
                        cand_part, text, cand_outcome = agents_delegates._mint_candidates_from_delegate(
                            loop_ctx, text,
                            ((req.get("inputs") or {}).get("catalog") or {}).get("rows")
                            or agents_delegates._dataset_discover_inputs(user_key, project_id, {})["catalog"]["rows"],
                        )
                        delegate_summary = text
                        if cand_part is not None:
                            minted.append(cand_part)
                            delegate_summary = "dataset candidates shown for review — select and confirm"
                        status = cand_outcome
                    elif status == "ok" and req["capability"] == "research.notes.compose":
                        # dev/95 (Follow-up D): notes success ⇒ the reviewed
                        # A16 sequence EXISTS — runtime-minted from the
                        # child's schema reply, never the model's second step.
                        note_parts, text, notes_outcome = agents_delegates._mint_notes_from_delegate(
                            user_key, project_id, loop_ctx, text,
                        )
                        delegate_summary = text
                        if note_parts:
                            minted.extend(note_parts)
                            delegate_summary = (
                                f"{len(note_parts)} reviewed note proposal(s) "
                                "— await Apply"
                            )
                        status = notes_outcome
                    # dev/72: the parent keeps the compact, linkable entry.
                    minted.append(agents_delegates._delegation_part_for(
                        resolution, req["capability"], status, delegate_summary, home_att,
                        child=child,
                    ))
                    result_msg = agents_tool_rounds._delegate_result_message(
                        resolution.coord, req["capability"], status, text, final=final
                    )
                else:
                    result_msg = agents_tool_rounds._delegate_result_message(
                        None, req["capability"], status, text, final=final
                    )
                if native_calls:
                    conversation.add_call_round(
                        turn, req, status, text, final=final, fenced_feedback=result_msg
                    )
                else:
                    conversation.add_text_round(reply, result_msg)
                continue
            status, text = agents_tool_rounds._execute_tool_request(
                user_key, project_id, loop_ctx, req, tool_calls, minted
            )
            if isinstance(text, ParamRefusal) and refusals_used < agents_tool_rounds.MAX_REFUSED_ROUNDS:
                refusals_used += 1  # dev/105 D2: a free correction, not a round
            else:
                rounds_used += 1
            final = rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS
            result_msg = agents_tool_rounds._tool_result_message(req["tool"], status, text, final=final)
            if native_calls:
                conversation.add_call_round(
                    turn, req, status, text, final=final, fenced_feedback=result_msg
                )
            else:
                conversation.add_text_round(reply, result_msg)
    except Exception as exc:
        agents_policy._add_usage(usage_total, usage_sink)
        # An error settles too: the hold releases and the truth is recorded.
        settled = ledger.settle(
            user_key, reservation, usage=usage_total or None, status="error"
        )
        agents_prepare._persist_exchange(
            user_key,
            project_id,
            session_id,
            attachment_id,
            message,
            f"(error) {provider_config.redact_error(exc, config)}",
            error=True,
            execution=agents_policy._execution_record(
                execution_id, pins, usage_total, started, "error", tool_calls,
                     delegations=delegations,
            ),
        )
        raise AgentServiceError(
            f"agent run failed: {provider_config.redact_error(exc, config)}", 502
        ) from exc
    reply_text = "\n\n".join(folded)
    run_parts = minted + final_parts  # proposals ride the turn (dev/41)
    settled = ledger.settle(user_key, reservation, usage=usage_total or None, status="ok")
    execution = agents_policy._execution_record(
        execution_id, pins, usage_total, started, "ok", tool_calls,
                     delegations=delegations,
        refused_rounds=refusals_used,
    )
    agents_prepare._persist_exchange(
        user_key,
        project_id,
        session_id,
        attachment_id,
        message,
        reply_text,
        execution=execution,
        parts=run_parts,
    )
    if wants_title:
        agents_titles._generate_conversation_title(user_key, project_id, attachment_id, message, config)
    return {
        "attachmentId": attachment_id,
        "coord": coord,
        "reply": reply_text,
        "executionId": execution_id,
        "usage": execution["usage"],
        # dev/80: the run's wall-clock duration — matches the persisted record.
        "durationMs": execution["durationMs"],
        "content": run_parts,
    }


def stream_attachment(
    user_key: str,
    project_id: str,
    attachment_id: str,
    message: str,
    config: ProviderConfig,
    run_context: str | None = None,
):
    """Streaming twin of :func:`run_attachment` (memo dev/22).

    Validates eagerly (404/422 raise before any streaming starts), then returns
    a generator opening with ``("execution", {executionId})`` (memo dev/37),
    followed by ``("delta", text)`` events, ``("usage", {usage})`` interim
    Actual sums once per provider round (memo dev/80), optionally
    ``("content", {parts})`` when the reply carried a valid structured tail
    (memo dev/39), ending in
    ``("done", {reply, executionId, usage, durationMs, content})`` — or
    ``("error", message)`` on a provider failure. Persistence semantics are
    identical to ``run_attachment``: the full exchange is written once at
    completion; a failure persists the user turn plus a display-only error
    marker. Nothing is persisted per-delta.
    """
    coord, session_id, messages, run_policy, wants_title, pins, loop_ctx = agents_prepare._prepare_run(
        user_key, project_id, attachment_id, message, config, run_context
    )
    # dev/114: the current user text — turns persist AFTER the run, so the
    # grounding gate cannot read it from the session; a path the user typed
    # is the one human-trusted source of a local path.
    loop_ctx["message"] = message
    execution_id = uuid.uuid4().hex
    # Eager atomic admission (dev/40): a quota/budget denial surfaces as a
    # plain 429 before any streaming begins, and consumes/persists nothing.
    reservation = ledger.reserve(
        user_key,
        reservation_id=execution_id,
        llm_config_id=config.config_id,
        **run_policy["admit"],
    )

    marker = content.TAIL_FENCE

    def _hold_split(buf: str) -> tuple[str, str]:
        """Emit-now / keep split: retain the longest trailing suffix of *buf*
        that could still be the start of the tail-fence marker (≤ ~16 chars
        held back at any moment — imperceptible in the live transcript)."""
        for k in range(min(len(marker) - 1, len(buf)), 0, -1):
            if marker.startswith(buf[-k:]):
                return buf[:-k], buf[-k:]
        return buf, ""

    def _stream_round(
        conversation: "_RunConversation", rounds_used: int, usage_sink: dict, result: dict,
        hold_plan_tail: bool = False, hold_request_tail: bool = False,
    ):
        """Stream one provider round: yields ("delta", text) with the dev/39
        tail withholding, then leaves {reply, visible, parts} in *result*.
        ``hold_plan_tail`` (dev/54): an INVALID tail that looks like a plan
        attempt is held (``result["heldPlanTail"]``) instead of flushed — the
        correction round must not leak raw plan JSON to the user; the caller
        releases it at the round cap (fail-open transparency).
        ``hold_request_tail`` (#245): the same for a mutate toolRequest tail —
        held in ``result["heldToolTail"]`` and, unlike the plan tail, never
        released: the params are a whole source file, and streaming them as
        chat prose IS the bug (see ``_handle_tool_reply``)."""
        chunks: list[str] = []
        calls: list = []
        buf = ""  # pass-mode text not yet emitted
        withheld: str | None = None  # not None → holding a candidate tail
        for delta in agents_providers.stream_chat_turn(
            config,
            conversation.messages,
            max_output_tokens=run_policy["max_output_tokens"],
            usage_out=usage_sink,
            **conversation.offer(rounds_used),
        ):
            if isinstance(delta, ToolCall):
                calls.append(delta)  # a native call is an event, never text
                continue
            if not isinstance(delta, str):
                continue  # a text delta is a bare string
            chunks.append(delta)
            if withheld is not None:
                withheld += delta
                close = withheld.find("\n```", len(marker))
                if close != -1 and withheld[close + 4 :].strip():
                    # Closed fence followed by more content: not terminal —
                    # flush the closed block verbatim and rescan the rest.
                    yield ("delta", withheld[: close + 4])
                    buf = withheld[close + 4 :]
                    withheld = None
                else:
                    continue
            else:
                buf += delta
            idx = buf.find(marker)
            if idx != -1:
                if buf[:idx]:
                    yield ("delta", buf[:idx])
                withheld = buf[idx:]
                buf = ""
            else:
                emit, buf = _hold_split(buf)
                if emit:
                    yield ("delta", emit)
        reply = "".join(chunks)
        visible, parts = content.extract_content(reply)
        agents_grounding._verify_candidate_parts(parts, loop_ctx)  # dev/67-4: no unverified laundering
        if withheld is not None and not parts:
            if hold_plan_tail and (
                '"dataflowPlan"' in withheld or '"dataflow.plan.write"' in withheld
            ):
                # A failed plan attempt (dev/54): held for the correction
                # round instead of leaking raw JSON into the chat.
                result["heldPlanTail"] = withheld
            elif hold_request_tail and '"toolRequest"' in withheld and any(
                f'"{tool}"' in withheld for tool in agents_tool_rounds.MUTATE_PROPOSAL_TOOLS
            ):
                # #245: a failed mutate request. The old code fell to the
                # fail-open branch below and streamed the whole node source
                # into the transcript as it arrived.
                result["heldToolTail"] = withheld
            else:
                # Invalid or non-terminal tail: fail-open (dev/39 §4.2) — the
                # withheld text is the model's, so it streams after all.
                yield ("delta", withheld)
        elif withheld is None and buf:
            yield ("delta", buf)  # stream ended on a partial fence prefix
        result["reply"] = reply
        result["visible"] = visible
        result["parts"] = parts
        result["turn"] = ChatTurn(text=reply, tool_calls=tuple(calls))

    def _events():
        usage_total: dict = {}
        tool_calls: list = []
        delegations: list = []
        minted: list = []
        # dev/73: reviews minted at a FOREIGN home (the node's agent) — they
        # never ride the parent turn's parts, but still pause at review.
        homed_reviews: list = []
        folded: list[str] = []
        final_parts: list = []
        conversation = _RunConversation(messages, loop_ctx)
        rounds_used = 0
        refusals_used = 0  # dev/105 D2: free parameter corrections taken
        usage_sink: dict = {}
        started = time.monotonic()
        # The typed-envelope handshake (memo dev/37): the execution identity
        # arrives before the first delta so a client can correlate the stream
        # with the record that will land on the transcript.
        yield ("execution", {"executionId": execution_id})
        try:
            # The bounded tool loop (memos dev/41/48): each round streams its
            # own deltas; a toolRequest tail becomes tool events and a
            # delegateRequest tail becomes delegate events, never text.
            while True:
                usage_sink = {}
                result: dict = {}
                try:
                    yield from _stream_round(
                        conversation,
                        rounds_used,
                        usage_sink,
                        result,
                        hold_plan_tail="dataflow.plan.write" in loop_ctx.get("granted", []),
                        hold_request_tail=bool(
                            set(loop_ctx.get("granted") or []) & agents_tool_rounds.MUTATE_PROPOSAL_TOOLS
                        ),
                    )
                except NativeToolsRefused as refusal:
                    # Refused before anything streamed: the same round again,
                    # on the fenced protocol.
                    conversation.fall_back(refusal, pins)
                    continue
                conversation.answered(config, user_key)
                agents_policy._add_usage(usage_total, usage_sink)
                if usage_sink:
                    # dev/80: interim Actual sums, once per provider round —
                    # the client's live token counter ticks during long tool
                    # loops. Additive; old clients skip unknown events.
                    yield ("usage", {"usage": dict(usage_total)})
                parts = result["parts"]
                req = (
                    parts[0]
                    if parts and parts[0].get("type") in ("toolRequest", "delegateRequest")
                    else None
                )
                native_calls = conversation.native_calls(result["turn"])
                if native_calls:
                    # A native call is the round's request, whatever the text says.
                    req, call_errors = agents_tool_rounds._native_request(native_calls[0])
                    if req is None:
                        if rounds_used < agents_tool_rounds.MAX_TOOL_ROUNDS:
                            rounds_used += 1
                            yield (
                                "tool_revision",
                                {"attempt": rounds_used, "errors": len(call_errors)},
                            )
                            conversation.add_unreadable_call_round(
                                result["turn"], call_errors,
                                final=rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS,
                            )
                            continue
                        # Past the cap: see the non-streaming path.
                        if result["visible"]:
                            folded.append(result["visible"])
                        if agents_tool_rounds._is_mutate_call(native_calls[0]):
                            final_parts = [agents_tool_rounds._tool_cap_card(call_errors)]
                        break
                if req is None:
                    # Plan handling (dev/52 mint; dev/54 correction rounds).
                    kind, payload, visible_override = agents_tool_rounds._handle_plan_reply(
                        user_key, project_id, loop_ctx, result["reply"], parts, minted, rounds_used
                    )
                    if kind == "correct":
                        rounds_used += 1
                        yield (
                            "plan_revision",
                            {"attempt": rounds_used, "errors": len(payload)},
                        )
                        conversation.add_text_round(
                            result["reply"], agents_tool_rounds._plan_correction_message(payload),
                            agents_tool_rounds._plan_correction_message(payload, native=True),
                        )
                        continue
                    if kind == "none":
                        # #245: the toolRequest twin, after the plan handler.
                        kind, payload, visible_override, req = agents_tool_rounds._handle_tool_reply(
                            loop_ctx, result["reply"], parts, rounds_used
                        )
                        if kind == "correct":
                            rounds_used += 1
                            yield (
                                "tool_revision",
                                {"attempt": rounds_used, "errors": len(payload)},
                            )
                            conversation.add_text_round(
                                result["reply"], agents_tool_rounds._tool_correction_message(payload),
                                agents_tool_rounds._tool_correction_message(payload, native=True),
                            )
                            continue
                        # A held request tail is NOT released at the cap: see
                        # _handle_tool_reply — a source file is not a spec.
                    if kind == "cap" and result.get("heldPlanTail"):
                        # Fail-open transparency at the cap: the held tail is
                        # the model's text — released, then explained by the
                        # error card in `payload`.
                        yield ("delta", result["heldPlanTail"])
                    if req is not None:
                        # A RECOVERED request: fall through to the shared
                        # request path with the block stripped from the text.
                        if visible_override is not None:
                            result["visible"] = visible_override
                    else:
                        effective_visible = (
                            visible_override if visible_override is not None
                            else result["visible"]
                        )
                        if effective_visible:
                            folded.append(effective_visible)
                        final_parts = payload
                        break
                if result["visible"]:
                    folded.append(result["visible"])
                if rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS:
                    # dev/73: a mutate request cut off at the cap is a visible
                    # outcome — never a silent drop under confident prose.
                    if req["type"] == "toolRequest" and req.get("tool") in agents_tool_rounds.MUTATE_PROPOSAL_TOOLS:
                        minted.append(agents_tool_rounds._round_cap_cutoff_card(req["tool"]))
                    break  # dangling read request at the cap: dropped, text kept
                if req["type"] == "delegateRequest":
                    rounds_used += 1
                    final = rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS
                    yield ("delegate_requested", {"capability": req["capability"]})
                    status, text, resolution = agents_delegates._resolve_delegate_request(
                        user_key, project_id, loop_ctx, req, minted
                    )
                    if resolution is not None:
                        yield (
                            "delegate_started",
                            {"capability": req["capability"], "coord": resolution.coord},
                        )
                        # dev/73: node-scoped content generation homes its
                        # trace AND its minted review at the node's own agent.
                        gen_node_id = (
                            agents_delegates._delegate_target_node_id(loop_ctx, req.get("inputs") or {})
                            if req["capability"] == "node.content.generate"
                            else None
                        )
                        status, text, child, home_att = agents_delegates._run_delegate_traced(
                            user_key,
                            project_id,
                            resolution.coord,
                            req["capability"],
                            agents_delegates._enriched_delegate_inputs(
                                user_key, project_id, loop_ctx,
                                req["capability"], req.get("inputs") or {},
                            ),
                            config,
                            parent_execution_id=execution_id,
                            parent_coord=loop_ctx["coord"],
                            attachment_id=loop_ctx.get("attachment_id"),
                            parent_name=getattr(loop_ctx.get("manifest"), "name", None),
                            node_id=gen_node_id,
                        )
                        delegations.append(child)
                        delegate_summary = text
                        if status == "ok" and gen_node_id:
                            # dev/73: generation success ⇒ the review EXISTS —
                            # runtime-minted, never the model's second step.
                            review_part, review_home, text = agents_delegates._mint_content_review_from_delegate(
                                user_key, project_id,
                                node_id=gen_node_id,
                                generated_text=text,
                                parent_attachment_id=loop_ctx.get("attachment_id"),
                                parent_session_id=loop_ctx.get("session_id"),
                                parent_loop_ctx=loop_ctx,
                            )
                            delegate_summary = text
                            if review_part is not None:
                                delegate_summary = (
                                    f"reviewed content change proposed for node "
                                    f"{gen_node_id!r} — awaits Apply"
                                )
                                if review_home == loop_ctx.get("attachment_id"):
                                    minted.append(review_part)
                                else:
                                    homed_reviews.append((review_part, review_home))
                        elif status == "ok" and req["capability"] in agents_delegates.PACKAGE_AUTHORING_CAPABILITIES:
                            # dev/90: authoring success ⇒ the reviewed draft
                            # EXISTS — runtime-minted from the child's
                            # payload, never the model's second step.
                            draft_part, text, draft_outcome = agents_delegates._mint_package_draft_from_delegate(
                                user_key, project_id, loop_ctx, text,
                                delegate_inputs=req.get("inputs") or {},
                                redelegate=agents_delegates._draft_corrector(
                                    user_key, project_id, loop_ctx, req, resolution,
                                    config, execution_id, delegations,
                                ),
                            )
                            delegate_summary = text
                            if draft_part is not None:
                                minted.append(draft_part)
                                delegate_summary = (
                                    "reviewed package draft proposed — awaits Apply"
                                )
                            # dev/93 D5: the card reports the OUTCOME (see the
                            # non-streaming path).
                            status = draft_outcome
                        elif status == "ok" and req["capability"] == "dataset.discover":
                            # dev/114: discovery success ⇒ the two-lane candidates part
                            # EXISTS on this turn — runtime-minted (catalog rows tool-
                            # grounded, external rows probed), never the model's claim.
                            cand_part, text, cand_outcome = agents_delegates._mint_candidates_from_delegate(
                                loop_ctx, text,
                                ((req.get("inputs") or {}).get("catalog") or {}).get("rows")
                                or agents_delegates._dataset_discover_inputs(user_key, project_id, {})["catalog"]["rows"],
                            )
                            delegate_summary = text
                            if cand_part is not None:
                                minted.append(cand_part)
                                delegate_summary = "dataset candidates shown for review — select and confirm"
                            status = cand_outcome
                        elif status == "ok" and req["capability"] == "research.notes.compose":
                            # dev/95: see the non-streaming path.
                            note_parts, text, notes_outcome = agents_delegates._mint_notes_from_delegate(
                                user_key, project_id, loop_ctx, text,
                            )
                            delegate_summary = text
                            if note_parts:
                                minted.extend(note_parts)
                                delegate_summary = (
                                    f"{len(note_parts)} reviewed note "
                                    "proposal(s) — await Apply"
                                )
                            status = notes_outcome
                        # dev/72: the parent keeps the compact, linkable entry.
                        minted.append(agents_delegates._delegation_part_for(
                            resolution, req["capability"], status, delegate_summary, home_att,
                            child=child,
                        ))
                        yield (
                            "delegate_result",
                            {
                                "capability": req["capability"],
                                "coord": resolution.coord,
                                # dev/72: the live line can link too.
                                "attachmentId": home_att,
                                "name": getattr(resolution.manifest, "name", None)
                                if resolution.manifest else None,
                                "status": status,
                                "durationMs": child.get("durationMs"),
                                # What the child ran on, which may not be the parent's.
                                "model": (child.get("pins") or {}).get("model"),
                                "llmLabel": ((child.get("pins") or {}).get("llm") or {}).get("label"),
                            },
                        )
                        result_msg = agents_tool_rounds._delegate_result_message(
                            resolution.coord, req["capability"], status, text, final=final
                        )
                    else:
                        yield (
                            "delegate_result",
                            {"capability": req["capability"], "status": status},
                        )
                        result_msg = agents_tool_rounds._delegate_result_message(
                            None, req["capability"], status, text, final=final
                        )
                    if native_calls:
                        conversation.add_call_round(
                            result["turn"], req, status, text,
                            final=final, fenced_feedback=result_msg,
                        )
                    else:
                        conversation.add_text_round(result["reply"], result_msg)
                    continue
                yield ("tool_requested", {"tool": req["tool"]})
                yield ("tool_started", {"tool": req["tool"]})
                status, text = agents_tool_rounds._execute_tool_request(
                    user_key, project_id, loop_ctx, req, tool_calls, minted
                )
                yield ("tool_result", {"tool": req["tool"], "status": status})
                if isinstance(text, ParamRefusal) and refusals_used < agents_tool_rounds.MAX_REFUSED_ROUNDS:
                    refusals_used += 1  # dev/105 D2: a free correction, not a round
                else:
                    rounds_used += 1
                final = rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS
                result_msg = agents_tool_rounds._tool_result_message(req["tool"], status, text, final=final)
                if native_calls:
                    conversation.add_call_round(
                        result["turn"], req, status, text,
                        final=final, fenced_feedback=result_msg,
                    )
                else:
                    conversation.add_text_round(result["reply"], result_msg)
        except Exception as exc:  # provider failure mid-stream
            agents_policy._add_usage(usage_total, usage_sink)
            settled = ledger.settle(
                user_key, reservation, usage=usage_total or None, status="error"
            )
            agents_prepare._persist_exchange(
                user_key,
                project_id,
                session_id,
                attachment_id,
                message,
                f"(error) {provider_config.redact_error(exc, config)}",
                error=True,
                execution=agents_policy._execution_record(
                    execution_id, pins, usage_total, started, "error", tool_calls,
                     delegations=delegations,
                ),
            )
            yield ("error", f"agent run failed: {provider_config.redact_error(exc, config)}")
            return
        reply_text = "\n\n".join(folded)
        run_parts = minted + final_parts  # proposals ride the turn (dev/41)
        settled = ledger.settle(
            user_key, reservation, usage=usage_total or None, status="ok"
        )
        execution = agents_policy._execution_record(
            execution_id, pins, usage_total, started, "ok", tool_calls,
                     delegations=delegations,
            refused_rounds=refusals_used,
        )
        agents_prepare._persist_exchange(
            user_key,
            project_id,
            session_id,
            attachment_id,
            message,
            reply_text,
            execution=execution,
            parts=run_parts,
        )
        # Title before the done frame: the reply text already streamed via
        # deltas, and the client's post-send refresh must see the title.
        if wants_title:
            agents_titles._generate_conversation_title(user_key, project_id, attachment_id, message, config)
        # A pending mutation pauses at review (dev/03:344 review_required).
        for part in minted:
            if part.get("type") != "proposal":
                continue  # dev/72: delegation entries ride the content event
            yield (
                "review_required",
                {
                    "proposalId": part["proposalId"],
                    "tool": part["tool"],
                    "summary": part["summary"],
                },
            )
        # dev/73: reviews homed at the node's agent pause visibly too — the
        # client refreshes and the parent's delegation entry links there.
        for part, review_home in homed_reviews:
            yield (
                "review_required",
                {
                    "proposalId": part["proposalId"],
                    "tool": part["tool"],
                    "summary": part["summary"],
                    "attachmentId": review_home,
                },
            )
        if run_parts:
            yield ("content", {"parts": run_parts})
        yield (
            "done",
            {
                "reply": reply_text,
                "executionId": execution_id,
                "usage": execution["usage"],
                # dev/80: the run's wall-clock duration — matches the
                # persisted execution record.
                "durationMs": execution["durationMs"],
                "content": run_parts,
            },
        )

    return _events()
