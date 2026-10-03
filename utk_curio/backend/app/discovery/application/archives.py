"""Unpack a downloaded archive into what the Data Catalog takes.

A portal often ships data zipped: a gzipped CSV (LODES), a GeoTIFF tile in a
zip (GHSL), a zipped shapefile (TIGER/Line), a GTFS feed. :func:`unpack` reads
the archive the download staged and says what it holds:

- a ``.gz`` is one file, named as the archive less ``.gz``;
- a ``.zip`` holding exactly one data file (CSV, GeoJSON, JSON, Parquet or
  GeoTIFF), with documentation beside it, is that file;
- a ``.zip`` holding one shapefile (its ``.shp`` with the ``.dbf`` and ``.shx``,
  and a ``.prj`` and ``.cpg`` when there are) is that shapefile;
- a ``.zip`` whose root, or single top folder, holds ``stops.txt`` and another
  GTFS table is a GTFS feed.

Anything else is refused, saying what was found. Every member passes through
the shared extractor (``common/safe_archive.py``): a name that climbs out of
the archive, a symbolic link and an archive inside the archive are refused, and
the bytes written are counted against the caps below as they are written.
Members land under names this module mints, never under their own.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from utk_curio.backend.app.common import safe_archive
from utk_curio.backend.app.discovery.application.storage_acquire import MAX_LOCAL_FILE_BYTES
from utk_curio.backend.app.discovery.domain import formats
from utk_curio.backend.app.discovery.domain.errors import UnsupportedFormatError
from utk_curio.backend.app.discovery.providers.storage_base import SHAPEFILE_PARTS

#: How many files an archive may hold. A GTFS feed holds about twenty, a
#: zipped shapefile under ten.
MAX_ARCHIVE_MEMBERS = 1_000

#: What one archive may unpack to, per member and in all: 4 GiB, the limit a
#: file read from a folder source has.
MAX_UNPACKED_BYTES = MAX_LOCAL_FILE_BYTES

#: A member that writes more than this many times its compressed size.
MAX_COMPRESSION_RATIO = 200

#: The files a zip may hold one of, and the format each lands as.
DATA_SUFFIXES = {
    ".csv": "csv",
    ".geojson": "geojson",
    ".json": "json",
    ".parquet": "parquet",
    ".tif": "geotiff",
    ".tiff": "geotiff",
}

#: A shapefile's spatial index files. The reader does not need them.
_SHAPEFILE_INDEXES = (".sbn", ".sbx", ".qix", ".fix", ".atx", ".ain", ".aih", ".ixs", ".mxs")

#: GTFS's core tables: a folder with ``stops.txt`` and one of these is a feed.
GTFS_CORE_TABLES = ("agency.txt", "routes.txt", "trips.txt", "stop_times.txt")

#: What a GTFS table's name may be; its file is ``<name>.txt``.
_TABLE_NAME = re.compile(r"^[a-z0-9_]{1,64}$")

#: Files every archiver leaves behind, skipped wherever they are.
_LITTER_NAMES = frozenset({"__macosx", "thumbs.db", "desktop.ini"})

WHAT_CURIO_TAKES = (
    "Curio takes one data file, a shapefile or a GTFS feed per archive; a data file "
    "is a CSV, GeoJSON, JSON, Parquet or GeoTIFF."
)


@dataclass(frozen=True)
class SingleFile:
    """The one data file an archive held. *name* is its own name in the archive."""

    path: Path
    name: str


@dataclass(frozen=True)
class Shapefile:
    """A shapefile, staged as ``data.shp`` with its parts beside it."""

    path: Path
    name: str


@dataclass(frozen=True)
class GtfsFeed:
    """A GTFS feed's tables, by name (``stops``, ``routes``, ...), each a ``.txt``."""

    tables: dict[str, Path]


Unpacked = SingleFile | Shapefile | GtfsFeed


def caps() -> safe_archive.Caps:
    """The caps, read when an archive is unpacked rather than at import."""
    return safe_archive.Caps(
        max_member_bytes=MAX_UNPACKED_BYTES,
        max_total_bytes=MAX_UNPACKED_BYTES,
        max_ratio=MAX_COMPRESSION_RATIO,
    )


def gzip_member_name(archive_name: str | None, head: bytes) -> str:
    """The name of the file inside a gzip.

    The archive's own name less ``.gz`` (``wac.csv.gz`` holds ``wac.csv``);
    when that names no file, the name the gzip header records, if it has one.
    """
    name = (archive_name or "").strip()
    if name.lower().endswith(".gz"):
        name = name[:-3]
    if formats._suffix_format(name) is None:
        recorded = _gzip_header_name(head)
        if recorded:
            return recorded
    return name or "download"


def unpack(
    kind: str,
    archive: Path,
    *,
    name: str,
    work: Path,
    check: Callable[[], None] | None = None,
) -> Unpacked:
    """What the *kind* archive at *archive* holds, extracted under *work*.

    *name* is the file a gzip holds (:func:`gzip_member_name`); a zip names
    its own members. *check* runs between chunks and may raise to stop.
    """
    try:
        if kind == "gzip":
            return _gunzip(archive, name=name, work=work, check=check)
        if kind == "zip":
            return _unzip(archive, work=work, check=check)
    except safe_archive.ArchiveRefused as exc:
        raise UnsupportedFormatError(str(exc)) from exc
    raise UnsupportedFormatError(f"Curio does not unpack {kind} archives. {formats.ARCHIVE_ADVICE}")


# ── gzip ────────────────────────────────────────────────────────────────────


def _gunzip(archive: Path, *, name: str, work: Path, check) -> SingleFile:
    if formats.archive_kind_of_name(name) is not None:
        raise UnsupportedFormatError(_nested(name))
    dest = work / f"member{_suffix(name)}"
    safe_archive.gunzip(archive, dest, caps(), name=name, check=check)
    with open(dest, "rb") as handle:
        if formats.sniff_archive(handle.read(formats.SNIFF_BYTES)) is not None:
            raise UnsupportedFormatError(_nested(name))
    return SingleFile(path=dest, name=name)


# ── zip ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Member:
    info: zipfile.ZipInfo
    folder: tuple[str, ...]
    name: str

    @property
    def lowered(self) -> str:
        return self.name.lower()


def _unzip(archive: Path, *, work: Path, check) -> Unpacked:
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise UnsupportedFormatError(f"the zip archive could not be read ({exc})") from exc
    with zf:
        files = [info for info in zf.infolist() if not info.is_dir()]
        if len(files) > MAX_ARCHIVE_MEMBERS:
            raise UnsupportedFormatError(
                f"the archive holds {len(files):,} files, more than the "
                f"{MAX_ARCHIVE_MEMBERS:,} Curio unpacks"
            )
        members: list[_Member] = []
        for info in files:
            # Every member's name is checked, litter included: one that climbs
            # out of the archive says what made it.
            segments = safe_archive.member_segments(info.filename)
            if safe_archive.is_symlink(info):
                raise UnsupportedFormatError(f"archive member {info.filename!r} is a symbolic link")
            if any(s.startswith(".") or s.lower() in _LITTER_NAMES for s in segments):
                continue
            members.append(_Member(info=info, folder=segments[:-1], name=segments[-1]))

        nested = [m for m in members if formats.archive_kind_of_name(m.name) is not None]
        if nested:
            raise UnsupportedFormatError(_nested(nested[0].info.filename))

        budget = safe_archive.Budget(caps())
        feed = _gtfs_members(members)
        if feed is not None:
            return _extract_feed(zf, feed, work, budget, check)

        shapefiles = [m for m in members if m.lowered.endswith(".shp")]
        data = [m for m in members if _suffix(m.name) in DATA_SUFFIXES]
        if len(shapefiles) == 1 and not data:
            return _extract_shapefile(zf, shapefiles[0], members, work, budget, check)
        if len(data) == 1 and not shapefiles:
            only = data[0]
            dest = work / f"member{_suffix(only.name)}"
            _copy(zf, only.info, dest, budget, check)
            return SingleFile(path=dest, name=only.name)
        found = shapefiles + data
        if found:
            raise UnsupportedFormatError(
                f"the archive holds {len(found)} data files ({_names(found)}). {WHAT_CURIO_TAKES}"
            )
        raise UnsupportedFormatError(
            f"the archive holds no file Curio can add ({_names(members) or 'nothing'}). "
            f"{WHAT_CURIO_TAKES}"
        )


def _gtfs_members(members: list[_Member]) -> list[_Member] | None:
    """The ``.txt`` tables of a GTFS feed at the root or in one top folder, or None."""
    for stops in (m for m in members if m.lowered == "stops.txt" and len(m.folder) <= 1):
        tables = [
            m for m in members
            if m.folder == stops.folder and m.lowered.endswith(".txt")
        ]
        names = {m.lowered for m in tables}
        if any(core in names for core in GTFS_CORE_TABLES):
            return tables
    return None


def _extract_feed(zf, tables: list[_Member], work: Path, budget, check) -> GtfsFeed:
    folder = work / "gtfs"
    folder.mkdir()
    staged: dict[str, Path] = {}
    for member in tables:
        table = member.lowered[: -len(".txt")]
        if not _TABLE_NAME.match(table) or table in staged:
            continue
        dest = folder / f"{table}.txt"
        _copy(zf, member.info, dest, budget, check)
        staged[table] = dest
    return GtfsFeed(tables=staged)


def _extract_shapefile(zf, shp: _Member, members, work: Path, budget, check) -> Shapefile:
    """The ``.shp`` and the parts beside it with its name, staged as ``data.*``,
    where the reader looks for them, in whatever letter case they came."""
    stem = shp.lowered[: -len(".shp")]
    parts = {
        suffix: m
        for m in members
        if m.folder == shp.folder
        for suffix in SHAPEFILE_PARTS
        if m.lowered == stem + suffix
    }
    missing = [suffix for suffix in (".dbf", ".shx") if suffix not in parts]
    if missing:
        raise UnsupportedFormatError(
            f"{shp.info.filename!r} needs its {' and '.join(missing)} beside it in the archive"
        )
    folder = work / "shapefile"
    folder.mkdir()
    target = folder / "data.shp"
    _copy(zf, shp.info, target, budget, check)
    for suffix, member in parts.items():
        _copy(zf, member.info, folder / f"data{suffix}", budget, check)
    return Shapefile(path=target, name=shp.name)


def _copy(zf, info: zipfile.ZipInfo, dest: Path, budget, check) -> None:
    if safe_archive.is_encrypted(info):
        raise UnsupportedFormatError(f"archive member {info.filename!r} is password-protected")
    try:
        safe_archive.copy_member(zf, info, dest, budget, check=check)
    except (zipfile.BadZipFile, EOFError, OSError) as exc:
        raise UnsupportedFormatError(
            f"archive member {info.filename!r} could not be read ({exc})"
        ) from exc


# ── helpers ─────────────────────────────────────────────────────────────────


def _suffix(name: str) -> str:
    """*name*'s suffix in lower case, when it is a plain one, else ``""``."""
    suffix = Path(name).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,16}", suffix) else ""


def _nested(name: str) -> str:
    return f"the archive holds another archive ({name}); Curio unpacks one level. {WHAT_CURIO_TAKES}"


def _names(members: list[_Member], limit: int = 5) -> str:
    shown = [m.info.filename for m in members[:limit]]
    more = len(members) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


def _gzip_header_name(head: bytes) -> str | None:
    """The original file name a gzip header records (``FNAME``), when it does."""
    if len(head) < 10 or not head.startswith(safe_archive.GZIP_MAGIC):
        return None
    flags = head[3]
    if not flags & 0x08:
        return None
    at = 10
    if flags & 0x04:  # FEXTRA: two length bytes, then that many
        if len(head) < at + 2:
            return None
        at += 2 + int.from_bytes(head[at:at + 2], "little")
    end = head.find(b"\x00", at)
    if end <= at:
        return None
    name = head[at:end].decode("latin-1").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name or None
