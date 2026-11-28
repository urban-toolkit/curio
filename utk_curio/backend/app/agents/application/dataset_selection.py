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
from utk_curio.backend.app.agents.application import editors as agents_editors
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import node_solve as agents_node_solve
from utk_curio.backend.app.agents.application.solve import node_work as agents_node_work
from utk_curio.backend.app.agents.application.solve import simulation as agents_simulation
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.agents.infrastructure import agent_jobs as agents_agent_jobs
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.projects import editor_requests as projects_editor_requests
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)

#: What an agent a selection is recorded on declares.
SELECT = "dataset.select"

#: What a selection's delegation says when a plan waits for the node: the
#: plan's agent goes on with it (:func:`_plan_waiting`), and nothing builds
#: beside.
PLAN_WAITING = "plan-waiting"


def record_dataset_selection(
    user_key: str, project_id: str, attachment_id: str, picks: object,
    guest: bool = False, owner_reviews: str | None = None, discovery_id: str | None = None,
) -> dict:
    """dev/126: record the user's confirmed dataset selection for a node.

    The picks are ``{lane, key}`` pairs (a catalog row's ``datasetId`` or an
    external row's ``url``), resolved against the candidates card they were
    made on (*discovery_id*), persisted in this attachment's own session, or
    against the LATEST card when the pick names none. The client therefore
    sends identifiers only: a source the runtime never proposed (and never
    probed) cannot enter through this endpoint. External picks are re-probed
    at confirmation time through the ``DEC-053`` chokepoint, and the verdict
    is what the record keeps: an unreachable pick does not resolve the node.

    A pick on a card the Finder's record no longer offers is refused (409): a
    card newer candidates replaced, one whose node needs no pick any more, or
    one gone with a cleared chat. So a pick is never read against another
    card's rows, and starts no build beside the plan.

    A pick of a Data Catalog dataset the dataflow does not hold adds it to
    the dataflow at once, as a pick downloads a row Curio downloads (the
    owner's "Pick adds it", 11-26): :func:`_add_catalog_picks`.

    *owner_reviews* names the dataflow's owner when an editor the owner
    invited confirms: a pick Curio would download into the Data Catalog then
    refuses the whole confirmation, before anything is downloaded or recorded
    (``editors.download_refusal``), and a pick of a dataset the dataflow does
    not hold asks the owner to add it, as his Add to project does, and waits
    for her review. The record keeps his account (``pickedBy``): once her
    Apply ends the wait, the plan that waited goes on from his tab
    (:func:`settle_source_waits`, :func:`claim_goes_on`).
    """

    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    coord = str(record.get("coord") or "")
    name = agents_spec_reads._agent_name(user_key, coord) or coord
    if not agents_spec_reads._declares(user_key, coord, SELECT):
        # The agent a selection belongs to, as its manifest names it: the
        # dataflow's own, else the shipped one.
        selector = agents_spec_reads._agent_name(
            user_key, agents_spec_reads._installed_coord_declaring(spec, SELECT, user_key=user_key) or "",
        ) or agents_spec_reads._shipped_name_declaring(SELECT) or "dataset selector"
        raise AgentServiceError(
            f"a dataset selection belongs to a {selector} attachment, an agent that "
            f"declares {SELECT}; {name} does not",
            400,
        )
    target = record.get("target") or {}
    if target.get("kind") != "node":
        raise AgentServiceError(
            f"a dataset selection belongs to a {name} attached to a node, not to the "
            f"{target.get('kind') or 'dataflow'}",
            400,
        )
    session_id = record.get("sessionId")
    turns = (
        sessions.read_turns(user_key, project_id, session_id)
        if isinstance(session_id, str) else []
    )
    cards = [
        p for turn in turns for p in (turn.get("content") or [])
        if isinstance(p, dict) and p.get("type") == "datasetCandidates"
    ]
    if discovery_id is None:
        part = cards[-1] if cards else None
    else:
        _still_offered(record, discovery_id, name)
        part = next((p for p in reversed(cards) if p.get("discoveryId") == discovery_id), None)
        if part is None:
            raise AgentServiceError(f"these candidates are no longer in the {name}'s chat", 409)
    rows = _resolved_picks(user_key, project_id, part, picks, editor=owner_reviews is not None)
    roster = _probe_the_external_picks_again(rows)
    if owner_reviews is not None and any(r["lane"] == "external" and r.get("acquirable") for r in rows):
        raise AgentServiceError(agents_editors.download_refusal(owner_reviews), 403)
    # A row Curio can download is downloaded now, by the Discovery Catalog, and
    # recorded as the catalog pick it becomes, titled as its portal titles it.
    acquisitions = agents_acquire._acquire_confirmed_picks(rows, roster=roster)
    node_id = str(target.get("targetId") or "")
    # Before the spec lock, which the add's own write takes.
    added = _add_catalog_picks(user_key, project_id, spec, rows, node_id=node_id, owner_reviews=owner_reviews)
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = agents_spec_reads._live_spec_or_404(user_key, project_id)
        if discovery_id is not None:
            # Newer candidates may have come while the picks were checked.
            _still_offered(agents_spec_reads._record_or_404(fresh, attachment_id), discovery_id, name)
        state = agents_dataset_resolution.record_selection(
            fresh, attachment_id, rows, picked_from=(part or {}).get("discoveryId"),
        )
        if state is None:
            raise AgentServiceError(f"attachment {attachment_id!r} not found", 404)
        if (added or {}).get("status") == OWNER_REVIEW:
            state["pickedBy"] = added["by"]
        # A plan that waits for the node waits as the record now says: for
        # the download or the install of the pick, or no more, and then its
        # agent goes on with it (or its running Build & validate builds it).
        moved = agents_simulation.follow_the_sources(user_key, fresh)
        waiting_plan = _plan_waiting_for(fresh, node_id)
        dataflow_docs.write(user_key, project_id, fresh, agents_spec_reads._person(user_key, "dataset"))
    released = next((m for m in moved if m["nodeId"] == node_id and m["state"] == "created"), None)
    payload = {
        "attachmentId": attachment_id,
        "nodeId": target.get("targetId"),
        "status": state["status"],
        "picks": rows,
    }
    askers = agents_dataset_resolution.askers_of(state)
    if askers:
        # The chats that asked for the candidates and hold their card, which
        # say the source is recorded too.
        payload["askedBy"] = askers[0]
        payload["askers"] = askers
    # dev/132 (R1): a confirmed row code can FETCH is handed to the node's own
    # builder automatically: the owner asked for the delegation, not for a
    # prompt they must compose. A manual row is not delegated: its file does
    # not exist yet, and its card teaches the download and offers Import.
    if acquisitions:
        payload["acquisitions"] = acquisitions
    delegated = _delegate_confirmed_fetch(
        user_key, project_id, node_id, rows, state, guest=guest, released=released,
    ) or agents_acquire._acquisition_outcome(
        acquisitions, once_it_lands=_once_it_lands(user_key, waiting_plan),
    ) or _add_outcome(user_key, added, waiting_plan, node_id)
    if delegated is not None:
        payload["delegated"] = delegated
    after = _what_comes_next(user_key, rows, state, delegated, waiting_plan)
    _keep_what_comes_next(user_key, project_id, attachment_id, state, after)
    _say_the_source_is_recorded(user_key, project_id, fresh, attachment_id, rows, state, after, node_id=node_id)
    return payload


def _resolved_picks(user_key: str, project_id: str, part: dict | None, picks: object, *, editor: bool) -> list[dict]:
    """The rows *picks* name on the card *part*, read again from the Data
    Catalog listing (``dataset_resolution.resolve_picks``); a pick that names
    no such row is refused (422).

    dev/132: the listing, so a dataset the user just imported from the
    card's download steps can be confirmed, though the card predates the
    file. For an *editor* the owner invited, a row of the card his listing
    does not hold is read from the owner's (her own datasets, which a card a
    run of hers made offers), so his pick asks her to add it
    (:func:`_add_catalog_picks`); a dataset of hers no card offered is never
    read for him."""
    try:
        return agents_dataset_resolution.resolve_picks(
            part, picks,
            catalog_rows=agents_grounding._catalog_rows_for_discovery(user_key, project_id),
            owners_listing=(
                (lambda: agents_grounding._catalog_rows_for_discovery(
                    user_key, project_id, user=agents_spec_reads._dataflow_owner(project_id)))
                if editor else None
            ),
        )
    except agents_dataset_resolution.DatasetResolutionError as exc:
        raise AgentServiceError(str(exc), 422) from exc


def _probe_the_external_picks_again(rows: list[dict]) -> "agents_roster._LazyRoster":
    """Probe each external pick again, and say again what can be done with
    it: the card may be minutes or days old, and the record must carry what
    is true now (the row keeps its own mint-time verdict in the transcript
    either way), as the delegation that follows depends on it (dev/132).
    Returns the roster it was confirmed with, which holds what each portal
    described of its rows, the title of each resource among it."""
    budget = egress.CallBudget(agents_budgets.RUN_EGRESS_CALLS)
    roster = agents_roster._LazyRoster()
    for row in rows:
        if row["lane"] != "external":
            continue
        if row.get("url"):
            row["verification"] = verify.verify_external_source(row["url"], budget=budget)
            agents_mint._mint_row_access(row)
        agents_acquire._mint_row_acquirable(row, roster, budget)
    return roster


def settle_source_waits(user_key: str, project_id: str) -> None:
    """End each wait of a node's source that came to an end outside a Solve:
    a pick whose dataset the dataflow holds now, as the owner's Apply of an
    editor's request adds it, or whose download landed; a plan that waited
    for such a node goes on (``acquire._settle_discovery_acquisitions``).
    Registered with the editor requests (``projects/editor_requests.py``,
    ``when_applied``), whose Apply calls it with the dataflow's owner key.

    Her Apply starts no build: it approves adding the dataset, not spending
    a build. What waited for a node whose source an editor picked goes on as
    after his own pick, from his tab: the Finder's record keeps how
    (:func:`_keep_how_it_goes_on`), which his tab takes once
    (:func:`claim_goes_on`)."""
    waiting = _waiting_for_the_owner(user_key, project_id)
    moved = agents_acquire._settle_discovery_acquisitions(user_key, project_id) or []
    if waiting:
        _keep_how_it_goes_on(user_key, project_id, waiting, moved)


#: The status of a go-on outside a plan (``goesOn``): the node's builder writes
#: the loader, as a direct pick outside a plan starts it
#: (:func:`_delegate_confirmed_fetch`); and what it says.
BUILDS_THE_NODE = "builds-the-node"
_THE_BUILDER_WRITES_IT = "the node's builder writes the loader from this source"


def _waiting_for_the_owner(user_key: str, project_id: str) -> dict[str, str]:
    """Each Dataset Finder whose record waits for the install of an editor's
    pick (``pickedBy``), with its node's id: read before an Apply's settle,
    so that a go-on is kept for the picks the Apply ends, and no other."""
    waiting: dict[str, str] = {}
    for record in attachments.list_attachments(projects_storage.read_spec(user_key, project_id) or {}):
        state = record.get(agents_dataset_resolution.RECORD_KEY)
        target = record.get("target") or {}
        if (isinstance(state, dict) and state.get("pickedBy")
                and state.get("status") == agents_dataset_resolution.STATE_AWAITING_INSTALL
                and target.get("kind") == "node" and target.get("targetId")):
            waiting[str(record.get("attachmentId"))] = str(target["targetId"])
    return waiting


def _keep_how_it_goes_on(user_key: str, project_id: str, waiting: dict[str, str], moved: list[dict]) -> None:
    """For each pick of an editor the owner's Apply ended (*waiting*, by its
    Finder, before the settle), the Finder's record keeps how what waited for
    the node goes on (``goesOn``), which his tab takes, and its sentence as
    what comes of the pick (``next``): the answer a direct pick gives,
    :func:`_plan_waiting`'s, for a plan node the settle put back to
    ``created`` (*moved*, ``simulation.follow_the_sources``' entries), or,
    with no plan waiting for the node, the node's builder starting, as a
    direct pick outside a plan starts it. A plan whose Build & validate runs
    now builds the node itself, and needs none."""
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = dataflow_docs.live(user_key, project_id)
        if fresh is None:
            return
        kept = False
        for finder_id, node_id in waiting.items():
            finder = attachments.get_attachment(fresh, finder_id)
            state = (finder or {}).get(agents_dataset_resolution.RECORD_KEY)
            if not (isinstance(state, dict) and state.get("pickedBy")
                    and state.get("status") == agents_dataset_resolution.STATE_RESOLVED):
                continue
            released = next((m for m in moved if m.get("nodeId") == node_id and m.get("state") == "created"), None)
            if released is not None:
                goes_on = _plan_waiting(user_key, node_id, released)
                if not goes_on["continueWith"]:
                    continue
            elif agents_simulation.plan_waiting_on(fresh, node_id) is None:
                goes_on = {"status": BUILDS_THE_NODE, "nodeId": node_id, "reason": _THE_BUILDER_WRITES_IT}
            else:
                continue
            state["goesOn"] = goes_on
            state["next"] = _sentence(goes_on["reason"])
            finder["revision"] = int(finder.get("revision", 1)) + 1
            kept = True
        if kept:
            dataflow_docs.write(user_key, project_id, fresh, dataflow_docs.by_curio(user_key, "dataset"))


def claim_goes_on(user_key: str, project_id: str, attachment_id: str) -> dict | None:
    """How the plan that the pick on this Dataset Finder (*attachment_id*)
    waited on goes on, once the owner added the dataset an editor picked: the
    answer a direct pick gives (``plan-waiting``, :func:`_plan_waiting`), for
    the tab of the editor who picked (``pickedBy``), once, which goes on with
    it as after his own pick. The record's ``goesOn`` waits for that tab, if
    it was closed when she applied, and goes as it is answered.

    Outside a plan (``builds-the-node``), the node's builder starts from his
    request, as a direct pick outside a plan starts it, through the same
    :func:`_delegate_confirmed_fetch`, whose answer (``delegating``) this is.

    None for any other account, which takes nothing; and None, the record's
    ``goesOn`` taken off, once it went on without it: the plan's node built or
    waiting again, or a Build & validate or the row's Solve running on it; a
    node outside a plan given code meanwhile."""
    account = str(getattr(agents_spec_reads._acting_user(), "id", "") or "")
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = agents_spec_reads._live_spec_or_404(user_key, project_id)
        record = agents_spec_reads._record_or_404(fresh, attachment_id)
        state = record.get(agents_dataset_resolution.RECORD_KEY)
        goes_on = state.get("goesOn") if isinstance(state, dict) else None
        if not isinstance(goes_on, dict) or not account or state.get("pickedBy") != account:
            return None
        state.pop("goesOn")
        record["revision"] = int(record.get("revision", 1)) + 1
        outside = goes_on.get("status") == BUILDS_THE_NODE
        still = _node_waits_for_its_builder(fresh, goes_on) if outside else _still_waits_to_go_on(fresh, goes_on)
        picks = [dict(pick) for pick in state.get("picks") or [] if isinstance(pick, dict)]
        resolved = dict(state)
        dataflow_docs.write(user_key, project_id, fresh, agents_spec_reads._person(user_key, "dataset"))
    if not still:
        return None
    if outside:
        return _delegate_confirmed_fetch(user_key, project_id, str(goes_on.get("nodeId") or ""), picks, resolved)
    return goes_on


def _node_waits_for_its_builder(spec: dict, goes_on: dict) -> bool:
    """Whether the node of a go-on outside a plan (*goes_on*'s ``nodeId``)
    still waits for its builder: it holds no code yet, and no plan waits for
    it."""
    node_id = goes_on.get("nodeId")
    node = next((n for n in (spec.get("dataflow") or {}).get("nodes") or []
                 if isinstance(n, dict) and n.get("id") == node_id), None)
    return (node is not None and not str(node.get("content") or "").strip()
            and agents_simulation.plan_waiting_on(spec, str(node_id)) is None)


def _still_waits_to_go_on(spec: dict, goes_on: dict) -> bool:
    """Whether the plan of *goes_on* (its agent, ``ref`` and ``nodeId``) still
    waits to go on with that node: placed again and not built since, with no
    Build & validate or row's Solve running on it."""
    plan = attachments.get_attachment(spec, str(goes_on.get("attachmentId") or "")) or {}
    session = plan.get("builderSession") if isinstance(plan.get("builderSession"), dict) else {}
    ref = goes_on.get("ref")
    return (
        (session.get("nodeIds") or {}).get(ref) == goes_on.get("nodeId")
        and (session.get("nodeStates") or {}).get(ref) == "created"
        and agents_node_work.build_running(session) is None
        and agents_node_work.row_solve_running(session) is None
    )


# The owner's Apply of an editor's request ends the wait of a pick for what it
# added, at once: the projects package tells what it applied, and imports
# nothing of the agents.
projects_editor_requests.when_applied(settle_source_waits)


#: What a pick's answer says when its Data Catalog dataset waits for the
#: dataflow owner's review of an editor's request, and when it could not be
#: added to the dataflow.
OWNER_REVIEW = "owner-review"
ADD_FAILED = "add-failed"


def _add_catalog_picks(user_key: str, project_id: str, spec: dict, rows: list[dict], *, node_id: str,
                       owner_reviews: str | None) -> dict | None:
    """The owner's "Pick adds it" (11-26): each picked Data Catalog dataset
    the dataflow does not hold is added to it now, as Add to project adds it
    (``acquire._add_to_the_dataflow``), so the pick resolves the node and a
    plan that waits for it goes on. So is a dataset already in the account's
    store: one the pick's download landed (``imported``), and one imported
    from a card's download steps.

    An editor the owner invited (*owner_reviews*, her name) changes no
    account but his own: his pick asks her to add the dataset, as his Add to
    project does (``projects/editor_requests.py``, the request naming the
    node of *spec*, as its header does), whether it is his, the shared
    catalog's or one of her own a card offered (:func:`_ask_the_owner`), and
    waits for her review. Her Apply adds it and ends the wait
    (:func:`settle_source_waits`).

    A pick whose download outlasted the confirmation's wait (``acquiring``)
    names no dataset yet: its landing adds it (``_settle_discovery_acquisitions``).

    Returns a summary while a pick still waits: ``owner-review`` with the
    names, the owner and his account, or ``add-failed`` with why the Data
    Catalog refused the add. None when the dataflow holds every pick."""
    needed = [
        row for row in rows
        if row.get("lane") == "catalog" and row.get("datasetId") and not row.get("acquiring")
        and not row.get("installed")
    ]
    if not needed:
        return None
    user = agents_spec_reads._acting_user()
    if owner_reviews is not None:
        return _ask_the_owner(user, project_id, needed, node_id=node_id, owner=owner_reviews,
                              node_name=_node_name(user_key, project_id, spec, node_id))
    refused = agents_acquire._add_to_the_dataflow(user, project_id, needed)
    if refused is None:
        return None
    row, exc = refused
    name = row.get("name") or row.get("datasetId")
    # The sentence opens with Curio's words: a name keeps its own case.
    return {"status": ADD_FAILED,
            "reason": f"the picked dataset {name} could not be added to the dataflow: {str(exc)[:200]}"}


def _node_name(user_key: str, project_id: str, spec: dict | None, node_id: str) -> str:
    """The node *node_id* of *spec*, named as its header on the canvas names
    it (``dataset_resolution.node_label``)."""
    node = next(
        (n for n in ((spec or {}).get("dataflow") or {}).get("nodes") or []
         if isinstance(n, dict) and n.get("id") == node_id),
        {"id": node_id},
    )
    return agents_dataset_resolution.node_label(user_key, project_id, node)


def _ask_the_owner(user, project_id: str, rows: list[dict], *, node_id: str, owner: str,
                   node_name: str | None = None) -> dict | None:
    """An editor's request that the dataflow's *owner* add each of *rows*,
    naming the node *node_id* and its name (*node_name*), which her card
    shows: a dataset of his, which her Apply copies into her store, one of
    the shared catalog, or one of her own, which a card of a run of hers
    offered (``owners_own``: the listing he picked from vouched for each row,
    :func:`_resolved_picks`). A dataset the dataflow holds already needs no
    request.

    Every row is checked before any is asked for, so a row the requests
    refuse, one no Data Catalog holds any more, refuses the pick (422) and
    leaves no request of its other rows in her review."""
    for row in rows:
        _asked_of_the_owner(user, project_id, row, node_id=node_id, check=True)
    waiting = []
    for row in rows:
        if _asked_of_the_owner(user, project_id, row, node_id=node_id, node_name=node_name).get("requested"):
            waiting.append(str(row.get("name") or row["datasetId"]))
        else:
            row["installed"] = True
    if not waiting:
        return None
    return {"status": OWNER_REVIEW, "names": waiting, "owner": owner, "by": str(getattr(user, "id", "") or "")}


def _asked_of_the_owner(user, project_id: str, row: dict, *, node_id: str, node_name: str | None = None,
                        check: bool = False) -> dict:
    """The editor's request for the dataset of *row* (:func:`_ask_the_owner`),
    or with *check* the request's checks alone, which ask for nothing. A
    refusal is the pick's: the request's own status, or a 422 for a dataset
    no Data Catalog holds."""
    from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

    dataset_id = str(row["datasetId"])
    try:
        if check:
            projects_editor_requests.check(user, project_id, "datasets", dataset_id, add=True, owners_own=True)
            return {}
        return projects_editor_requests.ask(user, project_id, "datasets", dataset_id, node_id=node_id,
                                            node_name=node_name, add=True, owners_own=True)
    except projects_editor_requests.RequestError as exc:
        raise AgentServiceError(str(exc), exc.status) from exc
    except DatasetCatalogError as exc:
        raise AgentServiceError(
            f"{row.get('name') or dataset_id!r} is not in the Data Catalog: select a dataset it holds", 422,
        ) from exc


def _add_outcome(user_key: str, added: dict | None, waiting_plan: dict | None, node_id: str) -> dict | None:
    """What a pick's answer says of a picked Data Catalog dataset that still
    waits (*added*, :func:`_add_catalog_picks`): for the owner's review, then
    what builds the loader once she added it (:func:`_once_it_is_added`), or
    why the add failed. The sentence opens with Curio's words, so a name it
    holds keeps its own case (:func:`_sentence`)."""
    if not added or added.get("status") != OWNER_REVIEW:
        return added
    names = ", ".join(added["names"])
    return {
        "status": OWNER_REVIEW,
        "reason": f"the pick waits for {added['owner']}, who owns this dataflow, to add {names} from the "
                  f"requests in the Data Catalog's drawer; {_once_it_is_added(user_key, node_id, waiting_plan)}",
    }


def _once_it_is_added(user_key: str, node_id: str, waiting_plan: dict | None) -> str:
    """What builds the loader once the dataflow's owner adds the dataset an
    editor's pick asked her for, from the tab of the editor who picked, which
    takes it whenever it is open once her Apply landed (:func:`claim_goes_on`):
    the plan that waits for the node goes on as after a direct pick, in its
    words (:func:`_plan_waiting`); outside a plan, the node's builder writes
    the loader, as a direct pick outside a plan has it. No control is named:
    her Apply ends a plan's pause, and Resume with it."""
    if not waiting_plan:
        return f"once it is added, {_THE_BUILDER_WRITES_IT}"
    return "once it is added, " + _plan_waiting(user_key, node_id, waiting_plan)["reason"]


def _plan_waiting_for(spec: dict, node_id: str) -> dict | None:
    """The landed plan whose node *node_id* waits for its source
    (``simulation.plan_waiting_on``) and what left the node waiting
    (``waitedBy``, from the plan's ``sourceWaitBy``), as
    ``simulation.follow_the_sources`` says it of a node it puts back: how the
    plan goes on once it does. None when no plan waits for it."""
    waiting = agents_simulation.plan_waiting_on(spec, node_id)
    if waiting:
        plan = attachments.get_attachment(spec, str(waiting.get("attachmentId") or "")) or {}
        waited_by = ((plan.get("builderSession") or {}).get("sourceWaitBy") or {}).get(waiting.get("ref"))
        waiting["waitedBy"] = waited_by
    return waiting


def _still_offered(record: dict, discovery_id: str, name: str) -> None:
    """Refuse a pick on the candidates card *discovery_id* (409) unless the
    Finder's *record* offers it now: newer candidates replaced it, or the
    node needs no pick from it any more (a skip, or the card went with a
    cleared chat)."""
    offered = ((record or {}).get(agents_dataset_resolution.RECORD_KEY) or {}).get("discoveryId")
    if offered == discovery_id:
        return
    if offered:
        raise AgentServiceError("newer candidates replaced these: pick one on the newest card", 409)
    raise AgentServiceError(f"the {name} no longer asks for a pick on these candidates", 409)


def _plan_agent_name(user_key: str, coord: str) -> str:
    """The plan's agent, as its manifest names it."""
    return agents_spec_reads._agent_name(user_key, coord) or coord.split("@", 1)[0]


def _once_it_lands(user_key: str, waiting_plan: dict | None) -> str:
    """What builds the loader once its source is here, for a source that
    downloads or waits for its install (*waiting_plan*, the plan that still
    waits for the node, from ``simulation.plan_waiting_on``): Solve the node
    when no plan waits for it; else nothing settles the source's arrival by
    itself, so the plan's Resume does when its build paused on the node or
    runs on the plan, and the node's row's Solve otherwise."""
    if not waiting_plan:
        return "Solve the node once it lands"
    name = _plan_agent_name(user_key, waiting_plan["coord"])
    action = "Resume" if waiting_plan.get("pausedOn") or waiting_plan.get("running") else "its row's Solve"
    return f"once it lands, press {action} in the {name}'s chat to build the loader"


def _sentence(reason: str) -> str:
    """*reason* as a sentence: capitalized, ending with a period. Every
    reason a pick's answer gives opens with Curio's own words, never with a
    name, whose case a sentence never changes ("x8fc-8rcq.geojson")."""
    reason = reason.strip().rstrip(".")
    return f"{reason[:1].upper()}{reason[1:]}." if reason else ""


def _what_comes_next(user_key: str, rows: list[dict], state: dict, delegated: dict | None,
                     waiting_plan: dict | None) -> str:
    """What comes of the pick, in one sentence, as the server decided it: the
    plan going on, the node's builder writing the loader, a portal file to
    import, a download or an install to wait for and what builds the loader
    then, or what the user must do. Both chats' Source recorded turns end
    with it, and the Finder's record keeps it (``next``), which a card the
    pick left open shows in every tab. A Recorded card names only the pick
    and where it comes from, so each chat says this once, in its turn. It
    never promises a build nobody starts."""
    status = (delegated or {}).get("status")
    reason = str((delegated or {}).get("reason") or "")
    if status in (PLAN_WAITING, "no-builder", "acquire-failed", OWNER_REVIEW, ADD_FAILED):
        return _sentence(reason)
    if status == "delegating":
        return f"Its {(delegated or {}).get('name') or 'builder'} is writing the loader from this source."
    if status == "session-running":
        return "The running Solve picks this node up on its next pass."
    if status == "manual-download":
        return ("It is a portal download: follow the steps on its card and use Import dataset, and the loader is "
                "built from the imported dataset.")
    if status == "skipped":
        return f"The loader's build could not start: {reason.rstrip('.')}."
    then = _once_it_lands(user_key, waiting_plan)
    if any(r.get("acquiring") for r in rows):
        return f"It is downloading into the Data Catalog: {then}."
    if state["status"] == agents_dataset_resolution.STATE_AWAITING_INSTALL:
        if not waiting_plan:
            return "It must be installed from the Data Catalog before Solve can load it."
        return f"It must be installed from the Data Catalog: {then.replace('once it lands', 'once it is')}."
    if state["status"] == agents_dataset_resolution.STATE_RESOLVED:
        return "Solve the node to build its loader from this source."
    return "Nothing selectable was confirmed: its link answered with an error, or not at all. Pick another row."


def _keep_what_comes_next(user_key: str, project_id: str, attachment_id: str, state: dict, after: str) -> None:
    """The Finder's record keeps what comes of its pick (``next``), while it
    still holds that pick: a pick recorded meanwhile keeps its own."""
    if not after:
        return
    try:
        with projects_storage.spec_write_lock(user_key, project_id):
            fresh = agents_spec_reads._live_spec_or_404(user_key, project_id)
            record = attachments.get_attachment(fresh, attachment_id)
            current = (record or {}).get(agents_dataset_resolution.RECORD_KEY)
            if not isinstance(current, dict) or current.get("recordedAt") != state.get("recordedAt") or (
                current.get("picks") != state.get("picks")
            ):
                return
            current["next"] = after
            record["revision"] = int(record.get("revision", 1)) + 1
            dataflow_docs.write(user_key, project_id, fresh, agents_spec_reads._person(user_key, "dataset"))
    except Exception:  # noqa: BLE001 - the Source recorded turns say it either way
        log.warning("Could not keep what comes of the pick on %s", attachment_id, exc_info=True)


def _say_the_source_is_recorded(user_key: str, project_id: str, spec: dict, attachment_id: str,
                                rows: list[dict], state: dict, after: str, *, node_id: str) -> None:
    """The Finder's chat says what was recorded and what comes next (*after*,
    :func:`_what_comes_next`), once the selection's delegation is decided,
    and so does every chat that asked for the candidates and holds their card
    (the record's askers), each in the same words, naming the node as its
    header does. *spec* is the dataflow the selection wrote. Read outside the
    spec lock: a node with no title is named by its template's label, from
    the package store."""
    try:
        names = ", ".join(str(r.get("name") or r.get("datasetId") or r.get("url")) for r in rows)
        lines = [
            f"{r['lane']} · {r.get('name') or r.get('datasetId') or r.get('url')}"
            + (f" · {_verdict_words(r.get('verification'))}"
               if r["lane"] == "external" else
               " · downloading" if r.get("acquiring") else
               (" · installed" if r.get("installed") else " · not installed yet"))
            for r in rows[:8]
        ]
        then = f" {after}" if after else ""
        card = {
            "type": "card",
            "kind": "result" if state["status"] != agents_dataset_resolution.STATE_CANDIDATES_PENDING
            else "error",
            "title": "Dataset selection recorded",
            "lines": lines,
        }
        node = next(
            (n for n in (spec.get("dataflow") or {}).get("nodes") or []
             if isinstance(n, dict) and n.get("id") == node_id),
            {"id": node_id},
        )
        said = f"Source recorded for {agents_dataset_resolution.node_label(user_key, project_id, node)}: {names}.{then}"
        finder_session = (attachments.get_attachment(spec, attachment_id) or {}).get("sessionId")
        if isinstance(finder_session, str):
            sessions.append_turns(
                user_key, project_id, finder_session, attachment_id,
                [sessions.make_turn("agent", said, content=[card])],
            )
        for asker in [a for a in agents_dataset_resolution.askers_of(state) if a != attachment_id]:
            asker_session = (attachments.get_attachment(spec, asker) or {}).get("sessionId")
            if isinstance(asker_session, str):
                sessions.append_turns(
                    user_key, project_id, asker_session, asker,
                    [sessions.make_turn("agent", said, content=[card])],
                )
    except Exception:  # noqa: BLE001
        log.warning("Could not log the dataset selection for %s", attachment_id,
                    exc_info=True)


def _verdict_words(verification: dict | None) -> str:
    """What an external pick's link answered, in the words its card's chip
    says it (``verificationChip.tsx``)."""
    verification = verification if isinstance(verification, dict) else {}
    status = verification.get("status")
    if status == verify.VERIFIED:
        return "web page" if verification.get("webPage") else "verified"
    if status in verify.FAILED_STATUSES:
        http_status = verification.get("httpStatus")
        return f"answered {http_status}" if isinstance(http_status, int) else "unreachable"
    return str(status or "unverified")


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
    released: dict | None = None,
) -> dict | None:
    """dev/132 (R1): start the node's own builder on the confirmed source.

    The owner's instruction — *"The datafinder should be able to automatically
    delegate the code to fetch external api datasets"* — closes `DEC-047`'s
    manual seam: the Finder no longer composes a prompt for the user to send.
    Nothing here authors anything itself: it starts the SAME detached per-node
    Solve the user's own button starts (dev/115, `DEC-073`), which reads the
    recorded source (dev/126), verifies before writing (dev/129) and lands
    its code in a node that already has some as the agent's change, with its
    Undo.

    Returns what happened — ``delegating`` with the job's execution id,
    ``session-running`` when dev/131's session will pick the node up on its
    next pass (its record just moved, which is exactly its trigger),
    ``plan-waiting`` when a plan's Build & validate or its row's Solve
    stopped at the node to wait for its source, which the pick ended
    (*released*, from ``simulation.follow_the_sources``: the plan's agent goes
    on with it, so nothing builds here), ``manual-download`` when the
    file is still on a portal, or a reason, never raising: a selection is
    recorded whether or not a build can start.

    The build runs on the BUILDER's LLM configuration, resolved once it is
    picked: the selection was posted to the Dataset Finder, whose choice in API
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
                    "this source is a portal download: follow the steps on the "
                    "card and use Import dataset; solving continues from the "
                    "imported dataset"
                ),
            }
    elif _a_session_runs(user_key, project_id):
        return {
            "status": "session-running",
            "reason": "the running Solve session picks this node up on its next pass",
        }
    # A plan that stopped at this node to wait for its source goes on with it
    # itself: started here too, the loader would be built twice.
    if released is not None:
        return _plan_waiting(user_key, node_id, released)
    if not fetchable:
        return None
    try:
        spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    except AgentServiceError:
        return None
    # dev/132: the node's content agent writes its fetch code (`DEC-047`).
    builder = agents_spec_reads._node_attachment_declaring(
        spec, "node.content.generate", node_id, user_key=user_key,
    )
    if builder is None:
        writer = agents_spec_reads._shipped_name_declaring("node.content.generate")
        return {
            "status": "no-builder",
            "reason": (
                "no builder is attached to this node: Solve the node, or attach "
                + (f"a {writer} to it" if writer else "an agent that writes node content to it")
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
        # The builder that writes the loader, as its manifest names it.
        "name": builder_name,
        "sources": [
            str(r.get("name") or r.get("datasetId") or r.get("url") or "")[:120]
            for r in fetchable[:8]
        ],
        **({"executionId": job.job_id} if job is not None else {}),
    }


def _a_session_runs(user_key: str, project_id: str) -> bool:
    """Whether a running dataflow session owns the dataflow's nodes: dev/131
    re-reads the spec each pass, and a moved selection record IS the change
    it watches for. Two builders on one node would race for its content."""
    try:
        spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    except AgentServiceError:
        return False
    for record in attachments.list_attachments(spec):
        job = agents_agent_jobs.live_job(user_key, str(record.get("attachmentId") or ""))
        if job is not None and job.kind == "solve-batch":
            return True
    return False


#: How the plan goes on after the pick, by what left the node waiting
#: (``simulation.follow_the_sources``' ``waitedBy``): as the user was going.
_GOES_ON_WITH = {"auto": "build", "step": "step", "node": "node"}


def _plan_waiting(user_key: str, node_id: str, released: dict) -> dict:
    """What the pick's answer says when it ended a plan's wait for the node
    (*released*, an entry of ``simulation.follow_the_sources``), and how the
    plan goes on. A Build & validate running now builds the loader, and a
    running Step's next Step does: nothing more is to start
    (``continueWith`` None, ``running`` names the run). Otherwise the plan's
    agent goes on by itself, from the tab that picked, as the user was going
    (``waitedBy``): with Build & validate (``build``) after a Build &
    validate, with one Step (``step``) after a Step, and with the plan row's
    Solve (``node``) that left the node waiting, for its ``ref``. A wait no
    record says the cause of goes on with Build & validate when it paused on
    the loader, else with the row's Solve."""
    name = _plan_agent_name(user_key, released["coord"])
    running = released.get("running")
    continue_with = None if running else (
        _GOES_ON_WITH.get(str(released.get("waitedBy") or ""))
        or ("build" if released.get("pausedOn") else "node")
    )
    if running == "auto":
        reason = f"the {name}'s Build & validate, running now, builds the loader from this source"
    elif running == "step":
        reason = f"the {name}'s next Step builds the loader from this source"
    elif continue_with == "step":
        reason = f"the {name} goes on with its plan by one Step, as you were stepping"
    else:
        reason = f"the {name} goes on with its plan and builds the loader from this source"
    return {
        "status": PLAN_WAITING,
        "attachmentId": released["attachmentId"],
        "nodeId": node_id,
        "ref": released.get("ref"),
        "running": running,
        "continueWith": continue_with,
        "reason": reason,
    }
