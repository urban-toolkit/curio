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
from utk_curio.backend.app.datalakes.application import scan as scanning
from utk_curio.backend.app.datalakes.application.storage_acquire import (
    Cancelled as StorageCancelled,
    StorageAcquire,
)
from utk_curio.backend.app.datalakes.application import jobs as job_store
from utk_curio.backend.app.datalakes.application.catalog import LakeCatalog
from utk_curio.backend.app.agents.infrastructure import egress
from utk_curio.backend.app.datalakes.domain.errors import (
    CapabilityUnsupported,
    DataLakeError,
    ResourceNotFound,
    SourceNotFound,
)
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest
from utk_curio.backend.app.datalakes.domain.resource import (
    LakeField,
    LakeResourceDetail,
    SearchPage,
    SearchQuery,
)
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


#: One page of a storage row's Files list.
FILES_PAGE = 100

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
            install_path=self._install_path,
            find_held=self._find_held,
            find_by_content=self._find_by_content,
        )
        self._storage_acquire = StorageAcquire(
            user_key=self.user_key,
            storage_for=self._storage_for,
            install_path=self._install_path,
            import_layers=self._import_layers,
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

    def _storage_for(self, manifest: LakeSourceManifest):
        from utk_curio.backend.app.datalakes.providers import build_storage

        return build_storage(manifest, self._transport_for(manifest))

    def _listing_scope(self, manifest: LakeSourceManifest) -> str:
        """Whose listing this is: every user's for a public source, this
        account's own for one that sends a token."""
        return f"user:{self.user_key}" if manifest.auth.uses_token else "shared"

    def _storage_builder(self, manifest: LakeSourceManifest):
        """A provider factory for a background scan.

        The transport, and any token it carries, is resolved here on the
        request thread; the scan thread only calls the factory.
        """
        from utk_curio.backend.app.datalakes.providers import build_storage

        transport = self._transport_for(manifest)
        return lambda: build_storage(manifest, transport)

    def _storage_needs_token(self, manifest: LakeSourceManifest) -> dict[str, Any] | None:
        """The leg for a source that cannot be listed without a token this
        account does not hold, as a portal's search reports it."""
        if manifest.auth.needs_token and not self._credential_for(manifest):
            return {
                "sourceId": manifest.id,
                "status": "needs-token",
                "detail": f"add a {manifest.auth.secret_id} token to list this source",
            }
        return None

    def _listing(self, manifest: LakeSourceManifest, **kwargs):
        return scanning.listings.get(
            manifest, self._storage_builder(manifest), scope=self._listing_scope(manifest), **kwargs
        )

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
        limit: int | None = None, cursor: str | None = None, rescan: bool = False,
    ) -> dict[str, Any]:
        manifest = self._catalog.get_manifest(dir_name)
        if manifest.is_storage:
            return self._storage_listing(manifest, q=q, rescan=rescan)
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
        provider: str | None = None, include_storage: bool = True,
    ) -> dict[str, Any]:
        manifests = self._catalog.manifests()
        if provider:
            manifests = [m for m in manifests if m.provider.type == provider]
        if not include_storage:
            manifests = [m for m in manifests if not m.is_storage]
        names = {m.id: m.name for m in manifests}
        portals = [m for m in manifests if not m.is_storage]
        query = _query(q, fmt, limit, None)
        storage_pages = []
        storage_legs = []
        for manifest in (m for m in manifests if m.is_storage):
            # A storage source searches what it declares, from the listing's
            # summary. It never waits here: a source being scanned for the
            # first time is a leg that says so, like a portal that did not
            # answer; one being rescanned answers from its last scan.
            blocked = self._storage_needs_token(manifest)
            if blocked is not None:
                storage_legs.append(blocked)
                continue
            state = self._listing(manifest, wait=0)
            view = state.view()
            if view is not None:
                found = [r for r in view.resources if _storage_matches(r, query.text)]
                if query.fmt:
                    found = [r for r in found if query.fmt in r.formats]
                storage_pages.append(SearchPage(resources=tuple(found)))
                storage_legs.append({"sourceId": manifest.id, "status": "ok", "count": len(found)})
            else:
                storage_legs.append({
                    "sourceId": manifest.id,
                    "status": "failed" if state.status == "failed" else "scanning",
                    **({"detail": state.error} if state.error else {}),
                })
        rows, legs = self._browse.search_all(portals, query, extra_pages=storage_pages)
        legs = sorted(legs + storage_legs, key=lambda leg: leg["sourceId"])
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
        if manifest.is_storage:
            detail = self._storage_detail(manifest, resource_id)
        else:
            detail = self._browse.describe(manifest, resource_id)
        held = self._held_index().get((manifest.dir_name, resource_id))
        return resource_detail_row(
            detail, source_name=manifest.name, already_held_dataset_id=held
        )

    # ── storage ────────────────────────────────────────────────────────────

    def _storage_listing(self, manifest: LakeSourceManifest, *, q: str, rescan: bool) -> dict[str, Any]:
        """A storage source's rows, from its declared resources and a scan.

        While a scan runs, the rows are the last finished scan's, and the leg
        says ``scanning`` with how many files it has walked so far.
        """
        blocked = self._storage_needs_token(manifest)
        if blocked is not None:
            return search_payload([], sources=[blocked])
        state = self._listing(manifest, rescan=rescan)
        view = state.view()
        held = self._held_index()
        rows = [
            resource_row(
                r,
                source_name=manifest.name,
                already_held_dataset_id=held.get((manifest.dir_name, r.resource_id)),
            )
            for r in (view.resources if view is not None else [])
            if _storage_matches(r, q)
        ]
        # "ok" like a portal leg; "scanning" and "failed" say why rows are missing.
        status = "ok" if state.status == "ready" else state.status
        leg = {"sourceId": manifest.id, "status": status, "count": len(rows)}
        if state.error:
            leg["detail"] = state.error
        if state.status == "scanning":
            leg["seen"] = state.seen
        payload = search_payload(rows, sources=[leg], truncated=view.truncated if view else False)
        payload["unmatched"] = view.unmatched if view else 0
        payload["scannedAt"] = _iso(view.scanned_at) if view else None
        return payload

    def storage_files(
        self, dir_name: str, resource_id: str, *, offset: int = 0, limit: int = FILES_PAGE
    ) -> dict[str, Any]:
        """One page of a storage row's files, in the order its thumbnails number them."""
        manifest = self._catalog.get_manifest(dir_name)
        if not manifest.is_storage:
            raise CapabilityUnsupported(f"{manifest.name} lists datasets, not files")
        scanning.parse_resource_id(manifest, resource_id)
        group = scanning.listings.group(manifest, resource_id, scope=self._listing_scope(manifest))
        if group is None:
            raise ResourceNotFound(f"{resource_id!r} is not listed; list {manifest.name} again")
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), FILES_PAGE))
        page = group.files[offset:offset + limit]
        return {
            "files": [
                {
                    "index": offset + i,
                    "relpath": f.relpath,
                    "size": f.size,
                    "updatedAt": _iso(f.mtime),
                    "values": {k: scanning._value_text(v) for k, v in f.values.items()},
                }
                for i, f in enumerate(page)
            ],
            "total": len(group.files),
            "offset": offset,
            "previews": group.spec.is_collection,
        }

    def _storage_detail(self, manifest: LakeSourceManifest, resource_id: str) -> LakeResourceDetail:
        state = self._listing(manifest)
        view = state.view()
        for resource in (view.resources if view is not None else []):
            if resource.resource_id == resource_id:
                spec = scanning.parse_resource_id(manifest, resource_id).spec
                return LakeResourceDetail(
                    resource=resource,
                    fields=tuple(
                        LakeField(name=c.name, type=c.type) for c in spec.template.captures
                    ),
                    license=manifest.license,
                    extra={"path": spec.path, "datasets": spec.datasets, "kind": spec.kind},
                )
        if view is None:
            raise SourceNotFound(f"{manifest.name} is still being scanned; try again shortly")
        raise SourceNotFound(f"{resource_id!r} is not a resource of {manifest.name}")

    def _import_layers(self, fmt, blob, filename, **kwargs):
        from utk_curio.backend.app.datasets.service import DatasetCatalogService

        mutations = DatasetCatalogService(self.user)._mutations
        if fmt == "gpkg":
            return mutations._import_gpkg_layers(blob, filename, **kwargs)
        return mutations._import_osm_pbf_layers(blob, filename, **kwargs)



    # ── acquisition ────────────────────────────────────────────────────────

    def _install_path(self, path, filename, fmt, **kwargs):
        """The seam into the Data Catalog. Imported here so the roster, which
        needs none of it, does not drag the datasets domain in."""
        from utk_curio.backend.app.datasets.service import DatasetCatalogService

        service = DatasetCatalogService(self.user)
        return service._mutations._install_imported_path(path, filename, fmt, **kwargs)

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

    def _find_by_content(self, content_sha256):
        from utk_curio.backend.app.datasets.repositories.user_store import (
            UserDatasetRepository,
        )

        return UserDatasetRepository(self.user).find_by_content(content_sha256)

    def start_acquire(
        self, dir_name: str, resource_id: str, *, fmt=None, title=None, refresh=False,
        filters=None, files=None,
    ) -> dict[str, Any]:
        """Begin a download, or answer immediately if we already hold it.

        Returns either ``{dataset, alreadyPresent: True}`` - no job, no request
        - or ``{jobId, status}``. The caller distinguishes them by which keys
        are present, and the route turns that into a 200 or a 202.
        """
        manifest = self._catalog.get_manifest(dir_name)
        narrowed = False
        if manifest.is_storage:
            # Refuses an id the manifest does not declare, or a narrowing it
            # cannot satisfy, before a job exists.
            narrowed = scanning.narrow(
                scanning.parse_resource_id(manifest, resource_id), filters=filters, files=files
            ).narrowed
            fmt = None
        elif filters or files is not None:
            raise CapabilityUnsupported(f"{manifest.name} is not narrowed by field or file")
        held = None if narrowed else self._acquire.already_held(manifest, resource_id, fmt)
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
                try:
                    # Re-loaded inside this context, so the worker's user
                    # belongs to the worker's own session. Everything
                    # downstream (the credential lookup, the install) hangs off
                    # it. Inside the try, so a failure here still ends the job
                    # and gives its slot back.
                    worker = DataLakeService(
                        user_key,
                        user=_user_by_id(user_id),
                        transport=transport,
                        budget=budget,
                    )
                    job.status = "running"
                    job.stage_message = (
                        "Reading the files…" if manifest.is_storage else "Contacting the portal…"
                    )

                    def _progress(written: int, total: int | None) -> None:
                        job.bytes_read = written
                        job.total_bytes = total
                        job.stage_message = "Copying…" if manifest.is_storage else "Downloading…"

                    def _items(done: int, total: int | None) -> None:
                        job.items_done = done
                        job.items_total = total

                    def _stage(message: str) -> None:
                        job.stage_message = message

                    if manifest.is_storage:
                        result = worker._storage_acquire.acquire(
                            manifest,
                            resource_id,
                            title=title,
                            refresh=refresh,
                            filters=filters,
                            files=files,
                            progress=_progress,
                            items=_items,
                            stage=_stage,
                            cancelled=lambda: job.cancelled,
                        )
                    else:
                        result = worker._acquire.acquire(
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
                except (_Cancelled, StorageCancelled):
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

        _start(job, _run, user_key)
        return job.to_row()

    # ── collections ────────────────────────────────────────────────────────

    def collection(self, dataset_id: str) -> tuple[dict[str, Any], LakeSourceManifest]:
        """This account's collection dataset and the lake source its files are in."""
        from utk_curio.backend.app.datasets.service import DatasetCatalogError, DatasetCatalogService
        from utk_curio.backend.app.datalakes.domain.errors import ResourceNotFound

        try:
            item = DatasetCatalogService(self.user).get_dataset(dataset_id)
        except DatasetCatalogError as exc:
            raise ResourceNotFound(f"no dataset {dataset_id!r}") from exc
        block = item.get("collection") or {}
        if item.get("format") != "collection" or not block.get("sourceId"):
            raise ResourceNotFound(f"{dataset_id!r} is not a collection")
        return item, self._catalog.get_manifest(block["sourceId"])

    def collection_status(self, dataset_id: str, *, samples: int = 12) -> dict[str, Any]:
        """Where a collection's files are, and a few of them to show.

        A folder's files are all on this machine; a bucket's are once cached.
        """
        import pandas as pd

        from utk_curio.backend.app.datalakes.application import cache_collection

        item, manifest = self.collection(dataset_id)
        block = item.get("collection") or {}
        total = int(block.get("fileCount") or 0)
        local = manifest.provider.type == "folder"
        if local:
            cached, cached_bytes = total, int(block.get("totalBytes") or 0)
        else:
            cached, cached_bytes = cache_collection.cached_count(self.user_key, dataset_id)
        rows = pd.read_parquet(item["path"], columns=["file_id", "name", "kind"]).head(samples)
        return {
            "datasetId": dataset_id,
            "provider": manifest.provider.type,
            "local": local,
            "fileCount": total,
            "totalBytes": int(block.get("totalBytes") or 0),
            "cachedFiles": min(cached, total),
            "cachedBytes": cached_bytes,
            "samples": [
                {"fileId": r.file_id, "name": r.name, "kind": r.kind}
                for r in rows.itertuples(index=False)
            ],
        }

    def start_cache(self, dataset_id: str) -> dict[str, Any]:
        """Fetch a bucket collection's files to this machine, as a job."""
        from utk_curio.backend.app.datalakes.application import cache_collection
        from utk_curio.backend.app.datalakes.domain.errors import CapabilityUnsupported

        item, manifest = self.collection(dataset_id)
        if manifest.provider.type == "folder":
            raise CapabilityUnsupported(f"{item['title']} is already on this machine")
        ratelimit.download_slots.acquire(self.user_key)
        job = job_store.jobs.create(self.user_key, manifest.dir_name, f"cache:{dataset_id}")
        app = current_app._get_current_object()
        user_id = getattr(self.user, "id", None)
        user_key, transport, budget = self.user_key, self._transport, self._budget

        def _run() -> None:
            with app.app_context():
                try:
                    worker = DataLakeService(
                        user_key, user=_user_by_id(user_id), transport=transport, budget=budget
                    )
                    job.status = "running"
                    job.stage_message = "Caching files…"

                    def _items(done: int, total: int | None) -> None:
                        job.items_done, job.items_total = done, total

                    def _progress(written: int, total: int | None) -> None:
                        job.bytes_read, job.total_bytes = written, total

                    result = cache_collection.cache(
                        user_key,
                        item,
                        worker._storage_for(manifest),
                        items=_items,
                        progress=_progress,
                        cancelled=lambda: job.cancelled,
                    )
                    job_store.jobs.finish(
                        job, "completed", dataset=item, dataset_id=dataset_id,
                        stage_message=f"{result['total']:,} files on this machine",
                    )
                except (_Cancelled, StorageCancelled):
                    job_store.jobs.finish(job, "cancelled", stage_message="Cancelled")
                except DataLakeError as exc:
                    job_store.jobs.finish(job, "failed", error=str(exc), stage_message="Failed")
                except egress.EgressRefused as exc:
                    job_store.jobs.finish(
                        job, "refused", error=f"refused by the egress policy: {exc}",
                        stage_message="Refused",
                    )
                except Exception as exc:  # noqa: BLE001 - a job must always end
                    job_store.jobs.finish(
                        job, "failed", error=f"{type(exc).__name__}: {exc}"[:300],
                        stage_message="Failed",
                    )
                finally:
                    ratelimit.download_slots.release(user_key)

        _start(job, _run, user_key)
        return job.to_row()

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = job_store.jobs.get(self.user_key, job_id)
        if job is None:
            raise JobNotFound(f"no download job {job_id!r}")
        return job.to_row()

    def cancel_job(self, job_id: str) -> None:
        if not job_store.jobs.cancel(self.user_key, job_id):
            raise JobNotFound(f"no download job {job_id!r} to cancel")



def _start(job, run, user_key: str) -> None:
    """Start *job*'s worker, or end the job and give its slot back."""
    try:
        job_store.run_in_background(run)
    except Exception as exc:  # noqa: BLE001 - no thread, so nothing else will
        ratelimit.download_slots.release(user_key)
        job_store.jobs.finish(job, "failed", error=f"{exc}"[:300], stage_message="Failed")
        raise


def _storage_matches(resource, text: str) -> bool:
    """A declared resource matches a search by its name, description or files."""
    needle = (text or "").strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        [resource.name, resource.description]
        + [str(v) for row in resource.fields for v in row.get("values", [])]
    ).lower()
    return all(word in haystack for word in needle.split())


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    import time as _time

    return _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(ts))


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
