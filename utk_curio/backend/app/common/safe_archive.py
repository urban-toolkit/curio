"""Reading an archive someone else made, without trusting it.

The one extractor for every archive Curio opens: a node package's
``.curio.zip`` (``packages/repositories/archive.py``) and a file the Discovery
Catalog downloaded (``discovery/application/archives.py``). Each caller brings
its own caps and its own rules about which members belong. What is shared is
how a member's name is checked and how its bytes come out:

- a member name may not climb out of the archive (``..``), start at the root,
  use a backslash or a drive letter, or hold a NUL byte;
- the bytes written are counted as they are written, against a cap per member
  and one for the whole archive. A member's declared size is a claim made by
  whoever built the archive, so a cap that trusts it is a cap the archive
  chooses;
- a member that expands far more than any data file does (``Caps.max_ratio``)
  is refused once it has written enough to tell.
"""

from __future__ import annotations

import stat
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CHUNK_BYTES = 1024 * 1024

GZIP_MAGIC = b"\x1f\x8b"


class ArchiveRefused(ValueError):
    """The archive, or a member of it, is unsafe or over its caps."""


@dataclass(frozen=True)
class Caps:
    """What one archive may write."""

    max_member_bytes: int
    max_total_bytes: int
    #: A member writing more than this many times its compressed size is
    #: refused. ``None`` checks nothing.
    max_ratio: float | None = None
    #: What a member must have written before its ratio is judged: a small
    #: file of one repeated value compresses that well and is still a file.
    ratio_floor: int = CHUNK_BYTES


class Budget:
    """The bytes one archive has written so far, against its :class:`Caps`."""

    def __init__(self, caps: Caps) -> None:
        self.caps = caps
        self.total = 0

    def charge(self, name: str, member_written: int, size: int, compressed: int) -> None:
        """Count *size* more bytes of member *name*, or raise :class:`ArchiveRefused`.

        *member_written* is what the member had written before these bytes;
        *compressed* is the member's compressed size, which is how much input
        the decompressor may read for it.
        """
        caps = self.caps
        written = member_written + size
        if written > caps.max_member_bytes:
            raise ArchiveRefused(
                f"archive member {name!r} unpacks to more than {caps.max_member_bytes:,} bytes"
            )
        if self.total + size > caps.max_total_bytes:
            raise ArchiveRefused(f"the archive unpacks to more than {caps.max_total_bytes:,} bytes")
        if (
            caps.max_ratio is not None
            and written > caps.ratio_floor
            and written > caps.max_ratio * max(compressed, 1)
        ):
            raise ArchiveRefused(
                f"archive member {name!r} expands more than {caps.max_ratio:g} times its "
                "compressed size, which no data file does"
            )
        self.total += size


def member_segments(raw_name: str) -> tuple[str, ...]:
    """The path segments of member *raw_name*, or :class:`ArchiveRefused`.

    Refuses an empty name, a NUL byte, a backslash, a leading ``/``, a ``:``
    (a drive letter), and a ``.`` or ``..`` segment: anything that could put a
    file outside the folder it is extracted into.
    """
    if not isinstance(raw_name, str) or not raw_name:
        raise ArchiveRefused("archive contains an empty member name")
    if "\x00" in raw_name:
        raise ArchiveRefused(f"archive member contains a NUL byte: {raw_name!r}")
    if "\\" in raw_name:
        raise ArchiveRefused(f"archive member uses Windows-style separator: {raw_name!r}")
    if raw_name.startswith("/"):
        raise ArchiveRefused(f"archive member is absolute: {raw_name!r}")
    if ":" in raw_name:
        raise ArchiveRefused(f"archive member contains ':': {raw_name!r}")
    parts = [part for part in raw_name.split("/") if part]
    if not parts:
        raise ArchiveRefused(f"archive member normalises to empty: {raw_name!r}")
    for segment in parts:
        if segment in (".", ".."):
            raise ArchiveRefused(f"archive member contains '{segment}': {raw_name!r}")
    return tuple(parts)


def is_symlink(info: zipfile.ZipInfo) -> bool:
    """Whether a zip member is a symbolic link, by the Unix mode it carries."""
    return stat.S_ISLNK(info.external_attr >> 16)


def is_encrypted(info: zipfile.ZipInfo) -> bool:
    return bool(info.flag_bits & 0x1)


def copy_member(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    dest: Path,
    budget: Budget,
    *,
    check: Callable[[], None] | None = None,
) -> int:
    """Write member *info* to *dest*, counting every byte against *budget*.

    Returns the bytes written. *check* runs between chunks, so a caller can
    stop a long extraction. A partial *dest* is removed when this raises.
    """
    written = 0
    try:
        with zf.open(info, "r") as source, open(dest, "wb") as out:
            while True:
                if check is not None:
                    check()
                chunk = source.read(CHUNK_BYTES)
                if not chunk:
                    break
                budget.charge(info.filename, written, len(chunk), info.compress_size)
                out.write(chunk)
                written += len(chunk)
    except NotImplementedError as exc:
        # Deflate64 and the other methods zipfile cannot read.
        Path(dest).unlink(missing_ok=True)
        raise ArchiveRefused(
            f"archive member {info.filename!r} is compressed with a method Curio "
            f"cannot read ({exc}); zip it again with ordinary compression"
        ) from exc
    except BaseException:
        Path(dest).unlink(missing_ok=True)
        raise
    return written


def gunzip(
    src: Path,
    dest: Path,
    caps: Caps,
    *,
    name: str,
    check: Callable[[], None] | None = None,
) -> int:
    """Decompress gzip file *src* to *dest* under *caps*. Returns the bytes written.

    Concatenated gzip members are one file, as ``gunzip`` reads them. The
    ratio is judged against the whole compressed file, which is all the input
    there is.
    """
    budget = Budget(caps)
    compressed = Path(src).stat().st_size
    written = 0
    decompressor = zlib.decompressobj(wbits=31)
    ended = False
    pending = b""
    try:
        with open(src, "rb") as reader, open(dest, "wb") as out:
            while True:
                if check is not None:
                    check()
                if not pending or (ended and len(pending) < len(GZIP_MAGIC)):
                    pending += reader.read(CHUNK_BYTES)
                if ended:
                    if not pending.startswith(GZIP_MAGIC):
                        break  # the end, or padding after the last member
                    decompressor = zlib.decompressobj(wbits=31)
                    ended = False
                # Bounded output per call, so a small piece of a bomb is never
                # inflated whole into memory.
                data = decompressor.decompress(pending, CHUNK_BYTES)
                if data:
                    budget.charge(name, written, len(data), compressed)
                    out.write(data)
                    written += len(data)
                if decompressor.eof:
                    ended = True
                    pending = decompressor.unused_data
                elif decompressor.unconsumed_tail:
                    pending = decompressor.unconsumed_tail
                elif not pending and not data:
                    break  # the input is spent and nothing more comes out
                else:
                    pending = b""
            if not ended:
                raise ArchiveRefused(f"{name!r} ends before its gzip stream does")
    except zlib.error as exc:
        Path(dest).unlink(missing_ok=True)
        raise ArchiveRefused(f"{name!r} could not be read as gzip ({exc})") from exc
    except BaseException:
        Path(dest).unlink(missing_ok=True)
        raise
    return written
