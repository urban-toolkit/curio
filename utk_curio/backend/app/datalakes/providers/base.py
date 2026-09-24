"""The provider contract.

A provider translates one portal API into the neutral shapes in
``domain/resource.py``. Adding a portal family is one module plus one registry
entry - the manifest format, the roster, the routes and the UI do not change.

Two invariants every provider is held to, because they are what keeps a
hostile or merely broken portal response from steering a request:

1. A ``resource_id`` is validated against the provider's own
   ``resource_id_re`` BEFORE it is interpolated into any URL. Ids reach us
   from search results, from saved agent proposals and from URLs a user typed,
   so none of them is trusted.
2. Every URL a provider builds starts with the manifest's ``provider.baseUrl``.
   Enforced centrally by :func:`assert_on_base`, the same posture
   ``packages/build_deps.py`` takes with its registry. Redirects OFF the base
   are still fine - CDN-hosted files are normal - and each hop is re-checked by
   the address policy.
"""

from __future__ import annotations

import re
from typing import ClassVar, Protocol
from urllib.parse import quote

from utk_curio.backend.app.datalakes.domain.errors import (
    CapabilityUnsupported,
    ResourceNotFound,
)
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest
from utk_curio.backend.app.datalakes.domain.resource import (
    DownloadTarget,
    LakeResourceDetail,
    SearchPage,
    SearchQuery,
)
from utk_curio.backend.app.datalakes.infrastructure.transport import LakeTransport


class LakeProvider(Protocol):
    type: ClassVar[str]
    resource_id_re: ClassVar[re.Pattern]

    def __init__(self, manifest: LakeSourceManifest, transport: LakeTransport) -> None: ...

    def search(self, query: SearchQuery) -> SearchPage: ...

    def describe(self, resource_id: str) -> LakeResourceDetail: ...

    def download_url(self, resource_id: str, fmt: str | None) -> DownloadTarget: ...


class BaseProvider:
    """Shared plumbing. Subclasses implement the three verbs."""

    type: ClassVar[str] = ""
    resource_id_re: ClassVar[re.Pattern] = re.compile(r"^(?!)")  # matches nothing

    def __init__(self, manifest: LakeSourceManifest, transport: LakeTransport) -> None:
        # Positional and required. A default here is how a test that forgot to
        # inject a fake quietly reaches a real portal instead of failing.
        self.manifest = manifest
        self.transport = transport

    # ── guards ─────────────────────────────────────────────────────────────

    def validate_resource_id(self, resource_id: str) -> str:
        if not isinstance(resource_id, str) or not self.resource_id_re.match(resource_id):
            raise ResourceNotFound(
                f"{resource_id!r} is not a valid {self.type} resource id"
            )
        return resource_id

    @property
    def base(self) -> str:
        return self.manifest.provider.base_url

    def assert_on_base(self, url: str) -> str:
        """Refuse a URL that does not start with this source's base.

        A search response is remote data. Without this, a portal that returned
        a crafted ``url`` field could steer request CONSTRUCTION anywhere the
        address policy happens to allow - which is every public address.
        """
        if not self.base:
            raise CapabilityUnsupported(f"{self.manifest.id} declares no base URL")
        if not url.startswith(self.base):
            raise ResourceNotFound(
                f"{self.manifest.name} returned a URL outside its own site"
            )
        return url

    def allowed_formats(self, requested: str | None) -> tuple[str, ...]:
        allowed = tuple(self.manifest.capabilities.formats)
        if requested is None:
            return allowed
        fmt = requested.strip().lower()
        if fmt not in allowed:
            raise CapabilityUnsupported(
                f"{self.manifest.name} cannot deliver {fmt!r}; it offers "
                f"{', '.join(allowed) or 'nothing'}"
            )
        return (fmt,)

    def pick_format(self, requested: str | None) -> str:
        allowed = self.allowed_formats(requested)
        if not allowed:
            raise CapabilityUnsupported(f"{self.manifest.name} declares no usable format")
        return allowed[0]

    # ── helpers ────────────────────────────────────────────────────────────

    def option(self, key: str, default=None):
        return self.manifest.provider.options.get(key, default)

    @staticmethod
    def q(value: str) -> str:
        """Percent-encode a value for a query string or a path segment."""
        return quote(str(value), safe="")

    def unsupported(self, verb: str):
        return CapabilityUnsupported(f"{self.manifest.name} does not support {verb}")
