"""A deterministic, scripted chat-completion backend for tests.

Selected by ``ProviderConfig.api_type == "testing"`` and honoured ONLY when
``CURIO_TESTING`` is set. The guard is re-checked at call time, not just at
import, so a stray ``testing`` provider config on a real deployment cannot
quietly turn into a working agent - it raises instead.

Why this exists: every agent surface worth an end-to-end test (chat, solve, a
minted proposal, the review card) is downstream of one LLM call. Pointing that
call at a real provider would make the suite need a key, a network, and a model
that answers the same way twice. Pointing it at a script keeps the WHOLE
backend loop under test - tools, the ledger, the content parser
- while making the model the one part that cannot vary.

Scripted through ``push_reply(...)`` / ``push_replies(...)``: an in-process
FIFO. Each call pops one reply; the queue is per-process and cleared by
:func:`reset`. :func:`route_by_intent` adds replies keyed by what a delegated
call asks for: Solve requests one node's content per call, in wave order and
interleaved with other delegations, so a position in the queue cannot know
which node it answers, but the call's ``intent`` can.

Out-of-process e2e reaches the same FIFO over HTTP, through
``/api/testing/agent-script`` (see ``app/testing/routes.py``). A previous
``CURIO_TESTING_LLM_SCRIPT`` file served that purpose and was removed as
speculative when nothing used it; the e2e agent suite now runs real turns, and
the HTTP endpoint is the replacement. It works because the backend serves
threaded in a single process, so this module's queue is the one every request
handler sees.

Every call's ``messages`` list is also recorded, readable through
:func:`captured` / :func:`last_messages`. That is what lets a per-agent test
prove *which* agent's prompt composed the turn - the run path assembles the
system turn from the agent's own preamble + instruction, and a reply alone
cannot distinguish one agent from another.

A reply is its text, or an entry ``{"text", "toolCalls"}`` whose calls the
model makes natively, each ``{"name", "arguments", "id"}`` (``name`` is the
tool id or its native name, ``id`` optional), or ``{"error", "status"}``,
which the call raises as that endpoint error. A native call can only answer a
call that offered tools (:func:`script_chat_capabilities`), and what each call
offered is recorded (:func:`offered`).

When nothing matches, :data:`FALLBACK_REPLY` is returned rather than raising:
a test that forgot to script one leg of a multi-turn conversation should fail
on the assertion it cares about, not on an exception from the provider.
"""

from __future__ import annotations

import itertools
import json
import threading
from collections import deque

#: Returned when neither the queue nor the script has an answer. Deliberately
#: inert prose: it carries no ```curio.v1``` block, so it parses as a plain
#: assistant turn and mints nothing.
FALLBACK_REPLY = "This is a scripted test reply."

#: Token counts reported when a rule does not specify its own. Non-zero so the
#: ledger reserve/settle path and the quota accounting are actually exercised.
DEFAULT_USAGE = {"in": 12, "out": 34}

#: How many message lists :func:`captured` retains. A bound, not a budget:
#: a long-lived backend process serving many e2e turns must not grow a list
#: for the lifetime of the run. Oldest entries drop first.
MAX_CAPTURED = 64

_lock = threading.Lock()
_queue: deque = deque()
_captured: deque = deque(maxlen=MAX_CAPTURED)
#: Which LLM configuration each call answered with: ``{configId, model}``, in
#: the same order as ``_captured``.
_calls: deque = deque(maxlen=MAX_CAPTURED)
#: What each call offered natively: ``{tools: [names], toolChoice,
#: replySchema}``, in the same order as ``_captured``.
_offered: deque = deque(maxlen=MAX_CAPTURED)
#: Replies keyed by a substring of a delegated call's ``intent``.
_by_intent: dict = {}
#: What the scripted endpoint says it can do beyond text
#: (``chat_capabilities``): nothing, so runs use the fenced protocol.
_DEFAULT_CHAT_CAPABILITIES = {"tools": False, "structuredOutput": False}
_chat_capabilities: dict = dict(_DEFAULT_CHAT_CAPABILITIES)
#: Ids for scripted calls that name none, unique for the process.
_call_ids = itertools.count(1)


class TestingProviderUnavailable(RuntimeError):
    """Raised when the testing provider is selected outside a test run."""


class ScriptedEndpointError(RuntimeError):
    """A scripted ``{"error", "status"}`` reply: the endpoint failed with
    that HTTP status, as a real SDK's error carries it."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def enabled() -> bool:
    """True when the scripted provider may be used at all."""
    from utk_curio.backend.config import _is_testing

    return _is_testing()


def push_reply(reply: str | dict, *, usage: dict | None = None) -> None:
    """Queue one reply for the next completion call: its text, or an entry
    (see the module docstring)."""
    with _lock:
        _queue.append((reply, usage))


def push_replies(*replies: str | dict) -> None:
    """Queue several replies, consumed in order."""
    for reply in replies:
        push_reply(reply)


def route_by_intent(routes: dict) -> None:
    """Answer a delegated call whose ``intent`` contains a key with its reply.

    Checked before the queue, longest key first, so a short key never answers
    for a longer one it is part of. A call that matches no key pops the queue
    as before.
    """
    with _lock:
        _by_intent.clear()
        _by_intent.update({str(k): str(v) for k, v in (routes or {}).items() if k})


def _delegated_intent(messages: list) -> str:
    """The ``intent`` of a delegated request, or "".

    A delegated request's last message is ``[delegated task from ...]`` followed
    by a JSON object. Only its ``intent`` names the node being asked about: the
    rest of the object lists sibling nodes too.
    """
    if not isinstance(messages, list) or not messages:
        return ""
    last = messages[-1]
    text = str(last.get("content") or "") if isinstance(last, dict) else ""
    start = text.find("{")
    if start < 0:
        return ""
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return ""
    return str(parsed.get("intent") or "") if isinstance(parsed, dict) else ""


def _routed_reply(messages: list):
    """The routed reply for this call, or None. Caller holds ``_lock``."""
    if not _by_intent:
        return None
    intent = _delegated_intent(messages)
    if not intent:
        return None
    for key in sorted(_by_intent, key=len, reverse=True):
        if key in intent:
            return _by_intent[key]
    return None


def reset() -> None:
    """Drop anything still queued and everything captured. Call between tests."""
    with _lock:
        _queue.clear()
        _captured.clear()
        _calls.clear()
        _offered.clear()
        _by_intent.clear()
        _chat_capabilities.clear()
        _chat_capabilities.update(_DEFAULT_CHAT_CAPABILITIES)


def script_chat_capabilities(*, tools: bool = False, structured_output: bool = False) -> None:
    """Script what the endpoint says it can do beyond text, until :func:`reset`."""
    with _lock:
        _chat_capabilities.update({"tools": bool(tools), "structuredOutput": bool(structured_output)})


def scripted_chat_capabilities() -> dict:
    """``{tools, structuredOutput}``: the fenced protocol unless scripted otherwise."""
    with _lock:
        return dict(_chat_capabilities)


def captured() -> list:
    """The ``messages`` list of every call since the last :func:`reset`.

    A copy, so a caller iterating it cannot be surprised by a concurrent run
    on the backend's other threads.
    """
    with _lock:
        return [list(m) for m in _captured]


def calls() -> list:
    """``{configId, model}`` of every call since the last :func:`reset`: which
    LLM configuration answered each, never its key."""
    with _lock:
        return [dict(c) for c in _calls]


def offered() -> list:
    """``{tools, toolChoice, replySchema}`` of every call since the last
    :func:`reset`: the native names of the tools it offered (none on the fenced
    protocol), whether it let the model call one, and the name of the reply
    schema it carried, or None."""
    with _lock:
        return [{"tools": list(o["tools"]), "toolChoice": o["toolChoice"],
                 "replySchema": o["replySchema"]} for o in _offered]


def last_messages() -> list | None:
    """The most recent call's ``messages``, or None when nothing ran yet."""
    with _lock:
        return list(_captured[-1]) if _captured else None


def pending() -> int:
    """How many scripted replies are still queued."""
    with _lock:
        return len(_queue)


def run_scripted_completion(messages: list, usage_out: dict | None = None, config=None) -> str:
    """The text of the next scripted reply (:func:`run_scripted_turn`)."""
    return run_scripted_turn(messages, usage_out=usage_out, config=config).text


def run_scripted_turn(
    messages: list,
    usage_out: dict | None = None,
    config=None,
    tools: list | None = None,
    tool_choice: str = "auto",
    reply_schema: dict | None = None,
):
    """Return the next scripted reply as a turn and record its token usage.

    ``messages`` does not choose the reply - the queue does, so a test's
    scripting stays independent of prompt wording. It is recorded, though, so a
    test can assert what actually reached the model (see :func:`captured`), as
    are the tools the call offered and the reply schema it carried
    (:func:`offered`). A reply to a call with a reply schema is scripted as the
    constrained JSON a provider would return.

    Raises :class:`TestingProviderUnavailable` when called outside a test run,
    :class:`ScriptedEndpointError` for an ``{"error", "status"}`` reply, and
    ``ValueError`` for native calls scripted where the call offered no tool to
    call: a real model could not have made them.
    """
    if not enabled():
        raise TestingProviderUnavailable(
            'The "testing" LLM provider is only available when CURIO_TESTING is set. '
            "Configure a real provider in API Settings."
        )

    with _lock:
        # Recorded before the pop, so a reply and the prompt that drew it keep
        # the same index in a multi-round run.
        _captured.append(list(messages) if isinstance(messages, list) else [])
        _calls.append({
            "configId": getattr(config, "config_id", None),
            "model": getattr(config, "model", None),
        })
        _offered.append({
            "tools": [t.get("name") for t in tools or ()],
            "toolChoice": tool_choice if tools else None,
            "replySchema": (reply_schema or {}).get("name"),
        })
        routed = _routed_reply(messages)
        queued = None if routed is not None else (_queue.popleft() if _queue else None)
    if routed is not None:
        reply, usage = routed, None
    else:
        reply, usage = queued if queued is not None else (FALLBACK_REPLY, None)
    if isinstance(reply, dict) and reply.get("error") is not None:
        # A failed call is not charged, so it reports no usage.
        raise ScriptedEndpointError(str(reply["error"]), int(reply.get("status") or 500))

    counts = usage if isinstance(usage, dict) else DEFAULT_USAGE
    if usage_out is not None:
        usage_out["inputTokens"] = int(counts.get("in", DEFAULT_USAGE["in"]))
        usage_out["outputTokens"] = int(counts.get("out", DEFAULT_USAGE["out"]))
        # A script may report cached input too, as a caching provider would.
        for key, name in (("cacheRead", "cacheReadTokens"), ("cacheWrite", "cacheWriteTokens")):
            if isinstance(counts.get(key), int):
                usage_out[name] = counts[key]
    return _scripted_turn(reply, tools, tool_choice)


def _scripted_turn(reply, tools: list | None, tool_choice: str):
    from utk_curio.backend.app.agents.domain import tool_names as tool_registry
    from utk_curio.backend.app.agents.infrastructure.providers import (
        ChatTurn,
        ToolCall,
    )

    if not isinstance(reply, dict):
        return ChatTurn.of(reply)
    scripted_calls = reply.get("toolCalls") or []
    if scripted_calls and (not tools or tool_choice == "none"):
        raise ValueError(
            "the script makes a native tool call, but this call offered no tool "
            "to call (the run speaks the fenced protocol, or this is its last round)"
        )
    calls = []
    for call in scripted_calls:
        name = str(call.get("name") or "")
        calls.append(ToolCall(
            id=str(call.get("id") or f"scripted-call-{next(_call_ids)}"),
            name=tool_registry.wire_name(name) if "." in name else name,
            arguments=dict(call.get("arguments") or {}),
        ))
    return ChatTurn(text=str(reply.get("text") or ""), tool_calls=tuple(calls))
