"""The Discovery Catalog acquisition proposal: a row minted as acquirable, the confirmed picks applied through the discovery service, the outcome settled.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging
import time
import uuid

from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.application import dataset_resolution as agents_dataset_resolution
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.agents.application.solve import simulation as agents_simulation
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.agents.domain import agent_text

log = logging.getLogger(__name__)


def _acquire_format(row: dict) -> str | None:
    """The format to download a confirmed row as, when it can be named: a
    ``direct`` row's from the content type the probe saw, a connector row's
    from its own ``format`` when that is one the Discovery Catalog accepts."""
    from utk_curio.backend.app.discovery.domain import formats
    from utk_curio.backend.app.discovery.domain.manifest import DISCOVERY_ACQUIRABLE_FORMATS

    probed = formats.CONTENT_TYPE_FORMATS.get(formats.content_type_of(
        {"Content-Type": str((row.get("verification") or {}).get("contentType") or "")}
    ))
    if probed and row.get("resourceId") == row.get("url"):
        return probed
    named = str(row.get("format") or "").strip().lower()
    return named if named in DISCOVERY_ACQUIRABLE_FORMATS else None


def _acquire_confirmed_picks(rows: list[dict]) -> list[dict]:
    """Download every confirmed acquirable row through the Discovery Catalog, and record
    each as the catalog pick it becomes.

    The download is ``DiscoveryService.start_acquire``, the one the Discovery Catalog page
    uses, so the dataset carries its ``discoverySource`` and a resource the account
    already holds is not fetched again. It is not handed to a builder: the
    builder writes fetch code, and here Curio fetches. Every download shares one
    wait. One that lands inside it becomes an imported catalog pick; one still
    running becomes a pick that is ``acquiring``, settled by
    ``_settle_discovery_acquisitions`` once the dataset is held. Returns one summary
    per download.
    """
    from utk_curio.backend.app.discovery.domain.errors import DiscoveryError

    summaries: list[dict] = []
    running: list[tuple[int, dict, str]] = []
    service = None
    for index, row in enumerate(rows):
        if row.get("lane") != "external" or not row.get("acquirable"):
            continue
        service = service or _discovery_service()
        summary = {"name": row.get("name"), "sourceId": row["sourceId"],
                   "resourceId": row["resourceId"]}
        try:
            started = service.start_acquire(
                row["sourceId"], row["resourceId"], fmt=_acquire_format(row),
            )
        except DiscoveryError as exc:
            row["acquireError"] = str(exc)[:200]
            summaries.append({**summary, "status": "failed", "error": row["acquireError"]})
            continue
        if started.get("alreadyPresent"):
            dataset_id = (started.get("dataset") or {}).get("id")
            rows[index] = agents_dataset_resolution.acquired_pick(row, dataset_id)
            summaries.append({**summary, "status": "acquired", "datasetId": dataset_id,
                              "alreadyPresent": True})
        else:
            running.append((index, summary, str(started.get("jobId") or "")))
    deadline = time.monotonic() + _DISCOVERY_APPLY_WAIT_S
    for index, summary, job_id in running:
        row = rows[index]
        outcome = _await_discovery_job(service, job_id, deadline=deadline) or {}
        status = outcome.get("status")
        dataset_id = outcome.get("datasetId") or (outcome.get("dataset") or {}).get("id")
        if status == "completed" and dataset_id:
            rows[index] = agents_dataset_resolution.acquired_pick(row, dataset_id)
            summaries.append({**summary, "status": "acquired", "datasetId": dataset_id})
        elif status in ("failed", "refused", "cancelled"):
            row["acquireError"] = str(outcome.get("error") or f"the download was {status}")[:200]
            summaries.append({**summary, "status": "failed", "error": row["acquireError"]})
        else:
            rows[index] = agents_dataset_resolution.acquiring_pick(row, job_id)
            summaries.append({**summary, "status": "acquiring", "jobId": job_id})
    return summaries


def _acquisition_outcome(acquisitions: list[dict], *,
                         once_it_lands: str = "Solve the node once it lands") -> dict | None:
    """What the confirmation says when no builder was started: a download still
    running, or one that failed. A running download's reason ends with what
    builds the loader once it lands (*once_it_lands*): nothing settles its
    landing by itself, so the user's Solve of the node, or, for a loader a
    plan waits on, the plan's Resume or the node's row's Solve
    (``dataset_selection._once_it_lands``)."""
    running = [a for a in acquisitions if a.get("status") == "acquiring"]
    failed = [a for a in acquisitions if a.get("status") == "failed"]
    if running:
        names = ", ".join(str(a.get("name") or a.get("resourceId")) for a in running)
        return {
            "status": "acquiring",
            "jobIds": [a["jobId"] for a in running],
            "reason": f"{names} is downloading into your Data Catalog; {once_it_lands}",
        }
    if failed:
        first = failed[0]
        return {
            "status": "acquire-failed",
            "reason": f"the download of {first.get('name') or first.get('resourceId')} failed: {first.get('error')}",
        }
    return None


def _settle_discovery_acquisitions(user_key: str, project_id: str) -> None:
    """Resolve nodes whose confirmed pick has come since it was confirmed: a
    download that landed, or a dataset the dataflow holds now that a pick
    waited for the install of, however it was added (Add to project, the
    owner's Apply of an editor's request).

    Called at the entry of a Solve, Solve this node and each validation of a
    plan's node (Build & validate, Resume, a row's Solve), while the request's
    user can read the datasets domain (a detached job cannot); an install
    needs only the dataflow. Reads the spec first, so a project with nothing
    to settle costs one read. A plan that waited for such a node goes on with
    it (``simulation.follow_the_sources``): a running Build & validate builds
    it, or the next one does.
    """

    spec = projects_storage.read_spec(user_key, project_id)
    downloading = agents_dataset_resolution.has_acquiring_picks(spec)
    installed = bool(agents_dataset_resolution.installs_awaited(spec) & agents_dataset_resolution.held_datasets(spec))
    if not downloading and not installed:
        return
    held = _held_discovery_resources(project_id) if downloading else {}
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = dataflow_docs.live(user_key, project_id)
        if fresh is None:
            return
        changed = agents_dataset_resolution.settle_acquisitions(fresh, held) if held else []
        changed += agents_dataset_resolution.settle_installs(fresh)
        if changed:
            agents_simulation.follow_the_sources(user_key, fresh)
            dataflow_docs.write(user_key, project_id, fresh, dataflow_docs.by_curio(user_key, "dataset"))


def _held_discovery_resources(project_id: str) -> dict:
    """What the acting user's store holds from the Discovery Catalog, by
    ``(sourceId, resourceId)``; empty with no request's user, or a store that
    cannot be read."""
    user = agents_spec_reads._acting_user()
    if user is None:
        return {}
    try:
        from utk_curio.backend.app.datasets.repositories.user_store import (
            UserDatasetRepository,
        )

        return UserDatasetRepository(user).discovery_resource_index()
    except Exception:  # noqa: BLE001 - an unreadable store settles nothing
        log.warning("Could not read the held Discovery Catalog datasets for project %s",
                    project_id, exc_info=True)
        return {}


def _discovery_service():
    """The Discovery Catalog of the request's account."""
    from flask import g

    return _discovery_service_for(getattr(g, "user", None))


def _discovery_service_for(user):
    """The Discovery Catalog of *user*: the request's account, or the person
    a job's thread runs for, which holds no request (a Solve's
    ``acting_user``). A portal's rate limit and token are that account's."""
    from utk_curio.backend.app.discovery.service import DiscoveryService
    from utk_curio.backend.app.projects.services import _user_dir_key

    return DiscoveryService(
        _user_dir_key(user) if user is not None else None, user=user
    )


def _mint_discovery_acquire(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """Propose downloading ONE portal resource into the Data Catalog.

    **Grounded in a real describe() call**, the way ``_mint_dataset_install`` is
    grounded in ``_resolve_catalog_dataset``: the card shows the portal's own
    name, format and size, not the model's claim about them. A model that
    invented a resource id produces a refusal here rather than a proposal the
    user approves on the strength of a fabricated description.

    Every refusal is honest chat instead of a dead proposal (docs/06
    idempotence), and each names what to do about it.
    """
    from utk_curio.backend.app.discovery.domain.errors import (
        CredentialRequired,
        DiscoveryError,
    )

    params = req.get("params") or {}
    source_id = str(params.get("sourceId") or "").strip()
    resource_id = str(params.get("resourceId") or "").strip()
    fmt = str(params.get("format") or "").strip().lower() or None
    if not source_id or not resource_id:
        return "refused", agent_text.message("acquire.source-and-resource-required"), None

    service = _discovery_service()
    try:
        manifest = service.get_manifest(source_id)
    except DiscoveryError:
        known = [
            row.get("dirName")
            for row in (service.list_catalog().get("sources") or [])
        ]
        return (
            "refused",
            agent_text.message(
                "acquire.unknown-source", source_id=repr(source_id), known=', '.join(str(k) for k in known) or 'none',
            ),
            None,
        )
    if not manifest.capabilities.download:
        return "refused", agent_text.message("acquire.source-offers-no-downloads", name=manifest.name), None
    if manifest.is_storage:
        return (
            "refused",
            agent_text.message("acquire.storage-source-not-offered", name=manifest.name),
            None,
        )
    if manifest.is_service:
        return (
            "refused",
            agent_text.message("acquire.service-source-not-offered", name=manifest.name),
            None,
        )
    if manifest.is_model:
        return (
            "refused",
            agent_text.message("acquire.model-source-not-datasets", name=manifest.name),
            None,
        )

    held = service._acquire.already_held(manifest, resource_id, fmt)
    if held is not None:
        return (
            "refused",
            agent_text.message("acquire.already-held", title=repr(held.get('title'))),
            None,
        )

    try:
        detail = service.describe_resource(source_id, resource_id)
    except CredentialRequired as exc:
        help_url = manifest.auth.help_url
        return (
            "refused",
            agent_text.message(
                "acquire.credential-required", exc=exc, secret_id=manifest.auth.secret_id,
                help=f' ({help_url})' if help_url else '',
            ),
            None,
        )
    except DiscoveryError as exc:
        return "refused", agent_text.message(
            "acquire.describe-failed", name=manifest.name, resource_id=repr(resource_id), exc=exc,
        ), None

    offered = [str(f) for f in (detail.get("formats") or [])]
    if fmt and fmt not in offered:
        return (
            "refused",
            agent_text.message(
                "acquire.format-not-offered", fmt=repr(fmt),
                offered=', '.join(offered) or agent_text.message("acquire.format-not-offered-none"),
            ),
            None,
        )

    spec = dataflow_docs.live(user_key, project_id)
    if spec is None:
        return "refused", agent_text.message("mint.no-saved-spec"), None

    name = str(detail.get("name") or resource_id)
    chosen = fmt or (offered[0] if offered else None)
    proposal_id = uuid.uuid4().hex
    summary = f"Download dataset · {name}"
    preview_bits = [name, manifest.name]
    if chosen:
        preview_bits.append(chosen.upper())
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="discovery.acquire",
        summary=summary,
        preview=" · ".join(preview_bits),
        pins={"sourceId": manifest.dir_name, "resourceId": resource_id, "format": chosen},
    )
    agents_store._store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "discovery.acquire",
            "sourceId": manifest.dir_name,
            "sourceName": manifest.name,
            "resourceId": resource_id,
            "format": chosen,
            "datasetName": name,
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return (
        "proposed",
        agent_text.message("acquire.proposed", proposal_id=proposal_id, name=repr(name), source=manifest.name),
        part,
    )


def _apply_discovery_acquire(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The ONLY path that downloads. Never the model loop.

    Re-resolves the source first: one removed between mint and apply is the
    drift analogue ``_apply_dataset_install`` handles the same way, 409 +
    ``stale``, rather than a confusing failure at the portal.

    Waits briefly on the job so the common case - a small file from a
    responsive portal - answers with the dataset. A slow one hands back the
    job id and says so, which is honest either way and is one code path rather
    than two.
    """
    from utk_curio.backend.app.discovery.domain.errors import DiscoveryError

    source_id = proposal.get("sourceId", "")
    resource_id = proposal.get("resourceId", "")
    service = _discovery_service()
    try:
        service.get_manifest(source_id)
    except DiscoveryError as exc:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"that Discovery Catalog source is no longer available ({exc}) - ask the "
            "agent to search again",
        )
    try:
        started = service.start_acquire(
            source_id, resource_id, fmt=proposal.get("format") or None
        )
    except DiscoveryError as exc:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id, str(exc)
        )

    if started.get("alreadyPresent"):
        dataset = started.get("dataset") or {}
        return {"ok": True, "datasetId": dataset.get("id"), "alreadyPresent": True}

    job_id = started.get("jobId")
    outcome = _await_discovery_job(service, job_id)
    if outcome is not None and outcome.get("status") == "failed":
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            outcome.get("error") or "that download did not finish",
        )
    dataset = (outcome or {}).get("dataset") or {}
    return {
        "ok": True,
        "jobId": job_id,
        "datasetId": dataset.get("id"),
        "status": (outcome or {}).get("status", "running"),
    }


#: How long the apply endpoint waits before handing the job back. Long enough
#: for a small file from a responsive portal, short enough not to hold a
#: request open on a large one.
_DISCOVERY_APPLY_WAIT_S = 20


def _await_discovery_job(service, job_id: str | None, *, deadline: float | None = None) -> dict | None:
    if not job_id:
        return None
    if deadline is None:
        deadline = time.monotonic() + _DISCOVERY_APPLY_WAIT_S
    while time.monotonic() < deadline:
        row = service.get_job(job_id)
        if row.get("status") in ("completed", "failed", "refused", "cancelled"):
            return row
        time.sleep(0.1)
    return None


def _mint_row_acquirable(row: dict, roster: "_LazyRoster", budget=None) -> None:
    """Whether Curio can download this row into the Data Catalog: the one answer.

    The model may name a source; it may not claim the source can be acted on,
    so a model-supplied ``acquirable`` never survives. The answer reads the
    roster, the source and the probe, never the run's grants: a person
    confirming the row uses the download route, which needs only their
    sign-in, and an agent's own ``discovery.acquire`` proposal is checked
    against its grant where it is minted.

    - A connector source (anything but ``direct``) is acquirable when the
      roster has it, it downloads, and it describes the resource: the
      Discovery Catalog confirms the resource id, as for a
      ``discovery.acquire`` proposal, spending one call of *budget*, the
      run's web budget, when one is given. The connector knows how to fetch
      the resource, so the probe of a landing page does not decide it. Once
      the budget is spent the source is not asked: the row keeps its
      coordinate, unconfirmed, and is not acquirable (:func:`_unconfirmed`).
    - A ``direct`` source downloads the URL itself, so the probe decides: an
      https URL the probe read as data, whose content type maps to a format the
      source accepts or which is a zip or a gzip the download unpacks, and
      whose ``resourceId`` is that same URL, so what is downloaded is what was
      probed.

    A row with a plain link and no coordinate gets one minted here, after
    parsing, so it is never model-supplied and never meets the parser's length
    cap: first its portal's, when the link is on a portal of the roster,
    names a dataset id its provider takes and asks for nothing more of it (no
    query; ``_LazyRoster.portal_coordinate``), which Curio downloads whole
    through the portal's own export; then a ``direct`` one, which downloads
    the link as it is, tried when the portal refused its coordinate. A
    coordinate, minted or the model's, stays only when the row qualifies or
    the source was not asked, so one the source refused never reaches a
    download, a builder or a file's provenance. A portal's coordinate the
    spent web budget left unconfirmed stays, as a copied one does, and the
    pick asks the portal with a budget of its own, rather than the link
    alone, which can answer less than the export (a Socrata link with no
    ``$limit`` answers its first 1,000 rows). A downloadable row offers that
    and nothing else, so it carries no portal steps.
    """
    row.pop("acquirable", None)
    url = str(row.get("url") or "")
    if (row.get("sourceId") and row.get("resourceId")) or not url.startswith("https://"):
        _keep_if_acquirable(row, roster, budget)
        return
    direct = roster.direct()
    for coordinate in (roster.portal_coordinate(url), (direct, url) if direct else None):
        if coordinate is None:
            continue
        row["sourceId"], row["resourceId"] = coordinate
        if _keep_if_acquirable(row, roster, budget) is not False:
            return


def _keep_if_acquirable(row: dict, roster: "_LazyRoster", budget=None) -> bool | None:
    """Mark *row* acquirable, or take its coordinate off when its source
    refused it; a coordinate its source was not asked about stays. Returns
    :func:`_acquirable`'s verdict."""
    verdict = _acquirable(row, roster, budget)
    if verdict:
        row["acquirable"] = True
        row.pop("downloadSteps", None)
    elif verdict is not None:
        row.pop("sourceId", None)
        row.pop("resourceId", None)
    return verdict


def _unconfirmed(rows: list) -> int:
    """How many of *rows* keep a Discovery coordinate the source was not asked
    to confirm, the run's web budget being spent: after
    :func:`_mint_row_acquirable`, every row with a coordinate that is not
    acquirable."""
    return sum(
        1 for row in rows or []
        if isinstance(row, dict) and row.get("sourceId") and row.get("resourceId")
        and not row.get("acquirable")
    )


def _source_describes(dir_name: str, resource_id: str, asker=None) -> bool:
    """Whether the Discovery Catalog describes *resource_id* of the source
    *dir_name*: the call a ``discovery.acquire`` proposal is grounded in,
    asked as *asker* when given, the person a Solve's thread runs for, else
    as the request's account. A describe asked as no one would share one rate
    limit per portal with every other and send no token. A describe that
    fails, for a resource the source does not have or for any other reason,
    is a no."""
    try:
        service = _discovery_service_for(asker) if asker is not None else _discovery_service()
        service.describe_resource(dir_name, resource_id)
    except Exception as exc:  # noqa: BLE001 - an unconfirmed resource is not offered, never a run error
        log.info("%s did not describe %s (%s): the row is not offered for download",
                 dir_name, resource_id, exc)
        return False
    return True


def _acquirable(row: dict, roster: "_LazyRoster", budget=None) -> bool | None:
    """Whether Curio can download *row*: True or False, or None for a
    connector row whose source was not asked, the budget being spent."""
    source = roster.get(row.get("sourceId")) if row.get("resourceId") else None
    # A storage source (a folder, a bucket, a dataset repository) is added from
    # the Discovery Catalog page, and a service downloads for an area set there:
    # neither is offered to agents.
    if (source or {}).get("kind") in ("storage", "service", "model"):
        return False
    capabilities = (source or {}).get("capabilities") or {}
    if not capabilities.get("download"):
        return False
    if source.get("provider") != "direct":
        return roster.describes(row["sourceId"], row["resourceId"], _source_describes, budget=budget)
    url = str(row.get("url") or "")
    if not url.startswith("https://") or row.get("resourceId") != url:
        return False
    if row.get("access") != verify.ACCESS_FETCHABLE:
        return False
    from utk_curio.backend.app.discovery.domain import formats

    raw_type = str((row.get("verification") or {}).get("contentType") or "")
    # A zip or a gzip is unpacked on the way in, so what it holds is decided
    # once it arrives, against the same formats.
    if verify.is_unpacked_archive(raw_type, (row.get("verification") or {}).get("finalUrl") or url):
        return True
    content_type = formats.content_type_of({"Content-Type": raw_type})
    return formats.CONTENT_TYPE_FORMATS.get(content_type) in (capabilities.get("formats") or ())
