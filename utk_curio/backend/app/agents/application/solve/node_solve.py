"""Per-node Solve: the stream and its events.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import time
import uuid

from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.infrastructure import agent_jobs
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import lifecycle as agents_lifecycle
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.solve import rounds as agents_rounds
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import policy as agents_policy
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.execution import workflow_spec
from utk_curio.backend.app.projects import storage as projects_storage


def solve_node_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    *,
    node_id: str,
    exec_fn=None,
):
    """dev/115 (DEC-073, Amendment A2): the per-node Solve — the user's
    explicit ask to run, fix, and re-run ONE node's code from the node's own
    agent (any attachment whose manifest resolves ``node.content.generate``).

    Round 0 executes the node's CURRENT content as-is; corrections run the
    shared loop. A node that already had content lands as a reviewed
    ``node.content.write`` that has already passed (DEC-006 — an existing
    node's content changes only through review); an EMPTY node is written
    directly on PASS; exhaustion mints nothing and says so; a sandbox outage
    says "not verified". Detached like the batch: the request subscribes.

    Eager validation (404/409 stay JSON); the generator yields
    ``solve_node_started`` → the loop's ``generation_round`` /
    ``node_executed`` / ``round_verdict`` → ``done {verdict, rounds,
    attempts, unchanged?, written?, proposalId?, proposalAttachmentId?}``.
    """
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    # DEC-080 (dev/126): as the batch — the per-node Solve resolves the same
    # required delegates.
    if agents_lifecycle._repair_required_closure(
        user_key, project_id, record.get("coord", ""), attachment_id=attachment_id
    ):
        spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
        record = agents_spec_reads._record_or_404(spec, attachment_id)
    if not isinstance(node_id, str) or not node_id:
        raise AgentServiceError("a nodeId is required", 422)
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    if node is None:
        raise AgentServiceError(f"node {node_id!r} not found in the saved spec", 404)
    manifest = agents_catalog._resolve_definition(user_key, record.get("coord", ""))
    resolution = delegation.resolve(
        user_key, project_id, manifest, "node.content.generate"
    ) if manifest is not None else delegation.Resolution("unresolvable")
    if resolution.outcome != "ok":
        raise AgentServiceError(
            "no installed agent declares node.content.generate — install the "
            "Node Content Builder first",
            409,
        )
    agents_session._check_delegate_llms(user_key, project_id, manifest, config, agents_session._delegate_capabilities([node]))
    try:
        agent_jobs.check_can_start(user_key, attachment_id)
    except agent_jobs.JobRefused as exc:
        raise AgentServiceError(str(exc), exc.status)
    execution_id = uuid.uuid4().hex
    # Request-context pieces, resolved before the job thread starts.
    agents_acquire._settle_lake_acquisitions(user_key, project_id)
    base = agents_grounding._solve_grounding_base(user_key, project_id, spec, {node_id: node}, [node_id])
    dataset_paths = agents_grounding._resolve_catalog_execution_paths(project_id, list(base.get("catalog_ids") or {}))
    events = _solve_node_events(
        user_key, project_id, attachment_id, config, spec, node, resolution,
        record.get("coord", ""), record.get("sessionId"), execution_id, exec_fn,
        manifest=manifest, grounding_base=base, dataset_paths=dataset_paths,
        catalog_rows=agents_grounding._catalog_rows_for_discovery(user_key, project_id),
        templates=agents_roster._roster_templates(user_key, project_id),
        acting_user=agents_spec_reads._acting_user(),
    )
    job = agent_jobs.start_job(
        user_key=user_key, project_id=project_id, attachment_id=attachment_id,
        kind="solve-node", job_id=execution_id, events=events,
        redact_values={"llm-api-key": config.api_key},
    )
    return agent_jobs.subscribe(job)


def _solve_node_events(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    spec: dict,
    node: dict,
    resolution,
    coord: str,
    session_id,
    execution_id: str,
    exec_fn,
    *,
    manifest,
    grounding_base: dict,
    dataset_paths: dict,
    templates: dict | None = None,
    catalog_rows: list | None = None,
    acting_user=None,
):
    """The per-node Solve body (dev/115 A2) over the ONE verified loop."""
    node_id = node.get("id")
    label = (node.get("goal") or node_id)[:60]
    started = time.monotonic()
    had_content = bool(str(node.get("content") or "").strip())
    yield "solve_node_started", {
        "nodeId": node_id, "executionId": execution_id, "hasContent": had_content,
    }

    kind = workflow_spec.content_kind(str(node.get("type") or ""), templates)
    # dev/134: a DOCUMENT kind (Vega-Lite, an AUTK grammar) goes through the
    # SAME loop as code — the runner reports "not executable" and dev/129's
    # validator decides whether the document is written. The per-node Solve used
    # to refuse these outright, which left the batch's unguarded write path as
    # the only way to fill such a node.
    if kind not in (workflow_spec.CONTENT_KIND_CODE, workflow_spec.CONTENT_KIND_GRAMMAR):
        # dev/118 (DEC-075) → dev/119 → dev/134: a kind that authors nothing at
        # all (a merge, a pool, a simple view, a spatial join) or presentation
        # content with no validator. No round, no sandbox, no generation —
        # nothing this loop could verify; say so and change nothing.
        outcome = _not_executable_outcome(node, label, kind)
    else:
        outcome = yield from _run_node_loop(
            user_key, project_id, attachment_id, config, spec, node, resolution, coord, session_id,
            execution_id, exec_fn, manifest=manifest, grounding_base=grounding_base,
            dataset_paths=dataset_paths, catalog_rows=catalog_rows, acting_user=acting_user,
        )
    verdict = outcome["verdict"]
    attempts = outcome["attempts"]
    rounds = outcome["rounds"]
    done: dict = {"nodeId": node_id, "verdict": verdict, "rounds": rounds,
                  "attempts": attempts, "evidence": outcome["evidence"]}
    trail_lines = _trail_lines(attempts)
    text, card_kind, parts = _conclude(
        user_key, project_id, attachment_id, session_id, spec, node, label, had_content,
        grounding_base, outcome, done,
    )
    card = {
        "type": "card", "kind": card_kind,
        "title": f"Solve · {verdict.upper()} after {rounds} round{'s' if rounds != 1 else ''}",
        "lines": trail_lines[:10],
    }
    if verdict != "pass" and attempts:
        # dev/127: the trail itself, with the code each attempt ran — in THIS
        # chat, durably, not only in the transient row above.
        trail_part = agents_rounds._solve_attempts_part(
            spec, node_id, str(node.get("goal") or node_id)[:120],
            {"attempts": attempts, "rounds": rounds, "verdict": verdict,
             "stoppedBy": outcome.get("stoppedBy")},
        )
        if trail_part is not None:
            parts.append(trail_part)
    if isinstance(session_id, str):
        _append_solve_turn(user_key, project_id, attachment_id, session_id, coord, config, execution_id,
                           started, text, card_kind, card, parts, outcome, verdict)
    yield "done", done


def _not_executable_outcome(node: dict, label: str, kind: str) -> dict:
    """dev/118 (DEC-075) → dev/119 → dev/134: a kind that authors nothing at all (a merge, a pool,
    a simple view, a spatial join) or presentation content with no validator. No round, no
    sandbox, no generation — nothing this loop could verify; say so and change nothing."""
    reason = (
        f"{label!r} ({node.get('type')}) is wired, not written — this kind has no "
        "content to author; it renders or forwards its input"
        if kind == workflow_spec.CONTENT_KIND_NONE else
        f"{label!r} ({node.get('type')}) has no code the sandbox could run — it works "
        "in the browser or through its own service; Play the dataflow to see it"
    )
    outcome = {
        "verdict": "not-executable",
        "evidence": {"kind": "not-executable", "detail": reason},
        "rounds": 0, "candidate": "", "delegations": [],
        "roundsTrace": [f"not executable — {reason}"], "attempts": [],
    }
    return outcome


def _run_node_loop(
    user_key, project_id, attachment_id, config, spec, node, resolution, coord, session_id,
    execution_id, exec_fn, *, manifest, grounding_base, dataset_paths, catalog_rows, acting_user,
):
    """The per-node Solve's rounds: the ONE verified-content loop, started from the node's current
    content, with the traced delegate runner (the trace lands in this node's own home)."""
    node_id = node.get("id")

    def _traced(delegate_inputs):
        st, tx, ch, _h = agents_delegates._run_delegate_traced(
            user_key, project_id, resolution.coord,
            "node.content.generate", delegate_inputs, config,
            parent_execution_id=execution_id,
            parent_coord=coord,
            attachment_id=attachment_id,
            node_id=node_id,
            home_create=False,
        )
        return st, tx, ch

    outcome = yield from agents_rounds._verified_content_rounds(
        user_key, project_id,
        spec=spec, node=node, resolution=resolution, config=config,
        parent_execution_id=execution_id, parent_coord=coord,
        attachment_id=attachment_id, exec_fn=exec_fn,
        grounding_loop_ctx={"granted": [], "manifest": manifest,
                            "attachment_id": attachment_id, "session_id": session_id},
        grounding_base=grounding_base,
        start_from_current=True,
        delegate_runner=_traced,
        # dev/132 (closes dev/131 F4): topped up for a dataset that
        # arrived after this job started — the per-pill Solve and the
        # Finder's own delegation both come through here.
        dataset_paths_fn=lambda codes: agents_grounding._session_dataset_paths(
            project_id, acting_user, dataset_paths, codes
        ),
        # dev/133: an empty result is a failed round here too — the
        # per-node Solve is where the owner presses "solve this node".
        result_summary_fn=agents_session._artifact_summary_fn(),
        exec_user_key=user_key,
        secrets_fn=agents_grounding._exec_secrets_resolver(user_key),
        resolve_source=agents_grounding._source_resolver(
            user_key, project_id, coord=coord, attachment_id=attachment_id,
            execution_id=execution_id, config=config, manifest=manifest,
            extra_texts=(str((spec.get("dataflow") or {}).get("task") or ""),),
            catalog_rows=catalog_rows,
        ),
    )
    return outcome


def _trail_lines(attempts: list) -> list[str]:
    """One line per attempt (the first eight): round, verdict, kind, and why."""
    trail_lines = []
    for attempt in attempts[:8]:
        why = agents_rounds._attempt_why(attempt, limit=160)
        line = f"round {attempt.get('round')} · {attempt.get('verdict')} · {attempt.get('kind')}"
        if attempt.get("verdict") == "pass":
            line += f" · {attempt.get('outputDataType') or '?'}"
        elif why:
            line += f" — {why}"
        if attempt.get("verdict") != "pass" and attempt.get("endpointEvidence"):
            line += f" · endpoint: {str(attempt['endpointEvidence'])[:200]}"
        trail_lines.append(line)
    return trail_lines


def _write_empty_node(user_key, project_id, node_id, candidate: str) -> bool:
    """An empty node (a plan placeholder solved from its own agent) is written directly on PASS —
    parity with the Dataflow Builder's Solve; a node that gained content meanwhile is left alone."""
    try:
        fresh = agents_spec_reads._read_spec_or_404(user_key, project_id)
        target = next(
            (n for n in (fresh.get("dataflow") or {}).get("nodes") or []
             if isinstance(n, dict) and n.get("id") == node_id), None,
        )
        if target is not None and not str(target.get("content") or "").strip():
            target["content"] = candidate
            projects_storage.write_spec(user_key, project_id, fresh)
            return True
    except Exception:
        return False
    return False


def _conclude(user_key, project_id, attachment_id, session_id, spec, node, label, had_content,
              grounding_base, outcome: dict, done: dict) -> tuple[str, str, list]:
    """What the per-node Solve says and shows for its verdict: the text, the card kind and the
    content parts (the minted review when PASS proposes; the caller adds the attempt trail).
    Writes the verdict-specific fields (unchanged, written, proposal ids, remedy) into *done*."""
    node_id = node.get("id")
    verdict = outcome["verdict"]
    attempts = outcome["attempts"]
    rounds = outcome["rounds"]
    unchanged = (
        verdict == "pass" and rounds == 1 and attempts
        and attempts[0].get("source") == "current content"
    )
    parts: list = []
    if verdict == "pass" and unchanged:
        text = f"Verified {label!r}: its current code ran successfully — no change needed."
        done["unchanged"] = True
        card_kind = "result"
    elif verdict == "pass" and not had_content:
        # An empty node (a plan placeholder solved from its own agent) is
        # written directly on PASS — parity with the Dataflow Builder's Solve.
        written = _write_empty_node(user_key, project_id, node_id, outcome["candidate"])
        done["written"] = written
        text = (
            f"Solved {label!r}: the code ran successfully after {rounds} round"
            f"{'s' if rounds != 1 else ''} and was written to the node."
            if written else
            f"Solved {label!r}: the code ran successfully, but the node gained content meanwhile — nothing written."
        )
        card_kind = "result"
    elif verdict == "pass":
        part, home_att, _mint_text = agents_delegates._mint_content_review_from_delegate(
            user_key, project_id,
            node_id=node_id,
            generated_text=outcome["candidate"],
            parent_attachment_id=attachment_id,
            parent_session_id=session_id,
            local_turn=False,
            validation={"verdict": verdict, "rounds": rounds,
                        "evidence": outcome["evidence"], "attempts": attempts},
            grounding_base=grounding_base,
        )
        if part is not None:
            done["proposalId"] = part["proposalId"]
            done["proposalAttachmentId"] = home_att
            if home_att == attachment_id:
                parts.append(part)
            text = (
                f"Solved {label!r}: the corrected code ran successfully after {rounds} "
                f"round{'s' if rounds != 1 else ''} — review and apply it below."
            )
        else:
            text = f"Solved {label!r} but the review could not be minted — nothing was changed."
        card_kind = "result"
    elif verdict == "infrastructure":
        text = (
            f"Not verified: the sandbox was unreachable while solving {label!r} — "
            "nothing was run, corrected, or written. Retry when it is back."
        )
        card_kind = "error"
    elif verdict == "not-executable":
        # dev/129: a document that validated says so; one that nothing could
        # check says THAT, and is not written.
        doc_evidence = outcome.get("evidence") or {}
        if doc_evidence.get("documentValidated"):
            text = (
                f"Validated {label!r}: its {doc_evidence['documentValidated']} document is valid "
                "and was written — the sandbox cannot run this kind, so it was not executed; "
                "Play the dataflow to see it render."
            )
        elif doc_evidence.get("documentUnchecked") and not doc_evidence.get("documentPassive"):
            text = (
                f"Wrote nothing for {label!r}: {str(doc_evidence['documentUnchecked'])[:200]}. "
                "Nothing unchecked is put into a node."
            )
        else:
            text = (
                f"Not executable: {label!r} has no code the sandbox could run — it works in the "
                "browser or through its own service. Play the dataflow to see it. Nothing was changed."
            )
        card_kind = "result"
    elif verdict == "awaiting-source":
        # dev/126: the source is with the user. Nothing was generated or
        # written; the node's own Dataset Finder holds the candidates.
        evidence = outcome.get("evidence") or {}
        remedy_payload = evidence.get("remedy")
        if isinstance(remedy_payload, dict):
            done["remedy"] = remedy_payload
        text = (
            f"Awaiting a source for {label!r}: {evidence.get('detail') or 'a dataset must be selected'} "
            "— open Dataset Finder on this node, select the source and confirm, then Solve "
            "again. Nothing was generated or written."
        )
        card_kind = "result"
    elif (outcome.get("evidence") or {}).get("upstreamEmpty"):
        text = (
            f"Not verified: {(outcome.get('evidence') or {}).get('detail') or 'an upstream node has no content yet'} "
            f"— {label!r} waits for it; solve or fill that node, then Solve this one again. Nothing was changed."
        )
        card_kind = "result"
    else:
        text = (
            f"Not fixed after {rounds} attempt{'s' if rounds != 1 else ''}"
            f"{agents_rounds._stopped_by_clause(outcome.get('stoppedBy'))}: {label!r} still "
            "fails — every attempt is listed below with the code it ran; nothing was written."
        )
        remedy_payload = (outcome.get("evidence") or {}).get("remedy")
        if isinstance(remedy_payload, dict):
            done["remedy"] = remedy_payload
            text += agents_grounding._source_missing_remedy(remedy_payload).replace(" — ", " ", 1).capitalize() + "."
        card_kind = "error"
    return text, card_kind, parts


def _append_solve_turn(user_key, project_id, attachment_id, session_id, coord, config, execution_id,
                       started, text, card_kind, card, parts, outcome, verdict) -> None:
    """The agent turn that carries the verdict, the card and the parts, with the execution record."""
    try:
        sessions.append_turns(
            user_key, project_id, session_id, attachment_id,
            [sessions.make_turn(
                "agent", text, error=(card_kind == "error"),
                content=[card, *parts],
                execution=agents_policy._execution_record(
                    execution_id,
                    {"coord": coord, "provider": getattr(config, "api_type", None),
                     "model": getattr(config, "model", None), "tools": [], "intentEdited": False},
                    {}, started, "ok" if verdict in ("pass", "not-executable") else "error",
                    delegations=[c for c in outcome["delegations"] if c is not None],
                ),
            )],
        )
    except Exception:
        pass
