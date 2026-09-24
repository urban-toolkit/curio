"""Public facade for the Data Lake Catalog.

The one stable import point for the rest of the app, mirroring
``datasets/service.py``. Everything outside this package imports from here, so
the internal layering can move without a sweep.
"""

from __future__ import annotations

from typing import Any

from flask import current_app

from utk_curio.backend.app.datalakes.application.acquire import LakeAcquire, _Cancelled
from utk_curio.backend.app.datalakes.application.browse import LakeBrowse
from utk_curio.backend.app.datalakes.application import jobs as job_store
from utk_curio.backend.app.datalakes.application.catalog import LakeCatalog
from utk_curio.backend.app.agents import egress
from utk_curio.backend.app.datalakes.domain.errors import DataLakeError, SourceNotFound
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest
from utk_curio.backend.app.datalakes.domain.resource import SearchQuery
from utk_curio.backend.app.datalakes.infrastructure import credentials, ratelimit
from utk_curio.backend.app.datalakes.infrastructure import transport as transport_mod
from utk_curio.backend.app.datalakes.schemas.payloads import (
    resource_detail_row,
    resource_row,
    search_payload,
)

#: Search asks each portal for at most this many rows.
class JobNotFound(SourceNotFound):
    """No such download job for this account - or it belongs to someone else,
    which is the same answer."""


MAX_SEARCH_LIMIT = 50
DEFAULT_SEARCH_LIMIT = 20


class DataLakeService:
    """Per-request entry point."""

    def __init__(
        self,
        user_key: str | None = None,
        *,
        user=None,
        icon_url_for=None,
        transport=None,
        budget=None,
    ) -> None:
        self.user_key = user_key or "-"
        # The ``User`` row, when there is one. Only ``credentials`` reads it,
        # and only to answer "does this account hold that slot" and to hand the
        # transport one header.
        self.user = user
        self._budget = budget
        # A caller may pass a transport (tests, and the agent runtime threading
        # its own call budget through). Otherwise one is built per request, so
        # the fixture/HTTP decision is re-made rather than cached at import.
        self._transport = transport
        self._catalog = LakeCatalog(
            credential_present=self._credential_present,
            icon_url_for=icon_url_for,
        )
        self._browse = LakeBrowse(
            user_key=self.user_key,
            transport_for=self._transport_for,
            credential_for=self._credential_for,
        )
        self._acquire = LakeAcquire(
            user=user,
            user_key=self.user_key,
            transport_for=self._transport_for,
            download_target=self._browse.download_target,
            install_bytes=self._install_bytes,
            find_held=self._find_held,
        )

    # ── collaborators ──────────────────────────────────────────────────────

    def _transport_for(self, manifest: LakeSourceManifest):
        inner = self._transport or transport_mod.build_transport(budget=self._budget)
        credential = self._credential_for(manifest)
        if credential is None:
            return inner
        # Bound here rather than passed down, so providers never handle a
        # token and cannot put one in a URL they build or a message they log.
        return transport_mod.CredentialedTransport(inner, credential)

    def _credential_for(self, manifest: LakeSourceManifest) -> str | None:
        return credentials.credential_header(self.user, manifest)

    def _credential_present(self, secret_id: str | None) -> bool:
        return credentials.has_token(self.user, secret_id)

    # ── roster (disk) ──────────────────────────────────────────────────────

    def list_catalog(self, **kwargs: Any) -> dict[str, Any]:
        return self._catalog.list_catalog(**kwargs)

    def get_source(self, dir_name: str) -> dict[str, Any]:
        return self._catalog.row(self._catalog.get_manifest(dir_name))

    def get_manifest(self, dir_name: str) -> LakeSourceManifest:
        return self._catalog.get_manifest(dir_name)

    # ── live ───────────────────────────────────────────────────────────────

    def search_source(
        self, dir_name: str, *, q: str = "", fmt: str | None = None,
        limit: int | None = None, cursor: str | None = None,
    ) -> dict[str, Any]:
        manifest = self._catalog.get_manifest(dir_name)
        page = self._browse.search(manifest, _query(q, fmt, limit, cursor))
        held = self._held_index()
        return search_payload(
            [
                resource_row(
                    r,
                    source_name=manifest.name,
                    already_held_dataset_id=held.get((manifest.dir_name, r.resource_id)),
                )
                for r in page.resources
            ],
            sources=[{"sourceId": manifest.id, "status": "ok", "count": len(page.resources)}],
            next_cursor=page.next_cursor,
            total_hint=page.total_hint,
            truncated=page.truncated,
        )

    def search_all(
        self, *, q: str = "", fmt: str | None = None, limit: int | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        manifests = self._catalog.manifests()
        if provider:
            manifests = [m for m in manifests if m.provider.type == provider]
        names = {m.id: m.name for m in manifests}
        rows, legs = self._browse.search_all(manifests, _query(q, fmt, limit, None))
        held = self._held_index()
        dirs = {m.id: m.dir_name for m in manifests}
        return search_payload(
            [
                resource_row(
                    r,
                    source_name=names.get(r.source_id, ""),
                    already_held_dataset_id=held.get(
                        (dirs.get(r.source_id, ""), r.resource_id)
                    ),
                )
                for r in rows
            ],
            sources=legs,
            # A fan-out has no coherent cursor: five portals paginate
            # independently and interleaving them past page one would repeat
            # and drop rows. Narrow to one source to page through it.
            next_cursor=None,
        )

    def describe_resource(self, dir_name: str, resource_id: str) -> dict[str, Any]:
        manifest = self._catalog.get_manifest(dir_name)
        detail = self._browse.describe(manifest, resource_id)
        return resource_detail_row(detail, source_name=manifest.name)



    # ── acquisition ────────────────────────────────────────────────────────

    def _install_bytes(self, blob, filename, fmt, **kwargs):
        """The seam into the Data Catalog. Imported here so the roster, which
        needs none of it, does not drag the datasets domain in."""
        from utk_curio.backend.app.datasets.service import DatasetCatalogService

        service = DatasetCatalogService(self.user)
        return service._mutations._install_imported_bytes(blob, filename, fmt, **kwargs)

    def _held_index(self) -> dict[tuple[str, str], str]:
        """What this account already downloaded, for a whole page of rows.

        Resolved here rather than per row: the question is one walk of the
        user's store, and asking it once per result turned it into twenty.
        """
        from utk_curio.backend.app.datasets.repositories.user_store import (
            UserDatasetRepository,
        )

        return UserDatasetRepository(self.user).lake_resource_index()

    def _find_held(self, lake_id, resource_id, fmt):
        from utk_curio.backend.app.datasets.repositories.user_store import (
            UserDatasetRepository,
        )

        return UserDatasetRepository(self.user).find_by_lake_resource(
            lake_id, resource_id, fmt
        )

    def start_acquire(
        self, dir_name: str, resource_id: str, *, fmt=None, title=None, refresh=False
    ) -> dict[str, Any]:
        """Begin a download, or answer immediately if we already hold it.

        Returns either ``{dataset, alreadyPresent: True}`` - no job, no request
        - or ``{jobId, status}``. The caller distinguishes them by which keys
        are present, and the route turns that into a 200 or a 202.
        """
        manifest = self._catalog.get_manifest(dir_name)
        held = self._acquire.already_held(manifest, resource_id, fmt)
        if held is not None and not refresh:
            return {"dataset": held, "alreadyPresent": True, "unchanged": True}

        # Bounded before the job exists, so a user cannot queue fifty downloads
        # and discover the limit fifty jobs later.
        ratelimit.download_slots.acquire(self.user_key)
        job = job_store.jobs.create(self.user_key, manifest.dir_name, resource_id)
        user_key = self.user_key
        # The worker reads the dataset index and writes through the datasets
        # service, both of which need an app context. Captured here, on the
        # request thread, because ``current_app`` is a proxy that resolves to
        # nothing on the thread we are about to start. Without it the work only
        # appeared to succeed: the index helpers are ``safe_*`` and degrade
        # quietly, so a missing context showed up as a dataset that could not
        # be found again rather than as an error.
        app = current_app._get_current_object()
        # The user's ID, never the ORM instance. A ``User`` row belongs to the
        # session that loaded it, and reading an attribute off it can emit a
        # query - so handing this object to another thread puts two threads on
        # one session and one connection. That surfaces as SQLAlchemy failing
        # to decode a row ("tuple index out of range") in whichever thread
        # loses the race, which is a plain 500 on an unrelated request, with a
        # traceback pointing at auth rather than at the download that caused
        # it. Intermittent by nature: it needs the poll and the worker to
        # overlap.
        user_id = getattr(self.user, "id", None)
        transport, budget = self._transport, self._budget

        def _run() -> None:
            with app.app_context():
                # Re-loaded inside this context, so the worker's user belongs
                # to the worker's own session. Everything downstream (the
                # credential lookup, the install) hangs off it.
                worker = DataLakeService(
                    user_key,
                    user=_user_by_id(user_id),
                    transport=transport,
                    budget=budget,
                )
                acquire = worker._acquire
                try:
                    job.status = "running"
                    job.stage_message = "Contacting the portal…"

                    def _progress(written: int, total: int | None) -> None:
                        job.bytes_read = written
                        job.total_bytes = total
                        job.stage_message = "Downloading…"

                    result = acquire.acquire(
                        manifest,
                        resource_id,
                        fmt=fmt,
                        title=title,
                        refresh=refresh,
                        progress=_progress,
                        cancelled=lambda: job.cancelled,
                    )
                    dataset = result["dataset"]
                    job_store.jobs.finish(
                        job,
                        "completed",
                        dataset=dataset,
                        dataset_id=dataset.get("id"),
                        already_present=result["alreadyPresent"],
                        unchanged=result["unchanged"],
                        stage_message="Added to your Data Catalog",
                    )
                except _Cancelled:
                    job_store.jobs.finish(job, "cancelled", stage_message="Cancelled")
                except DataLakeError as exc:
                    # A typed failure is the user's answer, verbatim: "that file is
                    # too large", "this source cannot deliver CSV".
                    job_store.jobs.finish(
                        job, "failed", error=str(exc), stage_message="Failed"
                    )
                except egress.EgressRefused as exc:
                    job_store.jobs.finish(
                        job,
                        "refused",
                        error=f"refused by the egress policy: {exc}",
                        stage_message="Refused",
                    )
                except Exception as exc:  # noqa: BLE001 - a job must always end
                    job_store.jobs.finish(
                        job,
                        "failed",
                        error=f"{type(exc).__name__}: {exc}"[:300],
                        stage_message="Failed",
                    )
                finally:
                    ratelimit.download_slots.release(user_key)

        job_store.run_in_background(_run)
        return job.to_row()

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = job_store.jobs.get(self.user_key, job_id)
        if job is None:
            raise JobNotFound(f"no download job {job_id!r}")
        return job.to_row()

    def cancel_job(self, job_id: str) -> None:
        if not job_store.jobs.cancel(self.user_key, job_id):
            raise JobNotFound(f"no download job {job_id!r} to cancel")



def _user_by_id(user_id: int | None):
    """The ``User`` row, loaded in whatever session is current here."""
    if user_id is None:
        return None
    from utk_curio.backend.app.users import repositories as user_repo

    return user_repo.user_by_id(user_id)


def _query(q: str, fmt: str | None, limit: int | None, cursor: str | None) -> SearchQuery:
    try:
        size = int(limit) if limit is not None else DEFAULT_SEARCH_LIMIT
    except (TypeError, ValueError):
        size = DEFAULT_SEARCH_LIMIT
    return SearchQuery(
        text=(q or "").strip(),
        fmt=(fmt or "").strip().lower() or None,
        limit=max(1, min(size, MAX_SEARCH_LIMIT)),
        cursor=cursor,
    )
