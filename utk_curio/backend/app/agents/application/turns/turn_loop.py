"""One chat turn on an attachment, as an object (memo dev/142, B3; re-derived on enh/agent-catalog).

``run_attachment`` and ``stream_attachment`` (memo dev/22) used to be two
copies of the same bounded tool loop (memos dev/41/48) — one blocking, one
streaming with dev/39's tail withholding — that drifted by a branch here and
an event there. :class:`AttachmentTurn` is that loop once. Every turn runs as
a job (``turn_jobs.py``) whose events reach the dataflow's room, so it always
yields them (:meth:`_emit`). Its provider round is two methods with one result
shape: a streamed one (:meth:`_streaming_round`), whose deltas are the reply as
it is written, and a blocking one (:meth:`_blocking_round`) for an ask whose
answer waits for the whole turn, whose reply arrives with its ``done``.

What a turn does: admission before dispatch (dev/40), the native-tools
fallback to the fenced protocol, the round cap and free parameter refusals
(dev/105 D2), the plan and tool correction rounds (dev/54, #245), delegate
rounds with what the runtime makes of their success: code written, drafts,
candidates, notes (dev/73/90/95/114), each change that lands as a ``change``
event, settlement and the persisted exchange, the title, and
review_required/content/done.

The rounds are the agent's work in the dataflow's room (:meth:`at_work`): it
joins as they begin, with who asked and the skills its run holds, and leaves
as they end, before the reply's settlement and its last events.

A turn may be stopped (:class:`Stop`): it stops at its next step, between two
pieces of the reply or before its next round, never in the middle of a tool's
or a delegate's landing. What it said and landed until then stays, as a reply
stopped by whoever stopped it.

A round whose model stopped at the output cap (``ChatTurn.cut_at_output_cap``)
ends the turn the same way: what the model wrote stays, all but a block it
began and did not close, and nothing that round asked for runs, since a call's
arguments and a request's block are cut too. The reply then ends with a line
that says it was cut at the cap (``turn.cut-at-output-limit``), or that the
model spent the cap thinking, when its server streamed thinking and no reply
came (``turn.cut-while-thinking``), and its record says ``cutAtOutputLimit``.
Each round offers the run policy's room for thinking (``thinking_tokens``),
which a model seen thinking gets on top of the cap (``providers``), so the
line names the cap the round's request carried (``ChatTurn.output_limit``).
A round whose server refused that room was asked without it, and the record
says ``thinkingRoomRefused``.

A model may write a call as text in its own call syntax (OpenAI's harmony
format, whose ``<|start|>``, ``<|message|>`` and ``<|call|>`` no answer holds),
and its server then sends that text as the reply: muse-glimmer does when its
last round offers it no call (``tool_choice`` none). Such a call is no text of
the turn's. Both rounds leave it out from its header to the reply's end
(:func:`_without_call_markup`), a stream shows no piece of it
(:func:`_stream_without_call_markup`), and nothing runs it. When the last
round offered the tools with no call (``tool_choice`` none), that round's call
is asked once more, once a turn, with no tools at all, and its reply answers
after the text before the call (:meth:`AttachmentTurn._asks_again`). Otherwise
at the cap, and when that reply writes a call as text too, the call is dropped
as a request the cap leaves is (:meth:`AttachmentTurn._dropped_at_the_cap`);
below the cap it is corrected as a request block the parser could not take is.
"""

from __future__ import annotations

import dataclasses
import re
import threading
import time
import uuid
from contextlib import ExitStack

from utk_curio.backend.app.agents.application.tool_rounds import ParamRefusal
from utk_curio.backend.app.agents.application.tool_rounds import _RunConversation
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import tool_names
from utk_curio.backend.app.agents.infrastructure import provider_config
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn
from utk_curio.backend.app.agents.infrastructure.providers import NativeToolsRefused
from utk_curio.backend.app.agents.infrastructure.providers import ToolCall
from utk_curio.backend.app.agents.repositories import ledger
from utk_curio.backend.app.agents.application import dataflow_block as agents_dataflow_block
from utk_curio.backend.app.agents.application import dataset_resolution as agents_dataset_resolution
from utk_curio.backend.app.agents.application import in_the_room as agents_room
from utk_curio.backend.app.agents.application import skill_runs as agents_skill_runs
from utk_curio.backend.app.agents.application import tool_rounds as agents_tool_rounds
from utk_curio.backend.app.agents.application.proposals import changes as agents_changes
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import policy as agents_policy
from utk_curio.backend.app.agents.application.turns import prepare as agents_prepare
from utk_curio.backend.app.agents.application.turns import titles as agents_titles
from utk_curio.backend.app.agents.infrastructure import providers as agents_providers

CONTINUE = "continue"
BREAK = "break"

#: The pin of a turn whose last round's call was asked once more with no tools
#: (:meth:`AttachmentTurn._asks_again`): ``answered``, or ``failed: <status>``
#: when that call raised, its HTTP status or else its error's class.
ASKED_AGAIN = "askedAgainWithoutTools"


def _before_an_open_block(text: str) -> str:
    """*text* without a ```curio.v1 block it begins and never closes, which a
    reply the output cap cut can end inside: such a block is half written, a
    request or a card that cannot be read, so it is no text to show. A block
    begins on a line of its own, as ``content.split_tail`` reads one."""
    at = text.rfind("\n" + content.TAIL_FENCE)
    at = at + 1 if at != -1 else (0 if text.startswith(content.TAIL_FENCE) else -1)
    if at == -1 or "\n```" in text[at + len(content.TAIL_FENCE):]:
        return text
    return text[:at].rstrip()


#: The tokens of a model's own call syntax, OpenAI's harmony format, which no
#: answer holds. muse-glimmer's call written as text at the round cap holds
#: them, 118 of its 486 replies in the 11-24 skill evaluation:
#: ``<|start|>assistant to=node__read<|message|><atem:function_calls>...``, or
#: the same from ``to=`` on.
_CALL_TOKENS = ("<|start|>", "<|message|>", "<|call|>")
#: A call's header right before its ``<|message|>``: whom it is to, its native
#: name, after the role or alone.
_CALL_HEADER = r"(?:assistant[ \t]{1,8})?to=[\w.\-]{1,64}[ \t]{0,8}"
_CALL_HEADER_BEFORE_MESSAGE = re.compile(r"(?<!\w)" + _CALL_HEADER + r"\Z")
#: The native name a call's header gives.
_CALL_TO = re.compile(r"(?<!\w)to=([\w.\-]{1,64})")


def _prefixes(word: str) -> str:
    """A pattern of every prefix of *word* from its first character on."""
    pattern = ""
    for char in reversed(word):
        pattern = re.escape(char) + (f"(?:{pattern})?" if pattern else "")
    return pattern


#: The end of a text that may still become the start of a call's markup: a
#: token begun, or a header that may yet reach its ``<|message|>``.
_MAY_BEGIN_A_CALL = re.compile(
    "(?:" + "|".join(_prefixes(token) for token in _CALL_TOKENS) + r")\Z"
    + r"|(?<!\w)(?:" + "|".join((
        _prefixes("assistant"),
        r"assistant[ \t]{1,8}",
        r"(?:assistant[ \t]{1,8})?" + _prefixes("to="),
        _CALL_HEADER + "(?:" + _prefixes("<|message|>") + ")?",
    )) + r")\Z"
)
#: The longest text that may still become the start of a call's markup.
_CALL_START_MAX = len("assistant") + 8 + len("to=") + 64 + 8 + len("<|message|>")


def _call_markup_at(text: str, start: int = 0) -> int | None:
    """Where a call *text* writes in a model's own call syntax begins, at
    *start* or after: at its first token, or at the header right before it
    when that token is its ``<|message|>``. None when *text* holds no token."""
    found = [at for at in (text.find(token, start) for token in _CALL_TOKENS) if at != -1]
    if not found:
        return None
    at = min(found)
    if text.startswith("<|message|>", at):
        header = _CALL_HEADER_BEFORE_MESSAGE.search(text, max(start, at - _CALL_START_MAX), at)
        if header is not None:
            return header.start()
    return at


def _without_call_markup(text: str) -> tuple[str, str | None]:
    """*text* before a call it writes in a model's own call syntax, and the
    call, from its start to the end of *text*: the call's markup. *text* and
    None when it writes none."""
    at = _call_markup_at(text)
    if at is None:
        return text, None
    return text[:at].rstrip(), text[at:]


def _called_tool(markup: str) -> str | None:
    """The tool id the header of the call *markup* names, its native name's
    ``__`` read as ``.`` (``tool_names.tool_id_of``), or None."""
    end = markup.find("<|message|>")
    named = _CALL_TO.search(markup, 0, end if end != -1 else len(markup))
    return tool_names.tool_id_of(named.group(1)) if named is not None else None


def _stream_without_call_markup(events, markup: list):
    """*events*, a streamed round's, with a call the model writes in its own
    call syntax left out: from the call's start (:func:`_call_markup_at`), its
    text goes to *markup*, never released, and only the text before it passes
    on. Text that may still begin a call is held back until it cannot, or the
    round ends; every other event passes as it comes."""
    pending = ""  # the text received and not passed on yet
    last = ""  # the last character passed on: a header may not begin after a word's
    for event in events:
        if not isinstance(event, str):
            yield event
            continue
        if markup:
            markup.append(event)
            continue
        pending += event
        text = last + pending
        at = _call_markup_at(text, len(last))
        if at is not None:
            if at > len(last):
                yield pending[: at - len(last)]
            markup.append(pending[at - len(last):])
            continue
        held = _MAY_BEGIN_A_CALL.search(text, max(len(last), len(text) - _CALL_START_MAX))
        upto = (held.start() if held is not None else len(text)) - len(last)
        if upto > 0:
            yield pending[:upto]
            last, pending = pending[upto - 1], pending[upto:]
    if pending and not markup:
        yield pending


class Stop:
    """Someone's ask to stop a turn, which the turn takes at its next step;
    ``by`` names who asked, as a chat message names its writer."""

    def __init__(self):
        self._asked = threading.Event()
        self.by: dict | None = None

    def ask(self, by: dict | None) -> bool:
        """Ask the turn to stop, as *by*. False when it was asked already,
        whose stop stays the first one's."""
        if self._asked.is_set():
            return False
        self.by = by
        self._asked.set()
        return True

    def asked(self) -> bool:
        return self._asked.is_set()


class AttachmentTurn:
    """One turn: prepared and admitted on construction, run by :meth:`rounds`."""

    def __init__(self, user_key: str, project_id: str, attachment_id: str, message: str,
                 config, run_context, *, streaming: bool, stop: Stop | None = None):
        self.user_key = user_key
        self.project_id = project_id
        self.attachment_id = attachment_id
        self.message = message
        self.config = config
        self.streaming = streaming
        self.stop = stop
        # Whether the turn stopped when it was asked to (:class:`Stop`).
        self.stopped = False
        # Whether a round's model stopped at the output cap, which ended the turn.
        self.cut = False
        # Whether the server refused a round the room a model that thinks gets.
        self.room_refused = False
        # What the turn settled with (:meth:`settle_ok`), for an ask that waits for it.
        self.result: dict | None = None
        (self.coord, self.session_id, messages, self.run_policy, self.wants_title,
         self.pins, self.loop_ctx) = agents_prepare._prepare_run(
            user_key, project_id, attachment_id, message, config, run_context
        )
        # dev/114: the current user text — turns persist AFTER the run, so the
        # grounding gate cannot read it from the session; a path the user typed
        # is the one human-trusted source of a local path.
        self.loop_ctx["message"] = message
        # Who asked, as the agent's peer in the room names them, read here in
        # the request: the changes the turn lands wait for anyone else.
        self.loop_ctx["room_asker"] = agents_room.asker()
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
        # The changes that landed, which a blocking ask's answer carries.
        self.landed: list = []
        self.folded: list[str] = []
        self.final_parts: list = []
        self.conversation = _RunConversation(messages, self.loop_ctx)
        # The tools the turn's latest call offered (_RunConversation.offer).
        self.offered: dict = {}
        # The last round's reply that wrote a call as text, while its call is
        # asked once more with no tools (_asks_again).
        self.asking_again: dict | None = None
        self.rounds_used = 0
        # The last round corrected a plan, so the next call is the plan's next
        # try, which a run on native tools is offered at the cap too
        # (plan_corrected); this round is that try (plan_try); and what the
        # plan's last refusal said (plan_errors).
        self.plan_corrected = False
        self.plan_try = False
        self.plan_errors: list[str] = []
        self.refusals_used = 0  # dev/105 D2: free parameter corrections taken
        self.skill_reads = 0  # skill.read calls, free up to skill_runs.FREE_READS a turn
        self.started = time.monotonic()

    def _emit(self, name: str, payload):
        yield (name, payload)

    def _stopping(self) -> bool:
        """Whether someone asked the turn to stop."""
        return self.stop is not None and self.stop.asked()

    def at_work(self):
        """The turn's agent at work in the dataflow's room for its rounds
        (``in_the_room.at_work``): named after its manifest, asked by whoever
        sent the message, holding the skills its run holds. A skill it loads
        joins them (``tool_rounds``)."""
        return agents_room.at_work(
            self.user_key, self.project_id, self.attachment_id,
            coord=self.coord, manifest=self.loop_ctx.get("manifest"), who=self.loop_ctx["room_asker"],
            skills=agents_room.held_skills(self.loop_ctx.get("skills")),
        )

    # ── the loop ────────────────────────────────────────────────────────────

    def rounds(self):
        """The bounded tool loop (memos dev/41/48): parse → execute granted
        read tool / mint proposal / run depth-1 delegate → re-prompt, at most
        MAX_TOOL_ROUNDS request executions per run (one shared budget), and a
        plan's last try at the cap, as a plan block has one (dev/54). Each
        streamed round streams its own deltas; a toolRequest tail becomes tool
        events and a delegateRequest tail becomes delegate events, never text.
        A stop ends the loop before its next round, or in a round as the
        model writes: what the model showed stays, and nothing it asked for
        in that round runs. A round the output cap cut ends it too
        (:meth:`_cut`)."""
        while True:
            if self._stopping():
                self.stopped = True
                break
            self.usage_sink = {}
            try:
                result = yield from self._provider_round()
            except NativeToolsRefused as refusal:
                # The endpoint takes no native tools after all: the same round
                # again, on the fenced protocol.
                self.conversation.fall_back(refusal, self.pins)
                continue
            # Only a correction of a plan in this round opens the next call.
            self.plan_try, self.plan_corrected = self.plan_corrected, False
            if self.usage_sink:
                # dev/80: interim Actual sums, once per provider round — the
                # client's live token counter ticks during long tool loops.
                # Additive; old clients skip unknown events.
                yield from self._emit("usage", {"usage": dict(self.usage_total)})
            if result.get("turn") is not None and result["turn"].thinking_room_refused:
                self.room_refused = True
            if result.get("stopped") or self._stopping():
                # What the round showed stays; what it asked for does not run.
                self.stopped = True
                shown = result["shown"] if result.get("stopped") else result["visible"]
                if shown:
                    self.folded.append(shown)
                break
            if result["turn"].cut_at_output_cap:
                self._cut(result)
                break
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
                yield from self._emit_landed()
                if outcome == CONTINUE:
                    continue
                if outcome == BREAK:
                    break
                req = outcome  # a RECOVERED request (#245) takes the shared path below
            if result["visible"]:
                self.folded.append(result["visible"])
            if self.rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS:
                if agents_tool_rounds._is_plan_request(self.loop_ctx, req):
                    # The plan's last try, judged as a plan block is at the
                    # cap (dev/54): it lands, or its card says why it could
                    # not. No round follows it.
                    yield from self._tool_round(req, result, native_calls, last_try=True)
                    yield from self._emit_landed()
                    break
                self._dropped_at_the_cap(req.get("tool") if req["type"] == "toolRequest" else None)
                break  # dangling read request at the cap: dropped, text kept
            if req["type"] == "delegateRequest":
                yield from self._delegate_round(req, result, native_calls)
                yield from self._emit_landed()
                continue
            yield from self._tool_round(req, result, native_calls)
            yield from self._emit_landed()

    def _dropped_at_the_cap(self, tool: str | None) -> None:
        """A request the round at the cap asked for is dropped, not run, and
        its text stays: *tool* is the tool it asked for, None for a
        delegation. A mutate request cut off gets its card (:meth:`_cut_off`),
        a plan whose try the request took could not be made
        (:meth:`_plan_not_made`), and a reply left with no text says that the
        agent used its tool rounds before it could answer
        (``turn.tool-rounds-used``)."""
        self._cut_off(tool)
        self._plan_not_made()
        if not self.folded:
            self.folded.append(agent_text.message("turn.tool-rounds-used"))

    def _cut_off(self, tool: str | None) -> None:
        """A mutate request cut off at the cap is a visible outcome, never a
        silent drop under confident prose (dev/73): its card, once for each
        tool, though a last round's call asked again may write it again
        (:meth:`_asks_again`)."""
        if tool in agents_tool_rounds.MUTATE_PROPOSAL_TOOLS:
            card = agents_tool_rounds._round_cap_cutoff_card(tool)
            if card not in self.minted:
                self.minted.append(card)

    def _cut(self, result: dict) -> None:
        """End the turn on a round whose model stopped at the output cap: its
        text stays, all but a block it began and did not close, and nothing
        it asked for runs (a call's arguments and a request's block are cut
        too), as with a stopped round. The reply ends with a line that says
        so, which later turns read with the rest of the reply."""
        turn = result["turn"]
        kept = _before_an_open_block(result["visible"])
        if kept:
            self.folded.append(kept)
        # The cap the request carried: with the room a model that thinks gets.
        limit = f"{turn.output_limit or self.run_policy['max_output_tokens']:,}"
        if turn.thinking and not kept:
            self.folded.append(agent_text.message("turn.cut-while-thinking", limit=limit))
        else:
            self.folded.append(agent_text.message("turn.cut-at-output-limit", limit=limit))
        self.cut = True

    def _emit_landed(self):
        """Each change that landed since the last round, as a ``change``
        event: a tab no doc binds takes its canvas mutation, and every tab
        knows its chat holds a new change. A blocking ask's answer carries
        them too (``changes``)."""
        for landed in agents_changes.take_landed(self.loop_ctx):
            self.landed.append(landed)
            yield from self._emit("change", landed)

    def _native_call_request(self, native_calls: list, result: dict):
        """The round's request is its first native call. Returns the parsed
        request, CONTINUE for an unreadable call re-prompted under the cap, or
        BREAK past the cap (the text stays; a proposal that could not be made
        says why)."""
        req, call_errors = agents_tool_rounds._native_request(native_calls[0])
        if req is not None:
            return req
        # A plan's call is corrected as a broken plan block is (dev/54).
        plan = agents_tool_rounds._is_plan_call(self.loop_ctx, native_calls[0])
        if self.rounds_used < agents_tool_rounds.MAX_TOOL_ROUNDS:
            self.rounds_used += 1
            yield from self._emit("tool_revision", {"attempt": self.rounds_used, "errors": len(call_errors)})
            self.plan_corrected = plan
            if plan:
                self.plan_errors = list(call_errors)
            self.conversation.add_unreadable_call_round(
                result["turn"], call_errors,
                final=self.rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS and not plan,
            )
            return CONTINUE
        if result["visible"]:
            self.folded.append(result["visible"])
        if plan:
            self.final_parts = [agents_tool_rounds._plan_cap_card(call_errors)]
            return BREAK
        if agents_tool_rounds._is_mutate_call(native_calls[0]):
            self.final_parts = [agents_tool_rounds._tool_cap_card(call_errors)]
        self._plan_not_made()
        return BREAK

    def _reply_without_request(self, result: dict):
        """Plan handling (dev/52 mint; dev/54 correction rounds), then the
        toolRequest twin (#245), then a call the model wrote as text in its
        own call syntax (``callMarkup``), when neither found a request: below
        the cap a request the parser could not take, which a correction round
        asks for again; in a last round that offered no call, a call asked
        once more with no tools (:meth:`_asks_again`); and otherwise at the
        cap a request dropped (:meth:`_dropped_at_the_cap`), never run from
        its text. Returns CONTINUE for a correction round or a call asked
        again, BREAK when the reply is final, or the recovered request."""
        kind, payload, visible_override = agents_tool_rounds._handle_plan_reply(
            self.user_key, self.project_id, self.loop_ctx, result["reply"], result["parts"],
            self.minted, self.rounds_used,
        )
        req = None
        request_capped = False  # a request block still broken at the cap
        if kind == "correct":
            # Corrective prose is not folded: the invalid attempt never
            # reaches the user; the final round's text is the truth.
            self.rounds_used += 1
            self.plan_corrected, self.plan_errors = True, list(payload)
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
            if (kind == "none" and "callMarkup" in result
                    and self.rounds_used < agents_tool_rounds.MAX_TOOL_ROUNDS
                    and (self.loop_ctx.get("granted") or self.loop_ctx.get("delegable"))):
                kind, payload = "correct", [
                    agent_text.message("tool-round.call-as-text"), agent_text.message("tool-round.tool-fence"),
                ]
            if kind == "correct":
                self.rounds_used += 1
                yield from self._emit("tool_revision", {"attempt": self.rounds_used, "errors": len(payload)})
                self.conversation.add_text_round(
                    result["reply"], agents_tool_rounds._tool_correction_message(payload),
                    agents_tool_rounds._tool_correction_message(payload, native=True),
                )
                return CONTINUE
            if kind == "none" and "callMarkup" in result and self._asks_again(result):
                return CONTINUE
            request_capped = kind == "cap"
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
        if request_capped:
            self._plan_not_made()
        elif (kind == "none" and "callMarkup" in result
              and self.rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS):
            self._dropped_at_the_cap(_called_tool(result["callMarkup"]))
        return BREAK

    def _asks_again(self, result: dict) -> bool:
        """Whether the call of the round *result* answers is asked once more,
        with no tools at all, its reply having written a call as text where
        that round offered the tools with no call (``tool_choice`` none): once
        a turn, and never on a plan's last try or the fenced protocol, whose
        calls are offered otherwise. The conversation is left as it was, so
        that call's messages are the round's own, and the reply that answers
        it is the turn's answer, after the text before the call, which stays
        the turn's. The call written as text is still never run, and a
        change's gets its card (:meth:`_cut_off`). The reply is kept
        (``asking_again``) for the turn to end on, as it did before that call
        was asked, should it fail (:meth:`_provider_round`)."""
        if self.offered.get("tool_choice") != "none" or ASKED_AGAIN in self.pins:
            return False
        if result["visible"]:
            self.folded.append(result["visible"])
        self._cut_off(_called_tool(result["callMarkup"]))
        self.asking_again = result
        return True

    def _plan_not_made(self) -> None:
        """At the cap, the try a plan's correction asked for went to another
        request, which the cap drops or cuts off: the plan could not be made,
        and its card says why, as it does for a plan refused at the cap."""
        if self.plan_try:
            self.final_parts = [*self.final_parts, agents_tool_rounds._plan_cap_card(self.plan_errors)]

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
        """One call of the model, offered the tools the conversation gives it
        (:attr:`offered`). The call asked once more after a last round whose
        reply wrote a call as text (:meth:`_asks_again`) is offered none, and
        the turn's record says how it went (:data:`ASKED_AGAIN`). Should it
        fail, the round's result is that reply again, its text the turn's
        already, which the turn ends on as it did before that call was asked
        (:meth:`_dropped_at_the_cap`)."""
        again, self.asking_again = self.asking_again, None
        self.offered = self.conversation.offer(self.rounds_used, self.plan_corrected, asked_again=again is not None)
        try:
            if self.streaming:
                result = yield from self._streaming_round()
                self._answered()
            else:
                result = self._blocking_round()
        except Exception as exc:
            if again is None:
                raise
            agents_policy._add_usage(self.usage_total, self.usage_sink)
            self.pins[ASKED_AGAIN] = f"failed: {agents_providers._status_code_of(exc) or type(exc).__name__}"
            return {**again, "visible": ""}
        if again is not None:
            self.pins[ASKED_AGAIN] = "answered"
        return result

    def _blocking_round(self) -> dict:
        turn = ChatTurn.of(agents_providers.run_chat_turn(
            self.config,
            self.conversation.messages,
            max_output_tokens=self.run_policy["max_output_tokens"],
            usage_out=self.usage_sink,
            thinking_tokens=self.run_policy["thinking_tokens"],
            **self.offered,
        ))
        self._answered()
        # A call written as text is no text of the turn's: the round's reply
        # is what came before it, as a stream's is (_streaming_round).
        reply, markup = _without_call_markup(turn.text)
        if markup is not None:
            turn = dataclasses.replace(turn, text=reply)
        visible, parts = content.extract_content(reply)
        self._check_candidates(parts)
        result = {"reply": reply, "visible": visible, "parts": parts, "turn": turn}
        if markup is not None:
            result["callMarkup"] = markup
        return result

    def _check_candidates(self, parts: list) -> None:
        """dev/67-4: no unverified laundering. A candidates card the reply
        holds is checked before anyone sees it, as a delegated card is: its
        catalog rows against the Data Catalog listing, its external rows by
        the runtime's probe."""
        agents_grounding._ground_catalog_lanes(
            parts,
            lambda: agents_grounding._catalog_rows_for_discovery(self.user_key, self.project_id),
        )
        agents_grounding._verify_candidate_parts(parts, self.loop_ctx)

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
        IS the bug (see ``_handle_tool_reply``). A stop asked meanwhile ends
        the round at the model's next piece: it returns ``{stopped, shown}``,
        *shown* the text its deltas showed, and nothing more is read. The
        turn carries the stop reason the stream ended with; a tail held in a
        round the output cap cut is half written, so it is neither held for a
        correction nor released (:meth:`_cut`). A call the model writes as
        text in its own call syntax reaches none of this: the deltas come
        through :func:`_stream_without_call_markup`, which keeps it as
        ``callMarkup`` and never releases it, and the round's reply is what
        came before it, as a blocking round's is."""
        marker = content.TAIL_FENCE
        granted = self.loop_ctx.get("granted", [])
        hold_plan_tail = "dataflow.plan.write" in granted
        hold_request_tail = bool(set(granted or []) & agents_tool_rounds.MUTATE_PROPOSAL_TOOLS)
        chunks: list[str] = []
        shown: list[str] = []  # what the round's deltas showed
        calls: list = []
        markup: list[str] = []  # a call written as text, from its start on
        buf = ""  # pass-mode text not yet emitted
        withheld: str | None = None  # not None → holding a candidate tail
        finish: dict = {}  # how the stream ended, once it has
        deltas = agents_providers.stream_chat_turn(
            self.config,
            self.conversation.messages,
            max_output_tokens=self.run_policy["max_output_tokens"],
            usage_out=self.usage_sink,
            finish=finish,
            thinking_tokens=self.run_policy["thinking_tokens"],
            **self.offered,
        )
        try:
            for delta in _stream_without_call_markup(deltas, markup):
                if self._stopping():
                    return {"stopped": True, "shown": "".join(shown)}
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
                        # Closed fence followed by more content: not terminal,
                        # so flush the closed block verbatim and rescan the rest.
                        shown.append(withheld[: close + 4])
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
                        shown.append(buf[:idx])
                        yield ("delta", buf[:idx])
                    withheld = buf[idx:]
                    buf = ""
                else:
                    emit, buf = self._hold_split(buf)
                    if emit:
                        shown.append(emit)
                        yield ("delta", emit)
        finally:
            close_stream = getattr(deltas, "close", None)
            if close_stream is not None:
                close_stream()
        reply, called = _without_call_markup("".join(chunks) + "".join(markup))
        visible, parts = content.extract_content(reply)
        self._check_candidates(parts)
        turn = ChatTurn(text=reply, tool_calls=tuple(calls), stop_reason=str(finish.get("reason") or ""),
                        thinking=bool(finish.get("thinking")), output_limit=int(finish.get("limit") or 0),
                        thinking_room_refused=bool(finish.get("thinking_room_refused")))
        result = {"reply": reply, "visible": visible, "parts": parts, "turn": turn}
        if called is not None:
            result["callMarkup"] = called
        # A tail the output cap cut is half written: neither held nor shown.
        if withheld is not None and not parts and not turn.cut_at_output_cap:
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
            # The delegate is at work in the room from its run until what it
            # made has landed.
            with ExitStack() as stay:
                status, text, child, home_att, delegate_summary = self._run_delegate(req, resolution, stay)
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

    def _run_delegate(self, req: dict, resolution, stay=None):
        """Run the resolved delegate and mint what its success PROVES exists
        (dev/73 content, dev/90 draft, dev/114 candidates, dev/95 notes),
        runtime-minted, never the model's second step. The delegate is at work
        in the dataflow's room while *stay*, the caller's ``ExitStack``, holds
        it. Returns (status, text, child, home_att, summary)."""
        loop_ctx = self.loop_ctx
        inputs = req.get("inputs") or {}
        # dev/73: node-scoped content generation homes its trace AND its
        # change at the node's own agent. Content for a new node (a
        # nodeType and no nodeId) has no node: it returns to this run, for
        # its node.create.
        gen_node_id = (
            agents_delegates._delegate_target_node_id(loop_ctx, inputs)
            if req["capability"] == "node.content.generate"
            else None
        )
        # Discovery: the runtime lists the Data Catalog once. The child is
        # shown it and its candidates are checked against it, whatever
        # catalog the request carried.
        catalog_rows = (
            agents_grounding._catalog_rows_for_discovery(self.user_key, self.project_id)
            if req["capability"] == "dataset.discover"
            else None
        )
        enriched = agents_delegates._enriched_delegate_inputs(
            self.user_key, self.project_id, loop_ctx, req["capability"], inputs,
            catalog_rows=catalog_rows,
        )
        status, text, child, home_att = agents_delegates._run_delegate_traced(
            self.user_key,
            self.project_id,
            resolution.coord,
            req["capability"],
            enriched,
            self.config,
            parent_execution_id=self.execution_id,
            parent_coord=loop_ctx["coord"],
            attachment_id=loop_ctx.get("attachment_id"),
            parent_name=getattr(loop_ctx.get("manifest"), "name", None),
            node_id=gen_node_id,
            # What the dataflow can use, for a child that writes code: the
            # runtime's, never a value the model put in the inputs, with the
            # datasets this turn read already.
            dataflow_block=agents_dataflow_block.for_delegated_run(
                self.user_key, self.project_id, req["capability"], enriched,
                datasets=loop_ctx.get("dataflow_datasets"),
            ),
            asker=loop_ctx.get("asker"),
            stay=stay,
            who=loop_ctx["room_asker"],
        )
        self.delegations.append(child)
        delegate_summary = text
        if status == "ok" and gen_node_id:
            # dev/73: generation success: the runtime writes the code into
            # the node, never the model's second step.
            change_part, change_home, text = agents_delegates._mint_content_review_from_delegate(
                self.user_key, self.project_id,
                node_id=gen_node_id,
                generated_text=text,
                parent_attachment_id=loop_ctx.get("attachment_id"),
                parent_session_id=loop_ctx.get("session_id"),
                parent_loop_ctx=loop_ctx,
                delegate_coord=resolution.coord,
            )
            delegate_summary = text
            if change_part is not None:
                delegate_summary = f"content written into node {gen_node_id!r}"
                if change_home == loop_ctx.get("attachment_id"):
                    self.minted.append(change_part)
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
                loop_ctx, text, catalog_rows,
                name=getattr(resolution.manifest, "name", None),
            )
            delegate_summary = text
            if cand_part is not None:
                self.minted.append(cand_part)
                delegate_summary = "dataset candidates shown for review — select and confirm"
            status = cand_outcome
        elif status == "ok" and req["capability"] == "research.notes.compose":
            # dev/95 (Follow-up D): notes success ⇒ the notes EXIST, each the
            # agent's change, runtime-minted from the child's schema reply,
            # never the model's second step.
            note_parts, text, notes_outcome = agents_delegates._mint_notes_from_delegate(
                self.user_key, self.project_id, loop_ctx, text,
            )
            delegate_summary = text
            if note_parts:
                self.minted.extend(note_parts)
                delegate_summary = f"{len(note_parts)} note(s) added"
            status = notes_outcome
        return status, text, child, home_att, delegate_summary

    def _tool_round(self, req: dict, result: dict, native_calls: list, *, last_try: bool = False):
        """Run *req* and answer it. A plan's *last_try*, at the cap, is not
        answered: it landed, or the plan's card ends the turn."""
        yield from self._emit("tool_requested", {"tool": req["tool"]})
        yield from self._emit("tool_started", {"tool": req["tool"]})
        status, text = agents_tool_rounds._execute_tool_request(
            self.user_key, self.project_id, self.loop_ctx, req, self.tool_calls, self.minted
        )
        # The event carries what the call's record holds for the chat: why it
        # failed, and whether the egress policy refused it (#447).
        record = self.tool_calls[-1]
        extra = {key: record[key] for key in ("reason", "egress") if key in record}
        yield from self._emit("tool_result", {"tool": req["tool"], "status": status, **extra})
        # A plan refused is a correction, as an invalid plan block is (dev/54).
        plan_refused = (agents_tool_rounds._is_plan_request(self.loop_ctx, req)
                        and status not in agents_tool_rounds._NATIVE_OK_STATUSES)
        if last_try:
            if plan_refused:
                self.final_parts = [agents_tool_rounds._plan_cap_card([text])]
            return
        if req["tool"] == agents_skill_runs.TOOL and self.skill_reads < agents_skill_runs.FREE_READS:
            self.skill_reads += 1  # loading a skill is no round, up to FREE_READS a turn
        elif isinstance(text, ParamRefusal) and self.refusals_used < agents_tool_rounds.MAX_REFUSED_ROUNDS:
            self.refusals_used += 1  # dev/105 D2: a free correction, not a round
        else:
            self.rounds_used += 1
        # Its result asks for the plan again, and the next call may make it.
        self.plan_corrected = plan_refused
        if plan_refused:
            self.plan_errors = [text]
        final = self.rounds_used >= agents_tool_rounds.MAX_TOOL_ROUNDS and not plan_refused
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
                skills_loaded=self._skills_loaded(),
            ),
            writer=self.loop_ctx.get("writer"),
        )

    def _skills_loaded(self) -> list[str]:
        """What skill.read loaded this turn, which later turns are handed again."""
        run_skills = self.loop_ctx.get("skills")
        return list(run_skills.loaded) if run_skills is not None else []

    @staticmethod
    def _name_its_offers(parts: list) -> dict | None:
        """Every candidates card the turn holds gets an id of its own
        (``discoveryId``), which a pick on it names; returns the newest, which
        a node's Dataset Finder offers for its node
        (``dataset_resolution.offer_from_chat``), or None."""
        cards = [part for part in parts if isinstance(part, dict) and part.get("type") == "datasetCandidates"]
        for card in cards:
            card.setdefault("discoveryId", uuid.uuid4().hex)
        return cards[-1] if cards else None

    def settle_ok(self) -> dict:
        """Settle the reservation, persist both turns, title the conversation
        when this is its first exchange; returns the run's result payload. A
        stopped turn settles as ``stopped``, its record naming who stopped it
        (``stoppedBy``), with what it said and landed until then, and asks
        the model for no title. A turn the output cap cut (:meth:`_cut`)
        says so in its record, its payload and its ``done``
        (``cutAtOutputLimit``)."""
        reply_text = "\n\n".join(self.folded)
        run_parts = self.minted + self.final_parts  # proposals ride the turn (dev/41)
        status = "stopped" if self.stopped else "ok"
        ledger.settle(self.user_key, self.reservation, usage=self.usage_total or None, status=status)
        execution = agents_policy._execution_record(
            self.execution_id, self.pins, self.usage_total, self.started, status, self.tool_calls,
            delegations=self.delegations,
            refused_rounds=self.refusals_used,
            skills_loaded=self._skills_loaded(),
        )
        stopped = {"by": self.stop.by} if self.stopped and self.stop is not None else None
        if stopped is not None:
            execution["stoppedBy"] = stopped["by"]
        if self.cut:
            execution["cutAtOutputLimit"] = True
        if self.room_refused:
            execution["thinkingRoomRefused"] = True
        offered = self._name_its_offers(run_parts)
        agents_prepare._persist_exchange(
            self.user_key,
            self.project_id,
            self.session_id,
            self.attachment_id,
            self.message,
            reply_text,
            execution=execution,
            parts=run_parts,
            writer=self.loop_ctx.get("writer"),
        )
        if offered is not None:
            # A node's Dataset Finder offered candidates in its own chat: its
            # record names the card as the one on offer now, once the card is
            # in the chat.
            agents_dataset_resolution.offer_from_chat(self.user_key, self.project_id, self.attachment_id, offered)
        # Title before the done frame: the reply text already streamed via
        # deltas, and the client's post-send refresh must see the title.
        if self.wants_title and not self.stopped:
            agents_titles._generate_conversation_title(
                self.user_key, self.project_id, self.attachment_id, self.message, self.config
            )
        # The skills the reply's line under it names, as the persisted record
        # holds them: those its system turn held (pins.skills, its catalog
        # left out) and those it loaded (skillsLoaded).
        held = {key: names for key, names in (self.pins.get("skills") or {}).items() if key != "catalog"}
        self.result = {
            "attachmentId": self.attachment_id,
            "coord": self.coord,
            "reply": reply_text,
            "executionId": self.execution_id,
            "usage": execution["usage"],
            # dev/80: the run's wall-clock duration — matches the persisted record.
            "durationMs": execution["durationMs"],
            "content": run_parts,
            **({"skills": held} if held else {}),
            **({"skillsLoaded": execution["skillsLoaded"]} if execution.get("skillsLoaded") else {}),
            **({"stopped": stopped} if stopped is not None else {}),
            **({"cutAtOutputLimit": True} if self.cut else {}),
            # What the stream sends as change events, for a tab no doc binds.
            **({"changes": list(self.landed)} if self.landed else {}),
        }
        return self.result

    # ── the streaming envelope ──────────────────────────────────────────────

    def stream(self):
        """The turn's events: the dev/37 execution handshake, the loop's
        events, then review_required / content / done, or error. A stopped
        turn's done says who stopped it (``stopped``), and a turn the output
        cap cut says so (``cutAtOutputLimit``)."""
        # The typed-envelope handshake (memo dev/37): the execution identity
        # arrives before the first delta so a client can correlate the stream
        # with the record that will land on the transcript.
        yield ("execution", {"executionId": self.execution_id})
        try:
            # The agent is in the room while it works, and gone before its
            # reply's last events: a reply on screen means it left.
            with self.at_work():
                yield from self.rounds()
        except Exception as exc:  # provider failure mid-stream
            self.settle_error(exc)
            yield ("error", f"agent run failed: {self.redacted(exc)}")
            return
        payload = self.settle_ok()
        # An install waits for the person's review (dev/03:344 review_required).
        for part in self.minted:
            if part.get("type") != "proposal":
                continue  # dev/72: delegation entries and changes ride the content event
            yield (
                "review_required",
                {
                    "proposalId": part["proposalId"],
                    "tool": part["tool"],
                    "summary": part["summary"],
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
                # The skills the reply's line names, as the blocking answer
                # carries them, who stopped it, and whether the cap cut it.
                **{key: payload[key] for key in ("skills", "skillsLoaded", "stopped", "cutAtOutputLimit")
                   if key in payload},
            },
        )
