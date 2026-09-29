"""Run policy, execution records, usage accounting, and the bounded attachment context.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import time


#: The output ceiling every agent run is dispatched with.
#:
#: This was ``policy.DEPLOYMENT_MAX_OUTPUT_TOKENS``, the deployment floor of a
#: three-scope resolver (account, per-dataflow, per-attachment) with
#: tighten-only writes and an optimistic revision. All three editors are gone,
#: so no user value can exist to resolve against and the resolver had exactly
#: one input left: this number. Passed to every provider as ``max_tokens``.
DEPLOYMENT_MAX_OUTPUT_TOKENS = 4096


def _run_policy(
    user_key: str,
    project_id: str,
    coord: str,
    spec: dict,
    attachment_record: dict | None = None,
) -> dict:
    """Dispatch inputs for one run.

    This was admission, then a policy resolver, and is now neither. It resolved
    account/template/attachment run ceilings and a budget the ledger gated on
    (all removed: Curio does not meter agent runs), then a three-scope
    ``maxOutputTokens``, whose editor had no interface left to reach it. What
    remains is the deployment-wide output cap and the two keys the ledger
    records so a run can be attributed to a template and an attachment.
    """
    attachment_id = (attachment_record or {}).get("attachmentId")
    max_output = DEPLOYMENT_MAX_OUTPUT_TOKENS
    return {
        "admit": {
            "template_key": f"{project_id}/{coord}",
            "attachment_key": attachment_id if isinstance(attachment_id, str) else None,
        },
        "max_output_tokens": max_output,
        # Pinned on the execution record: what the run was actually dispatched
        # with, so a later change of the constant does not rewrite history.
        "policy_pins": {"maxOutputTokens": max_output},
    }


def _execution_record(
    execution_id: str,
    pins: dict,
    usage: dict,
    started: float,
    status: str,
    tool_calls: list | None = None,
    delegations: list | None = None,
    refused_rounds: int = 0,
    retry_of: str | None = None,
) -> dict:
    """Assemble the per-run execution record persisted on the agent turn.

    ``usage`` is actual token counts or ``None``, never estimated - summed
    across loop rounds when tools ran, which is also when ``toolCalls``
    records what executed. There is no ``costUsd``: Curio ships no price
    table, so a USD figure would be invented. ``delegations`` lists the run's
    child execution records, each with its own pins, usage, and
    ``parentExecutionId`` back-link."""
    record = {
        "executionId": execution_id,
        "pins": pins,
        "usage": dict(usage) if usage else None,
        "durationMs": int((time.monotonic() - started) * 1000),
        "status": status,
    }
    if tool_calls:
        record["toolCalls"] = list(tool_calls)
    if delegations:
        record["delegations"] = list(delegations)
    if refused_rounds:
        # dev/105 D2 (additive): parameter refusals that did NOT spend a round
        # — auditable beside toolCalls[].status so a run that leaned on the
        # free corrections is legible after the fact.
        record["refusedRounds"] = refused_rounds
    if retry_of:
        # dev/115 (DEC-021): a retry after an interruption is a NEW execution
        # linked to the one that expired — nothing was replayed.
        record["retryOf"] = retry_of
    return record


def _add_usage(total: dict, sink: dict) -> None:
    """Sum one provider call's sink into the run's usage total (dev/41 — a
    tool loop makes several calls; the run settles their sum, dev/40). The
    cache counts are summed when a provider reported them."""
    for key in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens"):
        if isinstance(sink.get(key), int):
            total[key] = total.get(key, 0) + sink[key]


# Ephemeral run context (memo dev/44): the client-composed grounded inputs
# (live Trill, node id, subtask, …) framed as one provider message per send.
# Bounded server-side; legacy call sites sent unbounded payloads, this names
# the limit and truncates visibly instead of failing.
CONTEXT_MAX_CHARS = 120_000


_CONTEXT_TRUNCATION_MARKER = "\n…[truncated: context exceeded the run-context bound]"


_CONTEXT_FRAME = "[attachment context — current canvas state]\n"


def _bounded_context(run_context: str | None) -> str | None:
    if not isinstance(run_context, str) or not run_context.strip():
        return None
    if len(run_context) <= CONTEXT_MAX_CHARS:
        return run_context
    return run_context[:CONTEXT_MAX_CHARS] + _CONTEXT_TRUNCATION_MARKER
