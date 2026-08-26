"""A deterministic, scripted chat-completion backend for tests.

Selected by ``ProviderConfig.api_type == "testing"`` and honoured ONLY when
``CURIO_TESTING`` is set. The guard is re-checked at call time, not just at
import, so a stray ``testing`` provider config on a real deployment cannot
quietly turn into a working agent - it raises instead.

Why this exists: every agent surface worth an end-to-end test (chat, solve, a
minted proposal, the review card) is downstream of one LLM call. Pointing that
call at a real provider would make the suite need a key, a network, and a model
that answers the same way twice. Pointing it at a script keeps the WHOLE
backend loop under test - tools, policy, quotas, the ledger, the content parser
- while making the model the one part that cannot vary.

Two ways to script it:

* ``push_reply(...)`` / ``push_replies(...)`` - an in-process FIFO, for pytest.
  Each call pops one reply; the queue is per-process and cleared by
  :func:`reset`.
* ``CURIO_TESTING_LLM_SCRIPT`` - a path to a JSON file, for e2e, where the
  backend runs in another process. Shape::

      {
        "rules": [
          {"match": "substring of the prompt", "reply": "..."},
          {"match": "another", "reply": "...", "usage": {"in": 10, "out": 20}}
        ],
        "default": "..."
      }

  Rules are tried in order against the concatenated prompt text; the first
  whose ``match`` appears wins. The queue takes precedence over the file.

When nothing matches, :data:`FALLBACK_REPLY` is returned rather than raising:
a test that forgot to script one leg of a multi-turn conversation should fail
on the assertion it cares about, not on an exception from the provider.
"""

from __future__ import annotations

import json
import os
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


def _prompt_text(messages: list) -> str:
    parts = []
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _from_script(messages: list) -> tuple[str, dict | None] | None:
    """First matching rule from ``CURIO_TESTING_LLM_SCRIPT``, if configured."""
    path = os.environ.get("CURIO_TESTING_LLM_SCRIPT")
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            script = json.load(handle)
    except (OSError, ValueError):
        # A broken script file must not masquerade as a model that had nothing
        # to say - but it also must not crash a suite mid-run, so fall through
        # to the default reply and let the assertion report the mismatch.
        return None
    if not isinstance(script, dict):
        return None

    prompt = _prompt_text(messages)
    for rule in script.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        needle = rule.get("match")
        if isinstance(needle, str) and needle and needle in prompt:
            return str(rule.get("reply") or FALLBACK_REPLY), rule.get("usage")

    default = script.get("default")
    if isinstance(default, str):
        return default, script.get("defaultUsage")
    return None


def run_scripted_completion(messages: list, usage_out: dict | None = None) -> str:
    """Return the next scripted reply and record its token usage.

    Raises :class:`TestingProviderUnavailable` when called outside a test run.
    """
    if not enabled():
        raise TestingProviderUnavailable(
            'The "testing" LLM provider is only available when CURIO_TESTING is set. '
            "Configure a real provider in AI Settings."
        )

    with _lock:
        queued = _queue.popleft() if _queue else None

    if queued is not None:
        reply, usage = queued
    else:
        scripted = _from_script(messages)
        reply, usage = scripted if scripted is not None else (FALLBACK_REPLY, None)

    counts = usage if isinstance(usage, dict) else DEFAULT_USAGE
    if usage_out is not None:
        usage_out["inputTokens"] = int(counts.get("in", DEFAULT_USAGE["in"]))
        usage_out["outputTokens"] = int(counts.get("out", DEFAULT_USAGE["out"]))
    return reply
