"""One zip of the parts of a bundle.

What the Data Catalog's Export gives for a bundle, a node's output of several
parts or a layer group, and what ``curio_export`` writes for a tuple, list or
dict that holds a table or a raster (a Data Export node fed a bundle, or the
several outputs of the node before it). Both write it here, so the same parts
make the same zip.

The zip holds a file per part that is a table (CSV), a GeoDataFrame (GeoJSON)
or a raster (GeoTIFF), each written as ``curio_export`` writes one
(``exports.write``), and ``bundle.json``: the zip's ``version``, the
``container`` its parts were in (``tuple``, ``list`` or ``dict``), and each
part's ``index``, its ``key`` in a dict, its ``label``, its ``kind``, and its
``file`` or, for a JSON value, the ``value`` itself. Anything else is refused,
naming the part. Every member carries one date.

A part's label is, in order (:func:`part_label`): the label of the bundle part
it was read from, which a frame carries in ``metadata["partLabel"]``
(``codec.PART_LABEL``); its key in a dict; a frame's own layer name; its kind
and place. Its file is named after its label, made plain as an export's name
is (``exports._plain``), a run of ``_`` as one: a name another part's file
has, letter case aside, takes ``_2``, ``_3`` after it, and a label that
leaves nothing takes ``part_<n>``, its place counted from 1.

Import dataset reads such a zip back as a bundle
(``backend/app/datasets/install/bundle_zip.py``).
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

#: The zip's index of its parts, at its top.
BUNDLE_FILE = "bundle.json"
#: The version of the zip its ``bundle.json`` records.
VERSION = 1
#: The containers a bundle's parts can be in (``catalog_helpers.bundle_container``).
CONTAINERS = ("tuple", "list", "dict")
#: The kinds of part written as a file, and its file's extension.
FILE_KINDS = {"dataframe": "csv", "geodataframe": "geojson", "raster": "tif"}
#: The kinds of part kept in ``bundle.json`` as its value.
VALUE_KINDS = frozenset({"null", "bool", "int", "float", "str", "list", "dict"})
#: The date every member of a zip carries, so the same parts make the same zip.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
#: The longest name a part's file has, less its extension.
MAX_STEM_CHARS = 96

_RUNS = re.compile(r"_+")

#: A part's kind, as its label says it when nothing else names the part.
_KIND_NAMES = {
    "raster": "Raster",
    "dataframe": "Table",
    "geodataframe": "Geo table",
    "list": "Array",
    "dict": "Object",
    "str": "Text",
    "int": "Number",
    "float": "Number",
    "bool": "Flag",
    "null": "Empty",
}


class PartRefused(ValueError):
    """A part the zip cannot hold: the message names it and says why."""


@dataclass(frozen=True)
class Part:
    """One part of a zip: its place, its label, its key in a dict, and its
    value, or *read*, which reads the value when the zip writes it."""

    index: int
    label: str
    value: Any = None
    key: str | None = None
    read: Callable[[], Any] | None = None


def kind_label(index: int, kind: str) -> str:
    """A part's label by its kind and its place: ``Table · part 1``."""
    base = _KIND_NAMES.get(kind, kind.replace("_", " ").title())
    return f"{base} · part {index + 1}"


def part_label(index: int, kind: str, *, key=None, metadata=None) -> str:
    """The label of the part at *index*, of *kind*: the bundle's label its
    *metadata* carries, else its *key* in a dict, else the layer name its
    *metadata* carries, else its kind and place (:func:`kind_label`)."""
    from utk_curio.sandbox.util.codec import PART_LABEL

    meta = metadata if isinstance(metadata, dict) else {}
    for label in (meta.get(PART_LABEL), None if key is None else str(key), meta.get("name")):
        if isinstance(label, str) and label:
            return label
    return kind_label(index, kind)


def _frame_metadata(value):
    from utk_curio.sandbox.util.codec import detect_kind

    if detect_kind(value) not in ("dataframe", "geodataframe"):
        return None
    meta = value.__dict__.get("metadata")
    return meta if isinstance(meta, dict) else None


def parts_of(data) -> tuple[str, list[Part]]:
    """The container the tuple, list or dict *data* is, and its parts, each
    labelled (:func:`part_label`)."""
    from utk_curio.sandbox.util.codec import detect_kind

    if isinstance(data, dict):
        container, items = "dict", [(str(key), value) for key, value in data.items()]
    elif isinstance(data, (tuple, list)):
        container, items = ("tuple" if isinstance(data, tuple) else "list"), [(None, value) for value in data]
    else:
        raise TypeError(f"a zip is of the parts of a tuple, list or dict, and the data is {_named(data)}.")
    return container, [
        Part(index=index, label=part_label(index, detect_kind(value), key=key, metadata=_frame_metadata(value)),
             value=value, key=key)
        for index, (key, value) in enumerate(items)
    ]


def holds_parts(data) -> bool:
    """Whether ``curio_export`` writes *data* as a zip: a tuple, list or dict
    that holds a table, a GeoDataFrame or a raster."""
    from utk_curio.sandbox.util.codec import detect_kind

    if isinstance(data, dict):
        values = data.values()
    elif isinstance(data, (tuple, list)):
        values = data
    else:
        return False
    return any(detect_kind(value) in FILE_KINDS for value in values)


def _named(value) -> str:
    from utk_curio.sandbox.util.codec import named_type

    return named_type(value)


def _listed(labels: list[str]) -> str:
    quoted = [repr(label) for label in labels]
    if len(quoted) < 2:
        return "".join(quoted) or "none"
    return f"{', '.join(quoted[:-1])} and {quoted[-1]}"


def pick(data, part):
    """The one part of the tuple, list or dict *data* that *part* names: by
    its label, by its key in a dict, or by its position from 0, as a number or
    as text (a Part widget's). One value has no parts, and a name no part has
    is refused with the parts there are."""
    if not isinstance(data, (tuple, list, dict)):
        raise ValueError(
            f"part names one part of a tuple, list or dict, and the data is {_named(data)}: "
            "export it without part, curio_export(data, name)."
        )
    _container, parts = parts_of(data)
    wanted = str(part)
    for found in parts:
        if found.label == wanted:
            return found.value
    for found in parts:
        if found.key is not None and found.key == wanted:
            return found.value
    if isinstance(part, int) and not isinstance(part, bool):
        position = part
    else:
        position = int(wanted) if wanted.strip().isdigit() else None
    if position is not None and 0 <= position < len(parts):
        return parts[position].value
    raise ValueError(
        f"the data has no part {part!r}: its parts are {_listed([found.label for found in parts])}, "
        f"or 0 to {len(parts) - 1} by position."
    )


def file_stems(labels: list[str]) -> list[str]:
    """The name each part's file has, less its extension, by its label: one
    plain name each, and no two the same, letter case aside."""
    from utk_curio.sandbox.util.exports import _plain

    stems: list[str] = []
    taken: set[str] = set()
    for place, label in enumerate(labels, start=1):
        base = _RUNS.sub("_", _plain(str(label or ""))).strip("_")[:MAX_STEM_CHARS].rstrip("._")
        base = base or f"part_{place}"
        stem, count = base, 1
        while stem.lower() in taken:
            count += 1
            stem = f"{base}_{count}"
        taken.add(stem.lower())
        stems.append(stem)
    return stems


def json_value(value, *, part: str | None = None):
    """*value* as JSON holds it: numpy's numbers as numbers, NaN as null.
    Anything JSON cannot hold is refused, naming what it is
    (``exports._json_default``); in the part labelled *part*, a
    :class:`PartRefused` that names the part."""
    from utk_curio.sandbox.util.codec import _json_safe_value, detect_kind
    from utk_curio.sandbox.util.exports import _json_default

    refused: list = []

    def default(item):
        try:
            return _json_default(item)
        except TypeError:
            refused.append(item)
            raise

    try:
        return json.loads(json.dumps(_json_safe_value(value), ensure_ascii=False, default=default))
    except TypeError:
        if part is None or not refused:
            raise
        inner = refused[0]
        advice = (
            "make each table or raster a part of its own" if detect_kind(inner) in FILE_KINDS
            else "which is not a table, a raster or a JSON value"
        )
        separator = ": " if detect_kind(inner) in FILE_KINDS else ", "
        raise PartRefused(
            "a zip of several parts holds each as a file or a JSON value, and the part "
            f"{part!r} holds {_named(inner)}{separator}{advice}."
        ) from None


def _member(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def _add_file(archive: zipfile.ZipFile, path: str, name: str) -> None:
    large = os.path.getsize(path) > zipfile.ZIP64_LIMIT
    with open(path, "rb") as source, archive.open(_member(name), "w", force_zip64=large) as target:
        shutil.copyfileobj(source, target, 1024 * 1024)


def _write_part(archive: zipfile.ZipFile, work: str, part: Part, stem: str) -> dict:
    """Write *part* into *archive*, its file as *stem*, and return its entry
    in ``bundle.json``."""
    from utk_curio.sandbox.util.codec import detect_kind
    from utk_curio.sandbox.util.exports import write

    value, kind = (part.read() if part.read is not None else part.value), None
    try:
        kind = detect_kind(value)
        entry: dict[str, Any] = {"index": part.index}
        if part.key is not None:
            entry["key"] = part.key
        entry["label"] = part.label
        if kind in FILE_KINDS:
            name = f"{stem}.{FILE_KINDS[kind]}"
            written = os.path.join(work, name)
            write(value, written)
            _add_file(archive, written, name)
            os.remove(written)
            entry.update(kind=kind, file=name)
        elif kind in VALUE_KINDS or kind == "outputs":
            # A tuple inside a part is the list JSON holds.
            entry.update(kind="list" if kind == "outputs" else kind, value=json_value(value, part=part.label))
        else:
            raise PartRefused(
                "a zip of several parts holds each as a file or a JSON value, and the part "
                f"{part.label!r} is {_named(value)}, which is neither."
            )
        return entry
    finally:
        if part.read is not None and kind == "raster":
            value.close()


def write_zip(path: str, container: str, parts: list[Part]) -> None:
    """Write the zip of *parts*, which were in *container*, to *path*. The
    part files are written one at a time in a folder beside it, which goes
    once the zip is whole, and the zip takes *path* only then."""
    if container not in CONTAINERS:
        raise ValueError(f"a bundle's parts are in a tuple, a list or a dict, not a {container}.")
    stems = file_stems([part.label for part in parts])
    folder = os.path.dirname(os.path.abspath(path))
    with tempfile.TemporaryDirectory(prefix=".bundle-", dir=folder) as work:
        partial = os.path.join(work, ".bundle.zip")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
            entries = [_write_part(archive, work, part, stem) for part, stem in zip(parts, stems)]
            spec = {"version": VERSION, "container": container, "parts": entries}
            archive.writestr(_member(BUNDLE_FILE), json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
        os.replace(partial, path)


def saved_bundle_parts(bundle_path) -> tuple[str, list[Part]]:
    """The container and the parts of the bundle dataset whose ``bundle.json``
    is at *bundle_path*, each labelled as it labels it and read, as
    ``curio_load_data`` reads it, only when the zip writes it, from the files
    the dataset holds (``catalog_helpers.listed_bundle_parts``)."""
    from utk_curio.sandbox.util.catalog_helpers import bundle_container, listed_bundle_parts, read_bundle_part

    spec = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    named = spec.get("parts") if isinstance(spec, dict) else None
    listed = sorted(listed_bundle_parts(bundle_path), key=lambda item: item[0].get("index", 0))
    if not isinstance(named, list) or not named or len(listed) != len(named):
        raise ValueError("The bundle lists a part whose file it does not hold.")
    bundle_container(spec, [entry for entry, _file in listed])
    container = spec.get("container") or "tuple"
    parts = []
    for index, (entry, file) in enumerate(listed):
        key = entry.get("key") if container == "dict" else None
        label = entry.get("label")
        if not isinstance(label, str) or not label:
            label = part_label(index, str(entry.get("kind") or ""), key=key)
        parts.append(Part(index=index, label=label, key=key, read=functools.partial(read_bundle_part, str(file), entry)))
    return container, parts
