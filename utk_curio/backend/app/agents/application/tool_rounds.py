"""Tool and plan reply handling inside a turn: round caps, refusals, correction messages, and read-tool execution.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import json as _json
import re
import time

from utk_curio.backend.app.agents.application import tools
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.infrastructure import chat_capabilities
from utk_curio.backend.app.agents.infrastructure import egress
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.infrastructure.providers import ToolCall
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans


#: The correction for a plan found outside a terminal curio.v1 block.
_PLAN_FENCE_GUIDANCE = (
    "put the plan in a ```curio.v1 fenced block as the VERY LAST thing in "
    "your reply (not ```json)"
)


def _plan_correction_message(errors: list[str], *, native: bool = False) -> dict:
    """The corrective round's feedback (dev/54): precise, model-actionable,
    and explicit that the invalid block never reached the user. A run on
    native tools is asked for the plan as a call instead of a block."""
    if native:
        listed = "\n".join(f"- {e}" for e in [e for e in errors if e != _PLAN_FENCE_GUIDANCE][:10])
        return {
            "role": "user",
            "content": (
                "[plan validation] Your dataflowPlan was invalid and was NOT shown "
                "to the user. Fix exactly these problems and call "
                f"{tools.wire_name('dataflow.plan.write')} with the COMPLETE "
                "corrected plan (all nodes and edges):\n" + listed
            ),
        }
    listed = "\n".join(f"- {e}" for e in errors[:10])
    return {
        "role": "user",
        "content": (
            "[plan validation] Your dataflowPlan block was invalid and was NOT "
            "shown to the user. Fix exactly these problems and resend the "
            "COMPLETE corrected block (all nodes and edges, same fence syntax):\n"
            + listed
        ),
    }


def _handle_plan_reply(
    user_key: str,
    project_id: str,
    loop_ctx: dict,
    reply: str,
    parts: list,
    minted: list,
    rounds_used: int,
) -> tuple[str, list]:
    """In-loop plan handling (dev/52 mint, dev/54 correction rounds).

    Returns ``(kind, payload, visible_override)``: ``("none", parts, None)``
    — not a plan situation (ungranted agents keep the informational part;
    generic fail-open untouched); ``("mint", parts, override?)`` — the
    proposal was minted (appended to *minted*; the override strips a scanned
    fence block from the persisted text, dev/56); ``("correct", errors,
    None)`` — feed the errors back and re-round (shares the MAX_TOOL_ROUNDS
    budget); ``("cap", parts+card, None)`` — budget exhausted: fail loudly,
    never silently."""
    if "dataflow.plan.write" not in loop_ctx.get("granted", []):
        return "none", parts, None
    visible_override: str | None = None
    fence_guidance = _PLAN_FENCE_GUIDANCE
    plan_part = next((p for p in parts if p.get("type") == "dataflowPlan"), None)
    if plan_part is not None:
        status, error_text, part = agents_plans._mint_dataflow_plan(user_key, project_id, loop_ctx, plan_part)
        if part is not None:
            minted.append(part)
            return "mint", [p for p in parts if p is not plan_part], None
        errors = [error_text]
    else:
        _, tail_body = content.split_tail(reply)
        errors = content.plan_tail_diagnosis(tail_body)
        if not errors:
            # No terminal-tail attempt — the fence-agnostic scanner (dev/56):
            # models emit ```json / bare fences, often mid-reply.
            stripped, raw = content.extract_plan_attempt(reply)
            if raw is None:
                return "none", parts, None  # genuinely not a plan attempt
            if isinstance(raw, str):
                errors = (content.plan_tail_diagnosis(raw) or []) + [fence_guidance]
            else:
                plan, plan_errors = content.parse_dataflow_plan_verbose(raw)
                if not plan_errors:
                    status, error_text, part = agents_plans._mint_dataflow_plan(
                        user_key, project_id, loop_ctx, plan
                    )
                    if part is not None:
                        minted.append(part)
                        # The review card is the plan's home — the raw JSON
                        # block is stripped from the persisted text.
                        return "mint", parts, stripped
                    errors = [error_text, fence_guidance]
                else:
                    errors = plan_errors + [fence_guidance]
    if rounds_used < MAX_TOOL_ROUNDS:
        return "correct", errors, None
    card = {
        "type": "card",
        "kind": "error",
        "title": "Plan not proposable",
        "lines": [e[:300] for e in errors[:10]],
    }
    return "cap", [p for p in parts if p.get("type") != "dataflowPlan"] + [card], None


#: The correction for a tool request found outside a terminal curio.v1 block.
_TOOL_FENCE_GUIDANCE = (
    "put the tool request in a ```curio.v1 fenced block as the VERY LAST "
    "thing in your reply (not ```json, and with no text after it)"
)


def _tool_correction_message(errors: list[str], *, native: bool = False) -> dict:
    """The corrective round's feedback for a tool request (#245) — the
    ``_plan_correction_message`` twin: precise, model-actionable, and explicit
    that the invalid block never reached the user. A run on native tools is
    asked for a call instead of a block."""
    if native:
        listed = "\n".join(f"- {e}" for e in [e for e in errors if e != _TOOL_FENCE_GUIDANCE][:10])
        return {
            "role": "user",
            "content": (
                "[tool validation] Your tool request was invalid and was NOT "
                "shown to the user. Fix exactly these problems and call the "
                "tool with the COMPLETE corrected arguments:\n" + listed
            ),
        }
    listed = "\n".join(f"- {e}" for e in errors[:10])
    return {
        "role": "user",
        "content": (
            "[tool validation] Your tool request block was invalid and was NOT "
            "shown to the user. Fix exactly these problems and resend the "
            "COMPLETE corrected block (same fence syntax):\n" + listed
        ),
    }


def _tool_cap_card(errors: list[str]) -> dict:
    """The visible outcome of a request attempt that never became proposable.

    Distinct from :func:`_round_cap_cutoff_card`, which reports a *valid*
    request dangling at the round cap. This one reports a request the runtime
    could never turn into a proposal, and it is the ONLY thing the user sees
    of that block — see ``_handle_tool_reply`` for why the raw JSON is dropped.
    """
    return {
        "type": "card",
        "kind": "error",
        "title": "Proposal not created",
        "lines": [e[:300] for e in errors[:10]],
    }


def _requested_tool_of(payload: object) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("tool"), str):
        return payload["tool"]
    return None


def _handle_tool_reply(
    loop_ctx: dict,
    reply: str,
    parts: list,
    rounds_used: int,
) -> tuple[str, list, str | None, dict | None]:
    """In-loop toolRequest recovery (#245) — the dev/56 fence-agnostic scan and
    the dev/54 correction rounds that plans already have, for tool requests.

    Consulted ONLY after ``extract_content`` produced no request and
    ``_handle_plan_reply`` returned ``"none"``, so every existing path is
    byte-unchanged. ``extract_content`` itself is not touched: recovery lives
    here, exactly as ``extract_plan_attempt`` does for plans.

    Returns ``(kind, payload, visible_override, request)``:
    ``("none", parts, None, None)`` — not a request attempt, generic fail-open
    applies; ``("request", parts, stripped, req)`` — recovered, and the caller
    runs it through the ordinary request path (grant check, mint, and round
    accounting all unchanged); ``("correct", errors, None, None)`` — feed the
    errors back and re-round (shares the MAX_TOOL_ROUNDS budget, since a
    correction costs a real provider call); ``("cap", parts+card, stripped,
    None)`` — budget exhausted: fail loudly, never silently.
    """
    granted = loop_ctx.get("granted") or []
    if not granted:
        # A run with no tools cannot be attempting one — an agent quoting the
        # protocol keeps the pre-#245 fail-open behaviour exactly.
        return "none", parts, None, None

    def _claimed(payload: object) -> bool:
        """A request is ours to correct only when it names a GRANTED tool.

        Without this the runtime would 'correct' a model that merely echoed
        the literal ``{"tool": "<tool id>", "params": {}}`` out of the tail
        instruction — which is valid JSON — burning rounds on nothing.
        """
        tool = _requested_tool_of(payload)
        return tool is not None and tool in granted

    visible_override: str | None = None
    fence_guidance = _TOOL_FENCE_GUIDANCE

    _, tail_body = content.split_tail(reply)
    errors = content.tool_tail_diagnosis(tail_body)
    if errors:

        try:
            tool = _requested_tool_of((_json.loads(tail_body) or {}).get("toolRequest"))
        except (ValueError, TypeError, AttributeError):
            tool = None
        if tool is not None and tool not in granted:
            return "none", parts, None, None
    else:
        # No terminal-tail attempt (or a valid one, which never reaches here):
        # scan every fence, wherever the model put it.
        stripped, raw = content.extract_tool_request_attempt(reply)
        if raw is None:
            return "none", parts, None, None
        if isinstance(raw, str):
            # Broken JSON: claim it only when it names a granted tool, so a
            # malformed block about something else stays the model's text.
            if not any(f'"{t}"' in raw for t in granted):
                return "none", parts, None, None
            errors = (content.tool_tail_diagnosis(raw) or []) + [fence_guidance]
        else:
            if not _claimed(raw):
                return "none", parts, None, None
            request, request_errors = content.parse_tool_request_verbose(raw)
            if request is not None:
                return "request", parts, stripped, request
            errors = request_errors + [fence_guidance]
        visible_override = stripped

    if rounds_used < MAX_TOOL_ROUNDS:
        return "correct", errors, None, None
    # The cap. Unlike a plan tail (dev/54 releases it — a plan is a spec the
    # user can read), a mutate request's params are an entire source file:
    # releasing it IS the bug this fixes (#245 — 60KB of Python rendered as
    # chat prose under an Apply button that never existed). The model's own
    # prose still shows; only the machine block drops, and the card names
    # precisely why, which is more actionable than the JSON ever was.
    if visible_override is None:
        visible_override, _ = content.split_tail(reply)
    return "cap", list(parts) + [_tool_cap_card(errors)], visible_override, None


# How many tool executions one run may make (memo dev/41): total provider
# calls per run ≤ MAX_TOOL_ROUNDS + 1. A runtime constant until someone needs
# to tune it.
# dev/73: 3 — the Node Builder's documented modify flow (read the node →
# delegate generation → propose) is a three-round sequence; 2 forced models
# that follow their instructions to answer in prose instead of proposing.
MAX_TOOL_ROUNDS = 3


# dev/105 D2: a PARAMETER refusal — the mint rejected the request's params
# before touching any store, provider, or delegate — is a millisecond
# round-trip that produced exactly the correction the model needs. It does
# not spend a MAX_TOOL_ROUNDS round (that budget is provider cost; a refusal
# costs none) — up to this many per run, after which refusals count as rounds
# again so a model that never corrects still hits the dev/73 cap and its
# cutoff card. The live failure this fixes: search + two refusals = cap, and
# the reuse ladder's last rung (AUTHOR) was unreachable no matter what the
# model decided next.
MAX_REFUSED_ROUNDS = 2


class ParamRefusal(str):
    """The typed marker for a parameter refusal's text (dev/105 D2).

    A ``str`` subclass so every existing consumer — the tool-result message,
    the execution record, tests asserting on the text — sees a plain string;
    only the loop's round accounting asks ``isinstance``. A refusal caused by
    a broken store/catalog/spec is deliberately NOT one of these: that cost
    real work and must keep counting as a round so a dead store cannot loop.
    """


def _refuse_params(text: str) -> tuple[str, str, None]:
    """``("refused", ParamRefusal(text), None)`` — the mint return for a
    request the model can fix by changing its params."""
    return "refused", ParamRefusal(text), None


# The mutate tools _mint_proposal dispatches (dev/73): a request for one of
# these dangling at the round cap is a cut-off PROPOSAL — surfaced as an
# error card, never silently dropped under the reply's confident prose.
MUTATE_PROPOSAL_TOOLS = frozenset({
    "node.content.write",
    "node.create",
    "node.template.create",
    "dataset.install",
    "discovery.acquire",
    "package.install",  # dev/84
    "package.draft.apply",  # dev/89
    "dataflow.plan.write",
})


def _round_cap_cutoff_card(tool: str) -> dict:
    """The visible outcome of a mutate toolRequest dropped at the round cap."""
    return {
        "type": "card",
        "kind": "error",
        "title": "Proposal step cut off",
        "lines": [
            f"the run hit its tool-round limit before the {tool} proposal "
            "could be created — ask the agent to continue",
        ],
    }


#: The tools that spend the per-run web budget. ``discovery.sources`` is absent
#: on purpose: it reads manifests off disk, and charging it would burn a run's
#: allowance on a free call.
_EGRESS_TOOLS = ("web.fetch", "web.search", "discovery.search")


def _egress_cost(tool_id: str, params: dict) -> int:
    """How many requests this tool call will make."""
    if tool_id == "discovery.search":
        return tools.discovery_sources_contacted(params)
    return 1


def _execute_tool_request(
    user_key: str, project_id: str, loop_ctx: dict, req: dict, tool_calls: list, minted: list
) -> tuple[str, str]:
    """Handle one model toolRequest inside the loop (memo dev/41).

    Only granted read contracts execute; a granted mutate contract mints a
    review proposal (never executes — `DEC-006`); everything else resolves to
    a synthetic result the model can recover from, never a run error. The
    model gets the whole result; the user gets one bounded line of it, the
    record's ``reason``, under the reply (#447). Appends to ``tool_calls`` (the
    execution record's tool history) and ``minted`` (proposal parts for the
    persisted turn)."""
    tool_id = req.get("tool", "")
    started = time.monotonic()
    if tool_id not in loop_ctx["granted"]:
        status, text = "refused", f"tool {tool_id!r} is not granted for this run"
    elif tool_id in _EGRESS_TOOLS and loop_ctx.get("egressCalls", 0) >= egress.MAX_CALLS_PER_RUN:
        # dev/67-4 (DEC-053): the per-run egress budget — verification, never
        # crawling. The refusal is data the model must surface honestly.
        status, text = "error", (
            f"the egress budget is exhausted ({egress.MAX_CALLS_PER_RUN} web "
            "calls per run) — report what you verified so far"
        )
    else:
        if tool_id in _EGRESS_TOOLS:
            # Charged by the number of requests the call will ACTUALLY make,
            # not one per tool call. A federated discovery.search contacts every
            # searchable portal, so a flat tick would let one call issue five
            # requests against a budget of four - the same undercount
            # CallBudget's docstring records being fixed once already, where a
            # Socrata verification fetched twice per row.
            loop_ctx["egressCalls"] = loop_ctx.get("egressCalls", 0) + _egress_cost(
                tool_id, req.get("params") or {}
            )
        contract = tools.REGISTRY.get(tool_id)
        if contract is None:
            status, text = "refused", f"tool {tool_id!r} is not available"
        elif contract.effect == "mutate":
            status, text, part = agents_mint._mint_proposal(user_key, project_id, loop_ctx, req)
            if part is not None:
                minted.append(part)
        else:
            status, text = tools.execute_read_tool(
                tool_id,
                user_key=user_key,
                project_id=project_id,
                target=loop_ctx.get("target"),
                params=req.get("params") or {},
            )
    record = {
        "tool": tool_id,
        "status": status,
        "durationMs": int((time.monotonic() - started) * 1000),
    }
    reason = _failure_reason(status, text)
    if reason is not None:
        record["reason"] = reason
    tool_calls.append(record)
    return status, text


#: Appended to the result of the last round a run may spend on a tool.
_FINAL_ROUND_NOTE = "\nNo further tool calls are available this turn — answer with what you have."


def _tool_result_message(tool_id: str, status: str, text: str, *, final: bool) -> dict:
    """The tool result fed back as provider context (untrusted data, framed)."""
    suffix = _FINAL_ROUND_NOTE if final else ""
    return {"role": "user", "content": f"[tool result] {tool_id}: {status}\n{text}{suffix}"}


def _delegate_result_message(
    coord: str | None, capability: str, status: str, text: str, *, final: bool
) -> dict:
    """The delegate's result fed back as provider context (untrusted data,
    framed — memo dev/48 §3.4)."""
    who = f"{coord} ({capability})" if coord else capability
    suffix = _FINAL_ROUND_NOTE if final else ""
    return {"role": "user", "content": f"[delegate result] {who}: {status}\n{text}{suffix}"}


#: The statuses of a result that is not an error.
_NATIVE_OK_STATUSES = frozenset({"ok", "proposed"})

#: How long a failed call's reason may be: one line under the reply (#447).
_FAILURE_REASON_MAX_CHARS = 300

#: A URL's query string. A search provider's key rides there
#: (``CURIO_SEARCH_URL``), and transport errors repeat the URL they failed on.
_URL_QUERY = re.compile(r"\?[^\s'\"()<>]+")


def _failure_reason(status: str, text: object) -> str | None:
    """What the chat shows, and the turn saves, for a call that did not
    succeed (#447): the first line of its result, with URL query strings cut
    and the length bounded. None for a call that succeeded, so its event and
    record keep their shape."""
    if status in _NATIVE_OK_STATUSES:
        return None
    lines = str(text or "").strip().splitlines()
    if not lines:
        return None
    reason = _URL_QUERY.sub("?…", lines[0].strip())
    if len(reason) > _FAILURE_REASON_MAX_CHARS:
        reason = reason[: _FAILURE_REASON_MAX_CHARS - 1] + "…"
    return reason


#: The answer to every call of a reply after its first, which is the one run.
_NATIVE_NOT_RUN = (
    "not run: one tool call per reply, and this reply's first call was the "
    "one run. Call this one again on its own if you still need it."
)


def _native_request(call: ToolCall) -> tuple[dict | None, list[str]]:
    """*call* as the request part its fenced block would parse to, or why it
    is not one."""
    if call.error:
        return None, [call.error]
    if call.name == tools.DELEGATE_TOOL:
        return content.parse_delegate_request_verbose(call.arguments)
    tool_id = tools.tool_id_of(call.name)
    if tool_id is None:
        return None, [f"there is no tool named {call.name!r}"]
    return content.parse_tool_request_verbose({"tool": tool_id, "params": call.arguments})


def _native_result_text(status: str, text: str, *, final: bool) -> str:
    body = text if status in _NATIVE_OK_STATUSES and text else (
        f"{status}: {text}" if text else status
    )
    return body + (_FINAL_ROUND_NOTE if final else "")


def _fenced_request_reply(text: str, req: dict) -> str:
    """A reply whose request was a native call, as the fenced protocol
    writes it: its text, then the request's block."""

    if req.get("type") == "delegateRequest":
        payload = {"delegateRequest": {"capability": req.get("capability"),
                                       "inputs": req.get("inputs") or {}}}
    else:
        payload = {"toolRequest": {"tool": req.get("tool"), "params": req.get("params") or {}}}
    block = f"{content.TAIL_FENCE}\n{_json.dumps(payload, ensure_ascii=False)}\n```"
    return f"{text}\n\n{block}" if text else block


def _unreadable_call_reply(text: str, call: ToolCall) -> str:
    """A reply whose native call could not be read, as the fenced protocol
    writes it."""
    if call.name == tools.DELEGATE_TOOL:
        return _fenced_request_reply(text, {**(call.arguments or {}), "type": "delegateRequest"})
    return _fenced_request_reply(text, {"type": "toolRequest",
                                        "tool": tools.tool_id_of(call.name) or call.name,
                                        "params": call.arguments or {}})


def _is_mutate_call(call: ToolCall) -> bool:
    return tools.tool_id_of(call.name) in MUTATE_PROPOSAL_TOOLS


class _RunConversation:
    """The provider messages of one attached run, in the tool protocol it speaks.

    A run on native tools keeps the fenced form of every round beside the
    native one, so when its endpoint refuses the tools mid-run
    (``NativeToolsRefused``) the conversation carries on, fenced, from where it
    was. The refusal is recorded (``chat_capabilities.record_native_refusal``)
    once a fenced call has succeeded, which shows it was about the tools.
    """

    def __init__(self, messages: list, loop_ctx: dict):
        self.native_tools = loop_ctx.get("native_tools") or None
        fenced_system = loop_ctx.get("fenced_system")
        self._native = list(messages) if self.native_tools else None
        self._fenced = (
            [fenced_system, *messages[1:]]
            if self.native_tools and fenced_system is not None
            else list(messages)
        )
        self._refused: str | None = None

    @property
    def messages(self) -> list:
        return self._native if self.native_tools else self._fenced

    def offer(self, rounds_used: int) -> dict:
        """The next call's tool keywords. None on the fenced protocol, so its
        call is exactly what it was before native tools; on the last round the
        model may not call one."""
        if not self.native_tools:
            return {}
        return {
            "tools": self.native_tools,
            "tool_choice": "none" if rounds_used >= MAX_TOOL_ROUNDS else "auto",
        }

    def native_calls(self, turn: ChatTurn) -> tuple:
        """*turn*'s native calls, when this run offered any."""
        return tuple(turn.tool_calls) if self.native_tools else ()

    def fall_back(self, refusal: Exception, pins: dict) -> None:
        self.native_tools = None
        self._native = None
        self._refused = str(refusal)
        pins["toolProtocol"] = "fenced"
        pins["nativeToolsRefused"] = True

    def answered(self, config: ProviderConfig, user_key: str) -> None:
        if self._refused is not None:
            chat_capabilities.record_native_refusal(config, user_key, self._refused)
            self._refused = None

    def _lists(self) -> list:
        return [m for m in (self._native, self._fenced) if m is not None]

    def add_text_round(self, reply: str, feedback: dict, native_feedback: dict | None = None) -> None:
        """A reply answered with a user message: a correction, or the result
        of a request it wrote as a fenced block. *native_feedback* is what the
        native conversation receives instead, when its wording differs."""
        for messages in self._lists():
            messages.append({"role": "assistant", "content": reply})
            messages.append(
                native_feedback if native_feedback is not None and messages is self._native
                else feedback
            )

    def add_call_round(
        self, turn: ChatTurn, req: dict, status: str, text: str, *,
        final: bool, fenced_feedback: dict,
    ) -> None:
        """A reply whose first native call ran as *req*."""
        self._fenced.append({"role": "assistant", "content": _fenced_request_reply(turn.text, req)})
        self._fenced.append(fenced_feedback)
        self._answer_calls(
            turn, _native_result_text(status, text, final=final),
            is_error=status not in _NATIVE_OK_STATUSES,
        )

    def add_unreadable_call_round(self, turn: ChatTurn, errors: list[str], *, final: bool) -> None:
        """A reply whose first native call could not be read: the errors go
        back as its result, and the fenced form is a correction."""
        first = turn.tool_calls[0]
        self._fenced.append({"role": "assistant", "content": _unreadable_call_reply(turn.text, first)})
        self._fenced.append(_tool_correction_message(errors))
        listed = "\n".join(f"- {e}" for e in errors[:10])
        self._answer_calls(
            turn,
            "invalid call, not run. Fix exactly these problems and call it again:\n"
            + listed + (_FINAL_ROUND_NOTE if final else ""),
            is_error=True,
        )

    def _answer_calls(self, turn: ChatTurn, first_result: str, *, is_error: bool) -> None:
        if self._native is None:
            return
        self._native.append({
            "role": "assistant",
            "content": turn.text,
            "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in turn.tool_calls
            ],
        })
        first, *rest = turn.tool_calls
        self._native.append({"role": "tool", "tool_call_id": first.id, "name": first.name,
                             "content": first_result, "is_error": is_error})
        for call in rest:
            self._native.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                                 "content": _NATIVE_NOT_RUN, "is_error": True})
