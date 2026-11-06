"""Import a zip Curio exported as a bundle dataset (#1335).

A zip with ``bundle.json`` at its top is one a bundle's Export wrote, or a
Data Export node fed several values (``sandbox/util/bundle_zip.py``), and Import
dataset adds it back as a bundle of the same parts, labels, keys and container.
Its parts are stored under ``data/parts/``, under names minted here as the
computed bundles' are (``<index>_<kind>.<ext>``), never under the zip's own:
a table's CSV, a GeoDataFrame's GeoJSON and a raster's GeoTIFF as they are,
and a value its ``bundle.json`` holds as a ``{"value": ...}`` file (a list or
a dict as itself, as a computed bundle keeps one), each read back as
``curio_load_data`` reads a bundle's part.

The zip is read through the shared extractor (``common/safe_archive.py``),
under the caps a Discovery download's archive has (``archives.caps``), and
``bundle.json`` must describe exactly what the zip holds. A member whose name
climbs out of the zip or is a link, a part file in a folder, a file it does
not list, one it lists and the zip does not hold, a file whose extension is
not its kind's, or a ``bundle.json`` that is not one is refused, saying what
is wrong; nothing is stored.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

#: The zip's index of its parts, at its top (``bundle_zip.BUNDLE_FILE``).
BUNDLE_FILE = "bundle.json"

#: The extensions a part file of each kind may end in, the format it is
#: stored as, and the extension it is stored under.
FILE_KINDS = {
    "dataframe": ((".csv",), "csv", ".csv"),
    "geodataframe": ((".geojson", ".json"), "geojson", ".geojson"),
    "raster": ((".tif", ".tiff"), "geotiff", ".tif"),
}
#: The kinds of a value ``bundle.json`` holds, and those kept as ``{"value": ...}``.
VALUE_KINDS = frozenset({"null", "bool", "int", "float", "str", "list", "dict"})
SCALAR_KINDS = frozenset({"null", "bool", "int", "float", "str"})

#: Files every archiver leaves behind, skipped wherever they are.
_LITTER_NAMES = frozenset({"__macosx", "thumbs.db", "desktop.ini"})


class BundleZipRefused(ValueError):
    """A zip with a ``bundle.json`` that cannot be imported as a bundle."""


def holds_bundle(zip_bytes: bytes) -> bool:
    """Whether the zip *zip_bytes* has a ``bundle.json`` at its top."""
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            return any(info.filename == BUNDLE_FILE for info in zf.infolist())
    except (zipfile.BadZipFile, OSError):
        return False


def _kind_of(value) -> str:
    from utk_curio.sandbox.util.codec import detect_kind

    return detect_kind(value)


def _check_parts(spec: Any) -> tuple[str, list[dict[str, Any]]]:
    """The container and the parts *spec*, the zip's ``bundle.json``, records,
    in index order, or :class:`BundleZipRefused`."""
    from utk_curio.sandbox.util.catalog_helpers import bundle_container

    if not isinstance(spec, dict) or not isinstance(spec.get("parts"), list) or not spec["parts"]:
        raise BundleZipRefused("its bundle.json lists no parts")
    if spec.get("version") != 1:
        raise BundleZipRefused(f"its bundle.json is a version {spec.get('version')} bundle, and Curio reads version 1")
    parts = spec["parts"]
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get("index"), int) or isinstance(part.get("index"), bool):
            raise BundleZipRefused("its bundle.json lists a part with no index")
        if not isinstance(part.get("label"), str):
            raise BundleZipRefused(f"its bundle.json lists part {part['index']} with no label")
    if sorted(part["index"] for part in parts) != list(range(len(parts))):
        raise BundleZipRefused("its bundle.json numbers its parts other than 0, 1, 2 and on")
    parts = sorted(parts, key=lambda part: part["index"])
    try:
        bundle_container(spec, parts)
    except ValueError as exc:
        raise BundleZipRefused(str(exc)) from exc
    for part in parts:
        label, kind = part["label"], part.get("kind")
        if kind in FILE_KINDS:
            if "value" in part:
                raise BundleZipRefused(f"the part {label!r} is a {kind}, which is a file of the zip, not a value")
            name = part.get("file")
            if not isinstance(name, str) or not name:
                raise BundleZipRefused(f"the part {label!r} is a {kind} and names no file")
            if "/" in name or "\\" in name or name == BUNDLE_FILE:
                raise BundleZipRefused(f"bundle.json lists {name!r}, which is not a file at the top of the zip")
            endings = FILE_KINDS[kind][0]
            if not name.lower().endswith(endings):
                raise BundleZipRefused(
                    f"the part {label!r} is a {kind}, whose file ends in {' or '.join(endings)}, "
                    f"and its file is {name!r}"
                )
        elif kind in VALUE_KINDS:
            if "file" in part or "value" not in part:
                raise BundleZipRefused(f"the part {label!r} is a {kind}, which bundle.json holds as its value")
            if _kind_of(part["value"]) != kind:
                raise BundleZipRefused(f"the part {label!r} is a {kind}, and its value is not one")
        else:
            raise BundleZipRefused(f"the part {label!r} is a {kind!r}, which a bundle does not hold")
    files = [part["file"] for part in parts if part["kind"] in FILE_KINDS]
    if len(set(files)) != len(files):
        raise BundleZipRefused("its bundle.json lists one file for two parts")
    return spec.get("container") or "tuple", parts


def _members(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """The files of the zip by name, every name checked, archivers' litter
    left out, or :class:`BundleZipRefused`."""
    from utk_curio.backend.app.common import safe_archive
    from utk_curio.backend.app.discovery.application import archives

    files = [info for info in zf.infolist() if not info.is_dir()]
    if len(files) > archives.MAX_ARCHIVE_MEMBERS:
        raise BundleZipRefused(
            f"it holds {len(files):,} files, more than the {archives.MAX_ARCHIVE_MEMBERS:,} Curio unpacks"
        )
    found: dict[str, zipfile.ZipInfo] = {}
    for info in files:
        try:
            segments = safe_archive.member_segments(info.filename)
        except safe_archive.ArchiveRefused as exc:
            raise BundleZipRefused(str(exc)) from exc
        if safe_archive.is_symlink(info):
            raise BundleZipRefused(f"archive member {info.filename!r} is a symbolic link")
        if safe_archive.is_encrypted(info):
            raise BundleZipRefused(f"archive member {info.filename!r} is password-protected")
        if any(segment.startswith(".") or segment.lower() in _LITTER_NAMES for segment in segments):
            continue
        found["/".join(segments)] = info
    return found


def unpack(archive: Path, work: Path) -> dict[str, Any]:
    """Check the zip at *archive* and stage its parts in *work*/``parts``,
    under minted names. Returns the dataset's ``bundle.json``, whose files
    name the staged parts under ``data/parts/``. Raises
    :class:`BundleZipRefused` saying what is wrong."""
    from utk_curio.backend.app.common import safe_archive
    from utk_curio.backend.app.datasets.domain.constants import TIFF_SIGNATURES
    from utk_curio.backend.app.discovery.application import archives

    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BundleZipRefused(f"the zip could not be read ({exc})") from exc
    with zf:
        members = _members(zf)
        budget = safe_archive.Budget(archives.caps())
        staged = work / "parts"
        staged.mkdir(parents=True)
        try:
            safe_archive.copy_member(zf, members[BUNDLE_FILE], work / BUNDLE_FILE, budget)
            spec = json.loads((work / BUNDLE_FILE).read_text(encoding="utf-8"))
        except safe_archive.ArchiveRefused as exc:
            raise BundleZipRefused(str(exc)) from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise BundleZipRefused("its bundle.json is not JSON") from exc
        container, parts = _check_parts(spec)
        listed = {part["file"] for part in parts if part["kind"] in FILE_KINDS}
        for name in members:
            if name != BUNDLE_FILE and name not in listed:
                raise BundleZipRefused(f"it holds {name!r}, which bundle.json does not list")
        stored = []
        for part in parts:
            kind = part["kind"]
            entry = {"index": part["index"], **({"key": part["key"]} if "key" in part else {}), "label": part["label"], "kind": kind}
            if kind in FILE_KINDS:
                if part["file"] not in members:
                    raise BundleZipRefused(f"bundle.json lists {part['file']!r}, which the zip does not hold")
                _endings, fmt, suffix = FILE_KINDS[kind]
                target = staged / f"{part['index']:02d}_{kind}{suffix}"
                try:
                    safe_archive.copy_member(zf, members[part["file"]], target, budget)
                except safe_archive.ArchiveRefused as exc:
                    raise BundleZipRefused(str(exc)) from exc
                if kind == "raster":
                    with open(target, "rb") as handle:
                        if handle.read(4) not in TIFF_SIGNATURES:
                            raise BundleZipRefused(f"the part {part['label']!r} is a raster, and {part['file']!r} is not a TIFF")
            else:
                fmt = "json"
                target = staged / f"{part['index']:02d}_{kind}.json"
                value = {"value": part["value"]} if kind in SCALAR_KINDS else part["value"]
                target.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
            entry.update(format=fmt, file=f"data/parts/{target.name}")
            stored.append(entry)
    return {"version": 1, "container": container, "parts": stored}


def install(user_key: str, archive: Path, *, title: str, source_updated_at: str | None = None,
            discovery_source: dict | None = None):
    """Add the bundle the zip at *archive* holds to the account's store, as an
    import (``installer._install_imported``). Raises
    :class:`BundleZipRefused` before anything is stored."""
    import tempfile

    from utk_curio.backend.app.datasets.install.installer import _install_imported

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        spec = unpack(archive, work)

        def place(data_path: Path) -> None:
            parts = data_path.parent / "parts"
            parts.mkdir()
            for staged in sorted((work / "parts").iterdir()):
                shutil.move(str(staged), parts / staged.name)
            data_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")

        count = len(spec["parts"])
        return _install_imported(
            user_key,
            place,
            BUNDLE_FILE,
            "bundle",
            title=title,
            source_updated_at=source_updated_at,
            discovery_source=discovery_source,
            description=f"A bundle of {count} part{'s' if count != 1 else ''} imported by the user.",
        )
