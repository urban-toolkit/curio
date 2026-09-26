"""Provider-neutral shapes for what a portal holds.

Every provider translates its own vocabulary into these, so nothing above the
providers package knows the difference between a Socrata 4x4, a CKAN package
resource and a WFS feature type. That translation is the whole job of a
provider; adding one must not require a new field here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LakeResource:
    """One dataset on a portal, as a search result row."""

    source_id: str
    #: Provider-native, opaque above the provider that minted it, and always
    #: re-validated against that provider's ``resource_id_re`` before it is
    #: interpolated into a URL.
    resource_id: str
    name: str
    description: str = ""
    publisher: str = ""
    #: Formats this resource can be delivered in, already narrowed to what the
    #: source's manifest allows. Empty means "nothing we can ingest".
    formats: tuple[str, ...] = ()
    updated_at: str | None = None
    #: The portal's own page for this dataset, for a user who wants to read the
    #: documentation before downloading.
    landing_url: str | None = None
    #: Bytes, when the portal says. A hint, never trusted as a bound - the real
    #: cap is enforced against bytes actually written.
    size_hint: int | None = None


@dataclass(frozen=True)
class LakeField:
    name: str
    type: str | None = None
    description: str = ""


@dataclass(frozen=True)
class LakeResourceDetail:
    resource: LakeResource
    fields: tuple[LakeField, ...] = ()
    license: str = ""
    #: Anything provider-specific worth showing but not worth a column.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DownloadTarget:
    """Where the bytes are, and what we asked for.

    ``declared_format`` is the format we *requested*, which is the highest-trust
    input to format detection: we know what we asked for, whereas a
    ``Content-Type`` is only what the server chose to claim.
    """

    url: str
    declared_format: str | None = None
    filename_hint: str | None = None
    #: Extra request headers the provider needs. A credential is NEVER put here
    #: - the transport is the only code that materialises one, and it adds the
    #: header itself from ``credential_slot``.
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchQuery:
    text: str = ""
    fmt: str | None = None
    limit: int = 20
    cursor: str | None = None


@dataclass(frozen=True)
class SearchPage:
    resources: tuple[LakeResource, ...] = ()
    next_cursor: str | None = None
    #: The portal's claimed total, when it offers one. Display only.
    total_hint: int | None = None
    truncated: bool = False
