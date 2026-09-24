"""What did the portal actually send us?

A portal will tell you, variously: in the URL it gave you, in a
``Content-Type``, in a ``Content-Disposition``, or not at all. None of those is
reliable on its own - plenty of sites serve GeoJSON as ``application/json``,
or a CSV as ``application/octet-stream``, or answer a ``.geojson`` URL with an
HTML error page - so detection is a ladder of five, most-trusted first, and
whatever it decides is checked against what the source is allowed to deliver.

Getting this wrong is not cosmetic: the format decides which loader the Data
Catalog generates, so a GeoJSON filed as ``json`` produces a node that returns
a dict where the user expected a GeoDataFrame.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from urllib.parse import unquote, urlparse

from utk_curio.backend.app.common.safe_paths import PathTraversalError, validate_component
from utk_curio.backend.app.datalakes.domain.errors import UnsupportedFormatError
from utk_curio.backend.app.datalakes.domain.manifest import LAKE_ACQUIRABLE_FORMATS
from utk_curio.backend.app.datasets.domain.constants import SUPPORTED_SUFFIXES

#: Refused before a body is read. Nothing is unpacked in v1: unpacking a remote
#: archive is the decompression-bomb surface, and it deserves its own design
#: with its own caps rather than arriving as a side effect of a download.
ARCHIVE_CONTENT_TYPES = frozenset(
    {
        "application/zip",
        "application/x-zip-compressed",
        "application/gzip",
        "application/x-gzip",
        "application/x-tar",
        "application/x-7z-compressed",
        "application/x-bzip2",
        "application/vnd.rar",
    }
)

ARCHIVE_SUFFIXES = (".zip", ".gz", ".tar", ".tgz", ".7z", ".bz2", ".rar")

#: Content types we are willing to believe, when nothing better said otherwise.
CONTENT_TYPE_FORMATS = {
    "text/csv": "csv",
    "application/csv": "csv",
    "text/comma-separated-values": "csv",
    "application/geo+json": "geojson",
    "application/vnd.geo+json": "geojson",
    "application/json": "json",
    "text/json": "json",
    "application/vnd.apache.parquet": "parquet",
    "application/x-parquet": "parquet",
    "image/tiff": "geotiff",
    "image/geotiff": "geotiff",
}

#: How many bytes the magic-byte step needs.
SNIFF_BYTES = 512

_PARQUET_MAGIC = b"PAR1"
_TIFF_MAGIC = (b"II*\x00", b"MM\x00*")

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def content_type_of(headers: dict) -> str:
    raw = headers.get("Content-Type") or headers.get("content-type") or ""
    return str(raw).split(";")[0].strip().lower()


def disposition_filename(headers: dict) -> str | None:
    raw = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", str(raw), re.IGNORECASE)
    return unquote(match.group(1)).strip() if match else None


def refuse_archives(content_type: str, filename: str | None) -> None:
    """Raise before any body is read, if this is a container rather than a file."""
    if content_type in ARCHIVE_CONTENT_TYPES:
        raise UnsupportedFormatError(
            f"that resource is a {content_type} archive. Curio downloads single "
            "data files; unpack it and import the file you want."
        )
    lowered = (filename or "").lower()
    if any(lowered.endswith(suffix) for suffix in ARCHIVE_SUFFIXES):
        raise UnsupportedFormatError(
            f"{filename!r} is an archive. Curio downloads single data files; "
            "unpack it and import the file you want."
        )


def safe_remote_filename(candidate: str | None, *, fallback: str) -> str:
    """A filename safe to write, from something a remote server chose.

    A ``Content-Disposition`` filename and a URL basename are both
    attacker-controlled. This is the sanitiser; the structural defence is
    stronger and sits underneath it - the dataset DIRECTORY is minted as
    ``imported.x<uuid>`` by the installer, which no remote input can influence,
    and the installer re-validates at the write boundary.
    """
    name = posixpath.basename((candidate or "").replace("\\", "/")).strip()
    name = _UNSAFE.sub("_", name).lstrip(".")
    if not name or name in {"_", "__"}:
        name = _UNSAFE.sub("_", fallback).lstrip(".") or "download"
    name = name[:120]
    try:
        validate_component(name)
    except PathTraversalError:
        name = "download"
    return name


def _suffix_format(name: str | None) -> str | None:
    if not name:
        return None
    suffix = os.path.splitext(name.lower())[1]
    return SUPPORTED_SUFFIXES.get(suffix)


def _sniff(head: bytes) -> str | None:
    """Last resort: what do the first bytes look like?"""
    if not head:
        return None
    if head.startswith(_PARQUET_MAGIC):
        return "parquet"
    if any(head.startswith(magic) for magic in _TIFF_MAGIC):
        return "geotiff"
    stripped = head.lstrip()
    if stripped[:1] in (b"{", b"["):
        # GeoJSON is JSON, so the two are told apart by content rather than by
        # shape: a FeatureCollection loaded as plain json gives the user a dict
        # where they expected a GeoDataFrame.
        try:
            text = stripped.decode("utf-8", errors="ignore")
            match = re.search(r'"type"\s*:\s*"([A-Za-z]+)"', text[:SNIFF_BYTES])
            if match and match.group(1) in (
                "FeatureCollection", "Feature", "GeometryCollection",
                "Point", "LineString", "Polygon",
                "MultiPoint", "MultiLineString", "MultiPolygon",
            ):
                return "geojson"
        except Exception:  # noqa: BLE001 - a sniff never fails the download
            pass
        return "json"
    return None


def resolve_format(
    *,
    declared: str | None,
    final_url: str,
    headers: dict,
    head: bytes = b"",
    allowed: tuple[str, ...] = LAKE_ACQUIRABLE_FORMATS,
) -> tuple[str, str]:
    """``(format, filename)``, or raise :class:`UnsupportedFormatError`.

    The ladder, most-trusted first:

    1. **what we asked for** - the provider put a format in the URL, so we know
       what we requested, which beats anything the server merely claims;
    2. the **final URL's suffix**, after redirects;
    3. the **Content-Disposition** filename's suffix;
    4. the **Content-Type**, which plenty of sites get wrong;
    5. the **first bytes**.
    """
    content_type = content_type_of(headers)
    disposition = disposition_filename(headers)
    url_name = posixpath.basename(urlparse(final_url).path or "") or None

    refuse_archives(content_type, disposition or url_name)

    detected = (
        (declared or None)
        or _suffix_format(url_name)
        or _suffix_format(disposition)
        or CONTENT_TYPE_FORMATS.get(content_type)
        or _sniff(head)
    )

    if detected is None:
        raise UnsupportedFormatError(
            "could not tell what kind of file that is - it declared "
            f"{content_type or 'no content type'} and the link gives no usable "
            "extension. Download it yourself and import the file."
        )
    if detected not in allowed:
        raise UnsupportedFormatError(
            f"that resource is {detected.upper()}, which this source is not "
            f"configured to deliver (it offers {', '.join(allowed) or 'nothing'})."
        )

    fallback = f"download.{_extension_for(detected)}"
    name = safe_remote_filename(disposition or url_name, fallback=fallback)
    if _suffix_format(name) != detected:
        # The name and the verdict have to agree: the installer keys the stored
        # file's suffix off this, and the generated loader keys off the format.
        name = f"{os.path.splitext(name)[0] or 'download'}.{_extension_for(detected)}"
    return detected, name


def _extension_for(fmt: str) -> str:
    from utk_curio.backend.app.datasets.domain.constants import FORMAT_TO_EXTENSION

    return str(FORMAT_TO_EXTENSION.get(fmt, fmt)).lstrip(".")
