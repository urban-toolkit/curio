"""The user's dataset selection on a candidates card, and the fetch it delegates through Solve (memo dev/132).

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.infrastructure import egress
from utk_curio.backend.app.agents.infrastructure import provider_config
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import dataset_resolution as agents_dataset_resolution
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import node_solve as agents_node_solve
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.agents.infrastructure import agent_jobs as agents_agent_jobs
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)


def record_dataset_selection(
    user_key: str, project_id: str, attachment_id: str, picks: object,
    guest: bool = False,
) -> dict:
    """dev/126: record the user's confirmed dataset selection for a node.

    The picks are ``{lane, key}`` pairs — a catalog row's ``datasetId`` or an
    external row's ``url`` — resolved against the LATEST ``datasetCandidates``
    part persisted in this attachment's own session. The client therefore sends
    identifiers only: a source the runtime never proposed (and never probed)
    cannot enter through this endpoint. External picks are re-probed at
    confirmation time through the ``DEC-053`` chokepoint, and the verdict is
    what the record keeps — an unreachable pick does not resolve the node.
    """

    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    if record.get("coord", "").split("@", 1)[0] != agents_dataset_resolution.FINDER_AGENT_ID:
        raise AgentServiceError(
            "a dataset selection belongs to a Dataset Finder attachment", 400
        )
    target = record.get("target") or {}
    if target.get("kind") != "node":
        raise AgentServiceError(
            "a dataset selection belongs to a Dataset Finder attached to a node", 400
        )
    session_id = record.get("sessionId")
    turns = (
        sessions.read_turns(user_key, project_id, session_id)
        if isinstance(session_id, str) else []
    )
    part = next(
        (
            p for turn in reversed(turns) for p in (turn.get("content") or [])
            if isinstance(p, dict) and p.get("type") == "datasetCandidates"
        ),
        None,
    )
    try:
        rows = agents_dataset_resolution.resolve_picks(
            part, picks,
            # dev/132: the Data Catalog listing, so a dataset the user just
            # imported from the card's download steps can be confirmed — the
            # card predates the file.
            catalog_rows=agents_grounding._catalog_rows_for_discovery(user_key, project_id),
        )
    except agents_dataset_resolution.DatasetResolutionError as exc:
        raise AgentServiceError(str(exc), 422) from exc
    # Re-probe the external picks: the card may be minutes or days old, and the
    # record must carry what is true NOW (the row keeps its own mint-time
    # verdict in the transcript either way).
    budget = egress.CallBudget(agents_budgets._RUN_EGRESS_CALLS)
    roster = agents_roster._LazyRoster()
    for row in rows:
        if row["lane"] != "external":
            continue
        if row.get("url"):
            row["verification"] = verify.verify_external_source(row["url"], budget=budget)
            # dev/132: and what can be DONE with it now — the card's verdict
            # may be days old, and the delegation below depends on this one.
            agents_mint._mint_row_access(row)
        agents_acquire._mint_row_acquirable(row, roster)
    # A row Curio can download is downloaded now, by the Data Lake, and
    # recorded as the catalog pick it becomes.
    acquisitions = agents_acquire._acquire_confirmed_picks(rows)
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = agents_spec_reads._read_spec_or_404(user_key, project_id)
        state = agents_dataset_resolution.record_selection(fresh, attachment_id, rows)
        if state is None:
            raise AgentServiceError(f"attachment {attachment_id!r} not found", 404)
        projects_storage.write_spec(user_key, project_id, fresh)
    if isinstance(session_id, str):
        try:
            names = ", ".join(str(r.get("name") or r.get("datasetId") or r.get("url")) for r in rows)
            lines = [
                f"{r['lane']} · {r.get('name') or r.get('datasetId') or r.get('url')}"
                + (f" · {(r.get('verification') or {}).get('status')}"
                   if r["lane"] == "external" else
                   " · downloading" if r.get("acquiring") else
                   (" · installed" if r.get("installed") else " · not installed yet"))
                for r in rows[:8]
            ]
            sessions.append_turns(
                user_key, project_id, session_id, attachment_id,
                [sessions.make_turn(
                    "agent",
                    f"Source recorded for this node: {names}."
                    + (" It is downloading into the Data Catalog; Solve the node "
                       "once it lands."
                       if any(r.get("acquiring") for r in rows) else
                       " The dataset must be installed from the Data Catalog before "
                       "Solve can load it."
                       if state["status"] == agents_dataset_resolution.STATE_AWAITING_INSTALL else
                       " Solve the node to build its loader from this source."
                       if state["status"] == agents_dataset_resolution.STATE_RESOLVED else
                       " Nothing selectable was confirmed — the runtime could not reach it."),
                    content=[{
                        "type": "card",
                        "kind": "result" if state["status"] != agents_dataset_resolution.STATE_CANDIDATES_PENDING
                        else "error",
                        "title": "Dataset selection recorded",
                        "lines": lines,
                    }],
                )],
            )
        except Exception:  # noqa: BLE001
            log.warning("Could not log the dataset selection for %s", attachment_id,
                        exc_info=True)
    payload = {
        "attachmentId": attachment_id,
        "nodeId": target.get("targetId"),
        "status": state["status"],
        "picks": rows,
    }
    # dev/132 (R1): a confirmed row code can FETCH is handed to the node's own
    # builder automatically — the owner asked for the delegation, not for a
    # prompt they must compose. A manual row is not delegated: its file does
    # not exist yet, and its card teaches the download and offers Import.
    if acquisitions:
        payload["acquisitions"] = acquisitions
    delegated = _delegate_confirmed_fetch(
        user_key, project_id, str(target.get("targetId") or ""), rows, state, guest=guest,
    ) or agents_acquire._acquisition_outcome(acquisitions)
    if delegated is not None:
        payload["delegated"] = delegated
    return payload


#: dev/132: the two rows worth delegating a fetch for — an external row the
#: probe could read, and a catalog row already installed (its path exists).
#: A row Curio downloads is never one: it becomes a catalog pick instead.
def _fetchable_picks(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if row.get("lane") == "external" and row.get("acquirable"):
            continue
        if row.get("lane") == "external" and row.get("access") == verify.ACCESS_FETCHABLE:
            out.append(row)
        elif row.get("lane") == "catalog" and (row.get("installed") or row.get("imported")):
            out.append(row)
    return out


def _delegate_confirmed_fetch(
    user_key: str,
    project_id: str,
    node_id: str,
    rows: list[dict],
    state: dict,
    *,
    guest: bool = False,
) -> dict | None:
    """dev/132 (R1): start the node's own builder on the confirmed source.

    The owner's instruction — *"The datafinder should be able to automatically
    delegate the code to fetch external api datasets"* — closes `DEC-047`'s
    manual seam: the Finder no longer composes a prompt for the user to send.
    Nothing here authors anything itself: it starts the SAME detached per-node
    Solve the user's own button starts (dev/115, `DEC-073`), which reads the
    recorded source (dev/126), verifies before writing (dev/129) and lands
    reviewed content for a node that already has some (`DEC-006`).

    Returns what happened — ``delegating`` with the job's execution id,
    ``session-running`` when dev/131's session will pick the node up on its
    next pass (its record just moved, which is exactly its trigger),
    ``manual-download`` when the file is still on a portal, or a reason —
    never raising: a selection is recorded whether or not a build can start.

    The build runs on the BUILDER's LLM configuration, resolved once it is
    picked: the selection was posted to the Dataset Finder, whose choice in AI
    Settings says nothing about what builds the node.
    """

    if not node_id or state.get("status") != agents_dataset_resolution.STATE_RESOLVED:
        return None
    fetchable = _fetchable_picks(rows)
    if not fetchable:
        manual = [
            r for r in rows
            if (r or {}).get("access") == verify.ACCESS_MANUAL and not (r or {}).get("acquirable")
        ]
        if manual:
            return {
                "status": "manual-download",
                "reason": (
                    "this source is a portal download — follow the steps on the "
                    "card and use Import dataset; solving continues from the "
                    "imported dataset"
                ),
            }
        return None
    try:
        spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    except AgentServiceError:
        return None
    # A running dataflow session owns this node: dev/131 re-reads the spec each
    # pass and this record IS the change it watches for. Two builders on one
    # node would race for its content.
    for record in attachments.list_attachments(spec):
        job = agents_agent_jobs.live_job(user_key, str(record.get("attachmentId") or ""))
        if job is not None and job.kind == "solve-batch":
            return {
                "status": "session-running",
                "reason": "the running Solve session picks this node up on its next pass",
            }
    builder = None
    for agent_id in agents_plans._NODE_BUILD_AGENTS:
        builder = agents_spec_reads._node_attachment_of(spec, agent_id, node_id)
        if builder is not None:
            break
    if builder is None:
        return {
            "status": "no-builder",
            "reason": (
                "no builder is attached to this node — Solve the node, or attach "
                "a Node Builder to it"
            ),
        }
    builder_id = str(builder.get("attachmentId") or "")
    builder_coord = str(builder.get("coord") or "")
    builder_manifest = agents_catalog._resolve_definition(user_key, builder_coord)
    builder_name = getattr(builder_manifest, "name", None) or builder_coord.split("@", 1)[0]
    try:
        config = provider_config.resolve_llm(user_key, builder_coord.split("@", 1)[0], guest=guest)
        subscription = agents_node_solve.solve_node_stream(
            user_key, project_id, builder_id, config, node_id=node_id,
        )
    except provider_config.ProviderConfigError as exc:
        return {"status": "skipped", "reason": f"the node's {builder_name} cannot start: {exc}"}
    except AgentServiceError as exc:
        return {"status": "skipped", "reason": str(exc)}
    except Exception:  # noqa: BLE001 — a selection is recorded regardless
        log.warning("Could not delegate the fetch for node %s", node_id, exc_info=True)
        return {"status": "skipped", "reason": "the build could not be started"}
    job = agents_agent_jobs.live_job(user_key, builder_id)
    del subscription  # the job is detached; the client re-attaches to it
    return {
        "status": "delegating",
        "attachmentId": builder_id,
        "nodeId": node_id,
        "sources": [
            str(r.get("name") or r.get("datasetId") or r.get("url") or "")[:120]
            for r in fetchable[:8]
        ],
        **({"executionId": job.job_id} if job is not None else {}),
    }
