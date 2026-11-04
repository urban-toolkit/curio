"""One chat turn on an attachment, answered whole or followed as it streams.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and signature; since B3 both entry points
drive one :class:`turns.turn_loop.AttachmentTurn`. The turn itself is a job of the server
(``turns/turn_jobs.py``): each entry point asks, then waits for the turn or follows it, and a request that
goes away only stops waiting. Sibling modules are reached module-qualified (``agents_<module>.name``) so a
test that patches the owner is seen by every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.application.turns import turn_jobs


def run_attachment(
    user_key: str,
    project_id: str,
    attachment_id: str,
    message: str,
    config: ProviderConfig,
    run_context: str | None = None,
) -> dict:
    """Ask one turn of an attached agent and answer its reply once it ended.

    Session-aware (dev/20): the system turn is the attachment's intent override
    (dev/19) or the resolved instruction prompt, followed by a bounded window of
    the session's prior turns, then the new user message. Both sides of the
    exchange persist to the session file so a reload restores the conversation;
    a provider failure persists the user turn plus a display-only error marker
    (excluded from future context) so history matches what the user saw. The
    turn waits for the attachment's turns asked before it, and its reply
    arrives whole, with the turn's end.
    """
    asked, events = turn_jobs.ask(
        user_key, project_id, attachment_id, message, config, run_context, streaming=False, follow=True,
    )
    return turn_jobs.settled(asked, events)


def stream_attachment(
    user_key: str,
    project_id: str,
    attachment_id: str,
    message: str,
    config: ProviderConfig,
    run_context: str | None = None,
    *,
    ask_id: str | None = None,
):
    """Streaming twin of :func:`run_attachment` (memo dev/22). *ask_id*, from
    the tab that asks, names the ask (``turn_jobs.ask``).

    Validates eagerly (404/422 raise before any streaming starts), then returns
    a generator of the turn's events: ``("execution", {executionId})`` (memo
    dev/37), ``("delta", {text})`` events, ``("usage", {usage})`` interim
    Actual sums once per provider round (memo dev/80), optionally
    ``("content", {parts})`` when the reply carried a valid structured tail
    (memo dev/39), ending in
    ``("done", {reply, executionId, usage, durationMs, content})`` — or
    ``("error", {error})`` on a provider failure. Persistence semantics are
    identical to ``run_attachment``: the full exchange is written once at
    completion; a failure persists the user turn plus a display-only error
    marker. Nothing is persisted per-delta. Leaving the generator only stops
    following: the turn goes on.
    """
    asked, events = turn_jobs.ask(
        user_key, project_id, attachment_id, message, config, run_context, ask_id=ask_id, streaming=True,
        follow=True,
    )
    return turn_jobs.own_events(asked, events)
