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
from utk_curio.backend.app.projects import storage as projects_storage

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


def _acquisition_outcome(acquisitions: list[dict]) -> dict | None:
    """What the confirmation says when no builder was started: a download still
    running, or one that failed."""
    running = [a for a in acquisitions if a.get("status") == "acquiring"]
    failed = [a for a in acquisitions if a.get("status") == "failed"]
    if running:
        names = ", ".join(str(a.get("name") or a.get("resourceId")) for a in running)
        return {
            "status": "acquiring",
            "jobIds": [a["jobId"] for a in running],
            "reason": f"{names} is downloading into your Data Catalog; Solve the node once it lands",
        }
    if failed:
        first = failed[0]
        return {
            "status": "acquire-failed",
            "reason": f"the download of {first.get('name') or first.get('resourceId')} failed: {first.get('error')}",
        }
    return None


def _settle_discovery_acquisitions(user_key: str, project_id: str) -> None:
    """Resolve nodes whose confirmed download has landed since it was confirmed.

    Called at a Solve's entry, while the request's user can read the datasets
    domain (a detached job cannot). Reads the spec first, so a project with no
    download in flight costs one read.
    """

    spec = projects_storage.read_spec(user_key, project_id)
    if not agents_dataset_resolution.has_acquiring_picks(spec):
        return
    user = agents_spec_reads._acting_user()
    if user is None:
        return
    try:
        from utk_curio.backend.app.datasets.repositories.user_store import (
            UserDatasetRepository,
        )

        held = UserDatasetRepository(user).discovery_resource_index()
    except Exception:  # noqa: BLE001 - an unreadable store settles nothing
        log.warning("Could not read the held Discovery Catalog datasets for project %s",
                    project_id, exc_info=True)
        return
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = projects_storage.read_spec(user_key, project_id)
        if fresh is not None and agents_dataset_resolution.settle_acquisitions(fresh, held):
            projects_storage.write_spec(user_key, project_id, fresh)


def _discovery_service():
    from flask import g

    from utk_curio.backend.app.discovery.service import DiscoveryService
    from utk_curio.backend.app.projects.services import _user_dir_key

    user = getattr(g, "user", None)
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
        return "refused", "a download needs both a sourceId and a resourceId", None

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
            f"there is no Discovery Catalog source {source_id!r} here; this deployment "
            f"connects to {', '.join(str(k) for k in known) or 'none'}",
            None,
        )
    if not manifest.capabilities.download:
        return "refused", f"{manifest.name} does not offer downloads", None
    if manifest.is_storage:
        return (
            "refused",
            f"{manifest.name} is a storage source; add its resources from its "
            "page in the Discovery Catalog",
            None,
        )

    held = service._acquire.already_held(manifest, resource_id, fmt)
    if held is not None:
        return (
            "refused",
            f"{held.get('title')!r} is already in the user's Data Catalog from "
            "this resource - tell them instead of proposing a second copy",
            None,
        )

    try:
        detail = service.describe_resource(source_id, resource_id)
    except CredentialRequired as exc:
        help_url = manifest.auth.help_url
        return (
            "refused",
            f"{exc} - ask the user to add the {manifest.auth.secret_id} token in "
            f"AI Settings{f' ({help_url})' if help_url else ''}. Never ask them "
            "to paste it to you.",
            None,
        )
    except DiscoveryError as exc:
        return "refused", f"{manifest.name} could not describe {resource_id!r}: {exc}", None

    offered = [str(f) for f in (detail.get("formats") or [])]
    if fmt and fmt not in offered:
        return (
            "refused",
            f"that resource is not offered as {fmt!r}; it offers "
            f"{', '.join(offered) or 'nothing this catalog can ingest'}",
            None,
        )

    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None

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
        f"proposal {proposal_id} created to download {name!r} from "
        f"{manifest.name}; it awaits the user's explicit review - do NOT assume "
        "it was downloaded",
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


def _mint_row_acquirable(row: dict, roster: "_LazyRoster") -> None:
    """Whether Curio can download this row into the Data Catalog: the one answer.

    The model may name a source; it may not claim the source can be acted on,
    so a model-supplied ``acquirable`` never survives. The answer reads the
    roster and the probe, never the run's grants: a person confirming the row
    uses the download route, which needs only their sign-in, and an agent's
    own ``discovery.acquire`` proposal is checked against its grant where it is
    minted.

    - A connector source (anything but ``direct``) is acquirable when the
      roster has it and it downloads. The connector knows how to fetch the
      resource, so the probe of a landing page does not decide it.
    - A ``direct`` source downloads the URL itself, so the probe decides: an
      https URL the probe read as data, whose content type maps to a format the
      source accepts, and whose ``resourceId`` is that same URL, so what is
      downloaded is what was probed.

    A row with a plain link and no coordinate is tried as a ``direct`` row: the
    coordinate is minted here, after parsing, so it is never model-supplied and
    never meets the parser's length cap. It stays only when the row qualifies.
    A downloadable row offers that and nothing else, so it carries no portal
    steps.
    """
    row.pop("acquirable", None)
    minted = False
    if not (row.get("sourceId") and row.get("resourceId")) and str(row.get("url") or "").startswith("https://"):
        direct = roster.direct()
        if direct:
            row["sourceId"], row["resourceId"] = direct, row["url"]
            minted = True
    if _acquirable(row, roster):
        row["acquirable"] = True
        row.pop("downloadSteps", None)
    elif minted:
        row.pop("sourceId", None)
        row.pop("resourceId", None)


def _acquirable(row: dict, roster: "_LazyRoster") -> bool:
    source = roster.get(row.get("sourceId")) if row.get("resourceId") else None
    # A storage source (a folder, a bucket, a dataset repository) is added from
    # the Discovery Catalog page, never offered to agents.
    if (source or {}).get("kind") == "storage":
        return False
    capabilities = (source or {}).get("capabilities") or {}
    if not capabilities.get("download"):
        return False
    if source.get("provider") != "direct":
        return True
    url = str(row.get("url") or "")
    if not url.startswith("https://") or row.get("resourceId") != url:
        return False
    if row.get("access") != verify.ACCESS_FETCHABLE:
        return False
    from utk_curio.backend.app.discovery.domain import formats

    content_type = formats.content_type_of(
        {"Content-Type": str((row.get("verification") or {}).get("contentType") or "")}
    )
    return formats.CONTENT_TYPE_FORMATS.get(content_type) in (capabilities.get("formats") or ())
