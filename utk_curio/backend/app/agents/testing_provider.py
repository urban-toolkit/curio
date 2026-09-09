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
:func:`reset`.

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

#: How many message lists :func:`captured` retains. A bound, not a budget:
#: a long-lived backend process serving many e2e turns must not grow a list
#: for the lifetime of the run. Oldest entries drop first.
MAX_CAPTURED = 64

_lock = threading.Lock()
_queue: deque = deque()
_captured: deque = deque(maxlen=MAX_CAPTURED)


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
    """Drop anything still queued and everything captured. Call between tests.

    Also clears the scripted fine-tuning state (dev/122): one reset means one
    clean slate, not two things to remember.
    """
    with _lock:
        _queue.clear()
        _captured.clear()
    reset_fine_tuning()


def captured() -> list:
    """The ``messages`` list of every call since the last :func:`reset`.

    A copy, so a caller iterating it cannot be surprised by a concurrent run
    on the backend's other threads.
    """
    with _lock:
        return [list(m) for m in _captured]


def last_messages() -> list | None:
    """The most recent call's ``messages``, or None when nothing ran yet."""
    with _lock:
        return list(_captured[-1]) if _captured else None


def pending() -> int:
    """How many scripted replies are still queued."""
    with _lock:
        return len(_queue)


def run_scripted_completion(messages: list, usage_out: dict | None = None) -> str:
    """Return the next scripted reply and record its token usage.

    ``messages`` does not choose the reply - the queue does, so a test's
    scripting stays independent of prompt wording. It is recorded, though, so a
    test can assert what actually reached the model (see :func:`captured`).

    Raises :class:`TestingProviderUnavailable` when called outside a test run.
    """
    if not enabled():
        raise TestingProviderUnavailable(
            'The "testing" LLM provider is only available when CURIO_TESTING is set. '
            "Configure a real provider in AI Settings."
        )

    with _lock:
        # Recorded before the pop, so a reply and the prompt that drew it keep
        # the same index in a multi-round run.
        _captured.append(list(messages) if isinstance(messages, list) else [])
        queued = _queue.popleft() if _queue else None
    reply, usage = queued if queued is not None else (FALLBACK_REPLY, None)

    counts = usage if isinstance(usage, dict) else DEFAULT_USAGE
    if usage_out is not None:
        usage_out["inputTokens"] = int(counts.get("in", DEFAULT_USAGE["in"]))
        usage_out["outputTokens"] = int(counts.get("out", DEFAULT_USAGE["out"]))
    return reply


# ---------------------------------------------------------------------------
# Scripted fine-tuning (memo dev/122)
# ---------------------------------------------------------------------------
#
# The same idea as the scripted completion: the whole training lane — probe,
# upload, create, poll, cancel — has an in-process answer, so every test of it
# runs offline and a real fine-tune (money, hours) is never part of a suite.
# Scripted state lives beside the reply queue and is cleared by ``reset()``.

#: Default probe answer. ``script_fine_tuning`` overrides it per test.
_DEFAULT_CAPABILITY = {
    "supported": True,
    "reason": "Scripted endpoint: fine-tuning is available.",
    "base_models": ("scripted-base",),
    "surface": "openai_compatible_v1",
}

_ft_lock = threading.Lock()
_ft_capability: dict = dict(_DEFAULT_CAPABILITY)
_ft_jobs: dict = {}
_ft_uploads: list = []
_ft_status_script: deque = deque()
_ft_counter = [0]


def script_fine_tuning(
    *,
    supported: bool = True,
    reason: str | None = None,
    base_models: tuple = ("scripted-base",),
    statuses: list | None = None,
) -> None:
    """Stage the probe answer and, optionally, a status sequence.

    ``statuses`` is consumed one entry per :func:`scripted_get_fine_tuning_job`
    call, so a test can walk a job from ``queued`` to ``succeeded`` without a
    clock. An entry is either a status string or a ``(status, trained_model)``
    pair.
    """
    with _ft_lock:
        _ft_capability.clear()
        _ft_capability.update({
            "supported": supported,
            "reason": reason or (
                "Scripted endpoint: fine-tuning is available." if supported
                else "Scripted endpoint: this endpoint does not offer fine-tuning."
            ),
            "base_models": tuple(base_models),
            "surface": "openai_compatible_v1" if supported else "",
        })
        _ft_status_script.clear()
        for entry in statuses or []:
            _ft_status_script.append(entry)


def reset_fine_tuning() -> None:
    """Forget every scripted job, upload and staged status."""
    with _ft_lock:
        _ft_capability.clear()
        _ft_capability.update(_DEFAULT_CAPABILITY)
        _ft_jobs.clear()
        _ft_uploads.clear()
        _ft_status_script.clear()
        _ft_counter[0] = 0


def uploaded_training_files() -> list:
    """``[(filename, bytes)]`` for everything "uploaded" since the last reset.

    This is how a test asserts what would have left the install — the rows, the
    scrubbing, the row count — without anything leaving it.
    """
    with _ft_lock:
        return [(name, payload) for name, payload in _ft_uploads]


def scripted_fine_tuning_capabilities(*, probed_at: str = ""):
    from utk_curio.backend.app.agents.providers import FineTuningCapabilities

    if not enabled():
        raise TestingProviderUnavailable(
            "the scripted provider is only available under CURIO_TESTING"
        )
    with _ft_lock:
        state = dict(_ft_capability)
    return FineTuningCapabilities(
        supported=bool(state["supported"]),
        reason=str(state["reason"]),
        base_models=tuple(state["base_models"]),
        surface=str(state["surface"]),
        probed_at=probed_at,
    )


def scripted_upload_training_file(filename: str, content: bytes) -> str:
    if not enabled():
        raise TestingProviderUnavailable(
            "the scripted provider is only available under CURIO_TESTING"
        )
    with _ft_lock:
        _ft_uploads.append((str(filename), bytes(content)))
        return f"file-scripted-{len(_ft_uploads)}"


def _scripted_job(job_id: str, **fields):
    from utk_curio.backend.app.agents.providers import FineTuningJob

    state = dict(_ft_jobs.get(job_id) or {})
    state.update(fields)
    _ft_jobs[job_id] = state
    return FineTuningJob(
        id=job_id,
        status=str(state.get("status") or "queued"),
        raw_status=str(state.get("raw_status") or state.get("status") or "queued"),
        base_model=str(state.get("base_model") or ""),
        trained_model=state.get("trained_model"),
        trained_tokens=state.get("trained_tokens"),
        error=state.get("error"),
    )


def scripted_create_fine_tuning_job(
    *, training_file: str, base_model: str, suffix: str | None = None
):
    if not enabled():
        raise TestingProviderUnavailable(
            "the scripted provider is only available under CURIO_TESTING"
        )
    with _ft_lock:
        _ft_counter[0] += 1
        job_id = f"ftjob-scripted-{_ft_counter[0]}"
        return _scripted_job(
            job_id,
            status="queued",
            raw_status="validating_files",
            base_model=base_model,
            training_file=training_file,
            suffix=suffix,
        )


def scripted_get_fine_tuning_job(job_id: str):
    if not enabled():
        raise TestingProviderUnavailable(
            "the scripted provider is only available under CURIO_TESTING"
        )
    with _ft_lock:
        if job_id not in _ft_jobs:
            from utk_curio.backend.app.agents.providers import FineTuningUnavailable

            raise FineTuningUnavailable(f"Could not read job {job_id}: no such job")
        if _ft_status_script:
            entry = _ft_status_script.popleft()
            status, trained = (
                entry if isinstance(entry, (tuple, list)) else (entry, None)
            )
            fields: dict = {"status": str(status), "raw_status": str(status)}
            if status == "succeeded":
                suffix = _ft_jobs[job_id].get("suffix") or "scripted"
                fields["trained_model"] = trained or (
                    f"ft:{_ft_jobs[job_id].get('base_model') or 'base'}:{suffix}"
                )
                fields["trained_tokens"] = 4321
            return _scripted_job(job_id, **fields)
        return _scripted_job(job_id)


def scripted_cancel_fine_tuning_job(job_id: str):
    if not enabled():
        raise TestingProviderUnavailable(
            "the scripted provider is only available under CURIO_TESTING"
        )
    with _ft_lock:
        state = _ft_jobs.get(job_id) or {}
        if str(state.get("status")) in ("succeeded", "failed", "cancelled"):
            from utk_curio.backend.app.agents.providers import FineTuningUnavailable

            raise FineTuningUnavailable(
                f"Could not cancel job {job_id}: it is already "
                f"{state.get('status')}"
            )
        return _scripted_job(job_id, status="cancelled", raw_status="cancelled")
