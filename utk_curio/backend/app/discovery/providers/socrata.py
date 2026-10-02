"""Socrata: data.cityofchicago.org, data.ny.gov, and several hundred others.

Two APIs, used for what each is good at: the Discovery API (``/api/catalog/v1``)
to search, and the view metadata endpoint (``/api/views/<4x4>.json``) to
describe. Bulk export is ``/resource/<4x4>.<ext>``.

The module-level :func:`recognize` and :func:`metadata_evidence` are the seam
``agents/verify.py`` uses. Socrata's URL shape and metadata endpoint used to be
encoded there as well as here; they now live in this module alone, which is
what that module's docstring has always promised ("adding a provider is one
registry entry, never a new gate").
"""

from __future__ import annotations

import json
import re

from utk_curio.backend.app.discovery.domain.errors import ProviderError, ResourceNotFound
from utk_curio.backend.app.discovery.domain.parameters import ParameterError
from utk_curio.backend.app.discovery.domain.resource import (
    DownloadTarget,
    DiscoveryField,
    DiscoveryResource,
    DiscoveryResourceDetail,
    SearchPage,
    SearchQuery,
)
from utk_curio.backend.app.discovery.providers.base import BaseProvider

#: A Socrata dataset id is a "4x4": four alphanumerics, a hyphen, four more.
RESOURCE_ID_RE = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}$")

#: The URL shapes a 4x4 appears in. Used by ``verify.py`` to recognise a
#: Socrata URL a model produced.
_URL_ID_RE = re.compile(r"/(?:resource|api/views|d)/([a-z0-9]{4}-[a-z0-9]{4})\b")

_EXT = {"csv": "csv", "geojson": "geojson", "json": "json"}

#: SODA answers 1,000 rows to a request that names no ``$limit``, export
#: endpoints included, so every export names one. Version 2.1 endpoints take
#: any limit; the byte cap is what bounds the download.
EXPORT_LIMIT = 2_147_483_647

#: Column types an area applies to: a point is tested with ``within_box``, a
#: shape with ``intersects``.
_POINT_TYPES = frozenset({"point", "location"})
_SHAPE_TYPES = frozenset({"multipoint", "line", "multiline", "linestring", "multilinestring",
                          "polygon", "multipolygon"})
_COLUMN_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")

#: The parameters this provider reads.
PARAMETER_IDS = ("area",)

_SAMPLE_KEYS_MAX = 12


#: The verify.py refinement contract: what this family is called, and
#: whether its metadata is text rather than JSON.
PROVIDER_TYPE = "socrata"
EVIDENCE_TAKES_TEXT = False


def recognize(url: str) -> str | None:
    """The Socrata dataset id in *url*, or None."""
    if not isinstance(url, str):
        return None
    match = _URL_ID_RE.search(url)
    return match.group(1) if match else None


def metadata_url(url: str, resource_id: str) -> str | None:
    """The ``/api/views/<id>.json`` endpoint for a recognised Socrata URL."""
    host = re.match(r"^(https?://[^/]+)", url or "")
    return f"{host.group(1)}/api/views/{resource_id}.json" if host else None


def metadata_evidence(payload: dict) -> dict:
    """Name and columns out of an already-fetched view document."""
    out: dict = {"provider": "socrata"}
    if not isinstance(payload, dict):
        return out
    out["datasetName"] = str(payload.get("name") or "")[:120]
    columns = payload.get("columns") or []
    out["columns"] = [
        str(c.get("fieldName") or c.get("name") or "")[:60]
        for c in columns[:_SAMPLE_KEYS_MAX]
        if isinstance(c, dict)
    ]
    return out


class SocrataProvider(BaseProvider):
    type = "socrata"
    resource_id_re = RESOURCE_ID_RE

    def search(self, query: SearchQuery) -> SearchPage:
        limit = max(1, min(int(query.limit or 20), 50))
        offset = _offset(query.cursor)
        url = (
            f"{self.base}/api/catalog/v1"
            f"?search_context={self.q(_host_of(self.base))}"
            f"&only=dataset&limit={limit}&offset={offset}"
        )
        if query.text.strip():
            url += f"&q={self.q(query.text.strip())}"
        payload = _json(self.transport.json_get(url))
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise ProviderError(f"{self.manifest.name} returned no result list")

        rows = []
        for entry in results:
            row = self._row(entry)
            if row is not None:
                rows.append(row)
        total = payload.get("resultSetSize")
        return SearchPage(
            resources=tuple(rows),
            next_cursor=str(offset + limit) if len(results) >= limit else None,
            total_hint=int(total) if isinstance(total, int) else None,
        )

    def _row(self, entry) -> DiscoveryResource | None:
        if not isinstance(entry, dict):
            return None
        resource = entry.get("resource") or {}
        resource_id = str(resource.get("id") or "")
        # A row whose id we cannot use is dropped rather than shown: offering a
        # result that cannot be downloaded is worse than a shorter list.
        if not RESOURCE_ID_RE.match(resource_id):
            return None
        classification = entry.get("classification") or {}
        types = [str(t).strip().lower() for t in (resource.get("columns_datatype") or [])]
        has_geometry = any(t in _POINT_TYPES or t in _SHAPE_TYPES for t in types)
        return DiscoveryResource(
            source_id=self.manifest.id,
            resource_id=resource_id,
            name=str(resource.get("name") or resource_id),
            description=str(resource.get("description") or ""),
            publisher=str(
                (entry.get("metadata") or {}).get("domain")
                or classification.get("domain_category")
                or self.manifest.publisher
            ),
            formats=tuple(self.manifest.capabilities.formats),
            updated_at=str(resource.get("updatedAt") or "") or None,
            landing_url=str(entry.get("permalink") or "") or None,
            # An area narrows a dataset that has a location column, and only
            # such a dataset is offered one.
            parameter_ids=("area",) if has_geometry else (),
        )

    def describe(self, resource_id: str) -> DiscoveryResourceDetail:
        resource_id = self.validate_resource_id(resource_id)
        payload = _json(self.transport.json_get(f"{self.base}/api/views/{resource_id}.json"))
        if not isinstance(payload, dict):
            raise ProviderError(f"{self.manifest.name} returned no view document")
        if payload.get("error"):
            raise ResourceNotFound(f"{resource_id} is not on {self.manifest.name}")
        fields = tuple(
            DiscoveryField(
                name=str(c.get("fieldName") or c.get("name") or ""),
                type=str(c.get("dataTypeName") or "") or None,
                description=str(c.get("description") or ""),
            )
            for c in (payload.get("columns") or [])
            if isinstance(c, dict)
        )
        rows_updated = payload.get("rowsUpdatedAt")
        return DiscoveryResourceDetail(
            resource=DiscoveryResource(
                source_id=self.manifest.id,
                resource_id=resource_id,
                name=str(payload.get("name") or resource_id),
                description=str(payload.get("description") or ""),
                publisher=str((payload.get("attribution") or "")) or self.manifest.publisher,
                formats=tuple(self.manifest.capabilities.formats),
                updated_at=_iso(rows_updated),
                landing_url=f"{self.base}/d/{resource_id}",
                parameter_ids=("area",) if _has_geometry(payload.get("columns")) else (),
            ),
            fields=fields,
            license=str(((payload.get("license") or {}) or {}).get("name") or ""),
        )

    def download_url(self, resource_id: str, fmt: str | None, *, values: dict | None = None) -> DownloadTarget:
        resource_id = self.validate_resource_id(resource_id)
        chosen = self.pick_format(fmt)
        ext = _EXT.get(chosen)
        if ext is None:
            raise self.unsupported(f"{chosen} export")
        query = f"$limit={EXPORT_LIMIT}"
        area = (values or {}).get("area")
        if area:
            query += f"&$where={self.q(self._area_clause(resource_id, area['box']))}"
        url = self.assert_on_base(f"{self.base}/resource/{resource_id}.{ext}?{query}")
        return DownloadTarget(
            url=url,
            declared_format=chosen,
            filename_hint=f"{resource_id}.{ext}",
        )

    def _area_clause(self, resource_id: str, box: list[float]) -> str:
        """The SoQL ``$where`` that keeps the rows inside *box*.

        Read off the dataset's first location column: a point or location
        column takes ``within_box``, a line or polygon column ``intersects``.
        """
        payload = _json(self.transport.json_get(f"{self.base}/api/views/{resource_id}.json"))
        for column in (payload.get("columns") or []) if isinstance(payload, dict) else []:
            if not isinstance(column, dict):
                continue
            name = str(column.get("fieldName") or "")
            kind = str(column.get("dataTypeName") or "").strip().lower()
            if not _COLUMN_RE.match(name):
                continue
            if kind in _POINT_TYPES:
                return _point_clause(name, box)
            if kind in _SHAPE_TYPES:
                return _shape_clause(name, box)
        raise ParameterError(
            f"{resource_id} on {self.manifest.name} has no location column, so it cannot be narrowed to an area"
        )

def _has_geometry(columns) -> bool:
    return any(
        isinstance(c, dict)
        and str(c.get("dataTypeName") or "").strip().lower() in (_POINT_TYPES | _SHAPE_TYPES)
        for c in (columns or [])
    )


def _point_clause(column: str, box: list[float]) -> str:
    west, south, east, north = box
    return f"within_box({column}, {north}, {west}, {south}, {east})"


def _shape_clause(column: str, box: list[float]) -> str:
    west, south, east, north = box
    ring = f"{west} {south}, {east} {south}, {east} {north}, {west} {north}, {west} {south}"
    return f"intersects({column}, 'POLYGON(({ring}))')"


def _json(body):
    if isinstance(body, (dict, list)):
        return body
    try:
        return json.loads(body)
    except (TypeError, ValueError) as exc:
        raise ProviderError("the portal did not answer with JSON") from exc


def _offset(cursor: str | None) -> int:
    try:
        return max(0, int(cursor))
    except (TypeError, ValueError):
        return 0


def _host_of(base: str) -> str:
    from urllib.parse import urlparse

    return urlparse(base).hostname or ""


def _iso(value) -> str | None:
    """Socrata reports timestamps as epoch seconds."""
    if not isinstance(value, (int, float)):
        return None
    import datetime

    return datetime.datetime.fromtimestamp(
        value, datetime.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
