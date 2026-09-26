"""Typed failures for the Data Lake Catalog, each carrying its HTTP status.

The status lives on the exception rather than in the route, so a failure
raised three layers down cannot be reported as the wrong kind of problem by a
handler that has lost the context to tell. ``routes.py`` maps these and
nothing else.
"""

from __future__ import annotations


class DataLakeError(Exception):
    """Base for every Data Lake Catalog failure. 400 unless a subclass says otherwise."""

    status = 400


class SourceNotFound(DataLakeError):
    status = 404


class ResourceNotFound(DataLakeError):
    status = 404


class CredentialRequired(DataLakeError):
    """The source declares ``auth.mode: required-token`` and this account has none.

    428 rather than 401/403: the request is well-formed and the caller is
    authenticated, but a precondition the *user* can satisfy is missing. A 401
    would suggest their Curio session is the problem, which it is not.
    """

    status = 428


class RateLimited(DataLakeError):
    status = 429


class ProviderError(DataLakeError):
    """The portal answered, but not in a shape this provider can read.

    502, because the failure is upstream: nothing the caller sent was wrong.
    """

    status = 502


class CapabilityUnsupported(DataLakeError):
    """The source's manifest does not declare the capability being asked for."""

    status = 400


class UnsupportedFormatError(DataLakeError):
    status = 400


class DownloadTooLarge(DataLakeError):
    status = 400
