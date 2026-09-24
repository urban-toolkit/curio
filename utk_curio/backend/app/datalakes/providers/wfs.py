"""OGC WFS: GeoServer and MapServer, which is what most municipal geospatial
portals outside the US run.

Added for GeoSampa (São Paulo's Mapa Digital), and worth far more than one
portal for that reason. There is no bespoke API to reverse-engineer here: WFS
is a standard, so one connector reaches every server that speaks it.

    search      GetCapabilities once, then filter the feature-type list locally
    describe    DescribeFeatureType, plus the bbox and CRS from capabilities
    download    GetFeature with outputFormat=application/json

**Capabilities is a catalogue, not a query**, which is why it is the one
response this package caches. It lists every published layer, changes only when
an operator publishes one, and is large - GeoSampa's is 425 KB across 483
feature types. Re-fetching it per keystroke would be absurd. A short TTL rather
than permanent caching is what keeps a newly published layer discoverable.

The cache also makes a WFS source nearly free inside a federated fan-out: a
warm search issues no request at all.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

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

#: A qualified type name: ``workspace:layer``.
RESOURCE_ID_RE = re.compile(r"^[A-Za-z][\w-]{0,63}:[A-Za-z][\w.-]{0,127}$")

_URL_RE = re.compile(r"[?&]service=wfs\b", re.IGNORECASE)

#: Long enough that a search session costs one fetch; short enough that a layer
#: published this morning is findable this afternoon.
CAPABILITIES_TTL_S = 15 * 60

_NS = {
    "wfs": "http://www.opengis.net/wfs/2.0",
    "wfs1": "http://www.opengis.net/wfs",
    "ows": "http://www.opengis.net/ows/1.1",
    "xsd": "http://www.w3.org/2001/XMLSchema",
}


#: The verify.py refinement contract: what this family is called, and
#: whether its metadata is text rather than JSON.
PROVIDER_TYPE = "wfs"
EVIDENCE_TAKES_TEXT = True


def recognize(url: str) -> str | None:
    if not isinstance(url, str):
        return None
    return url if _URL_RE.search(url) else None


def metadata_url(url: str, _resource_id: str) -> str | None:
    """Point a WFS URL at its capabilities document."""
    if not isinstance(url, str):
        return None
    base = url.split("?")[0]
    return f"{base}?service=WFS&request=GetCapabilities&version=2.0.0"


def metadata_evidence(payload) -> dict:
    """Evidence from a capabilities document. Takes TEXT, not a dict - this is
    the one provider whose metadata is XML, and ``verify.py`` hands over
    whatever the body was."""
    out: dict = {"provider": "wfs"}
    try:
        types = _parse_capabilities(payload if isinstance(payload, str) else "")
    except ProviderError:
        return out
    out["columns"] = [t["name"] for t in types[:12]]
    out["rows"] = len(types)
    return out


class WfsProvider(BaseProvider):
    type = "wfs"
    resource_id_re = RESOURCE_ID_RE

    #: Keyed by base URL, so two sources pointing at the same server share it.
    _cache: dict[str, tuple[float, list[dict]]] = {}

    @property
    def version(self) -> str:
        return str(self.option("version", "2.0.0"))

    @property
    def output_format(self) -> str:
        return str(self.option("outputFormat", "application/json"))

    def capabilities_url(self) -> str:
        return f"{self.base}?service=WFS&request=GetCapabilities&version={self.version}"

    def feature_types(self) -> list[dict]:
        cached = self._cache.get(self.base)
        now = time.monotonic()
        if cached and now - cached[0] < CAPABILITIES_TTL_S:
            return cached[1]
        body = self.transport.json_get(self.capabilities_url())
        types = _parse_capabilities(body if isinstance(body, str) else str(body))
        self._cache[self.base] = (now, types)
        return types

    @classmethod
    def clear_cache(cls) -> None:
        """For tests, and for an operator who just published a layer."""
        cls._cache.clear()

    def search(self, query: SearchQuery) -> SearchPage:
        limit = max(1, min(int(query.limit or 20), 50))
        offset = _offset(query.cursor)
        types = self.feature_types()
        needle = query.text.strip().lower()
        if needle:
            types = [t for t in types if needle in t["haystack"]]
        window = types[offset : offset + limit]
        rows = tuple(
            LakeResource(
                source_id=self.manifest.id,
                resource_id=t["name"],
                name=t["title"] or t["name"],
                description=t["abstract"],
                publisher=self.manifest.publisher,
                formats=tuple(self.manifest.capabilities.formats),
                landing_url=self.manifest.homepage,
            )
            for t in window
            if RESOURCE_ID_RE.match(t["name"])
        )
        return SearchPage(
            resources=rows,
            next_cursor=str(offset + limit) if offset + limit < len(types) else None,
            total_hint=len(types),
        )

    def describe(self, resource_id: str) -> LakeResourceDetail:
        resource_id = self.validate_resource_id(resource_id)
        match = next((t for t in self.feature_types() if t["name"] == resource_id), None)
        if match is None:
            raise ResourceNotFound(f"{resource_id} is not published by {self.manifest.name}")
        url = (
            f"{self.base}?service=WFS&request=DescribeFeatureType"
            f"&version={self.version}&typeName={self.q(resource_id)}"
        )
        # Best-effort: a server that refuses DescribeFeatureType still gives a
        # usable card from capabilities, so a failure here costs the field list
        # rather than the whole result.
        try:
            fields = _parse_describe(self.transport.json_get(url))
        except (ProviderError, Exception):  # noqa: B014 - intent is "anything"
            fields = ()
        return LakeResourceDetail(
            resource=LakeResource(
                source_id=self.manifest.id,
                resource_id=resource_id,
                name=match["title"] or resource_id,
                description=match["abstract"],
                publisher=self.manifest.publisher,
                formats=tuple(self.manifest.capabilities.formats),
                landing_url=self.manifest.homepage,
            ),
            fields=fields,
            license=self.manifest.license,
            extra={"crs": match["crs"], "bbox": match["bbox"]} if match["bbox"] else {},
        )

    def download_url(self, resource_id: str, fmt: str | None) -> DownloadTarget:
        resource_id = self.validate_resource_id(resource_id)
        chosen = self.pick_format(fmt)
        if chosen != "geojson":
            raise self.unsupported(f"{chosen} export")
        url = self.assert_on_base(
            f"{self.base}?service=WFS&request=GetFeature"
            f"&version={self.version}&typeName={self.q(resource_id)}"
            f"&outputFormat={self.q(self.output_format)}&srsName=EPSG:4326"
        )
        return DownloadTarget(
            url=url,
            declared_format="geojson",
            filename_hint=f"{resource_id.replace(':', '_')}.geojson",
        )


def _parse_capabilities(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ProviderError(f"the server's capabilities document is not XML: {exc}") from exc
    out = []
    # Namespace-agnostic: WFS 1.1 and 2.0 differ in namespace but not in the
    # element names that matter, and some servers answer with neither.
    for node in root.iter():
        if not node.tag.endswith("}FeatureType") and node.tag != "FeatureType":
            continue
        name = _text(node, "Name")
        if not name:
            continue
        title = _text(node, "Title")
        abstract = _text(node, "Abstract")
        keywords = " ".join(
            (child.text or "").strip()
            for child in node.iter()
            if child.tag.endswith("Keyword")
        )
        out.append(
            {
                "name": name,
                "title": title,
                "abstract": abstract,
                "crs": _text(node, "DefaultCRS") or _text(node, "DefaultSRS"),
                "bbox": _bbox(node),
                "haystack": " ".join([name, title, abstract, keywords]).lower(),
            }
        )
    if not out:
        raise ProviderError("the server published no feature types")
    return out


def _parse_describe(xml_text) -> tuple[LakeField, ...]:
    root = ET.fromstring(xml_text if isinstance(xml_text, str) else str(xml_text))
    fields = []
    for node in root.iter():
        if not node.tag.endswith("}element") and node.tag != "element":
            continue
        name = node.get("name")
        if not name:
            continue
        kind = (node.get("type") or "").split(":")[-1] or None
        fields.append(LakeField(name=name, type=kind))
    return tuple(fields)


def _text(node, local: str) -> str:
    for child in node:
        if child.tag.endswith("}" + local) or child.tag == local:
            return (child.text or "").strip()
    return ""


def _bbox(node) -> list[float] | None:
    lower = upper = None
    for child in node.iter():
        if child.tag.endswith("LowerCorner"):
            lower = (child.text or "").split()
        elif child.tag.endswith("UpperCorner"):
            upper = (child.text or "").split()
    if not lower or not upper or len(lower) < 2 or len(upper) < 2:
        return None
    try:
        return [float(lower[0]), float(lower[1]), float(upper[0]), float(upper[1])]
    except ValueError:
        return None


def _offset(cursor: str | None) -> int:
    try:
        return max(0, int(cursor))
    except (TypeError, ValueError):
        return 0
