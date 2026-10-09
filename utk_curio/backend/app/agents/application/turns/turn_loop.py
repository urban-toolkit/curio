"""One chat turn on an attachment, as an object (memo dev/142, B3; re-derived on enh/agent-catalog).

``run_attachment`` and ``stream_attachment`` (memo dev/22) used to be two
copies of the same bounded tool loop (memos dev/41/48) — one blocking, one
streaming with dev/39's tail withholding — that drifted by a branch here and
an event there. :class:`AttachmentTurn` is that loop once: the streaming
entry point yields its events, the blocking one drains the same generator
and yields nothing, because every event is emitted through :meth:`_emit`,
which is silent unless ``streaming`` is set. The only genuinely different
stage, the provider round, is two methods (:meth:`_blocking_round`,
:meth:`_streaming_round`) with one result shape.

Nothing about WHAT a turn does changed: admission before dispatch (dev/40),
the native-tools fallback to the fenced protocol, the round cap and free
parameter refusals (dev/105 D2), the plan and tool correction rounds
(dev/54, #245), delegate rounds with their runtime-minted
reviews/drafts/candidates/notes (dev/73/90/95/114), settlement and the
persisted exchange, the title, review_required/content/done.
"""

from __future__ import annotations

import time
import uuid

from utk_curio.backend.app.agents.application.tool_rounds import ParamRefusal
from utk_curio.backend.app.agents.application.tool_rounds import _RunConversation
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.infrastructure import provider_config
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn
from utk_curio.backend.app.agents.infrastructure.providers import NativeToolsRefused
from utk_curio.backend.app.agents.infrastructure.providers import ToolCall
from utk_curio.backend.app.agents.repositories import ledger
from utk_curio.backend.app.agents.application import tool_rounds as agents_tool_rounds
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import policy as agents_policy
from utk_curio.backend.app.agents.application.turns import prepare as agents_prepare
from utk_curio.backend.app.agents.application.turns import titles as agents_titles
from utk_curio.backend.app.agents.infrastructure import providers as agents_providers

CONTINUE = "continue"
BREAK = "break"


class AttachmentTurn:
    """One turn: prepared and admitted on construction, run by :meth:`rounds`."""

    def __init__(self, user_key: str, project_id: str, attachment_id: str, message: str,
                 config, run_context, *, streaming: bool):
        self.user_key = user_key
        self.project_id = project_id
        self.attachment_id = attachment_id
        self.message = message
        self.config = config
        self.streaming = streaming
        (self.coord, self.session_id, messages, self.run_policy, self.wants_title,
         self.pins, self.loop_ctx) = agents_prepare._prepare_run(
            user_key, project_id, attachment_id, message, config, run_context
        )
        # dev/114: the current user text — turns persist AFTER the run, so the
        # grounding gate cannot read it from the session; a path the user typed
        # is the one human-trusted source of a local path.
        self.loop_ctx["message"] = message
        self.execution_id = uuid.uuid4().hex
        # Atomic admission (dev/40): after validation (an invalid request never
        # consumes quota), before provider dispatch (a denied run never reaches a
        # provider). The reservation IS this execution (one id), and the price
        # snapshot pinned here is what settlement charges. For a stream, a
        # quota/budget denial surfaces as a plain 429 before any streaming
        # begins, and consumes/persists nothing.
        self.reservation = ledger.reserve(
            user_key,
            reservation_id=self.execution_id,
            llm_config_id=config.config_id,
            **self.run_policy["admit"],
        )
        self.usage_total: dict = {}
        self.usage_sink: dict = {}
        self.tool_calls: list = []
        self.delegations: list = []
        self.minted: list = []
        # dev/73: reviews minted at a FOREIGN home (the node's agent) — they
        # never ride the parent turn's parts, but still pause at review.
        self.homed_reviews: list = []
        self.folded: list[str] = []
        self.final_parts: list = []
        self.conversation = _RunConversation(messages, self.loop_ctx)
        self.rounds_used = 0
        self.refusals_used = 0  # dev/105 D2: free parameter corrections taken
        self.started = time.monotonic()

    def _emit(self, name: str, payload):
        if self.streaming:
            yield (name, payload)

    # ── the loop ────────────────────────────────────────────────────────────

    def rounds(self):
        """The bounded tool loop (memos dev/41/48): parse → execute granted
        read tool / mint proposal / run depth-1 delegate → re-prompt, at most
        MAX_TOOL_ROUNDS request executions per run (one shared budget). Each
        streamed round streams its own deltas; a toolRequest tail becomes tool
        events and a delegateRequest tail becomes delegate events, never text."""
        while True:
            self.usage_sink = {}
            try:
                result = yield from self._provider_round()
            except NativeToolsRefused as refusal:
                # The endpoint takes no native tools after all: the same round
                # again, on the fenced protocol.
                self.conversation.fall_back(refusal, self.pins)
                continue
            if self.usage_sink:
                # dev/80: interim Actual sums, once per provider round — the
                # client's live token counter ticks during long tool loops.
                # Additive; old clients skip unknown events.
                yield from self._emit("usage", {"usage": dict(self.usage_total)})
            parts = result["parts"]
            req = parts[0] if parts and parts[0].get("type") in ("toolRequest", "delegateRequest") else None
            native_calls = self.conversation.native_calls(result["turn"])
            if native_calls:
                # A native call is the round's request, whatever the text says.
                token = yield from self._native_call_request(native_calls, result)
                if token == CONTINUE:
                    continue
                if token == BREAK:
                    break
                req = token
            if req is None:
                outcome = yield from self._reply_without_request(result)
                if outcome == CONTINUE:
                    continue
                if outcome == BREAK:
                    break
                req = outcome  # a RECOVERED request (#245) takes the shared path below
            if result["visible"]:
                self.folded.append(result["visible"])
            if self.rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS:
                # dev/73: a mutate request cut off at the cap is a visible
                # outcome — never a silent drop under confident prose.
                if req["type"] == "toolRequest" and req.get("tool") in agents_tool_rounds.MUTATE_PROPOSAL_TOOLS:
                    self.minted.append(agents_tool_rounds._round_cap_cutoff_card(req["tool"]))
                break  # dangling read request at the cap: dropped, text kept
            if req["type"] == "delegateRequest":
                yield from self._delegate_round(req, result, native_calls)
                continue
            yield from self._tool_round(req, result, native_calls)

    def _native_call_request(self, native_calls: list, result: dict):
        """The round's request is its first native call. Returns the parsed
        request, CONTINUE for an unreadable call re-prompted under the cap, or
        BREAK past the cap (the text stays; a proposal that could not be made
        says why)."""
        req, call_errors = agents_tool_rounds._native_request(native_calls[0])
        if req is not None:
            return req
        if self.rounds_used < agents_tool_rounds.MAX_TOOL_ROUNDS:
            self.rounds_used += 1
            yield from self._emit("tool_revision", {"attempt": self.rounds_used, "errors": len(call_errors)})
            self.conversation.add_unreadable_call_round(
                result["turn"], call_errors, final=self.rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS
            )
            return CONTINUE
        if result["visible"]:
            self.folded.append(result["visible"])
        if agents_tool_rounds._is_mutate_call(native_calls[0]):
            self.final_parts = [agents_tool_rounds._tool_cap_card(call_errors)]
        return BREAK

    def _reply_without_request(self, result: dict):
        """Plan handling (dev/52 mint; dev/54 correction rounds), then the
        toolRequest twin (#245). Returns CONTINUE for a correction round,
        BREAK when the reply is final, or the recovered request."""
        kind, payload, visible_override = agents_tool_rounds._handle_plan_reply(
            self.user_key, self.project_id, self.loop_ctx, result["reply"], result["parts"],
            self.minted, self.rounds_used,
        )
        req = None
        if kind == "correct":
            # Corrective prose is not folded: the invalid attempt never
            # reaches the user; the final round's text is the truth.
            self.rounds_used += 1
            yield from self._emit("plan_revision", {"attempt": self.rounds_used, "errors": len(payload)})
            self.conversation.add_text_round(
                result["reply"], agents_tool_rounds._plan_correction_message(payload),
                agents_tool_rounds._plan_correction_message(payload, native=True),
            )
            return CONTINUE
        if kind == "none":
            # #245: only once the plan handler has declined — a toolRequest the
            # parser could not take (wrong fence, trailing prose, correctable
            # params) must never fold into the chat as raw JSON.
            kind, payload, visible_override, req = agents_tool_rounds._handle_tool_reply(
                self.loop_ctx, result["reply"], result["parts"], self.rounds_used
            )
            if kind == "correct":
                self.rounds_used += 1
                yield from self._emit("tool_revision", {"attempt": self.rounds_used, "errors": len(payload)})
                self.conversation.add_text_round(
                    result["reply"], agents_tool_rounds._tool_correction_message(payload),
                    agents_tool_rounds._tool_correction_message(payload, native=True),
                )
                return CONTINUE
            # A held request tail is NOT released at the cap: see
            # _handle_tool_reply — a source file is not a spec.
        if kind == "cap" and result.get("heldPlanTail"):
            # Fail-open transparency at the cap: the held tail is the model's
            # text — released, then explained by the error card in `payload`.
            yield from self._emit("delta", result["heldPlanTail"])
        if req is not None:
            # A RECOVERED request: fall through to the shared request path
            # with the block stripped from the text, so grant re-check, mint,
            # cap card and the dev/105 D2 free-refusal accounting all apply.
            if visible_override is not None:
                result["visible"] = visible_override
            return req
        effective_visible = visible_override if visible_override is not None else result["visible"]
        if effective_visible:
            self.folded.append(effective_visible)
        self.final_parts = payload
        return BREAK

    def _re_prompt(self, result: dict, native_calls: list, req: dict, status: str, text,
                   *, final: bool, result_msg: dict) -> None:
        if native_calls:
            self.conversation.add_call_round(
                result["turn"], req, status, text, final=final, fenced_feedback=result_msg
            )
        else:
            self.conversation.add_text_round(result["reply"], result_msg)

    # ── provider rounds ─────────────────────────────────────────────────────

    def _answered(self) -> None:
        self.conversation.answered(self.config, self.user_key)
        agents_policy._add_usage(self.usage_total, self.usage_sink)

    def _provider_round(self):
        if self.streaming:
            result = yield from self._streaming_round()
            self._answered()
            return result
        return self._blocking_round()

    def _blocking_round(self) -> dict:
        turn = ChatTurn.of(agents_providers.run_chat_turn(
            self.config,
            self.conversation.messages,
            max_output_tokens=self.run_policy["max_output_tokens"],
            usage_out=self.usage_sink,
            **self.conversation.offer(self.rounds_used),
        ))
        self._answered()
        reply = turn.text
        visible, parts = content.extract_content(reply)
        agents_grounding._verify_candidate_parts(parts, self.loop_ctx)  # dev/67-4: no unverified laundering
        return {"reply": reply, "visible": visible, "parts": parts, "turn": turn}

    @staticmethod
    def _hold_split(buf: str) -> tuple[str, str]:
        """Emit-now / keep split: retain the longest trailing suffix of *buf*
        that could still be the start of the tail-fence marker (≤ ~16 chars
        held back at any moment — imperceptible in the live transcript)."""
        marker = content.TAIL_FENCE
        for k in range(min(len(marker) - 1, len(buf)), 0, -1):
            if marker.startswith(buf[-k:]):
                return buf[:-k], buf[-k:]
        return buf, ""

    def _streaming_round(self):
        """Stream one provider round: yields ("delta", text) with the dev/39
        tail withholding, then returns {reply, visible, parts, turn}.
        ``heldPlanTail`` (dev/54): an INVALID tail that looks like a plan
        attempt is held instead of flushed — the correction round must not
        leak raw plan JSON to the user; the caller releases it at the round
        cap (fail-open transparency). ``heldToolTail`` (#245): the same for a
        mutate toolRequest tail — and, unlike the plan tail, never released:
        the params are a whole source file, and streaming them as chat prose
        IS the bug (see ``_handle_tool_reply``)."""
        marker = content.TAIL_FENCE
        granted = self.loop_ctx.get("granted", [])
        hold_plan_tail = "dataflow.plan.write" in granted
        hold_request_tail = bool(set(granted or []) & agents_tool_rounds.MUTATE_PROPOSAL_TOOLS)
        chunks: list[str] = []
        calls: list = []
        buf = ""  # pass-mode text not yet emitted
        withheld: str | None = None  # not None → holding a candidate tail
        for delta in agents_providers.stream_chat_turn(
            self.config,
            self.conversation.messages,
            max_output_tokens=self.run_policy["max_output_tokens"],
            usage_out=self.usage_sink,
            **self.conversation.offer(self.rounds_used),
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
                emit, buf = self._hold_split(buf)
                if emit:
                    yield ("delta", emit)
        reply = "".join(chunks)
        visible, parts = content.extract_content(reply)
        agents_grounding._verify_candidate_parts(parts, self.loop_ctx)  # dev/67-4: no unverified laundering
        result = {"reply": reply, "visible": visible, "parts": parts,
                  "turn": ChatTurn(text=reply, tool_calls=tuple(calls))}
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
        return result

    # ── delegate and tool rounds ────────────────────────────────────────────

    def _delegate_round(self, req: dict, result: dict, native_calls: list):
        self.rounds_used += 1
        final = self.rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS
        yield from self._emit("delegate_requested", {"capability": req["capability"]})
        status, text, resolution = agents_delegates._resolve_delegate_request(
            self.user_key, self.project_id, self.loop_ctx, req, self.minted
        )
        if resolution is not None:
            yield from self._emit("delegate_started", {"capability": req["capability"], "coord": resolution.coord})
            status, text, child, home_att, delegate_summary = self._run_delegate(req, resolution)
            # dev/72: the parent keeps the compact, linkable entry.
            self.minted.append(agents_delegates._delegation_part_for(
                resolution, req["capability"], status, delegate_summary, home_att,
                child=child,
            ))
            yield from self._emit("delegate_result", {
                "capability": req["capability"],
                "coord": resolution.coord,
                # dev/72: the live line can link too.
                "attachmentId": home_att,
                "name": getattr(resolution.manifest, "name", None) if resolution.manifest else None,
                "status": status,
                "durationMs": child.get("durationMs"),
                # What the child ran on, which may not be the parent's.
                "model": (child.get("pins") or {}).get("model"),
                "llmLabel": ((child.get("pins") or {}).get("llm") or {}).get("label"),
            })
            result_msg = agents_tool_rounds._delegate_result_message(
                resolution.coord, req["capability"], status, text, final=final
            )
        else:
            yield from self._emit("delegate_result", {"capability": req["capability"], "status": status})
            result_msg = agents_tool_rounds._delegate_result_message(
                None, req["capability"], status, text, final=final
            )
        self._re_prompt(result, native_calls, req, status, text, final=final, result_msg=result_msg)

    def _run_delegate(self, req: dict, resolution):
        """Run the resolved delegate and mint what its success PROVES exists
        (dev/73 review, dev/90 draft, dev/114 candidates, dev/95 notes) —
        runtime-minted, never the model's second step. Returns
        (status, text, child, home_att, summary)."""
        loop_ctx = self.loop_ctx
        inputs = req.get("inputs") or {}
        # dev/73: node-scoped content generation homes its trace AND its
        # minted review at the node's own agent.
        gen_node_id = (
            agents_delegates._delegate_target_node_id(loop_ctx, inputs)
            if req["capability"] == "node.content.generate"
            else None
        )
        status, text, child, home_att = agents_delegates._run_delegate_traced(
            self.user_key,
            self.project_id,
            resolution.coord,
            req["capability"],
            agents_delegates._enriched_delegate_inputs(
                self.user_key, self.project_id, loop_ctx, req["capability"], inputs,
            ),
            self.config,
            parent_execution_id=self.execution_id,
            parent_coord=loop_ctx["coord"],
            attachment_id=loop_ctx.get("attachment_id"),
            parent_name=getattr(loop_ctx.get("manifest"), "name", None),
            node_id=gen_node_id,
        )
        self.delegations.append(child)
        delegate_summary = text
        if status == "ok" and gen_node_id:
            # dev/73: generation success ⇒ the review EXISTS — runtime-minted,
            # never the model's second step.
            review_part, review_home, text = agents_delegates._mint_content_review_from_delegate(
                self.user_key, self.project_id,
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
                    self.minted.append(review_part)
                else:
                    self.homed_reviews.append((review_part, review_home))
        elif status == "ok" and req["capability"] in agents_delegates.PACKAGE_AUTHORING_CAPABILITIES:
            # dev/90: authoring success ⇒ the reviewed draft EXISTS —
            # runtime-minted from the child's payload, never the model's
            # second step.
            draft_part, text, draft_outcome = agents_delegates._mint_package_draft_from_delegate(
                self.user_key, self.project_id, loop_ctx, text,
                delegate_inputs=inputs,
                redelegate=agents_delegates._draft_corrector(
                    self.user_key, self.project_id, loop_ctx, req, resolution,
                    self.config, self.execution_id, self.delegations,
                ),
            )
            delegate_summary = text
            if draft_part is not None:
                self.minted.append(draft_part)
                delegate_summary = "reviewed package draft proposed — awaits Apply"
            # dev/93 D5: the delegation card reports the OUTCOME, not merely
            # that the child ran — "ok" beside "returned no parseable draft"
            # is how the parent learned nothing.
            status = draft_outcome
        elif status == "ok" and req["capability"] == "dataset.discover":
            # dev/114: discovery success ⇒ the two-lane candidates part EXISTS
            # on this turn — runtime-minted (catalog rows tool-grounded,
            # external rows probed), never the model's claim.
            cand_part, text, cand_outcome = agents_delegates._mint_candidates_from_delegate(
                loop_ctx, text,
                (inputs.get("catalog") or {}).get("rows")
                or agents_delegates._dataset_discover_inputs(self.user_key, self.project_id, {})["catalog"]["rows"],
            )
            delegate_summary = text
            if cand_part is not None:
                self.minted.append(cand_part)
                delegate_summary = "dataset candidates shown for review — select and confirm"
            status = cand_outcome
        elif status == "ok" and req["capability"] == "research.notes.compose":
            # dev/95 (Follow-up D): notes success ⇒ the reviewed A16 sequence
            # EXISTS — runtime-minted from the child's schema reply, never the
            # model's second step.
            note_parts, text, notes_outcome = agents_delegates._mint_notes_from_delegate(
                self.user_key, self.project_id, loop_ctx, text,
            )
            delegate_summary = text
            if note_parts:
                self.minted.extend(note_parts)
                delegate_summary = (
                    f"{len(note_parts)} reviewed note proposal(s) "
                    "— await Apply"
                )
            status = notes_outcome
        return status, text, child, home_att, delegate_summary

    def _tool_round(self, req: dict, result: dict, native_calls: list):
        yield from self._emit("tool_requested", {"tool": req["tool"]})
        yield from self._emit("tool_started", {"tool": req["tool"]})
        status, text = agents_tool_rounds._execute_tool_request(
            self.user_key, self.project_id, self.loop_ctx, req, self.tool_calls, self.minted
        )
        # A call that did not succeed says why, as its saved record does (#447).
        reason = agents_tool_rounds._failure_reason(status, text)
        yield from self._emit(
            "tool_result",
            {"tool": req["tool"], "status": status, **({"reason": reason} if reason is not None else {})},
        )
        if isinstance(text, ParamRefusal) and self.refusals_used < agents_tool_rounds.MAX_REFUSED_ROUNDS:
            self.refusals_used += 1  # dev/105 D2: a free correction, not a round
        else:
            self.rounds_used += 1
        final = self.rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS
        result_msg = agents_tool_rounds._tool_result_message(req["tool"], status, text, final=final)
        self._re_prompt(result, native_calls, req, status, text, final=final, result_msg=result_msg)

    # ── settlement ──────────────────────────────────────────────────────────

    def redacted(self, exc: BaseException) -> str:
        return provider_config.redact_error(exc, self.config)

    def settle_error(self, exc: BaseException) -> None:
        """An error settles too: the hold releases and the truth is recorded."""
        agents_policy._add_usage(self.usage_total, self.usage_sink)
        ledger.settle(self.user_key, self.reservation, usage=self.usage_total or None, status="error")
        agents_prepare._persist_exchange(
            self.user_key,
            self.project_id,
            self.session_id,
            self.attachment_id,
            self.message,
            f"(error) {self.redacted(exc)}",
            error=True,
            execution=agents_policy._execution_record(
                self.execution_id, self.pins, self.usage_total, self.started, "error", self.tool_calls,
                delegations=self.delegations,
            ),
        )

    def settle_ok(self) -> dict:
        """Settle the reservation, persist both turns, title the conversation
        when this is its first exchange; returns the run's result payload."""
        reply_text = "\n\n".join(self.folded)
        run_parts = self.minted + self.final_parts  # proposals ride the turn (dev/41)
        ledger.settle(self.user_key, self.reservation, usage=self.usage_total or None, status="ok")
        execution = agents_policy._execution_record(
            self.execution_id, self.pins, self.usage_total, self.started, "ok", self.tool_calls,
            delegations=self.delegations,
            refused_rounds=self.refusals_used,
        )
        agents_prepare._persist_exchange(
            self.user_key,
            self.project_id,
            self.session_id,
            self.attachment_id,
            self.message,
            reply_text,
            execution=execution,
            parts=run_parts,
        )
        # Title before the done frame: the reply text already streamed via
        # deltas, and the client's post-send refresh must see the title.
        if self.wants_title:
            agents_titles._generate_conversation_title(
                self.user_key, self.project_id, self.attachment_id, self.message, self.config
            )
        return {
            "attachmentId": self.attachment_id,
            "coord": self.coord,
            "reply": reply_text,
            "executionId": self.execution_id,
            "usage": execution["usage"],
            # dev/80: the run's wall-clock duration — matches the persisted record.
            "durationMs": execution["durationMs"],
            "content": run_parts,
        }

    # ── the streaming envelope ──────────────────────────────────────────────

    def stream(self):
        """The SSE stream: the dev/37 execution handshake, the loop's events,
        then review_required / content / done — or error."""
        # The typed-envelope handshake (memo dev/37): the execution identity
        # arrives before the first delta so a client can correlate the stream
        # with the record that will land on the transcript.
        yield ("execution", {"executionId": self.execution_id})
        try:
            yield from self.rounds()
        except Exception as exc:  # provider failure mid-stream
            self.settle_error(exc)
            yield ("error", f"agent run failed: {self.redacted(exc)}")
            return
        payload = self.settle_ok()
        # A pending mutation pauses at review (dev/03:344 review_required).
        for part in self.minted:
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
        for part, review_home in self.homed_reviews:
            yield (
                "review_required",
                {
                    "proposalId": part["proposalId"],
                    "tool": part["tool"],
                    "summary": part["summary"],
                    "attachmentId": review_home,
                },
            )
        if payload["content"]:
            yield ("content", {"parts": payload["content"]})
        yield (
            "done",
            {
                "reply": payload["reply"],
                "executionId": payload["executionId"],
                "usage": payload["usage"],
                # dev/80: the run's wall-clock duration — matches the
                # persisted execution record.
                "durationMs": payload["durationMs"],
                "content": payload["content"],
            },
        )
