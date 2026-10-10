"""Part of a remote Parquet file, read through the Discovery transport.

A GeoParquet file can be hundreds of megabytes while the rows an area needs
sit in a few of its row groups. Its footer says where each row group is and,
for a ``bbox`` column, the smallest box holding each group's rows. So a box
query reads the footer, keeps the groups whose box meets the area, and fetches
only those, one ``Range`` request per group.

Every byte comes through ``transport.download``: the egress address policy
applies, and under test the recorded corpus answers each range by its own key
(``<url> bytes=<a>-<b>``). The requests are computed here from the footer,
never left to the Parquet reader, so a recorded answer stays valid whatever
the reader's own reading pattern is: pyarrow reads from the bytes already
fetched, and a read outside them is an error rather than another request.

A file whose size nobody gave (a pasted link) is asked for its first byte,
and the answer's ``Content-Range`` says the size.
"""

from __future__ import annotations

import io
import json
import re
import struct
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urlsplit

from utk_curio.backend.app.discovery.domain.errors import DownloadTooLarge, ProviderError

#: Parquet's magic, at both ends of a file.
MAGIC = b"PAR1"

#: The columns of a GeoParquet ``bbox`` covering, as the footer names them,
#: when the file's ``geo`` metadata names none.
BBOX_COLUMNS = ("bbox.xmin", "bbox.ymin", "bbox.xmax", "bbox.ymax")

#: How much of a file's end the Parquet reader reads first, whatever its
#: footer's length (Arrow's default footer read size).
READER_TAIL_BYTES = 64 * 1024

#: The longest footer read.
MAX_FOOTER_BYTES = 16 * 1024 * 1024

#: A ranged answer's ``Content-Range``: the bytes sent, and the file's size.
_CONTENT_RANGE_RE = re.compile(r"^\s*bytes\s+\d+-\d+/(\d+)\s*$", re.IGNORECASE)


def boxes_meet(a, b) -> bool:
    """Whether two ``[west, south, east, north]`` boxes share any point."""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


@dataclass(frozen=True)
class Span:
    """A byte range of a file: ``start`` included, ``stop`` excluded."""

    start: int
    stop: int

    @property
    def header(self) -> str:
        """The ``Range`` header for it, whose end is inclusive."""
        return f"bytes={self.start}-{self.stop - 1}"

    def __len__(self) -> int:
        return self.stop - self.start


class SparseFile(io.RawIOBase):
    """A file of *size* bytes of which only some ranges are held.

    What pyarrow reads from: a read inside a held range answers from it, and a
    read anywhere else raises, so a reading pattern that would need bytes not
    fetched fails loudly instead of quietly asking the network again.
    """

    def __init__(self, size: int) -> None:
        super().__init__()
        self.size = size
        self.position = 0
        self.held: list[tuple[int, bytes]] = []

    def hold(self, start: int, data: bytes) -> None:
        self.held.append((start, data))

    def drop(self, start: int) -> None:
        self.held = [(s, d) for s, d in self.held if s != start]

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self.position = offset
        elif whence == io.SEEK_CUR:
            self.position += offset
        elif whence == io.SEEK_END:
            self.position = self.size + offset
        return self.position

    def readinto(self, buffer) -> int:
        want = min(len(buffer), self.size - self.position)
        if want <= 0:
            return 0
        for start, data in self.held:
            if start <= self.position and self.position + want <= start + len(data):
                offset = self.position - start
                buffer[:want] = data[offset:offset + want]
                self.position += want
                return want
        raise ProviderError(
            f"the Parquet reader asked for bytes {self.position}-{self.position + want - 1}, "
            "which were not fetched"
        )


class RemoteParquet:
    """One remote Parquet file, read in ranges.

    Its *size* is given when it is known (a bucket's listing, a catalog), or
    None for a link, which is then asked for it. Each request is bounded by
    the bytes it asks for: a server that ignores ``Range`` and answers with
    the whole file is refused on its declared length instead of being read.
    """

    def __init__(self, transport, url: str, size: int | None, *, max_footer_bytes: int,
                 cancelled: Callable[[], bool] | None = None) -> None:
        self.transport = transport
        self.url = url
        self.max_footer_bytes = max_footer_bytes
        self.cancelled = cancelled
        self.requests: list[Span] = []
        self._metadata = None
        self.size = size
        self.file: SparseFile | None = None
        if size is not None:
            self._sized(size)

    def _sized(self, size: int) -> None:
        if size < 12:
            raise ProviderError(f"{self.url} is too small to be a Parquet file")
        self.size = size
        self.file = SparseFile(size)

    def fetch(self, span: Span) -> bytes:
        """The bytes of *span*, in one request."""
        return self._fetch(span)[0]

    def _fetch(self, span: Span) -> tuple[bytes, dict]:
        """The bytes of *span* and the answer's headers."""
        from utk_curio.backend.app.discovery.providers.autark_osm import Cancelled

        if self.cancelled is not None and self.cancelled():
            raise Cancelled()
        chunks: list[bytes] = []
        try:
            result = self.transport.download(
                self.url, chunks.append, max_bytes=len(span), ceiling=len(span),
                headers={"Range": span.header},
            )
        except DownloadTooLarge as exc:
            raise ProviderError(
                f"{urlsplit(self.url).hostname or self.url} does not send parts of a file, so an Area "
                "cannot be read from it; download the file without an Area"
            ) from exc
        data = b"".join(chunks)
        if len(data) != len(span):
            raise ProviderError(
                f"asked {self.url} for {len(span):,} bytes at {span.start:,} and got {len(data):,}"
            )
        self.requests.append(span)
        return data, dict(getattr(result, "headers", None) or {})

    def _probe_size(self) -> None:
        """Learn the file's size from a one-byte answer's ``Content-Range``."""
        _data, headers = self._fetch(Span(0, 1))
        sent = next((value for name, value in headers.items() if name.lower() == "content-range"), "")
        match = _CONTENT_RANGE_RE.match(str(sent))
        if match is None:
            raise ProviderError(f"{self.url} answered a part of the file without saying how large the file is")
        self._sized(int(match.group(1)))

    @property
    def metadata(self):
        """The file's footer, read with two requests: its length, then itself.

        The second takes at least the file's last :data:`READER_TAIL_BYTES`,
        which the Parquet reader reads first whatever the footer's length.
        """
        if self._metadata is None:
            import pyarrow.parquet as pq

            if self.file is None:
                self._probe_size()
            tail = self.fetch(Span(self.size - 8, self.size))
            length = struct.unpack("<I", tail[:4])[0]
            if tail[4:] != MAGIC:
                raise ProviderError(f"{self.url} does not end as a Parquet file does")
            if length + 8 > self.size or length > self.max_footer_bytes:
                raise ProviderError(
                    f"{self.url} has a footer of {length:,} bytes, more than Curio reads "
                    f"({self.max_footer_bytes:,})"
                )
            start = max(0, self.size - max(length + 8, READER_TAIL_BYTES))
            self.file.hold(start, self.fetch(Span(start, self.size)))
            self._metadata = pq.ParquetFile(self.file).metadata
        return self._metadata

    def geo(self) -> dict:
        """The file's GeoParquet ``geo`` metadata, or ``{}``."""
        raw = (self.metadata.metadata or {}).get(b"geo")
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    def row_group_span(self, index: int) -> Span:
        """Where row group *index* lies: from its first column chunk's first
        page to the end of its last."""
        group = self.metadata.row_group(index)
        starts, stops = [], []
        for c in range(group.num_columns):
            column = group.column(c)
            first = column.data_page_offset
            if column.dictionary_page_offset is not None and 0 < column.dictionary_page_offset < first:
                first = column.dictionary_page_offset
            starts.append(first)
            stops.append(first + column.total_compressed_size)
        return Span(min(starts), max(stops))

    def covering(self) -> tuple[str, str, str, str] | None:
        """The columns holding each row's box, as the footer names them
        (``bbox.xmin`` and so on), or None when the file has none.

        GeoParquet 1.1 names them in the primary geometry column's
        ``covering``; a file that names none may still have Overture's.
        """
        meta = self.metadata
        paths = [meta.schema.column(c).path for c in range(meta.num_columns)]
        geo = self.geo()
        column = (geo.get("columns") or {}).get(geo.get("primary_column") or "geometry") or {}
        named = ((column.get("covering") or {}).get("bbox")) or {}
        try:
            declared = tuple(".".join(named[key]) for key in ("xmin", "ymin", "xmax", "ymax"))
        except (KeyError, TypeError):
            declared = BBOX_COLUMNS
        return declared if all(name in paths for name in declared) else None

    def row_groups_meeting(self, box) -> list[int]:
        """The row groups whose box statistics meet *box*.

        A file with no box columns, or a group missing a statistic, cannot be
        narrowed: its every group is kept.
        """
        meta = self.metadata
        paths = [meta.schema.column(c).path for c in range(meta.num_columns)]
        names = self.covering()
        if names is None:
            return list(range(meta.num_row_groups))
        where = {name: paths.index(name) for name in names}
        xmin, ymin, xmax, ymax = names
        kept = []
        for g in range(meta.num_row_groups):
            group = meta.row_group(g)
            stats = {name: group.column(i).statistics for name, i in where.items()}
            if any(s is None or not s.has_min_max for s in stats.values()):
                kept.append(g)
                continue
            extent = (stats[xmin].min, stats[ymin].min, stats[xmax].max, stats[ymax].max)
            if boxes_meet(extent, box):
                kept.append(g)
        return kept

    def planned_bytes(self, groups: Iterable[int]) -> int:
        return sum(len(self.row_group_span(g)) for g in groups)

    def read_row_group(self, index: int):
        """Row group *index* as a pyarrow table, fetched in one request."""
        import pyarrow.parquet as pq

        span = self.row_group_span(index)
        self.file.hold(span.start, self.fetch(span))
        try:
            reader = pq.ParquetFile(self.file, metadata=self.metadata, pre_buffer=False)
            return reader.read_row_group(index)
        finally:
            self.file.drop(span.start)


__all__ = ["RemoteParquet", "SparseFile", "Span", "boxes_meet", "BBOX_COLUMNS", "MAX_FOOTER_BYTES"]
