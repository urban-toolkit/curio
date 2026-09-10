"""A data-loading node's source: the state machine and the discovery it starts.

Memo dev/126. Resolving a data-loading node used to end one of two ways when
nothing grounded its source: the DEC-072 gate refused a fabricated path
(``ungrounded-source``), or the content builder declined and the decline was
terminal (``source-missing``, dev/115). Both failures ended in a sentence
asking the USER to attach the Dataset Finder and drive it by hand — a remedy
the runtime can take itself, since it already holds the tool-less discovery
delegate, the catalog listing that grounds its catalog lane, and the
runtime-minted two-lane candidates part with real verification verdicts.

So resolution INITIATES discovery. The rule, in one place:

- a node whose source is already grounded (a path the user typed, a dataset in
  the project's Data Catalog, a URL verified in this conversation, an explicit
  synthetic request) needs no discovery — the skip is RECORDED with the literal
  that grounded it, so "always initiated" stays auditable instead of assumed,
  and the record never suppresses a later discovery;
- a node whose ROUND failed for its source anyway — the gate refused a
  fabricated literal, or the content builder declined — is unresolved by
  evidence, and discovery is initiated then, with the attempt trail kept;
- a node with candidates already awaiting the user is ``candidates-pending``:
  no second delegation, no duplicate card, no model call;
- a node whose confirmed catalog pick is not installed yet is
  ``awaiting-install`` — the reviewed ``dataset.install`` lane owns that step;
- anything else is ``unresolved``, and ``initiate`` runs one ``dataset.discover``
  delegation whose candidates land in that node's OWN Dataset Finder chat.

State lives on the node's Dataset Finder attachment record (``DEC-040`` —
graph-backed), which is a backend-owned section of the spec, so a canvas save
cannot wipe it and deleting the node prunes it. The selection is recorded from
the runtime's own persisted candidate rows: a client sends KEYS, never a source.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

FINDER_AGENT_ID = "agent.dataset-finder"

#: The record's home on the attachment (memo dev/126).
RECORD_KEY = "datasetSource"

STATE_RESOLVED = "resolved"
STATE_UNRESOLVED = "unresolved"
STATE_CANDIDATES_PENDING = "candidates-pending"
STATE_AWAITING_INSTALL = "awaiting-install"

#: Recorded when discovery was NOT needed, with the literal that grounded the
#: node instead. Informational only — it never suppresses a later discovery,
#: because the evidence that grounded the node once (a non-empty Data Catalog,
#: a path in the goal) can turn out not to ground the code the builder writes.
STATE_NOT_NEEDED = "not-needed"

#: Rows a selection may carry (a lane's rows are already bounded at parse).
MAX_PICKS = 8

_LANES = ("catalog", "external")


class DatasetResolutionError(ValueError):
    """A selection that does not resolve against the runtime's own rows."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── the record ───────────────────────────────────────────────────────────────


def finder_attachment(spec: dict | None, node_id: str) -> dict | None:
    """The node's own Dataset Finder attachment record, or None."""
    from utk_curio.backend.app.agents import attachments

    for record in attachments.list_attachments(spec):
        target = record.get("target") or {}
        if (
            record.get("coord", "").split("@", 1)[0] == FINDER_AGENT_ID
            and target.get("kind") == "node"
            and target.get("targetId") == node_id
        ):
            return record
    return None


def source_record(spec: dict | None, node_id: str) -> dict | None:
    """The node's recorded source state, or None when discovery never ran."""
    record = finder_attachment(spec, node_id) or {}
    value = record.get(RECORD_KEY)
    return value if isinstance(value, dict) else None


def node_source_state(
    spec: dict | None,
    node_id: str,
    *,
    grounded_literal: str | None = None,
    project_literal: str | None = None,
) -> dict:
    """The node's source state — the ONE reading of it (memo dev/126).

    Two kinds of grounding evidence, deliberately ranked (the caller owns
    grounding; this module owns the state):

    - ``grounded_literal`` is about THIS node — a path or dataset id in its own
      intent, a URL verified for it, an explicit synthetic request. It wins
      over a pending card, because the user has since said what to load and
      should not be stuck answering a card they have overtaken.
    - ``project_literal`` is about the PROJECT — "the Data Catalog holds N
      datasets", which may or may not cover this node. It grounds a first
      attempt (the content child is handed those rows and the ``DEC-072`` gate
      enforces them), but it loses to a pending card: once candidates are
      waiting, re-generating against the whole catalog is not progress.

    Returns ``{state, attachmentId, detail}``.
    """
    attachment = finder_attachment(spec, node_id) or {}
    attachment_id = attachment.get("attachmentId")
    record = attachment.get(RECORD_KEY)
    record = record if isinstance(record, dict) else {}
    status = record.get("status")
    if status == STATE_RESOLVED:
        return {"state": STATE_RESOLVED, "attachmentId": attachment_id,
                "detail": _picks_detail(record)}
    if grounded_literal:
        return {"state": STATE_RESOLVED, "attachmentId": attachment_id,
                "detail": f"{grounded_literal} already grounds this node"}
    if status in (STATE_CANDIDATES_PENDING, STATE_AWAITING_INSTALL):
        return {"state": status, "attachmentId": attachment_id,
                "detail": _pending_detail(record, status)}
    if project_literal:
        return {"state": STATE_RESOLVED, "attachmentId": attachment_id,
                "detail": f"{project_literal} may cover this node"}
    return {"state": STATE_UNRESOLVED, "attachmentId": attachment_id, "detail": ""}


def _picks_detail(record: dict) -> str:
    picks = record.get("picks") or []
    names = [str(p.get("name") or p.get("datasetId") or p.get("url")) for p in picks]
    return ", ".join(n for n in names if n)[:200]


def _pending_detail(record: dict, status: str) -> str:
    if status == STATE_AWAITING_INSTALL:
        return f"{_picks_detail(record)} — waiting for the reviewed install"
    count = record.get("candidates")
    if isinstance(count, int) and count > 0:
        return f"{count} candidate(s) awaiting your selection"
    return "candidates awaiting your selection"


def mark_candidates_pending(spec: dict, attachment_id: str, *, count: int) -> dict | None:
    """Record that candidates were minted for this node's Dataset Finder."""
    from utk_curio.backend.app.agents import attachments

    record = attachments.get_attachment(spec, attachment_id)
    if record is None:
        return None
    record[RECORD_KEY] = {
        "status": STATE_CANDIDATES_PENDING,
        "candidates": int(count),
        "proposedAt": _now(),
    }
    record["revision"] = int(record.get("revision", 1)) + 1
    return record[RECORD_KEY]


def mark_skipped(spec: dict, attachment_id: str, *, literal: str) -> dict | None:
    """Record that discovery was skipped because the source is already
    grounded — the audit trail behind "always initiated"."""
    from utk_curio.backend.app.agents import attachments

    record = attachments.get_attachment(spec, attachment_id)
    if record is None:
        return None
    current = record.get(RECORD_KEY)
    written = {
        "status": STATE_NOT_NEEDED,
        "skippedBecause": literal[:200],
        "recordedAt": _now(),
    }
    if (
        isinstance(current, dict)
        and current.get("status") == STATE_NOT_NEEDED
        and current.get("skippedBecause") == written["skippedBecause"]
    ):
        return None  # nothing changed: no write, no revision bump
    record[RECORD_KEY] = written
    record["revision"] = int(record.get("revision", 1)) + 1
    return written


def resolve_picks(part: dict | None, picks: object) -> list[dict]:
    """Resolve client-supplied ``{lane, key}`` picks against the runtime's OWN
    candidate rows (the persisted ``datasetCandidates`` part).

    The key is a catalog row's ``datasetId`` or an external row's ``url`` — the
    client never sends a name, path or URL of its own, so a selection cannot
    introduce a source the runtime did not propose and probe. Raises
    ``DatasetResolutionError`` naming the first key that does not resolve.
    """
    if not isinstance(part, dict) or not isinstance(part.get("lanes"), dict):
        raise DatasetResolutionError(
            "there are no dataset candidates on this node to select from"
        )
    if not isinstance(picks, list) or not picks:
        raise DatasetResolutionError("picks must be a non-empty list")
    if len(picks) > MAX_PICKS:
        raise DatasetResolutionError(f"at most {MAX_PICKS} picks may be confirmed at once")
    lanes = part["lanes"]
    resolved: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for pick in picks:
        if not isinstance(pick, dict):
            raise DatasetResolutionError("each pick must be an object")
        lane = pick.get("lane")
        key = pick.get("key")
        if lane not in _LANES or not isinstance(key, str) or not key.strip():
            raise DatasetResolutionError(
                f"each pick needs a lane ({' or '.join(_LANES)}) and a key, got {pick!r}"
            )
        rows = lanes.get(lane) or []
        field = "datasetId" if lane == "catalog" else "url"
        row = next(
            (r for r in rows if isinstance(r, dict) and str(r.get(field) or "") == key.strip()),
            None,
        )
        if row is None:
            raise DatasetResolutionError(
                f"{key!r} is not a {lane} candidate on this node — select a row the "
                "Dataset Finder proposed"
            )
        if (lane, key) in seen:
            continue
        seen.add((lane, key))
        resolved.append({"lane": lane, **row})
    return resolved


def record_selection(spec: dict, attachment_id: str, rows: list[dict]) -> dict | None:
    """Record the confirmed selection on the node's Dataset Finder attachment.

    A catalog pick that is not installed yet leaves the node
    ``awaiting-install`` — the reviewed ``dataset.install`` lane owns that
    step; an external pick the runtime could not reach is recorded WITH its
    verdict and does not resolve the node (the card says why).
    """
    from utk_curio.backend.app.agents import attachments

    record = attachments.get_attachment(spec, attachment_id)
    if record is None:
        return None
    needs_install = [
        r for r in rows if r["lane"] == "catalog" and not r.get("installed")
    ]
    unreachable = [
        r for r in rows
        if r["lane"] == "external" and (r.get("verification") or {}).get("status") == "unreachable"
    ]
    if unreachable and len(unreachable) == len(rows):
        status = STATE_CANDIDATES_PENDING  # nothing usable was confirmed
    elif needs_install:
        status = STATE_AWAITING_INSTALL
    else:
        status = STATE_RESOLVED
    record[RECORD_KEY] = {
        "status": status,
        "picks": rows,
        "recordedAt": _now(),
    }
    record["revision"] = int(record.get("revision", 1)) + 1
    return record[RECORD_KEY]


def mark_dataset_installed(spec: dict, dataset_id: str) -> list[str]:
    """An applied ``dataset.install`` resolves every node awaiting exactly that
    dataset. Returns the attachment ids whose state changed."""
    from utk_curio.backend.app.agents import attachments

    changed: list[str] = []
    for record in attachments.list_attachments(spec):
        if record.get("coord", "").split("@", 1)[0] != FINDER_AGENT_ID:
            continue
        state = record.get(RECORD_KEY)
        if not isinstance(state, dict) or state.get("status") != STATE_AWAITING_INSTALL:
            continue
        picks = state.get("picks") or []
        if not any(str(p.get("datasetId") or "") == str(dataset_id) for p in picks):
            continue
        for pick in picks:
            if str(pick.get("datasetId") or "") == str(dataset_id):
                pick["installed"] = True
        if all(p.get("installed") for p in picks if p.get("lane") == "catalog"):
            state["status"] = STATE_RESOLVED
            state["recordedAt"] = _now()
            record["revision"] = int(record.get("revision", 1)) + 1
            changed.append(record.get("attachmentId"))
    return changed


def confirmed_source(spec: dict | None, node_id: str) -> dict | None:
    """The confirmed source a content delegate is HANDED for this node, or
    None. Shape mirrors the candidate rows the user actually confirmed."""
    record = source_record(spec, node_id)
    if not isinstance(record, dict) or record.get("status") != STATE_RESOLVED:
        return None
    picks = record.get("picks") or []
    if not picks:
        return None
    return {
        "note": (
            "The user confirmed these sources for this node. Load ONLY these: a "
            "catalog row through curio_dataset_path(\"<datasetId>\"), an external "
            "row from its exact url."
        ),
        "picks": [
            {k: v for k, v in pick.items() if k in
             ("lane", "name", "datasetId", "url", "format", "requirement", "installed",
              "verification")}
            for pick in picks
        ],
    }


# ── initiation ───────────────────────────────────────────────────────────────


def initiate(
    user_key: str,
    project_id: str,
    node: dict,
    *,
    config,
    parent_manifest,
    parent_coord: str,
    parent_execution_id: str,
    parent_attachment_id: str | None = None,
    mission: str | None = None,
    catalog_rows: list | None = None,
) -> dict:
    """Run ONE ``dataset.discover`` delegation for *node* and leave its
    candidates awaiting the user in that node's own Dataset Finder chat.

    Server-initiated: the model does not choose this, which is why the Dataset
    Finder is a declared hard dependency of both composites (``DEC-068``'s
    criterion, memo dev/126 §A). Every piece is the existing one — the node's
    attachment comes from the plan-apply helper, the delegate's catalog input
    and reply schema from the ``DEC-063`` enrichment, the two-lane part from
    the runtime mint (ungrounded catalog rows dropped, external rows carrying
    the ``DEC-053`` verdict), and the trace from the dev/72 delegation home.

    Returns ``{"status": "awaiting" | "no-candidates" | "unavailable",
    "attachmentId", "candidates", "detail"}``. Never raises into the caller's
    action: an unavailable specialist is reported, not thrown.
    """
    from utk_curio.backend.app.agents import (
        delegation,
        node_context,
        services,
        tools,
    )
    from utk_curio.backend.app.projects import storage as projects_storage

    node_id = str(node.get("id") or "")
    node_type = node.get("type")
    if not node_id:
        return {"status": "unavailable", "attachmentId": None,
                "detail": "the node has no id"}
    # The attachment is a read-modify-write of the spec, and a Solve batch
    # runs its nodes in a worker pool: under the project's own spec lock, so
    # two data-loading nodes resolving at once cannot lose each other's
    # attachment (dev/124's chokepoint, dev/118's pool).
    with projects_storage.spec_write_lock(user_key, project_id):
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is None:
            return {"status": "unavailable", "attachmentId": None,
                    "detail": "the project spec is unavailable"}
        attached = services._attach_node_agent(
            user_key, spec, FINDER_AGENT_ID, node_id, node_type
        )
        attachment_id = attached.get("attachmentId")
        if not attachment_id:
            return {"status": "unavailable", "attachmentId": None,
                    "detail": f"no Dataset Finder on this node: {attached.get('reason')}"}
        if attached.get("status") == "attached":
            # Persist BEFORE the delegate runs: the dev/72 home lookup reads
            # the saved spec, and the trace turns belong in this session.
            projects_storage.write_spec(user_key, project_id, spec)
    resolution = delegation.resolve(
        user_key, project_id, parent_manifest, "dataset.discover"
    ) if parent_manifest is not None else None
    if resolution is None or resolution.outcome != "ok":
        outcome = getattr(resolution, "outcome", "unresolvable")
        return {"status": "unavailable", "attachmentId": attachment_id,
                "detail": f"the Dataset Finder could not be resolved ({outcome})"}
    loop_ctx: dict = {
        "attachment_id": parent_attachment_id,
        "manifest": parent_manifest,
        "target": {"kind": "node", "targetId": node_id},
    }
    inputs = {
        "mission": (mission or str(node.get("goal") or "") or "").strip()[:2000],
        "nodeId": node_id,
    }
    if catalog_rows is not None:
        # dev/126: the rows were listed where a request context existed (a
        # detached Solve job has none). Supplying them here also means
        # ``_dataset_discover_inputs`` leaves them alone — the model-supplied
        # key rule, applied to the runtime's own input.
        inputs["catalog"] = {
            "note": (
                "The project's Data Catalog as catalog.search returned it"
                if catalog_rows else
                "The Data Catalog listing was empty or unavailable — the catalog lane "
                "must stay empty; say so."
            ),
            "rows": catalog_rows,
        }
    composed = node_context.compose_node_context(user_key, project_id, spec, node_id)
    if composed is not None:
        inputs["nodeContext"] = composed
    inputs = services._enriched_delegate_inputs(
        user_key, project_id, loop_ctx, "dataset.discover", inputs
    )
    status, text, _child, _home = services._run_delegate_traced(
        user_key, project_id, resolution.coord, "dataset.discover", inputs, config,
        parent_execution_id=parent_execution_id,
        parent_coord=parent_coord,
        attachment_id=parent_attachment_id,
        node_id=node_id,
    )
    if status != "ok":
        return {"status": "unavailable", "attachmentId": attachment_id,
                "detail": f"the Dataset Finder run failed: {(text or '')[:200]}"}
    if catalog_rows is None:
        try:
            catalog_rows = tools._catalog_search_rows(user_key, project_id, {})
        except Exception:  # noqa: BLE001
            log.warning("Catalog listing unavailable while minting candidates for node %s",
                        node_id, exc_info=True)
            catalog_rows = []
    part, model_text, outcome = services._mint_candidates_from_delegate(
        loop_ctx, text, catalog_rows
    )
    if part is None:
        return {"status": "no-candidates", "attachmentId": attachment_id,
                "detail": model_text[:300]}
    total = sum(len(rows) for rows in (part.get("lanes") or {}).values())
    _append_candidates_turn(user_key, project_id, attachment_id, part, total)
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = projects_storage.read_spec(user_key, project_id)
        if fresh is not None:
            mark_candidates_pending(fresh, attachment_id, count=total)
            projects_storage.write_spec(user_key, project_id, fresh)
    return {"status": "awaiting", "attachmentId": attachment_id,
            "candidates": total,
            "detail": f"{total} candidate(s) awaiting your selection"}


def _append_candidates_turn(
    user_key: str, project_id: str, attachment_id: str, part: dict, total: int
) -> None:
    """Put the two-lane card in the node's Dataset Finder chat — where the
    user selects, and where the agent that owns discovery lives."""
    from utk_curio.backend.app.agents import attachments, sessions
    from utk_curio.backend.app.projects import storage as projects_storage

    try:
        spec = projects_storage.read_spec(user_key, project_id)
        record = attachments.get_attachment(spec or {}, attachment_id) or {}
        session_id = record.get("sessionId")
        if not isinstance(session_id, str):
            return
        sessions.append_turns(
            user_key, project_id, session_id, attachment_id,
            [sessions.make_turn(
                "agent",
                f"{total} dataset candidate(s) for this node — select the source to "
                "use and confirm; external rows carry the runtime's verification "
                "verdict.",
                content=[part],
            )],
        )
    except Exception:  # noqa: BLE001
        log.warning("Could not append the candidates turn for attachment %s",
                    attachment_id, exc_info=True)
