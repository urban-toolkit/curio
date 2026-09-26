"""ArcGIS Hub Open Data: the public feature layers cities, counties and
agencies publish through ArcGIS.

Hub's v3 API is JSON:API shaped - ``data[]`` of ``{id, type, attributes}`` -
which is why the parsing here looks different from Socrata's and CKAN's even
though the job is the same.

Downloads go through Hub's own export endpoint rather than the underlying
FeatureServer, because that endpoint is what produces a single complete file;
querying a FeatureServer directly means paging and stitching, which is a
different feature.
"""

from __future__ import annotations

import json
import re

from utk_curio.backend.app.datalakes.domain.errors import ProviderError, ResourceNotFound
from utk_curio.backend.app.datalakes.domain.resource import (
    DownloadTarget,
    LakeField,
    LakeResource,
    LakeResourceDetail,
    SearchPage,
    SearchQuery,
)
from utk_curio.backend.app.datalakes.providers.base import BaseProvider

#: An ArcGIS item id is 32 hex characters; a Hub dataset id may append a layer
#: index (``<itemId>_<n>``) when one item publishes several layers.
RESOURCE_ID_RE = re.compile(r"^[0-9a-f]{32}(?:_\d{1,4})?$")

_URL_RE = re.compile(r"(?:hub\.arcgis\.com|/api/v3/datasets|arcgis\.com/home/item)", re.I)
_ITEM_RE = re.compile(r"\b([0-9a-f]{32})(?:_(\d{1,4}))?\b")

_EXT = {"geojson": "geojson", "csv": "csv"}


#: The verify.py refinement contract: what this family is called, and
#: whether its metadata is text rather than JSON.
PROVIDER_TYPE = "arcgis"
EVIDENCE_TAKES_TEXT = False


def recognize(url: str) -> str | None:
    if not isinstance(url, str) or not _URL_RE.search(url):
        return None
    match = _ITEM_RE.search(url)
    if not match:
        return None
    return f"{match.group(1)}_{match.group(2)}" if match.group(2) else match.group(1)


def metadata_url(url: str, resource_id: str) -> str | None:
    host = re.match(r"^(https?://[^/]+)", url or "")
    return f"{host.group(1)}/api/v3/datasets/{resource_id}" if host else None


def metadata_evidence(payload: dict) -> dict:
    out: dict = {"provider": "arcgis"}
    if not isinstance(payload, dict):
        return out
    data = payload.get("data")
    if isinstance(data, list):
        out["rows"] = len(data)
        return out
    attributes = (data or {}).get("attributes") if isinstance(data, dict) else None
    if isinstance(attributes, dict):
        out["datasetName"] = str(attributes.get("name") or "")[:120]
        out["columns"] = [
            str(f.get("name") or "")[:60]
            for f in (attributes.get("fields") or [])[:12]
            if isinstance(f, dict)
        ]
    return out


class ArcgisProvider(BaseProvider):
    type = "arcgis"
    resource_id_re = RESOURCE_ID_RE

    @property
    def api(self) -> str:
        return f"{self.base}{self.option('apiPath', '/api/v3/datasets')}"

    def search(self, query: SearchQuery) -> SearchPage:
        limit = max(1, min(int(query.limit or 20), 50))
        page = _page(query.cursor)
        url = f"{self.api}?page[size]={limit}&page[number]={page}"
        if query.text.strip():
            url += f"&q={self.q(query.text.strip())}"
        payload = _json(self.transport.json_get(url))
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ProviderError(f"{self.manifest.name} returned no dataset list")

        rows = []
        for entry in data:
            row = self._row(entry)
            if row is not None:
                rows.append(row)
        total = ((payload.get("meta") or {}).get("stats") or {}).get("totalCount")
        return SearchPage(
            resources=tuple(rows),
            next_cursor=str(page + 1) if len(data) >= limit else None,
            total_hint=int(total) if isinstance(total, int) else None,
        )

    def _row(self, entry) -> LakeResource | None:
        if not isinstance(entry, dict):
            return None
        resource_id = str(entry.get("id") or "")
        if not RESOURCE_ID_RE.match(resource_id):
            return None
        attributes = entry.get("attributes") or {}
        return LakeResource(
            source_id=self.manifest.id,
            resource_id=resource_id,
            name=str(attributes.get("name") or resource_id),
            description=_strip_html(str(attributes.get("description") or ""))[:600],
            publisher=str(
                attributes.get("owner") or attributes.get("orgName") or self.manifest.publisher
            ),
            formats=tuple(self.manifest.capabilities.formats),
            updated_at=str(attributes.get("modified") or "") or None,
            landing_url=f"{self.base}/datasets/{resource_id}",
        )

    def describe(self, resource_id: str) -> LakeResourceDetail:
        resource_id = self.validate_resource_id(resource_id)
        payload = _json(self.transport.json_get(f"{self.api}/{resource_id}"))
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ResourceNotFound(f"{resource_id} is not on {self.manifest.name}")
        attributes = data.get("attributes") or {}
        fields = tuple(
            LakeField(
                name=str(f.get("name") or ""),
                type=str(f.get("type") or "") or None,
                description=str(f.get("alias") or ""),
            )
            for f in (attributes.get("fields") or [])
            if isinstance(f, dict) and f.get("name")
        )
        return LakeResourceDetail(
            resource=LakeResource(
                source_id=self.manifest.id,
                resource_id=resource_id,
                name=str(attributes.get("name") or resource_id),
                description=_strip_html(str(attributes.get("description") or ""))[:600],
                publisher=str(attributes.get("owner") or self.manifest.publisher),
                formats=tuple(self.manifest.capabilities.formats),
                updated_at=str(attributes.get("modified") or "") or None,
                landing_url=f"{self.base}/datasets/{resource_id}",
                size_hint=_int_or_none(attributes.get("size")),
            ),
            fields=fields,
            license=str(attributes.get("license") or ""),
        )

    def download_url(self, resource_id: str, fmt: str | None) -> DownloadTarget:
        resource_id = self.validate_resource_id(resource_id)
        chosen = self.pick_format(fmt)
        ext = _EXT.get(chosen)
        if ext is None:
            raise self.unsupported(f"{chosen} export")
        url = self.assert_on_base(
            f"{self.api}/{resource_id}/downloads/data?format={ext}&spatialRefId=4326"
        )
        return DownloadTarget(
            url=url, declared_format=chosen, filename_hint=f"{resource_id}.{ext}"
        )


def _strip_html(text: str) -> str:
    """ArcGIS descriptions are HTML. The card renders text, so a description
    full of markup would otherwise read as tag soup."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _json(body):
    if isinstance(body, (dict, list)):
        return body
    try:
        return json.loads(body)
    except (TypeError, ValueError) as exc:
        raise ProviderError("the portal did not answer with JSON") from exc


def _page(cursor: str | None) -> int:
    try:
        return max(1, int(cursor))
    except (TypeError, ValueError):
        return 1


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
