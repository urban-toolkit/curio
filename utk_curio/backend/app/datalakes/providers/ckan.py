"""CKAN: data.gov, data.gov.uk, data.europa.eu, and most academic portals.

CKAN's unit is a *package* (a dataset) holding several *resources* (the actual
files: a CSV, a GeoJSON, a PDF). Curio's unit is the file, so one package
becomes several rows and a resource id is the pair ``<packageId>:<resourceId>``.
Flattening the other way - one row per package - would mean asking the user to
pick a file after choosing a result, from a list we already had.

CKAN is also the one provider whose downloads legitimately leave the portal: a
package on catalog.data.gov usually points at a file on the publishing agency's
own host. That is opt-in per manifest (``allowOffBaseDistributions``), because
it widens what a crafted search response could aim a request at, and those URLs
still pass the full address policy.
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

#: ``<packageId>:<resourceId>``. CKAN ids are UUIDs, but older instances and
#: some mirrors use slugs, so this is permissive about the segments while
#: staying strict about what matters: no separators, no scheme, one colon.
_SEG = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
RESOURCE_ID_RE = re.compile(rf"^{_SEG}:{_SEG}$")

_URL_RE = re.compile(r"/api/3/action/(?:package_show|package_search)\b")


#: The verify.py refinement contract: what this family is called, and
#: whether its metadata is text rather than JSON.
PROVIDER_TYPE = "ckan"
EVIDENCE_TAKES_TEXT = False


def recognize(url: str) -> str | None:
    """CKAN's action API shape. Returns the URL itself - CKAN has no single
    id in its URLs the way Socrata does, so there is nothing narrower to
    return, and ``verify.py`` only needs a truthy recognition."""
    if not isinstance(url, str):
        return None
    return url if _URL_RE.search(url) else None


def metadata_url(url: str, _resource_id: str) -> str | None:
    """CKAN action URLs already ARE the metadata endpoint."""
    return url


def metadata_evidence(payload: dict) -> dict:
    out: dict = {"provider": "ckan"}
    if not isinstance(payload, dict):
        return out
    result = payload.get("result")
    if isinstance(result, dict) and "title" in result:
        out["datasetName"] = str(result.get("title") or "")[:120]
        out["columns"] = [
            str(r.get("format") or "")[:60]
            for r in (result.get("resources") or [])[:12]
            if isinstance(r, dict)
        ]
    elif isinstance(result, dict) and isinstance(result.get("results"), list):
        out["rows"] = len(result["results"])
    return out


class CkanProvider(BaseProvider):
    type = "ckan"
    resource_id_re = RESOURCE_ID_RE

    @property
    def api(self) -> str:
        return f"{self.base}{self.option('apiPath', '/api/3/action')}"

    @property
    def landing_base(self) -> str:
        """Where a human should be sent, when that differs from the API host.

        data.gov.uk serves its CKAN from ckan.publishing.service.gov.uk. Using
        the API host as the base keeps requests one hop shorter - a redirect is
        charged per hop against the egress budget - while landing links still
        have to point at the site people know.
        """
        return str(self.option("landingBase", self.base))

    def search(self, query: SearchQuery) -> SearchPage:
        limit = max(1, min(int(query.limit or 20), 50))
        start = _offset(query.cursor)
        action = self.option("searchAction", "package_search")
        url = f"{self.api}/{action}?rows={limit}&start={start}"
        if query.text.strip():
            url += f"&q={self.q(query.text.strip())}"
        payload = _json(self.transport.json_get(url))
        result = payload.get("result") if isinstance(payload, dict) else None
        packages = (result or {}).get("results") if isinstance(result, dict) else None
        if not isinstance(packages, list):
            raise ProviderError(f"{self.manifest.name} returned no result list")

        rows: list[LakeResource] = []
        for package in packages:
            rows.extend(self._rows_for(package, query.fmt))
        total = (result or {}).get("count")
        return SearchPage(
            resources=tuple(rows[:limit]),
            next_cursor=str(start + limit) if len(packages) >= limit else None,
            total_hint=int(total) if isinstance(total, int) else None,
            truncated=len(rows) > limit,
        )

    def _rows_for(self, package, fmt_filter: str | None) -> list[LakeResource]:
        if not isinstance(package, dict):
            return []
        package_id = str(package.get("id") or package.get("name") or "")
        out = []
        for resource in package.get("resources") or []:
            if not isinstance(resource, dict):
                continue
            fmt = _format_of(resource)
            if fmt is None or fmt not in self.manifest.capabilities.formats:
                continue
            if fmt_filter and fmt != fmt_filter:
                continue
            resource_id = str(resource.get("id") or "")
            coord = f"{package_id}:{resource_id}"
            if not RESOURCE_ID_RE.match(coord):
                continue
            out.append(
                LakeResource(
                    source_id=self.manifest.id,
                    resource_id=coord,
                    # The file's own name when it has one, else the package's -
                    # a package with four CSVs all called by the package title
                    # is indistinguishable in a result list.
                    name=str(resource.get("name") or package.get("title") or coord),
                    description=str(
                        resource.get("description") or package.get("notes") or ""
                    )[:600],
                    publisher=str(
                        (package.get("organization") or {}).get("title")
                        or self.manifest.publisher
                    ),
                    formats=(fmt,),
                    updated_at=str(
                        resource.get("last_modified") or package.get("metadata_modified") or ""
                    ) or None,
                    landing_url=f"{self.landing_base}/dataset/{package.get('name') or package_id}",
                    size_hint=_int_or_none(resource.get("size")),
                )
            )
        return out

    def _package_and_file(self, resource_id: str) -> tuple[dict, dict]:
        """One ``package_show`` call, and the resource inside it.

        Shared by describe and download_url rather than each fetching its own:
        the same document answers both, and fetching twice would double every
        budget tick - the exact bug ``CallBudget``'s docstring records being
        fixed once already for Socrata verification.
        """
        resource_id = self.validate_resource_id(resource_id)
        package_id, _, file_id = resource_id.partition(":")
        action = self.option("showAction", "package_show")
        payload = _json(
            self.transport.json_get(f"{self.api}/{action}?id={self.q(package_id)}")
        )
        package = (payload or {}).get("result") if isinstance(payload, dict) else None
        if not isinstance(package, dict):
            raise ResourceNotFound(f"{package_id} is not on {self.manifest.name}")
        match = next(
            (
                r
                for r in package.get("resources") or []
                if isinstance(r, dict) and str(r.get("id") or "") == file_id
            ),
            None,
        )
        if match is None:
            raise ResourceNotFound(f"{resource_id} is not on {self.manifest.name}")
        return package, match

    def describe(self, resource_id: str) -> LakeResourceDetail:
        package, match = self._package_and_file(resource_id)
        package_id = str(package.get("id") or package.get("name") or "")
        fmt = _format_of(match)
        return LakeResourceDetail(
            resource=LakeResource(
                source_id=self.manifest.id,
                resource_id=resource_id,
                name=str(match.get("name") or package.get("title") or resource_id),
                description=str(match.get("description") or package.get("notes") or "")[:600],
                publisher=str(
                    (package.get("organization") or {}).get("title") or self.manifest.publisher
                ),
                formats=(fmt,) if fmt else (),
                updated_at=str(match.get("last_modified") or "") or None,
                landing_url=f"{self.landing_base}/dataset/{package.get('name') or package_id}",
                size_hint=_int_or_none(match.get("size")),
            ),
            # CKAN's per-field metadata lives behind a separate datastore call
            # that most instances do not enable, so an empty field list is the
            # honest answer rather than a fabricated one.
            fields=tuple(
                LakeField(name=str(f))
                for f in (match.get("datastore_fields") or [])
                if isinstance(f, str)
            ),
            license=str(package.get("license_title") or ""),
        )

    def download_url(self, resource_id: str, fmt: str | None) -> DownloadTarget:
        package, match = self._package_and_file(resource_id)
        url = str(match.get("url") or "")
        if not url:
            raise ResourceNotFound(f"{resource_id} has no download URL")
        chosen = self.pick_format(fmt or _format_of(match))
        if not url.startswith(self.base):
            # The one place a download may leave the portal, and only when the
            # operator said so for this source.
            if not self.manifest.capabilities.allow_off_base_distributions:
                raise ResourceNotFound(
                    f"{self.manifest.name} points this file at another host, which "
                    "this source is not configured to follow"
                )
            if not url.startswith("https://"):
                raise ResourceNotFound("that file is not served over https")
        return DownloadTarget(
            url=url,
            declared_format=chosen,
            filename_hint=str(match.get("name") or package.get("title") or resource_id),
        )


def _format_of(resource: dict) -> str | None:
    raw = str(resource.get("format") or "").strip().lower()
    return {
        "csv": "csv",
        "geojson": "geojson",
        "json": "json",
        "parquet": "parquet",
        "geotiff": "geotiff",
        "tiff": "geotiff",
        "tif": "geotiff",
    }.get(raw)


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


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
