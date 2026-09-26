"""A bare https link to a file.

The escape hatch: for a portal Curio has no connector for, the resource id IS
the URL. There is nothing to search - a URL is not a catalogue - so ``search``
refuses, and the manifest declares ``capabilities.search: false`` so the route
says so before a provider is even built.

This is the one provider with no base URL, and therefore the one where
``assert_on_base`` cannot apply. What stands in its place is the address policy
itself: the URL is checked by ``egress.check_url`` before anything is fetched,
exactly as every other provider's constructed URLs are, so "no base" removes a
narrowing guard rather than the guard.
"""

from __future__ import annotations

import posixpath
import re
from urllib.parse import unquote, urlparse

from utk_curio.backend.app.datalakes.domain.errors import ResourceNotFound
from utk_curio.backend.app.datalakes.domain.resource import (
    DownloadTarget,
    LakeResource,
    LakeResourceDetail,
    SearchPage,
    SearchQuery,
)
from utk_curio.backend.app.datalakes.providers.base import BaseProvider

#: An https URL. Deliberately not a precise URL grammar: the real check is
#: ``egress.check_url``, which resolves the host and applies the address
#: policy. This only keeps obvious nonsense out of the transport.
RESOURCE_ID_RE = re.compile(r"^https://[^\s\"'<>\\]{3,2000}$")

_SUFFIX_FORMAT = {
    ".csv": "csv",
    ".geojson": "geojson",
    ".json": "json",
    ".parquet": "parquet",
    ".tif": "geotiff",
    ".tiff": "geotiff",
}


def recognize(_url: str) -> str | None:
    """Never recognises. The generic probe in ``verify.py`` is already the
    right answer for a URL no provider claims, and claiming everything here
    would shadow every other refinement."""
    return None


class DirectProvider(BaseProvider):
    type = "direct"
    resource_id_re = RESOURCE_ID_RE

    def search(self, _query: SearchQuery) -> SearchPage:
        raise self.unsupported("search")

    def describe(self, resource_id: str) -> LakeResourceDetail:
        url = self.validate_resource_id(resource_id)
        name = _filename(url)
        fmt = _format_of(name)
        return LakeResourceDetail(
            resource=LakeResource(
                source_id=self.manifest.id,
                resource_id=url,
                name=name or url,
                description="A file fetched directly from its link.",
                publisher=urlparse(url).hostname or "",
                formats=(fmt,) if fmt else (),
                landing_url=url,
            ),
            license=self.manifest.license,
        )

    def download_url(self, resource_id: str, fmt: str | None) -> DownloadTarget:
        url = self.validate_resource_id(resource_id)
        name = _filename(url)
        guessed = _format_of(name)
        if fmt:
            chosen = self.pick_format(fmt)
        elif guessed:
            chosen = self.pick_format(guessed)
        else:
            # Honest rather than guessing: a link with no recognisable
            # extension could be anything, and the detection ladder will get
            # another chance from the response headers.
            chosen = None
        if chosen is not None and chosen not in self.manifest.capabilities.formats:
            raise ResourceNotFound(f"this source cannot deliver {chosen!r}")
        return DownloadTarget(url=url, declared_format=chosen, filename_hint=name)


def _filename(url: str) -> str:
    path = urlparse(url).path or ""
    return posixpath.basename(unquote(path)) or ""


def _format_of(name: str) -> str | None:
    lowered = (name or "").lower()
    for suffix, fmt in _SUFFIX_FORMAT.items():
        if lowered.endswith(suffix):
            return fmt
    return None
