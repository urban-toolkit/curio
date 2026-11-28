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

- a node whose source is already grounded (a path the user typed, a Data
  Catalog dataset it names, a URL verified in this conversation, an explicit
  synthetic request) needs no discovery — the skip is RECORDED with the literal
  that grounded it, so "always initiated" stays auditable instead of assumed,
  and the record never suppresses a later discovery;
- a node with its own Dataset Finder is grounded for a first attempt only by
  what may be its source, each tied to it (its code, its dataset widget, a
  dataset of its dataflow, a dataset or URL its goal names, a path the user
  typed in the chat that asked whose file its goal names): with none of it,
  its Finder is asked before any round, since the Data Catalog listing holds
  every dataset Curio ships and says nothing about the node. A node without
  one is grounded by any dataset of the Data Catalog, as before;
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

Every candidates card the node's Finder offers carries an id of its own
(``discoveryId``), the same on the card the chat that asked holds (a
``sourcePick`` part). The record names the card on offer now
(``discoveryId``), the card its pick was made on (``pickedFrom``), every chat
besides the Finder's that holds the card on offer (``askers``, the first of
them also ``askedBy``) and, once the pick is recorded, what comes of it
(``next``). A pick names its card, and one on a card the record no longer
offers is refused, so a card is never read against another card's rows. The
record also keeps what the node held when the card was offered or the pick
made (``held``): only what the node holds since may end a wait on it.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application.proposals import plans
from utk_curio.backend.app.agents.application.turns import delegates
from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import spec_reads
from utk_curio.backend.app.agents.application import tools
from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.domain import labels
from utk_curio.backend.app.agents.domain import node_context
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.datasets.domain.code_refs import dataset_widget_ids

log = logging.getLogger(__name__)

#: What the agent that finds a node its source declares: the node's own
#: attachment of that agent holds the node's source state.
DISCOVER = "dataset.discover"

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


def new_discovery_id() -> str:
    """The id of a candidates card the node's Finder offers."""
    return uuid.uuid4().hex


# ── the record ───────────────────────────────────────────────────────────────


def finder_attachment(spec: dict | None, node_id: str, *, user_key: str | None = None) -> dict | None:
    """The node's own attachment of the agent that finds its datasets (it
    declares ``dataset.discover``), or None. *user_key* finds the account's
    own agents; without it, only the shipped ones are read."""
    return spec_reads._node_attachment_declaring(spec, DISCOVER, node_id, user_key=user_key)


def source_record(spec: dict | None, node_id: str, *, user_key: str | None = None) -> dict | None:
    """The node's recorded source state, or None when discovery never ran."""
    record = finder_attachment(spec, node_id, user_key=user_key) or {}
    value = record.get(RECORD_KEY)
    return value if isinstance(value, dict) else None


def node_source_state(
    spec: dict | None,
    node_id: str,
    *,
    grounded_literal: str | None = None,
    project_literal: str | None = None,
    user_key: str | None = None,
) -> dict:
    """The node's source state — the ONE reading of it (memo dev/126).

    Two kinds of grounding evidence, deliberately ranked (the caller owns
    grounding; this module owns the state):

    - ``grounded_literal`` is about THIS node: a path or dataset id in its own
      intent, a URL verified for it, an explicit synthetic request, and, for a
      node with its own Dataset Finder, the source the user gave the node
      itself, its code or its dataset widget, counted while a card waits
      only when it came after the card (``grounding._node_own_source``). It
      wins over a pending card, because the user has since said what to load
      and should not be stuck answering a card they have overtaken.
    - ``project_literal`` is about the DATAFLOW, and may or may not cover this
      node: for a node with its own Dataset Finder, what may be its source in
      the dataflow and in the chat that asked
      (``grounding._dataflow_grounded_literal``), else "the Data Catalog
      holds N datasets". It grounds a first attempt (the content child is
      handed those rows and the ``DEC-072`` gate enforces them), but it loses
      to a pending card: once candidates are waiting, re-generating against
      the whole catalog is not progress.

    Returns ``{state, attachmentId, detail}``.
    """
    attachment = finder_attachment(spec, node_id, user_key=user_key) or {}
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


def _counted(total: int) -> str:
    """*total* candidates in the words a person reads: "1 candidate", "3
    candidates"."""
    return f"{total} candidate{'' if total == 1 else 's'}"


def _pending_detail(record: dict, status: str) -> str:
    if status == STATE_AWAITING_INSTALL and any(
        p.get("acquiring") for p in record.get("picks") or [] if isinstance(p, dict)
    ):
        return f"{_picks_detail(record)}: downloading into the Data Catalog"
    if status == STATE_AWAITING_INSTALL:
        return f"{_picks_detail(record)}: waiting for the reviewed install"
    count = record.get("candidates")
    if isinstance(count, int) and count > 0:
        return f"{_counted(count)} awaiting your selection"
    return "candidates awaiting your selection"


def askers_of(record: dict | None) -> list[str]:
    """Every chat besides the node's Finder's that holds the card the
    record offers, in the order they asked (``askers``; a record written
    before them names its one asker as ``askedBy``)."""
    if not isinstance(record, dict):
        return []
    askers = [a for a in record.get("askers") or [] if isinstance(a, str) and a]
    if not askers and isinstance(record.get("askedBy"), str) and record["askedBy"]:
        askers = [record["askedBy"]]
    return list(dict.fromkeys(askers))


def _set_askers(record: dict, askers: list[str]) -> None:
    """Write *askers* on *record*: ``askers``, and ``askedBy`` as the first
    of them; neither when there is none."""
    askers = list(dict.fromkeys(a for a in askers if a))
    if askers:
        record["askers"] = askers
        record["askedBy"] = askers[0]
    else:
        record.pop("askers", None)
        record.pop("askedBy", None)


def held_by(node: dict | None) -> dict:
    """What *node* holds that may be its source: a digest of its code, read
    without the spaces that end its lines, and the Data Catalog ids its
    dataset widgets hold (``code_refs.dataset_widget_ids``). The record of a
    card offered for the node keeps it (``held``), so that only what the node
    holds since may end the wait on the card (``grounding._node_own_source``)."""
    node = node if isinstance(node, dict) else {}
    code = "\n".join(line.rstrip() for line in str(node.get("content") or "").splitlines()).strip()
    return {"code": hashlib.sha256(code.encode("utf-8")).hexdigest(), "datasets": dataset_widget_ids(node)}


def _node_of(spec: dict | None, record: dict | None) -> dict | None:
    """The node of *spec* that the attachment *record* is on, or None."""
    target = (record or {}).get("target") or {}
    if target.get("kind") != "node" or not target.get("targetId"):
        return None
    nodes = ((spec or {}).get("dataflow") or {}).get("nodes") or []
    return next((n for n in nodes if isinstance(n, dict) and n.get("id") == target["targetId"]), None)


def held_while_waiting(record: dict | None) -> dict | None:
    """While the node's source waits on a card, its candidates for a pick or
    its pick for an install, what the node held when that card was offered
    or that pick made (``held``, :func:`held_by`); an empty dict for a record
    written before records kept it, so that nothing the node holds is newer
    than its card. None while nothing waits."""
    if not isinstance(record, dict) or record.get("status") not in (STATE_CANDIDATES_PENDING, STATE_AWAITING_INSTALL):
        return None
    held = record.get("held")
    return dict(held) if isinstance(held, dict) else {}


def mark_candidates_pending(spec: dict, attachment_id: str, *, count: int,
                            asked_by: str | None = None, discovery_id: str | None = None) -> dict | None:
    """Record that candidates were minted for this node's Dataset Finder, the
    card that offers them (*discovery_id*), what the node holds now
    (:func:`held_by`), and the attachment whose chat asked for them
    (*asked_by*: the agent whose Solve or Build & validate reached the node),
    which holds the same card and waits for the pick too
    (:func:`waiting_on_user`)."""

    record = attachments.get_attachment(spec, attachment_id)
    if record is None:
        return None
    state: dict = {
        "status": STATE_CANDIDATES_PENDING,
        "candidates": int(count),
        "proposedAt": _now(),
        **({"discoveryId": discovery_id} if discovery_id else {}),
        "held": held_by(_node_of(spec, record)),
    }
    _set_askers(state, [asked_by] if asked_by else [])
    record[RECORD_KEY] = state
    record["revision"] = int(record.get("revision", 1)) + 1
    return record[RECORD_KEY]


def note_offer(spec: dict, attachment_id: str, discovery_id: str, *, count: int) -> list[str] | None:
    """The node's Dataset Finder offered the candidates card *discovery_id*
    (of *count* rows) in its own chat: the record names it as the card on
    offer now, keeping its status. While the record waits for the user's pick
    (:func:`source_wait`), the chats that asked hold the new card too, and
    their ids are returned to put it there; otherwise no other chat holds it,
    and the record names no asker. None when *attachment_id* is no
    attachment of *spec*."""
    record = attachments.get_attachment(spec, attachment_id)
    if record is None:
        return None
    current = record.get(RECORD_KEY)
    state = dict(current) if isinstance(current, dict) else {}
    state["discoveryId"] = discovery_id
    if source_wait(current) == WAITS_FOR_PICK:
        if state.get("status") == STATE_CANDIDATES_PENDING:
            state["candidates"] = int(count)
        askers = askers_of(state)
        # The node waits on this card now: what it holds is older than it.
        state["held"] = held_by(_node_of(spec, record))
    else:
        askers = []
    _set_askers(state, askers)
    record[RECORD_KEY] = state
    record["revision"] = int(record.get("revision", 1)) + 1
    return [asker for asker in askers if asker != attachment_id]


#: What a node's source waits for, as its Dataset Finder's record says
#: (:func:`source_wait`): the user, a download into the Data Catalog, or the
#: install of the dataset picked.
WAITS_FOR_PICK = "pick"
WAITS_FOR_DOWNLOAD = "download"
WAITS_FOR_INSTALL = "install"


def _portal_download(pick: dict) -> bool:
    """A pick whose file is on a portal: the user downloads it and imports it
    from the card, and Curio does not download it."""
    return (pick.get("lane") == "external" and pick.get("access") == verify.ACCESS_MANUAL
            and not pick.get("acquirable"))


def source_wait(record: dict | None) -> str | None:
    """What a node's source waits for, by its Dataset Finder's *record*: the
    user (``pick``) while its candidates await a pick, or while every pick
    is a portal download, which the user downloads and imports from the card
    and then picks; a download into the Data Catalog (``download``); or the
    install of the dataset picked (``install``). None when it waits for
    nothing: the pick resolved the node, discovery was skipped, or there is
    no record."""
    if not isinstance(record, dict):
        return None
    status = record.get("status")
    picks = [pick for pick in record.get("picks") or [] if isinstance(pick, dict)]
    if status == STATE_CANDIDATES_PENDING:
        return WAITS_FOR_PICK
    if status == STATE_AWAITING_INSTALL:
        return WAITS_FOR_DOWNLOAD if any(pick.get("acquiring") for pick in picks) else WAITS_FOR_INSTALL
    if status == STATE_RESOLVED and picks and all(_portal_download(pick) for pick in picks):
        return WAITS_FOR_PICK
    return None


def waiting_on_user(spec: dict | None) -> dict[str, list[str]]:
    """Who waits for the user to pick a node's source, by attachment id: the
    ids of the nodes it waits on. A node's Dataset Finder waits while its
    source waits for the user (:func:`source_wait`): its candidates await a
    pick, or the portal file picked awaits its import. So does each
    attachment whose chat asked for them and holds their card (the record's
    askers, :func:`askers_of`) while it is on the dataflow. A pick that
    resolves the node, a skip, the node's removal or its Finder taken off
    ends every wait; an asker's chat cleared ends its own
    (:func:`forget_asker`)."""
    records = attachments.list_attachments(spec or {})
    present = {record.get("attachmentId") for record in records}
    waits: dict[str, list[str]] = {}
    for record in records:
        target = record.get("target") or {}
        node_id = target.get("targetId")
        if source_wait(record.get(RECORD_KEY)) != WAITS_FOR_PICK:
            continue
        if target.get("kind") != "node" or not node_id:
            continue
        for waiter in (record.get("attachmentId"), *askers_of(record[RECORD_KEY])):
            if waiter in present and node_id not in waits.setdefault(waiter, []):
                waits[waiter].append(node_id)
    return waits


def forget_asker(spec: dict, attachment_id: str) -> list[str]:
    """The chat of *attachment_id* was cleared, so it holds no candidates it
    asked for: it is no asker of them any more, and no longer waits for their
    pick. Each node's Dataset Finder, and every other asker, still does.
    Returns the Finder attachments whose record changed."""
    changed: list[str] = []
    for record in attachments.list_attachments(spec):
        state = record.get(RECORD_KEY)
        askers = askers_of(state)
        if isinstance(state, dict) and attachment_id and attachment_id in askers:
            _set_askers(state, [asker for asker in askers if asker != attachment_id])
            record["revision"] = int(record.get("revision", 1)) + 1
            changed.append(record.get("attachmentId"))
    return changed


def forget_candidates(spec: dict, attachment_id: str) -> bool:
    """The Dataset Finder chat of *attachment_id* was cleared while its
    source waited for the user (:func:`source_wait`): the card went with it,
    so nothing is left to pick or import from. The record goes, the node is
    unresolved again, and the next Solve or Build & validate asks its Finder
    for candidates again. A pick that resolved the node, one that waits for
    its download or install, and a skip are kept. Returns whether the record
    went."""
    record = attachments.get_attachment(spec, attachment_id)
    state = (record or {}).get(RECORD_KEY)
    if source_wait(state) != WAITS_FOR_PICK:
        return False
    record.pop(RECORD_KEY)
    record["revision"] = int(record.get("revision", 1)) + 1
    return True


def mark_skipped(spec: dict, attachment_id: str, *, literal: str) -> dict | None:
    """Record that discovery was skipped because the source is already
    grounded: the audit trail behind "always initiated".

    A confirmed selection is never replaced: it is what grounds the node, and
    ``node_source_state`` ranks it above every literal. Writing the note over
    it would erase the user's pick, so the next round that missed it would
    start discovery again and later Solves would hand the builder nothing."""

    record = attachments.get_attachment(spec, attachment_id)
    if record is None:
        return None
    current = record.get(RECORD_KEY)
    if isinstance(current, dict) and current.get("status") == STATE_RESOLVED:
        return None
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


def resolve_picks(
    part: dict | None, picks: object, *, catalog_rows: list[dict] | None = None, owners_listing=None,
) -> list[dict]:
    """Resolve client-supplied ``{lane, key}`` picks against the runtime's OWN
    candidate rows (the persisted ``datasetCandidates`` part).

    The key is a catalog row's ``datasetId`` or an external row's ``url``, or
    for an external row with no url its Discovery Catalog coordinate (``row_key``). The
    client never sends a name, path or URL of its own, so a selection cannot
    introduce a source the runtime did not propose and probe. Raises
    ``DatasetResolutionError`` naming the first key that does not resolve.

    With *catalog_rows*, the Data Catalog listing as it is now, a catalog row
    of the card is read from it again, as an external row is probed again at
    confirmation: one the listing no longer holds is refused, and whether it
    is installed is the listing's answer, not the card's.

    *owners_listing*, for an editor the owner invited, returns the dataflow
    owner's listing, read once and only for a catalog row of the card that
    his own listing does not hold: a dataset of hers that a card of a run of
    hers offered, which his pick asks her to add. A row no listing holds is
    refused; a key no card offered is read from his listing alone.
    """
    if not isinstance(part, dict) or not isinstance(part.get("lanes"), dict):
        if not catalog_rows:
            raise DatasetResolutionError(
                "there are no dataset candidates on this node to select from"
            )
        part = {"lanes": {"catalog": [], "external": []}}
    if not isinstance(picks, list) or not picks:
        raise DatasetResolutionError("picks must be a non-empty list")
    if len(picks) > MAX_PICKS:
        raise DatasetResolutionError(f"at most {MAX_PICKS} picks may be confirmed at once")
    lanes = part["lanes"]
    resolved: list[dict] = []
    seen: set[tuple[str, str]] = set()
    owners: list[list[dict]] = []  # the owner's listing, once read

    def _listed(key: str) -> dict | None:
        listed = _listing_item(catalog_rows, key)
        if listed is None and owners_listing is not None:
            if not owners:
                owners.append(owners_listing() or [])
            listed = _listing_item(owners[0], key)
        return listed

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
        row = next(
            (r for r in rows if isinstance(r, dict) and row_key(lane, r) == key.strip()),
            None,
        )
        if row is not None and lane == "catalog" and catalog_rows is not None:
            listed = _listed(key.strip())
            if listed is None:
                raise DatasetResolutionError(
                    f"{key!r} is not in the Data Catalog: select a dataset it holds"
                )
            row = {**row, "installed": bool(listed.get("installed"))}
        if row is None and lane == "catalog":
            # dev/132: a dataset the user JUST IMPORTED is not on the card —
            # the card is older than the file. It is still a legitimate pick:
            # the Data Catalog is the runtime's own listing (the same one
            # ``catalog.search`` serves and `DEC-072`'s gate grounds against),
            # so a key it contains was never introduced by the client.
            row = _catalog_row(catalog_rows, key.strip())
        if row is None:
            raise DatasetResolutionError(
                f"{key!r} is not a {lane} candidate of this node: select a row the "
                "Dataset Finder proposed"
            )
        if (lane, key) in seen:
            continue
        seen.add((lane, key))
        resolved.append({"lane": lane, **row})
    return resolved


def _listing_item(rows: list[dict] | None, dataset_id: str) -> dict | None:
    """The item of the Data Catalog listing *rows* whose id is *dataset_id*."""
    return next(
        (item for item in rows or [] if isinstance(item, dict) and str(item.get("id") or "") == dataset_id),
        None,
    )


def row_key(lane: str, row: dict) -> str:
    """How a pick addresses a candidate row: a catalog row by ``datasetId``, an
    external row by ``url``, or by ``sourceId/resourceId`` when it has none."""
    if lane == "catalog":
        return str(row.get("datasetId") or "")
    if row.get("url"):
        return str(row["url"])
    if row.get("sourceId") and row.get("resourceId"):
        return f"{row['sourceId']}/{row['resourceId']}"
    return ""


def _needs_install(pick: dict) -> bool:
    """A catalog pick whose file is not readable yet: neither installed into the
    dataflow nor held in the account store (a download still running counts)."""
    return pick.get("lane") == "catalog" and not pick.get("installed") and not pick.get("imported")


def _from(origin: str | None) -> dict:
    """A downloaded pick's ``provider``: where its data comes from (*origin*,
    ``acquire._picked_from``), which the card's Recorded line names in place of
    the Data Catalog it lands in."""
    origin = str(origin or "").strip()[:120]
    return {"provider": origin} if origin else {}


def acquired_pick(row: dict, dataset_id: str, *, origin: str | None = None) -> dict:
    """The catalog pick a downloaded external row becomes. The file is in the
    account store, so ``curio_data_path("<id>")`` resolves it like an import.
    *origin* is where its data comes from (:func:`_from`)."""
    return {
        "lane": "catalog",
        "name": str(row.get("name") or dataset_id)[:120],
        "sourceType": "catalog",
        "datasetId": str(dataset_id),
        "installed": False,
        "imported": True,
        "discoverySource": {"sourceId": row.get("sourceId"), "resourceId": row.get("resourceId")},
        **_from(origin),
    }


def acquiring_pick(row: dict, job_id: object, *, origin: str | None = None) -> dict:
    """The catalog pick for a download still running. It waits like an
    uninstalled dataset until ``settle_acquisitions`` sees the file held.
    *origin* is where its data comes from (:func:`_from`)."""
    return {
        "lane": "catalog",
        "name": str(row.get("name") or row.get("resourceId") or "")[:120],
        "sourceType": "catalog",
        "installed": False,
        "discoverySource": {"sourceId": row.get("sourceId"), "resourceId": row.get("resourceId")},
        "acquiring": {"jobId": str(job_id or "")},
        **_from(origin),
    }


def has_acquiring_picks(spec: dict | None) -> bool:
    """Whether any node waits on a download, so a caller can skip the lookup."""

    for record in attachments.list_attachments(spec or {}):
        state = record.get(RECORD_KEY)
        if isinstance(state, dict) and any(
            isinstance(p, dict) and p.get("acquiring") for p in state.get("picks") or []
        ):
            return True
    return False


def settle_acquisitions(spec: dict, held: dict) -> list[str]:
    """Resolve picks whose download has landed since they were confirmed.

    ``held`` maps ``(sourceId, resourceId)`` to the id of the dataset the
    account holds from that resource. Returns the attachment ids that changed.
    """

    changed: list[str] = []
    for record in attachments.list_attachments(spec):
        state = record.get(RECORD_KEY)
        if not isinstance(state, dict) or state.get("status") != STATE_AWAITING_INSTALL:
            continue
        picks = state.get("picks") or []
        settled = False
        for index, pick in enumerate(picks):
            if not isinstance(pick, dict) or not pick.get("acquiring"):
                continue
            discovered = pick.get("discoverySource") or {}
            dataset_id = held.get((discovered.get("sourceId"), discovered.get("resourceId")))
            if dataset_id:
                picks[index] = acquired_pick(
                    {**discovered, "name": pick.get("name")}, dataset_id, origin=pick.get("provider"),
                )
                settled = True
        if not settled:
            continue
        if not any(_needs_install(p) for p in picks if isinstance(p, dict)):
            state["status"] = STATE_RESOLVED
        # What the pick said came next was the download: it landed.
        state.pop("next", None)
        state["recordedAt"] = _now()
        record["revision"] = int(record.get("revision", 1)) + 1
        changed.append(record.get("attachmentId"))
    return changed


def _catalog_row(catalog_rows: list[dict] | None, dataset_id: str) -> dict | None:
    """A candidate-shaped row for a dataset that is IN the project's Data
    Catalog (dev/132), or None. ``catalog_rows`` is the runtime's own listing,
    every row of it (``tools._catalog_listing_rows``), resolved by the caller
    in the request context, as dev/126 already does for discovery."""
    for item in catalog_rows or []:
        if not isinstance(item, dict) or str(item.get("id") or "") != dataset_id:
            continue
        return {
            "name": str(item.get("name") or dataset_id)[:120],
            "sourceType": "catalog",
            "datasetId": dataset_id,
            "installed": bool(item.get("installed")),
            **({"format": str(item.get("format"))[:160]} if item.get("format") else {}),
            "imported": True,
        }
    return None


def record_selection(spec: dict, attachment_id: str, rows: list[dict], *,
                     picked_from: str | None = None) -> dict | None:
    """Record the confirmed selection on the node's Dataset Finder attachment.

    A catalog pick that is not installed yet leaves the node
    ``awaiting-install`` — the reviewed ``dataset.install`` lane owns that
    step; an external pick the runtime could not reach is recorded WITH its
    verdict and does not resolve the node (the card says why). The record
    keeps the card on offer and the chats that hold it, and names the card
    the pick was made on (*picked_from*); what came of an earlier pick
    (``next``) goes with it.
    """

    record = attachments.get_attachment(spec, attachment_id)
    if record is None:
        return None
    # dev/132: a dataset the user brought in themselves after the card was
    # minted (the Import button under a portal row's download steps) is
    # ``imported``: its file is in their own account store and
    # ``curio_data_path("<id>")`` resolves it, so the node is RESOLVED. The
    # reviewed install lane adds a dataset to the DATAFLOW, which is a separate
    # act and not what reading the file needs.
    needs_install = [r for r in rows if _needs_install(r)]
    unreachable = [
        r for r in rows
        if r["lane"] == "external" and (r.get("verification") or {}).get("status") in verify.FAILED_STATUSES
    ]
    if unreachable and len(unreachable) == len(rows):
        status = STATE_CANDIDATES_PENDING  # nothing usable was confirmed
    elif needs_install:
        status = STATE_AWAITING_INSTALL
    else:
        status = STATE_RESOLVED
    # The card on offer and the chats that asked for it are kept with the
    # pick, which names the card it was made on.
    previous = record.get(RECORD_KEY)
    previous = previous if isinstance(previous, dict) else {}
    offered = previous.get("discoveryId") or picked_from
    state: dict = {
        "status": status,
        "picks": rows,
        "recordedAt": _now(),
        **({"discoveryId": offered} if offered else {}),
        **({"pickedFrom": picked_from} if picked_from else {}),
        # A pick that waits, for its install or for another pick, waits on
        # what the node holds now: the pick came after it.
        "held": held_by(_node_of(spec, record)),
    }
    _set_askers(state, askers_of(previous))
    record[RECORD_KEY] = state
    record["revision"] = int(record.get("revision", 1)) + 1
    return record[RECORD_KEY]


def mark_dataset_installed(spec: dict, dataset_id: str) -> list[str]:
    """An applied ``dataset.install`` resolves every node awaiting exactly that
    dataset: every attachment whose source record waits for it. Returns the
    attachment ids whose state changed."""

    changed: list[str] = []
    for record in attachments.list_attachments(spec):
        state = record.get(RECORD_KEY)
        if not isinstance(state, dict) or state.get("status") != STATE_AWAITING_INSTALL:
            continue
        picks = state.get("picks") or []
        if not any(str(p.get("datasetId") or "") == str(dataset_id) for p in picks):
            continue
        for pick in picks:
            if str(pick.get("datasetId") or "") == str(dataset_id):
                pick["installed"] = True
        if not any(_needs_install(p) for p in picks if isinstance(p, dict)):
            state["status"] = STATE_RESOLVED
            # What the pick said came next was the install: it is applied.
            state.pop("next", None)
            state["recordedAt"] = _now()
            record["revision"] = int(record.get("revision", 1)) + 1
            changed.append(record.get("attachmentId"))
    return changed


def held_datasets(spec: dict | None) -> set[str]:
    """The ids of the datasets the dataflow of *spec* holds: the refs Add to
    project, an applied install and an owner's Apply of an editor's request
    write."""
    refs = ((spec or {}).get("dataflow") or {}).get("datasets") or []
    return {
        str(ref.get("datasetId") or ref.get("id"))
        for ref in refs if isinstance(ref, dict) and (ref.get("datasetId") or ref.get("id"))
    }


def installs_awaited(spec: dict | None) -> set[str]:
    """The ids of the datasets a pick waits for the install of, in *spec*."""
    awaited: set[str] = set()
    for record in attachments.list_attachments(spec or {}):
        state = record.get(RECORD_KEY)
        if not isinstance(state, dict) or state.get("status") != STATE_AWAITING_INSTALL:
            continue
        awaited |= {
            str(pick["datasetId"]) for pick in state.get("picks") or []
            if isinstance(pick, dict) and pick.get("datasetId") and _needs_install(pick)
        }
    return awaited


def settle_installs(spec: dict) -> list[str]:
    """Resolve every pick that waits for the install of a dataset the
    dataflow of *spec* holds now, however it got there: Add to project from
    the Data Catalog, the owner's Apply of an editor's request, or an applied
    ``dataset.install``. Returns the attachment ids whose record resolved."""
    changed: list[str] = []
    for dataset_id in sorted(installs_awaited(spec) & held_datasets(spec)):
        changed += mark_dataset_installed(spec, dataset_id)
    return changed


def confirmed_source(spec: dict | None, node_id: str, *, user_key: str | None = None) -> dict | None:
    """The confirmed source a content delegate is HANDED for this node, or
    None. Shape mirrors the candidate rows the user actually confirmed."""
    record = source_record(spec, node_id, user_key=user_key)
    if not isinstance(record, dict) or record.get("status") != STATE_RESOLVED:
        return None
    picks = record.get("picks") or []
    if not picks:
        return None
    return {
        "note": agent_text.message("dataset.confirmed-source"),
        "picks": [
            {k: v for k, v in pick.items() if k in
             ("lane", "name", "datasetId", "url", "format", "requirement", "installed",
              # dev/132: whether code can fetch this row, and the portal steps
              # when it cannot — the builder must not author a fetch for a
              # source that only exists behind a browser download.
              "verification", "access", "accessWhy", "downloadSteps",
              # The Discovery Catalog coordinate, and whether Curio downloads it: a
              # builder must not write fetch code for a row Curio downloads.
              "sourceId", "resourceId", "acquirable", "discoverySource")}
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
    asker=None,
    lookups=None,
) -> dict:
    """Run ONE ``dataset.discover`` delegation for *node* and leave its
    candidates awaiting the user in that node's own Dataset Finder chat, and
    in the chat of *parent_attachment_id*, which asked for them
    (:func:`_mirror_candidates_turn`).

    *asker* is the person the run is for, which a Solve's thread names (its
    ``acting_user``) where no request does: the delegated run holds the
    skills of the dataflow's packages as that person's runs do
    (``delegation.run_delegate``), and the portals are searched for it as that
    person, holding *lookups*, the Solve batch's lock on its reads of the
    account's store, when it gives one.

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
    from utk_curio.backend.app.projects import storage as projects_storage

    node_id = str(node.get("id") or "")
    if not node_id:
        return {"status": "unavailable", "attachmentId": None,
                "detail": "the node has no id"}
    # The agent the parent asks for datasets, among the dataflow's installed
    # agents: the one this node's own attachment is of.
    resolution = delegation.resolve(
        user_key, project_id, parent_manifest, DISCOVER
    ) if parent_manifest is not None else None
    if resolution is None or resolution.outcome != "ok":
        outcome = getattr(resolution, "outcome", "unresolvable")
        name = getattr(getattr(resolution, "manifest", None), "name", None)
        existing = finder_attachment(
            projects_storage.read_spec(user_key, project_id), node_id, user_key=user_key,
        )
        return {"status": "unavailable", "attachmentId": (existing or {}).get("attachmentId"),
                "detail": (f"the {name} could not be resolved ({outcome})" if name
                           else f"no installed agent declares {DISCOVER} ({outcome})")}
    finder_name = getattr(resolution.manifest, "name", None) or resolution.coord
    attached = _attach_the_finder(user_key, project_id, node, resolution, finder_name)
    if attached["status"] != "ok":
        return attached
    attachment_id, spec = attached["attachmentId"], attached["spec"]
    loop_ctx: dict = {
        "attachment_id": parent_attachment_id,
        "manifest": parent_manifest,
        "target": {"kind": "node", "targetId": node_id},
        "asker": asker, "lookups": lookups,  # whom the portals are searched as, and the batch's lock
    }
    inputs = {
        "mission": (mission or str(node.get("goal") or "") or "").strip()[:2000],
        "nodeId": node_id,
    }
    if catalog_rows is None:
        # dev/126: a caller that held a request context listed the rows there
        # (a detached Solve job has none); one listing serves the child's
        # input and the check of its candidates.
        try:
            catalog_rows = tools._catalog_listing_rows(user_key, project_id, {})
        except Exception:  # noqa: BLE001
            log.warning("Catalog listing unavailable for the candidates of node %s",
                        node_id, exc_info=True)
            catalog_rows = []
    composed = node_context.compose_node_context(user_key, project_id, spec, node_id)
    if composed is not None:
        inputs["nodeContext"] = composed
    inputs = delegates._enriched_delegate_inputs(
        user_key, project_id, loop_ctx, DISCOVER, inputs, catalog_rows=catalog_rows, delegate=resolution.manifest,
    )
    status, text, _child, _home = delegates._run_delegate_traced(
        user_key, project_id, resolution.coord, DISCOVER, inputs, config,
        parent_execution_id=parent_execution_id,
        parent_coord=parent_coord,
        attachment_id=parent_attachment_id,
        # The Finder's chat names the agent that asked, as its manifest does.
        parent_name=getattr(parent_manifest, "name", None),
        node_id=node_id,
        asker=asker,
    )
    if status != "ok":
        return {"status": "unavailable", "attachmentId": attachment_id,
                "detail": f"the {finder_name} run failed: {(text or '')[:200]}"}
    part, model_text, outcome = delegates._mint_candidates_from_delegate(
        loop_ctx, text, catalog_rows, name=finder_name,
    )
    if part is None:
        return {"status": "no-candidates", "attachmentId": attachment_id,
                "detail": model_text[:300]}
    total = _offer_the_card(user_key, project_id, node, part, attachment_id, parent_attachment_id,
                            coord=resolution.coord, finder_name=finder_name)
    return {"status": "awaiting", "attachmentId": attachment_id,
            "candidates": total,
            "detail": f"{_counted(total)} awaiting your selection"}


def _attach_the_finder(user_key: str, project_id: str, node: dict, resolution, finder_name: str) -> dict:
    """The node's own attachment of the Finder *resolution* names, made when
    the node has none: ``{"status": "ok", "attachmentId", "spec"}``, or
    :func:`initiate`'s ``unavailable`` answer.

    The attachment is a read-modify-write of the spec, and a Solve batch runs
    its nodes in a worker pool: under the project's own spec lock, so two
    data-loading nodes resolving at once cannot lose each other's attachment
    (dev/124's chokepoint, dev/118's pool)."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.packages import service as packages_services
    from utk_curio.backend.app.projects import storage as projects_storage

    # Read before the spec lock, which the package store's own lock must not nest in.
    templates = packages_services.roster_templates(user_key, project_id)
    with projects_storage.spec_write_lock(user_key, project_id):
        spec = dataflow_docs.live(user_key, project_id)
        if spec is None:
            return {"status": "unavailable", "attachmentId": None,
                    "detail": "the project spec is unavailable"}
        attached = plans._attach_node_agent(
            user_key, spec, resolution.coord.split("@", 1)[0], str(node.get("id") or ""), node.get("type"),
            templates=templates,
        )
        attachment_id = attached.get("attachmentId")
        if not attachment_id:
            return {"status": "unavailable", "attachmentId": None,
                    "detail": f"no {finder_name} on this node: {attached.get('reason')}"}
        if attached.get("status") == "attached":
            # Persist BEFORE the delegate runs: the dev/72 home lookup reads
            # the saved spec, and the trace turns belong in this session.
            dataflow_docs.write(user_key, project_id, spec, dataflow_docs.by_agent(resolution.coord, user_key, "dataset"))
    return {"status": "ok", "attachmentId": attachment_id, "spec": spec}


def _offer_the_card(user_key: str, project_id: str, node: dict, part: dict, attachment_id: str,
                    parent_attachment_id: str | None, *, coord: str, finder_name: str) -> int:
    """Offer the candidates card *part*, under an id of its own, in the
    Finder's chat and in the chat of *parent_attachment_id*, which asked for
    it, and leave the Finder's record waiting for its pick. Returns how many
    rows it holds."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects import storage as projects_storage

    total = sum(len(rows) for rows in (part.get("lanes") or {}).values())
    # The card's own id, the same in the Finder's chat and the chat that asked.
    part["discoveryId"] = new_discovery_id()
    _append_candidates_turn(user_key, project_id, attachment_id, node, part, total)
    if parent_attachment_id and parent_attachment_id != attachment_id:
        _mirror_candidates_turn(
            user_key, project_id, parent_attachment_id, attachment_id, node, part, total, finder_name=finder_name,
        )
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = dataflow_docs.live(user_key, project_id)
        if fresh is not None:
            mark_candidates_pending(
                fresh, attachment_id, count=total,
                asked_by=parent_attachment_id if parent_attachment_id != attachment_id else None,
                discovery_id=part["discoveryId"],
            )
            dataflow_docs.write(user_key, project_id, fresh, dataflow_docs.by_agent(coord, user_key, "dataset"))
    return total


def _append_candidates_turn(
    user_key: str, project_id: str, attachment_id: str, node: dict, part: dict, total: int
) -> None:
    """Put the two-lane card in the node's Dataset Finder chat, where the
    user selects and where the agent that owns discovery lives, under one
    line that counts the candidates and names *node* as its header does. The
    line is in the Finder's model context. Read outside the spec lock: a node
    with no title is named by its template's label, from the package store."""
    from utk_curio.backend.app.projects import storage as projects_storage

    try:
        spec = projects_storage.read_spec(user_key, project_id)
        record = attachments.get_attachment(spec or {}, attachment_id) or {}
        session_id = record.get("sessionId")
        if not isinstance(session_id, str):
            return
        label = labels.on_a_word(node_label(user_key, project_id, node), 120)
        sessions.append_turns(
            user_key, project_id, session_id, attachment_id,
            [sessions.make_turn(
                "agent",
                f"I found {_counted(total)} for {label}. Pick one with Use this source.",
                content=[part],
            )],
        )
    except Exception:  # noqa: BLE001
        log.warning("Could not append the candidates turn for attachment %s",
                    attachment_id, exc_info=True)


def node_label(user_key: str, project_id: str, node: dict | None) -> str:
    """The name the node's header shows (``labels.node_label``): its title,
    else its template's label, read only when it has no title."""
    from utk_curio.backend.app.execution import node_names

    title = node_names.saved_node_title(node) if isinstance(node, dict) else ""
    return title or labels.node_label(node, templates=node_names.template_labels(user_key, project_id))


def _mirror_candidates_turn(
    user_key: str, project_id: str, asker_id: str, finder_id: str, node: dict, part: dict, total: int,
    *, finder_name: str,
) -> None:
    """The same candidates in the chat that asked for them (*asker_id*, the
    agent whose Solve or Build & validate reached the node): one line that
    asks for the node's source and counts what its Dataset Finder found
    ("Pick a source for **CPL branches**. Its Dataset Finder found 4."),
    which the asking agent's next runs read in their context, and the card, a
    ``sourcePick`` part, its rows in the Finder's card's order. The card is no
    text, so no run reads it (``sessions.context_messages``), and its pick
    posts on the route of the Finder (*finder_id*), which records it. Read
    outside the spec lock: a node with no title is named by its template's
    label, from the package store."""
    from utk_curio.backend.app.projects import storage as projects_storage

    try:
        spec = projects_storage.read_spec(user_key, project_id)
        session_id = (attachments.get_attachment(spec or {}, asker_id) or {}).get("sessionId")
        if not isinstance(session_id, str):
            return
        node_id = str(node.get("id") or "")
        label = labels.on_a_word(node_label(user_key, project_id, node), 120)
        sessions.append_turns(
            user_key, project_id, session_id, asker_id,
            [sessions.make_turn(
                "agent",
                f"Pick a source for **{label}**. Its {finder_name} found {total}.",
                content=[{
                    "type": "sourcePick",
                    "finderAttachmentId": finder_id,
                    "nodeId": node_id,
                    "nodeLabel": label,
                    **({"discoveryId": part["discoveryId"]} if part.get("discoveryId") else {}),
                    "lanes": part.get("lanes") or {},
                    # Its lanes and its rows as the Finder's card draws them,
                    # best first.
                    **({"laneOrder": part["laneOrder"]} if part.get("laneOrder") else {}),
                    **({"rowOrder": part["rowOrder"]} if part.get("rowOrder") else {}),
                }],
            )],
        )
    except Exception:  # noqa: BLE001 - the Finder's own chat holds the card either way
        log.warning("Could not put the candidates of node %s in the chat of %s",
                    node.get("id"), asker_id, exc_info=True)


def _rows_in(part: dict) -> int:
    """How many candidate rows the card *part* holds."""
    return sum(len(rows) for rows in (part.get("lanes") or {}).values() if isinstance(rows, list))


def _offered_part(user_key: str, project_id: str, finder: dict) -> dict | None:
    """The candidates card the Finder *finder* offers now, as its chat holds
    it: the one its record names (``discoveryId``), else, for a record written
    before cards had ids, the newest. None when its chat holds none."""
    session_id = finder.get("sessionId")
    if not isinstance(session_id, str):
        return None
    record = finder.get(RECORD_KEY) if isinstance(finder.get(RECORD_KEY), dict) else {}
    offered = record.get("discoveryId")
    cards = [
        part for turn in sessions.read_turns(user_key, project_id, session_id)
        for part in (turn.get("content") or [])
        if isinstance(part, dict) and part.get("type") == "datasetCandidates"
    ]
    if offered:
        return next((part for part in reversed(cards) if part.get("discoveryId") == offered), None)
    return cards[-1] if cards else None


def _finder_name(user_key: str, finder: dict) -> str:
    """The name of the Finder *finder*, as its manifest gives it."""
    coord = str(finder.get("coord") or "")
    return spec_reads._agent_name(user_key, coord) or coord.split("@", 1)[0] or "Dataset Finder"


def ask_again(user_key: str, project_id: str, node: dict, asker_id: str) -> bool:
    """A Solve or Build & validate of the chat of *asker_id* reached *node*,
    whose candidates already wait for the user's pick, which another chat
    asked for: this chat gets the card on offer too, the same card with the
    same id, under the same line (:func:`_mirror_candidates_turn`), and joins
    the record's askers, so it waits for the pick as well. The node's Finder,
    and a chat already among the askers, get nothing. No model is asked.
    Returns whether the chat got the card."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects import storage as projects_storage

    node_id = str(node.get("id") or "")
    try:
        spec = projects_storage.read_spec(user_key, project_id)
        finder = finder_attachment(spec, node_id, user_key=user_key) or {}
        finder_id = finder.get("attachmentId")
        record = finder.get(RECORD_KEY) if isinstance(finder.get(RECORD_KEY), dict) else None
        if (not finder_id or asker_id == finder_id or source_wait(record) != WAITS_FOR_PICK
                or asker_id in askers_of(record)):
            return False
        if not isinstance((attachments.get_attachment(spec, asker_id) or {}).get("sessionId"), str):
            return False
        part = _offered_part(user_key, project_id, finder)
        if part is None:
            return False
        # The card first, then the record: a tab that sees the record name this
        # chat among the askers finds the card in it.
        _mirror_candidates_turn(
            user_key, project_id, asker_id, finder_id, node, part, _rows_in(part),
            finder_name=_finder_name(user_key, finder),
        )
        with projects_storage.spec_write_lock(user_key, project_id):
            fresh = dataflow_docs.live(user_key, project_id)
            fresh_finder = attachments.get_attachment(fresh or {}, finder_id) if fresh is not None else None
            state = (fresh_finder or {}).get(RECORD_KEY)
            if not isinstance(state, dict) or state.get("discoveryId") != record.get("discoveryId"):
                return True
            askers = askers_of(state)
            if asker_id not in askers:
                _set_askers(state, [*askers, asker_id])
                fresh_finder["revision"] = int(fresh_finder.get("revision", 1)) + 1
                dataflow_docs.write(user_key, project_id, fresh, dataflow_docs.by_curio(user_key, "dataset"))
        return True
    except Exception:  # noqa: BLE001 - the Finder's own chat holds the card either way
        log.warning("Could not put the candidates of node %s in the chat of %s", node_id, asker_id, exc_info=True)
        return False


def offer_from_chat(user_key: str, project_id: str, attachment_id: str, part: dict) -> None:
    """The chat reply of *attachment_id* offered the candidates card *part*,
    which carries its id (``discoveryId``). When that agent is its node's
    Dataset Finder, the record names the card as the one on offer now
    (:func:`note_offer`); while the node waits for the user's pick, the chats
    that asked get the same card first. Any other chat's card changes
    nothing. Never raises: the card is in the Finder's chat either way."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects import storage as projects_storage

    discovery_id = part.get("discoveryId") if isinstance(part, dict) else None
    if not discovery_id:
        return
    try:
        spec = projects_storage.read_spec(user_key, project_id)
        record = attachments.get_attachment(spec or {}, attachment_id) or {}
        target = record.get("target") or {}
        node_id = target.get("targetId")
        if target.get("kind") != "node" or not node_id:
            return
        if (finder_attachment(spec, node_id, user_key=user_key) or {}).get("attachmentId") != attachment_id:
            return
        node = next(
            (n for n in ((spec or {}).get("dataflow") or {}).get("nodes") or []
             if isinstance(n, dict) and n.get("id") == node_id),
            {"id": node_id},
        )
        state = record.get(RECORD_KEY) if isinstance(record.get(RECORD_KEY), dict) else None
        if source_wait(state) == WAITS_FOR_PICK:
            for asker in askers_of(state):
                if asker != attachment_id:
                    _mirror_candidates_turn(
                        user_key, project_id, asker, attachment_id, node, part, _rows_in(part),
                        finder_name=_finder_name(user_key, record),
                    )
        with projects_storage.spec_write_lock(user_key, project_id):
            fresh = dataflow_docs.live(user_key, project_id)
            if fresh is not None and note_offer(fresh, attachment_id, discovery_id, count=_rows_in(part)) is not None:
                dataflow_docs.write(user_key, project_id, fresh, dataflow_docs.by_curio(user_key, "dataset"))
    except Exception:  # noqa: BLE001
        log.warning("Could not record the candidates card of attachment %s", attachment_id, exc_info=True)
