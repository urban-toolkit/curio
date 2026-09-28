"""Match a storage source's files to the resources its manifest declares.

The manifest says how the files are organized; this module only applies it. A
file belongs to a resource when its relpath matches the resource's template
and its extension is one the resource takes. Every capture becomes a value,
and the resource's ``datasets`` granularity groups the matches into the rows
the lake lists:

- ``one``: a single row for everything the template matched;
- ``per:<field>``: one row per distinct value of the field;
- ``per-file``: one row per file.

A listing keeps only a summary of each row (counts, sizes, the values each
field took, a few sample files), cached per source, because a source is shared
by every user and a walk of a large folder or bucket is not free. Adding a row
to the Data Catalog scans that one resource again, so what is added is what
the folder holds at that moment.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable

from utk_curio.backend.app.datalakes.domain.errors import ResourceNotFound
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest, ResourceSpec
from utk_curio.backend.app.datalakes.domain.resource import LakeResource
from utk_curio.backend.app.datalakes.domain.templates import compile_template
from utk_curio.backend.app.datalakes.providers.storage_base import (
    SHAPEFILE_PARTS,
    FileEntry,
    is_sidecar,
    validate_relpath,
)

#: How long a listing's summary is reused before the source is walked again.
SUMMARY_TTL_SECONDS = 15 * 60

#: A field with more distinct values than this is summarized by its range.
MAX_LISTED_VALUES = 24

#: Sample files kept per row, for the thumbnails a listing shows.
MAX_SAMPLES = 8

#: How long a listing waits for a scan before answering "scanning".
LISTING_WAIT_SECONDS = 2.0

KIND_LABEL = {
    "rasters": "Rasters",
    "frames": "Frames",
    "images": "Images",
    "videos": "Videos",
    "media": "Photos and videos",
    "audio": "Audio",
}


@dataclass(frozen=True, slots=True)
class MatchedFile:
    relpath: str
    size: int
    mtime: float
    values: dict[str, Any]
    etag: str | None = None
    #: A shapefile's other parts (``.dbf``, ``.shx``...), as the source names them.
    parts: tuple[FileEntry, ...] = ()


@dataclass
class Group:
    """One lake row: a resource, or one split value of it, or one file."""

    spec: ResourceSpec
    resource_id: str
    key: tuple
    files: list[MatchedFile] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(f.size + sum(p.size for p in f.parts) for f in self.files)

    @property
    def latest_mtime(self) -> float | None:
        return max((f.mtime for f in self.files), default=None)


@dataclass
class ScanResult:
    groups: list[Group]
    matched: int
    unmatched: int
    truncated: bool
    scanned_at: float


# ── resource ids ───────────────────────────────────────────────────────────


def _value_text(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _escape(value: str) -> str:
    """A split value inside a row id, where ``;`` separates the fields."""
    return value.replace("%", "%25").replace(";", "%3B")


_ESCAPED = re.compile(r"%(25|3[Bb])")


def _unescape(value: str) -> str:
    return _ESCAPED.sub(lambda m: "%" if m.group(1) == "25" else ";", value)


def group_id(spec: ResourceSpec, key: tuple) -> str:
    """The id a lake row carries, which the acquire route is later given back.

    ``<resource>``, ``<resource>@<field>=<value>[;...]`` for a split row (a
    ``;`` or ``%`` in a value is written ``%3B`` or ``%25``), and
    ``<resource>/<relpath>`` for one file.
    """
    if spec.datasets == "per-file":
        return f"{spec.id}/{key[0]}"
    if spec.split_by:
        return spec.id + "@" + ";".join(
            f"{name}={_escape(_value_text(value))}" for name, value in zip(spec.split_by, key)
        )
    return spec.id


@dataclass(frozen=True)
class Selection:
    spec: ResourceSpec
    #: Split values as text, keyed by field.
    split: dict[str, str] = field(default_factory=dict)
    #: One file, for a ``per-file`` row.
    relpath: str | None = None
    #: Values to keep, as text, keyed by field: a row narrowed when added.
    filters: dict[str, frozenset[str]] = field(default_factory=dict)
    #: Inclusive ``(low, high)`` bounds to keep, typed like the field.
    ranges: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    #: The files picked from the row's Files list, when only some were.
    files: frozenset[str] | None = None

    @property
    def narrowed(self) -> bool:
        return bool(self.filters or self.ranges) or self.files is not None

    def describe(self) -> dict[str, Any]:
        """What the narrowing kept, for the dataset's provenance."""
        out: dict[str, Any] = {}
        for name, values in self.filters.items():
            out[name] = sorted(values)
        for name, (low, high) in self.ranges.items():
            out[name] = {"min": _value_text(low), "max": _value_text(high)}
        return out


#: Bounds on what one add may narrow by.
MAX_FILTER_VALUES = 1000
MAX_CHOSEN_FILES = 5000


def _bound(capture, raw: Any) -> Any:
    text = str(raw)[:64]
    if capture.type == "int":
        return int(text)
    if capture.type == "date":
        return date.fromisoformat(text)
    if capture.type == "datetime":
        # Captured times carry no zone, so neither does a bound.
        return datetime.fromisoformat(text).replace(tzinfo=None)
    return text


def narrow(selection: Selection, *, filters: Any = None, files: Any = None) -> Selection:
    """*selection*, keeping only the field values and files a user picked.

    Each filter names one of the template's captures that the row is not
    already split by, and either the values to keep or ``{"min", "max"}``
    bounds. Files are relpaths of the row. Anything else is refused, so a
    request can only ever select fewer of the files the manifest declares.
    """
    if not filters and files is None:
        return selection
    spec = selection.spec
    if selection.relpath is not None:
        raise ResourceNotFound(f"{spec.name} is one file; there is nothing to narrow")
    captures = {c.name: c for c in spec.template.captures if c.name not in spec.split_by}
    kept: dict[str, frozenset[str]] = {}
    ranges: dict[str, tuple[Any, Any]] = {}
    if filters:
        if not isinstance(filters, dict):
            raise ResourceNotFound("filters name fields and the values to keep")
        for name, wanted in filters.items():
            capture = captures.get(name)
            if capture is None:
                raise ResourceNotFound(f"{spec.name} has no field {name!r} to narrow by")
            if isinstance(wanted, dict):
                try:
                    low, high = _bound(capture, wanted["min"]), _bound(capture, wanted["max"])
                except (KeyError, ValueError, TypeError):
                    raise ResourceNotFound(f"{name} needs a min and a max like its values") from None
                ranges[name] = (low, high)
            elif isinstance(wanted, list) and 0 < len(wanted) <= MAX_FILTER_VALUES:
                kept[name] = frozenset(str(v)[:200] for v in wanted)
            else:
                raise ResourceNotFound(f"keep between 1 and {MAX_FILTER_VALUES} values of {name}")
    chosen: frozenset[str] | None = None
    if files is not None:
        if not isinstance(files, list) or not files or len(files) > MAX_CHOSEN_FILES:
            raise ResourceNotFound(f"pick between 1 and {MAX_CHOSEN_FILES} files")
        chosen = frozenset(validate_relpath(str(f)) for f in files)
    return Selection(spec=spec, split=selection.split, filters=kept, ranges=ranges, files=chosen)


def parse_resource_id(manifest: LakeSourceManifest, resource_id: str) -> Selection:
    """Turn a row's id back into the resource and the files it selects."""
    if not isinstance(resource_id, str) or not resource_id:
        raise ResourceNotFound("no such resource")
    head, sep, rest = resource_id.partition("/")
    if sep:
        spec = manifest.resource(head)
        if spec is None or spec.datasets != "per-file":
            raise ResourceNotFound(f"{resource_id!r} is not a resource of {manifest.name}")
        return Selection(spec=spec, relpath=rest)
    head, sep, rest = resource_id.partition("@")
    spec = manifest.resource(head)
    if spec is None:
        raise ResourceNotFound(f"{resource_id!r} is not a resource of {manifest.name}")
    if spec.datasets == "per-file":
        raise ResourceNotFound(f"{spec.name} is added one file at a time")
    if not sep:
        if spec.split_by:
            raise ResourceNotFound(f"{spec.name} is added one {', '.join(spec.split_by)} at a time")
        return Selection(spec=spec)
    split: dict[str, str] = {}
    for part in rest.split(";"):
        name, eq, value = part.partition("=")
        if not eq or name not in spec.split_by:
            raise ResourceNotFound(f"{resource_id!r} is not a resource of {manifest.name}")
        split[name] = _unescape(value)
    if set(split) != set(spec.split_by):
        raise ResourceNotFound(f"{resource_id!r} names only part of how {spec.name} is split")
    return Selection(spec=spec, split=split)


# ── matching ───────────────────────────────────────────────────────────────


def _extension(relpath: str) -> str:
    name = relpath.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def match_file(spec: ResourceSpec, entry: FileEntry) -> MatchedFile | None:
    if _extension(entry.relpath) not in spec.extensions:
        return None
    values = spec.template.match(entry.relpath)
    if values is None:
        return None
    return MatchedFile(
        relpath=entry.relpath, size=entry.size, mtime=entry.mtime, values=values, etag=entry.etag,
    )


def common_prefix(specs: Iterable[ResourceSpec]) -> str:
    """The longest folder prefix every resource's template starts with."""
    prefixes = [spec.template.literal_prefix for spec in specs]
    if not prefixes:
        return ""
    first = prefixes[0].split("/")[:-1]
    shared: list[str] = []
    for index, part in enumerate(first):
        if all(p.split("/")[:-1][index:index + 1] == [part] for p in prefixes):
            shared.append(part)
        else:
            break
    return "/".join(shared) + ("/" if shared else "")


def scan(
    manifest: LakeSourceManifest,
    provider,
    *,
    specs: Iterable[ResourceSpec] | None = None,
    selection: Selection | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int], None] | None = None,
) -> ScanResult:
    """Walk the source once and group what each resource's template matches."""
    if selection is not None:
        specs = [selection.spec]
    specs = list(specs if specs is not None else manifest.resources)
    # A resource's metadata table belongs to the resource, not to "unmatched".
    attached = [
        compile_template(spec.metadata["path"], reserved=frozenset())
        for spec in manifest.resources
        if spec.metadata
    ]
    groups: dict[tuple[str, tuple], Group] = {}
    matched = unmatched = seen = 0
    truncated = False
    # A shapefile is read with its parts, so they are kept to be found again.
    sidecars: dict[str, FileEntry] | None = {} if any(s.format == "shp" for s in specs) else None
    for entry in provider.scan(common_prefix(specs)):
        if cancelled is not None and cancelled():
            break
        seen += 1
        if progress is not None and seen % 500 == 0:
            progress(seen)
        if sidecars is not None and is_sidecar(entry.relpath):
            sidecars[entry.relpath.lower()] = entry
        hit = False
        for spec in specs:
            found = match_file(spec, entry)
            if found is None:
                continue
            if selection is not None and not _selected(selection, found):
                hit = True
                continue
            hit = True
            if matched >= manifest.max_files:
                # A file past the limit, so the scan stops short of the source.
                truncated = True
                break
            if spec.datasets == "per-file":
                key: tuple = (found.relpath,)
            elif spec.split_by:
                key = tuple(found.values[name] for name in spec.split_by)
            else:
                key = ()
            group = groups.get((spec.id, key))
            if group is None:
                group = groups[(spec.id, key)] = Group(
                    spec=spec, resource_id=group_id(spec, key), key=key
                )
            group.files.append(found)
            matched += 1
        if (
            not hit
            and not is_sidecar(entry.relpath)
            and not any(t.match(entry.relpath) is not None for t in attached)
        ):
            unmatched += 1
        if truncated:
            break
    order = {spec.id: index for index, spec in enumerate(specs)}
    out = sorted(groups.values(), key=lambda g: (order[g.spec.id], tuple(map(_value_text, g.key))))
    for group in out:
        if sidecars is not None and group.spec.format == "shp":
            group.files = [_with_parts(f, sidecars) for f in group.files]
        group.files.sort(key=lambda f: f.relpath)
    return ScanResult(
        groups=out, matched=matched, unmatched=unmatched, truncated=truncated,
        scanned_at=time.time(),
    )


def _with_parts(found: MatchedFile, sidecars: dict[str, FileEntry]) -> MatchedFile:
    """*found*, a ``.shp``, with the parts beside it, whatever their case."""
    stem = found.relpath[:-4].lower() if found.relpath.lower().endswith(".shp") else found.relpath.lower()
    parts = tuple(sidecars[stem + suffix] for suffix in SHAPEFILE_PARTS if stem + suffix in sidecars)
    return replace(found, parts=parts)


def _selected(selection: Selection, found: MatchedFile) -> bool:
    if selection.relpath is not None:
        return found.relpath == selection.relpath
    if selection.files is not None and found.relpath not in selection.files:
        return False
    if any(_value_text(found.values[name]) not in values for name, values in selection.filters.items()):
        return False
    if any(not low <= found.values[name] <= high for name, (low, high) in selection.ranges.items()):
        return False
    return all(_value_text(found.values[name]) == value for name, value in selection.split.items())


# ── the listing's view of a group ──────────────────────────────────────────


def field_summary(spec: ResourceSpec, files: list[MatchedFile]) -> list[dict[str, Any]]:
    """The values each capture took across *files*."""
    out = []
    for capture in spec.template.captures:
        values = sorted({f.values[capture.name] for f in files}, key=lambda v: (str(type(v)), v))
        row: dict[str, Any] = {"name": capture.name, "type": capture.type, "distinct": len(values)}
        if len(values) <= MAX_LISTED_VALUES:
            row["values"] = [_value_text(v) for v in values]
        else:
            row["min"] = _value_text(values[0])
            row["max"] = _value_text(values[-1])
        out.append(row)
    return out


def _iso(ts: float | None) -> str | None:
    """*ts* as ISO time; None when unknown, which a Hugging Face listing gives as 0."""
    if not ts or ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _size_text(n: int) -> str:
    step = 1024.0
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < step or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= step
    return f"{n} B"


def _counted(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


_FILE_NOUNS = {"image": ("image", "images"), "video": ("video", "videos"), "audio": ("recording", "recordings")}


def count_parts(group: Group) -> list[str]:
    """How many of what a row holds: frames by sequence, media by kind."""
    from utk_curio.backend.app.datalakes.application.probe import file_kind

    spec, files = group.spec, group.files
    if spec.kind == "frames":
        sequences = {
            f.values["sequence"] if f.values.get("sequence") is not None
            else (f.relpath.rsplit("/", 2)[-2] if "/" in f.relpath else "")
            for f in files
        }
        return [_counted(len(sequences), "sequence", "sequences"), _counted(len(files), "frame", "frames")]
    if spec.kind in ("media", "images", "videos", "audio"):
        counts: dict[str, int] = {}
        for f in files:
            kind = file_kind(spec.kind, f.relpath)
            counts[kind] = counts.get(kind, 0) + 1
        return [", ".join(
            _counted(counts[kind], *_FILE_NOUNS[kind]) for kind in _FILE_NOUNS if counts.get(kind)
        )]
    return [_counted(len(files), "file", "files")]


def describe_line(group: Group, fields: list[dict[str, Any]]) -> str:
    """The profile line a row shows: kind, count, what its fields cover, size."""
    spec = group.spec
    kind = KIND_LABEL.get(spec.kind) or (spec.format or "table").upper()
    parts = [kind] + count_parts(group)
    for row in fields:
        if row["name"] in spec.split_by:
            continue
        if "values" in row:
            values = row["values"]
            shown = ", ".join(values[:4]) + (" and more" if len(values) > 4 else "")
            if shown:
                parts.append(f"{row['name']} {shown}")
        else:
            parts.append(f"{row['name']} {row['min']} to {row['max']}")
    parts.append(_size_text(group.total_bytes))
    return " · ".join(parts)


def group_name(group: Group) -> str:
    spec = group.spec
    if spec.datasets == "per-file":
        return group.key[0]
    if spec.split_by:
        return spec.name + " · " + ", ".join(_value_text(v) for v in group.key)
    return spec.name


def to_resource(manifest: LakeSourceManifest, group: Group) -> LakeResource:
    fields = field_summary(group.spec, group.files)
    return LakeResource(
        source_id=manifest.id,
        resource_id=group.resource_id,
        name=group_name(group),
        description=describe_line(group, fields) + (
            f". {group.spec.description}" if group.spec.description else ""
        ),
        publisher=manifest.publisher,
        formats=(group.spec.dataset_format,),
        updated_at=_iso(group.latest_mtime),
        size_hint=group.total_bytes,
        kind=group.spec.kind,
        file_count=len(group.files),
        fields=tuple(fields),
        samples=tuple(f.relpath for f in group.files[:MAX_SAMPLES]),
    )


# ── the shared listing cache ───────────────────────────────────────────────


@dataclass(frozen=True)
class Sample:
    """One file of a row, as the row's thumbnails draw it."""

    relpath: str
    kind: str
    bytes: int
    mtime: float
    etag: str | None = None


def sample_at(group: Group, index: int) -> Sample | None:
    from utk_curio.backend.app.datalakes.application.probe import file_kind

    if not 0 <= index < len(group.files):
        return None
    f = group.files[index]
    return Sample(f.relpath, file_kind(group.spec.kind, f.relpath), f.size, f.mtime, f.etag)


@dataclass
class _State:
    status: str = "idle"
    resources: list[LakeResource] = field(default_factory=list)
    groups: dict[str, Group] = field(default_factory=dict)
    unmatched: int = 0
    truncated: bool = False
    scanned_at: float | None = None
    started_at: float = 0.0
    #: Files walked so far, while a scan runs.
    seen: int = 0
    error: str | None = None
    #: The last finished scan, served while this one runs.
    previous: "_State | None" = None
    done: threading.Event = field(default_factory=threading.Event)

    def view(self) -> "_State | None":
        """The scan whose rows to serve: this one once ready, else the last."""
        return self if self.status == "ready" else self.previous


class ListingCache:
    """One summary per source and scope, refreshed in the background.

    A public source's summary is shared by every user. A source that sends a
    token is scanned per user (*scope*), so one account's listing is never
    served to another.
    """

    def __init__(self, ttl_seconds: int = SUMMARY_TTL_SECONDS) -> None:
        self._states: dict[tuple[str, str], _State] = {}
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds

    def get(
        self,
        manifest: LakeSourceManifest,
        build_provider: Callable[[], Any],
        *,
        scope: str = "shared",
        rescan: bool = False,
        wait: float = LISTING_WAIT_SECONDS,
    ) -> _State:
        """The source's summary, scanning first when it is missing or stale.

        Waits up to *wait* seconds for a scan it starts or finds running, so a
        small folder answers in one request, and returns the state as it stands
        otherwise. While a scan runs, ``view()`` is the last finished one.
        """
        key = (manifest.dir_name, scope)
        now = time.time()
        with self._lock:
            state = self._states.get(key)
            if state is not None and state.status == "scanning":
                pass
            else:
                fresh = (
                    state is not None
                    and state.status == "ready"
                    and state.scanned_at is not None
                    and now - state.scanned_at < self.ttl_seconds
                )
                # One walk at a time per source and scope: a rescan asked for
                # while one runs is that same walk.
                if state is None or state.status == "failed" or not fresh or rescan:
                    previous = state.view() if state is not None else None
                    state = _State(status="scanning", started_at=now, previous=previous)
                    self._states[key] = state
                    threading.Thread(
                        target=self._run, args=(manifest, build_provider, state), daemon=True
                    ).start()
        if state.status == "scanning" and wait > 0:
            state.done.wait(wait)
        return state

    def _run(self, manifest: LakeSourceManifest, build_provider, state: _State) -> None:
        def progress(seen: int) -> None:
            state.seen = seen

        try:
            result = scan(manifest, build_provider(), progress=progress)
            state.resources = [to_resource(manifest, group) for group in result.groups]
            state.groups = {group.resource_id: group for group in result.groups}
            state.unmatched = result.unmatched
            state.truncated = result.truncated
            state.scanned_at = result.scanned_at
            state.previous = None
            state.status = "ready"
        except Exception as exc:  # noqa: BLE001 - a scan must always end
            state.error = f"{exc}"[:300] or type(exc).__name__
            state.status = "failed"
        finally:
            state.done.set()

    def group(self, manifest: LakeSourceManifest, resource_id: str, *, scope: str = "shared") -> Group | None:
        """One row of the last finished scan, without starting another."""
        with self._lock:
            state = self._states.get((manifest.dir_name, scope))
        view = state.view() if state is not None else None
        return view.groups.get(resource_id) if view is not None else None

    def sample(
        self, manifest: LakeSourceManifest, resource_id: str, index: int, *, scope: str = "shared"
    ) -> Sample | None:
        """The file at *index* of a collection row, to draw a thumbnail of."""
        group = self.group(manifest, resource_id, scope=scope)
        if group is None or not group.spec.is_collection:
            return None
        return sample_at(group, index)

    def reset(self) -> None:
        with self._lock:
            self._states.clear()


#: Process-wide: a public source is walked once for every user.
listings = ListingCache()
