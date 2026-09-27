"""The storage provider contract.

A storage provider lists and reads the files under one source: a folder, a
bucket, a repo. It knows nothing about resources or datasets; the manifest's
templates decide which files belong to which resource (``application/scan``).

Two invariants, the storage counterparts of the portal ones in ``base.py``:

1. A relpath is POSIX, relative to the source, and never escapes it: no
   absolute path, no ``..``, and on disk every access re-checks the resolved
   path against the root, so a symlink cannot point a read elsewhere.
2. Nothing is ever written to the source. Indexes, thumbnails and caches live
   under Curio's own state directory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import BinaryIO, ClassVar, Iterator, Protocol

from utk_curio.backend.app.datalakes.domain.errors import ResourceNotFound

#: Names skipped wherever they appear: operating-system and sync-tool litter.
SYSTEM_NAMES = frozenset(
    {"Thumbs.db", "desktop.ini", "@eaDir", "__MACOSX", "$RECYCLE.BIN", "System Volume Information"}
)

#: Files that travel with another file rather than standing alone: a
#: shapefile's parts, a world file, GDAL's side files.
SIDECAR_SUFFIXES = (
    ".dbf", ".shx", ".prj", ".cpg", ".qix", ".sbn", ".sbx", ".shp.xml",
    ".jgw", ".pgw", ".tfw", ".wld", ".j2w", ".aux.xml", ".ovr",
)

#: The sibling files a shapefile needs, beside the ``.shp`` itself.
SHAPEFILE_PARTS = (".dbf", ".shx", ".prj", ".cpg")

MAX_DEPTH = 32

_RELPATH_RE = re.compile(r"^[^\x00]{1,1024}$")


@dataclass(frozen=True)
class FileEntry:
    """One file under a source."""

    relpath: str
    size: int
    #: Seconds since the epoch.
    mtime: float
    etag: str | None = None


def is_skipped(name: str) -> bool:
    return name.startswith(".") or name in SYSTEM_NAMES


def is_sidecar(relpath: str) -> bool:
    lower = relpath.lower()
    return any(lower.endswith(suffix) for suffix in SIDECAR_SUFFIXES)


def validate_relpath(relpath: str) -> str:
    """Refuse a relpath that could reach outside its source."""
    if not isinstance(relpath, str) or not _RELPATH_RE.match(relpath):
        raise ResourceNotFound("not a file of this source")
    if relpath.startswith("/") or "\\" in relpath:
        raise ResourceNotFound("not a file of this source")
    parts = relpath.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ResourceNotFound("not a file of this source")
    if any(is_skipped(part) for part in parts):
        raise ResourceNotFound("not a file of this source")
    return relpath


class StorageProvider(Protocol):
    type: ClassVar[str]

    def scan(self, prefix: str = "") -> Iterator[FileEntry]:
        """Every file under *prefix*, recursively. Hidden and system files are
        never yielded."""
        ...

    def open(self, relpath: str, *, byte_range: tuple[int, int] | None = None) -> BinaryIO:
        """Read one file, or ``byte_range`` (inclusive start, exclusive end) of it."""
        ...

    def local_path(self, relpath: str):
        """A readable path on this machine, or None when the file is remote."""
        ...
