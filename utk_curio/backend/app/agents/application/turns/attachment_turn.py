"""One chat turn on an attachment: ``run_attachment`` and its streaming twin.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and signature; since B3 both entry points
drive one :class:`turns.turn_loop.AttachmentTurn`. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.application.turns import turn_loop


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
    turn = turn_loop.AttachmentTurn(
        user_key, project_id, attachment_id, message, config, run_context, streaming=False
    )
    try:
        for _event in turn.rounds():
            pass  # a blocking turn emits nothing
    except Exception as exc:
        turn.settle_error(exc)
        raise AgentServiceError(f"agent run failed: {turn.redacted(exc)}", 502) from exc
    return turn.settle_ok()


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
    turn = turn_loop.AttachmentTurn(
        user_key, project_id, attachment_id, message, config, run_context, streaming=True
    )
    return turn.stream()
