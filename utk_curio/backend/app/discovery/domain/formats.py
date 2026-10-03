"""What did the portal actually send us?

A portal will tell you, variously: in the URL it gave you, in a
``Content-Type``, in a ``Content-Disposition``, or not at all. None of those is
reliable on its own - plenty of sites serve GeoJSON as ``application/json``,
or a CSV as ``application/octet-stream``, or answer a ``.geojson`` URL with an
HTML error page - so detection is a ladder of five, most-trusted first, and
whatever it decides is checked against what the source is allowed to deliver.

An archive is told apart first (:func:`archive_kind`): a zip or a gzip is
unpacked (``application/archives.py``) and the ladder then runs on the file
inside; any other archive is refused (:func:`refuse_archives`).

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
from utk_curio.backend.app.discovery.domain.errors import UnsupportedFormatError
from utk_curio.backend.app.discovery.domain.manifest import DISCOVERY_ACQUIRABLE_FORMATS
from utk_curio.backend.app.datasets.domain.constants import SUPPORTED_SUFFIXES, TIFF_SIGNATURES

#: Archive content types, by the kind of archive they name.
ARCHIVE_CONTENT_TYPES = {
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/gzip": "gzip",
    "application/x-gzip": "gzip",
    "application/x-tar": "tar",
    "application/x-gtar": "tar",
    "application/x-7z-compressed": "7z",
    "application/x-bzip2": "bz2",
    "application/vnd.rar": "rar",
    "application/x-rar-compressed": "rar",
}

#: Archive suffixes, by kind. Longest first: a ``.tar.gz`` is a tar.
ARCHIVE_SUFFIX_KINDS = (
    (".tar.gz", "tar"),
    (".tar.bz2", "tar"),
    (".tgz", "tar"),
    (".tar", "tar"),
    (".zip", "zip"),
    (".gz", "gzip"),
    (".7z", "7z"),
    (".bz2", "bz2"),
    (".rar", "rar"),
)
ARCHIVE_SUFFIXES = tuple(suffix for suffix, _kind in ARCHIVE_SUFFIX_KINDS)

#: The archives Curio unpacks (``application/archives.py``): a zip, and a gzip
#: of one file. Every other kind is refused, before its body is read whenever
#: its content type or its name says what it is.
UNPACKED_ARCHIVES = frozenset({"zip", "gzip"})

#: What every refusal of an archive says Curio does take.
ARCHIVE_ADVICE = (
    "Curio unpacks a .zip or a .gz holding one data file, a shapefile or a GTFS feed."
)

#: The first bytes of each kind. A tar has no magic at its start; its
#: ``ustar`` marker is at offset 257.
_ARCHIVE_MAGIC = (
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),  # an empty zip
    (b"\x1f\x8b", "gzip"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
)
#: A bzip2 stream: ``BZh``, a block size digit, then the block magic. All of it,
#: so a CSV whose header starts with ``BZh`` is not taken for one.
_BZIP2_MAGIC = re.compile(rb"^BZh[1-9]1AY&SY")
_TAR_MARKER_AT = 257
_TAR_MARKERS = (b"ustar\x00", b"ustar ")

_ARCHIVE_LABELS = {"zip": "zip", "gzip": "gzip", "tar": "tar", "7z": "7z", "bz2": "bzip2", "rar": "RAR"}

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

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def content_type_of(headers: dict) -> str:
    raw = headers.get("Content-Type") or headers.get("content-type") or ""
    return str(raw).split(";")[0].strip().lower()


def disposition_filename(headers: dict) -> str | None:
    raw = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", str(raw), re.IGNORECASE)
    return unquote(match.group(1)).strip() if match else None


def archive_kind_of_name(filename: str | None) -> str | None:
    """The kind of archive *filename*'s suffix names, or None."""
    lowered = (filename or "").strip().lower()
    for suffix, kind in ARCHIVE_SUFFIX_KINDS:
        if lowered.endswith(suffix):
            return kind
    return None


def archive_kind_of_content_type(content_type: str | None) -> str | None:
    """The kind of archive a ``Content-Type`` names (parameters ignored), or None."""
    return ARCHIVE_CONTENT_TYPES.get(content_type_of({"Content-Type": content_type or ""}))


def sniff_archive(head: bytes) -> str | None:
    """The kind of archive the first bytes are, or None."""
    for magic, kind in _ARCHIVE_MAGIC:
        if head.startswith(magic):
            return kind
    if _BZIP2_MAGIC.match(head):
        return "bz2"
    if head[_TAR_MARKER_AT:_TAR_MARKER_AT + 6] in _TAR_MARKERS:
        return "tar"
    return None


def archive_kind(content_type: str = "", filename: str | None = None, head: bytes = b"") -> str | None:
    """What kind of archive this is, from everything known about it, or None.

    The first bytes win over what the server said, except that a gzip named
    ``.tar.gz`` or ``.tgz`` is a tar. Then the name, then the content type.
    """
    named = archive_kind_of_name(filename)
    sniffed = sniff_archive(head) if head else None
    if sniffed == "gzip" and named == "tar":
        return "tar"
    return sniffed or named or archive_kind_of_content_type(content_type)


def refuse_archives(content_type: str, filename: str | None) -> None:
    """Raise if the content type or the name says this is an archive Curio
    does not unpack.

    Needs no body, so it runs before the request on the name a provider gave
    the resource, and before the body on the response's headers. A zip and a
    gzip pass: they are unpacked once they arrive.
    """
    by_type = archive_kind_of_content_type(content_type)
    if by_type is not None and by_type not in UNPACKED_ARCHIVES:
        raise UnsupportedFormatError(
            f"that resource is a {_ARCHIVE_LABELS[by_type]} archive ({content_type_of({'Content-Type': content_type})}), "
            f"which Curio does not unpack. {ARCHIVE_ADVICE}"
        )
    by_name = archive_kind_of_name(filename)
    if by_name is not None and by_name not in UNPACKED_ARCHIVES:
        raise UnsupportedFormatError(
            f"{filename!r} is a {_ARCHIVE_LABELS[by_name]} archive, which Curio does not "
            f"unpack. {ARCHIVE_ADVICE}"
        )


def refuse_sniffed_archive(head: bytes) -> None:
    """Raise if the first bytes are an archive Curio does not unpack."""
    kind = sniff_archive(head)
    if kind is not None and kind not in UNPACKED_ARCHIVES:
        raise UnsupportedFormatError(
            f"that resource is a {_ARCHIVE_LABELS[kind]} archive, which Curio does not "
            f"unpack. {ARCHIVE_ADVICE}"
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
    if head[:4] in TIFF_SIGNATURES:
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
    allowed: tuple[str, ...] = DISCOVERY_ACQUIRABLE_FORMATS,
    filename: str | None = None,
) -> tuple[str, str]:
    """``(format, filename)``, or raise :class:`UnsupportedFormatError`.

    The ladder, most-trusted first:

    1. **what we asked for** - the provider put a format in the URL, so we know
       what we requested, which beats anything the server merely claims;
    2. the **final URL's suffix**, after redirects;
    3. the **Content-Disposition** filename's suffix;
    4. the **Content-Type**, which plenty of sites get wrong;
    5. the **first bytes**.

    *filename* is the name of a file taken out of an archive. It stands in for
    the link and the headers, which describe the archive rather than the file.
    """
    if filename is not None:
        content_type, disposition, url_name = "", None, filename
    else:
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
