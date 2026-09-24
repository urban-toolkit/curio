"""Public facade for the Data Lake Catalog.

The one stable import point for the rest of the app, mirroring
``datasets/service.py``. Everything outside this package imports from here, so
the internal layering can move without a sweep.
"""

from __future__ import annotations

from typing import Any

from utk_curio.backend.app.datalakes.application.browse import LakeBrowse
from utk_curio.backend.app.datalakes.application.catalog import LakeCatalog
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest
from utk_curio.backend.app.datalakes.domain.resource import SearchQuery
from utk_curio.backend.app.datalakes.infrastructure import transport as transport_mod
from utk_curio.backend.app.datalakes.schemas.payloads import (
    resource_detail_row,
    resource_row,
    search_payload,
)

#: Search asks each portal for at most this many rows.
MAX_SEARCH_LIMIT = 50
DEFAULT_SEARCH_LIMIT = 20


class DataLakeService:
    """Per-request entry point."""

    def __init__(
        self,
        user_key: str | None = None,
        *,
        icon_url_for=None,
        transport=None,
        budget=None,
    ) -> None:
        self.user_key = user_key or "-"
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

    # ── collaborators ──────────────────────────────────────────────────────

    def _transport_for(self, _manifest: LakeSourceManifest):
        if self._transport is not None:
            return self._transport
        return transport_mod.build_transport(budget=self._budget)

    def _credential_for(self, _manifest: LakeSourceManifest) -> str | None:
        # Credentials arrive in their own phase. Until then no account holds
        # one, which is what `_credential_present` reports.
        return None

    def _credential_present(self, _secret_id: str | None) -> bool:
        return False

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
        return search_payload(
            [resource_row(r, source_name=manifest.name) for r in page.resources],
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
        return search_payload(
            [resource_row(r, source_name=names.get(r.source_id, "")) for r in rows],
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
