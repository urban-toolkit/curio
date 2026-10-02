"""Typed failures for the Discovery Catalog, each carrying its HTTP status.

The status lives on the exception rather than in the route, so a failure
raised three layers down cannot be reported as the wrong kind of problem by a
handler that has lost the context to tell. ``routes.py`` maps these and
nothing else.
"""

from __future__ import annotations


class DiscoveryError(Exception):
    """Base for every Discovery Catalog failure. 400 unless a subclass says otherwise."""

    status = 400


class SourceNotFound(DiscoveryError):
    status = 404


class ResourceNotFound(DiscoveryError):
    status = 404


class CredentialRequired(DiscoveryError):
    """The source declares ``auth.mode: required-token`` and this account has none.

    428 rather than 401/403: the request is well-formed and the caller is
    authenticated, but a precondition the *user* can satisfy is missing. A 401
    would suggest their Curio session is the problem, which it is not.
    """

    status = 428


class RateLimited(DiscoveryError):
    status = 429


class ProviderError(DiscoveryError):
    """The portal answered, but not in a shape this provider can read.

    502, because the failure is upstream: nothing the caller sent was wrong.
    """

    status = 502


class CapabilityUnsupported(DiscoveryError):
    """The source's manifest does not declare the capability being asked for."""

    status = 400


class UnsupportedFormatError(DiscoveryError):
    status = 400


class DownloadTooLarge(DiscoveryError):
    status = 400


class StorageUnavailable(DiscoveryError):
    """A storage source's folder or bucket cannot be read right now.

    503: the manifest is fine, but the files it names are not reachable, for
    example a folder that is not mounted.
    """

    status = 503
