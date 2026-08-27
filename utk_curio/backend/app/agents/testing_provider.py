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
FIFO for pytest. Each call pops one reply; the queue is per-process and cleared
by :func:`reset`.

There was also a ``CURIO_TESTING_LLM_SCRIPT`` file, so an out-of-process e2e
could script a reply. Nothing ever used it - the agent e2e suite covers the
drawer, the palette and the requiresAgents closure, none of which runs a turn -
so it was speculative infrastructure and came out. If a chat e2e is written
later, that is the point to add it back.

When nothing matches, :data:`FALLBACK_REPLY` is returned rather than raising:
a test that forgot to script one leg of a multi-turn conversation should fail
on the assertion it cares about, not on an exception from the provider.
"""

from __future__ import annotations

import threading
from collections import deque

#: Returned when neither the queue nor the script has an answer. Deliberately
#: inert prose: it carries no ```curio.v1``` block, so it parses as a plain
#: assistant turn and mints nothing.
FALLBACK_REPLY = "This is a scripted test reply."

#: Token counts reported when a rule does not specify its own. Non-zero so the
#: ledger reserve/settle path and the quota accounting are actually exercised.
DEFAULT_USAGE = {"in": 12, "out": 34}

_lock = threading.Lock()
_queue: deque = deque()


class TestingProviderUnavailable(RuntimeError):
    """Raised when the testing provider is selected outside a test run."""


def enabled() -> bool:
    """True when the scripted provider may be used at all."""
    from utk_curio.backend.config import _is_testing

    return _is_testing()


def push_reply(reply: str, *, usage: dict | None = None) -> None:
    """Queue one reply for the next completion call."""
    with _lock:
        _queue.append((reply, usage))


def push_replies(*replies: str) -> None:
    """Queue several replies, consumed in order."""
    for reply in replies:
        push_reply(reply)


def reset() -> None:
    """Drop anything still queued. Call between tests."""
    with _lock:
        _queue.clear()


def pending() -> int:
    """How many scripted replies are still queued."""
    with _lock:
        return len(_queue)


def run_scripted_completion(messages: list, usage_out: dict | None = None) -> str:
    """Return the next scripted reply and record its token usage.

    ``messages`` is unread. It stays in the signature so this drops into
    ``run_chat_completion``'s call shape unchanged: the queue decides the
    reply, not the prompt.

    Raises :class:`TestingProviderUnavailable` when called outside a test run.
    """
    if not enabled():
        raise TestingProviderUnavailable(
            'The "testing" LLM provider is only available when CURIO_TESTING is set. '
            "Configure a real provider in AI Settings."
        )

    with _lock:
        queued = _queue.popleft() if _queue else None
    reply, usage = queued if queued is not None else (FALLBACK_REPLY, None)

    counts = usage if isinstance(usage, dict) else DEFAULT_USAGE
    if usage_out is not None:
        usage_out["inputTokens"] = int(counts.get("in", DEFAULT_USAGE["in"]))
        usage_out["outputTokens"] = int(counts.get("out", DEFAULT_USAGE["out"]))
    return reply
