"""Node-factory builder: turn a wizard draft into a ``.curio-package`` archive.

The Node Factory wizard posts a single JSON draft to the backend. This
module materialises that draft into a self-contained zip whose layout
matches what :mod:`utk_curio.backend.app.packages.installer` will accept.

A draft looks like::

    {
      "manifest": {                  # full manifest schema, validated below
        "id": "ai.urbanlab.uhvi",
        "version": "1.0.0",
        "name": "UHVI",
        "publisher": "Urban Lab",
        "description": "...",
        "license": "MIT",
        "compatibility": { "major": 1, "curioRuntime": ">=0.5.0" },
        "dependencies": { "packages": {}, "python": {...}, "js": {} },
        "permissions": ["filesystem.read"],
        "kinds": [
          {
            "id": "uhvi-load",
            "label": "UHVI Loader",
            "category": "data",
            "engine": "python",
            "editor": "code",
            "lifecycle": "code",
            "iconRef": "fa-solid:upload",
            "inputPorts": [],
            "outputPorts": [{"types": ["RASTER"], "cardinality": "1"}],
            "source": "sources/uhvi-load.py",
            ...
          }
        ]
      },
      "sources": {
        "uhvi-load": { "filename": "uhvi-load.py", "code": "import rasterio\n..." }
      },
      "readme": "...",        # optional; goes to README.md
      "license_text": "..."   # optional; goes to LICENSE
    }

The builder:

* validates the manifest through :class:`PackageManifest` (the same code
  path the installer uses) so the artifact can only be created if it
  would also install,
* lays out each kind's optional starter under ``sources/<filename>``
  (POSIX paths, validated against the storage-layer safe-segment rules),
* refuses any source filename that is not a single safe segment, and
* writes a deterministic ZIP — entries sorted, stable mtime — so two
  identical drafts always produce byte-identical archives.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from utk_curio.backend.app.packages.manifest import (
    ManifestError,
    PackageManifest,
)
from utk_curio.backend.app.packages.storage import KIND_ID_RE


# Each ``sources`` filename must be a single safe segment with an
# extension (e.g. ``uhvi-load.py``, ``chart.vl.json``, ``hook.js``).
# We do not allow nested paths — each kind ships at most one starter,
# laid out at ``sources/<filename>`` in the archive.
_SOURCE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.[A-Za-z0-9]+$")

# Deterministic mtime for every zip entry. Pinned to 2024-01-01 UTC so
# two byte-identical drafts produce byte-identical archives — useful for
# integrity hashing and CDN caches.
_FIXED_DATE = (2024, 1, 1, 0, 0, 0)


class FactoryError(ValueError):
    """Raised when a draft fails validation."""


@dataclass(frozen=True)
class BuildResult:
    manifest: PackageManifest
    archive: bytes
    filename: str  # suggested download name


def _validate_sources(
    manifest: PackageManifest, sources: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    """Ensure every kind's ``sources`` entry is well-formed and referenceable.

    Each entry is ``{"filename": "...", "code": "..."}`` — one starter
    per kind. If a kind manifest declares ``source: "sources/<X>"``,
    the entry under ``sources[kind_id]`` must provide a matching
    ``filename``.

    Returns a copy with stable iteration order. Unknown kind ids fail
    fast.
    """
    valid_kinds = {k.kind_id for k in manifest.kinds}
    out: dict[str, dict[str, str]] = {}
    for kind_id, entry in sources.items():
        if kind_id not in valid_kinds:
            raise FactoryError(
                f"sources references unknown kind id {kind_id!r}; valid: "
                f"{sorted(valid_kinds)}"
            )
        if not KIND_ID_RE.match(kind_id):
            raise FactoryError(f"sources key {kind_id!r} is not a valid kind id")
        if not isinstance(entry, dict):
            raise FactoryError(
                f"sources[{kind_id!r}] must be an object "
                f'{{"filename": "...", "code": "..."}}, got {type(entry).__name__}'
            )
        filename = entry.get("filename")
        code = entry.get("code")
        if not isinstance(filename, str) or not _SOURCE_FILENAME_RE.match(filename):
            raise FactoryError(
                f"sources[{kind_id!r}].filename {filename!r} must be a single safe "
                f"segment with an extension"
            )
        if not isinstance(code, str):
            raise FactoryError(
                f"sources[{kind_id!r}].code must be a string"
            )
        out[kind_id] = {"filename": filename, "code": code}

    # Cross-check manifest `source` references.
    for kind in manifest.kinds:
        if not kind.source:
            continue
        expected = kind.source.rsplit("/", 1)[-1]
        entry = out.get(kind.kind_id)
        if entry is None or entry.get("filename") != expected:
            raise FactoryError(
                f"kind {kind.kind_id!r} source references "
                f"{kind.source!r} but sources[{kind.kind_id!r}] "
                f"does not provide filename {expected!r}"
            )
    return out


def _stamp_manifest_created_at_when_absent(raw: dict[str, Any]) -> dict[str, Any]:
    """Shallow-copy *raw* and set ``createdAt`` to UTC ISO if missing / blank."""

    merged = dict(raw)
    cv = merged.get("createdAt")
    if isinstance(cv, str) and cv.strip():
        return merged
    merged["createdAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return merged


def _validate_manifest_dict(raw: dict[str, Any]) -> PackageManifest:
    """Round-trip the manifest dict through the on-disk validator.

    We don't have a "validate dict" entry point yet — the on-disk loader
    in :mod:`utk_curio.backend.app.packages.manifest` reads from a temp file.
    Reusing it (vs duplicating validation logic here) keeps the
    factory artifact 1:1 with the install path: anything the factory
    produces will install, and anything that won't install fails here.
    """
    import tempfile
    from pathlib import Path
    from utk_curio.backend.app.packages.manifest import load_packageage_manifest

    package_id = raw.get("id")
    major = (raw.get("compatibility") or {}).get("major")
    if not isinstance(package_id, str) or not isinstance(major, int):
        raise FactoryError(
            "manifest must declare string 'id' and integer "
            "'compatibility.major'"
        )

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / f"{package_id}@{major}"
        root.mkdir()
        (root / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
        try:
            return load_packageage_manifest(root)
        except ManifestError as exc:
            raise FactoryError(str(exc)) from exc


def _add_entry(zf: zipfile.ZipFile, name: str, body: bytes) -> None:
    info = zipfile.ZipInfo(filename=name, date_time=_FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, body)


def build_packageage_archive(draft: dict[str, Any]) -> BuildResult:
    """Build a deterministic ``.curio-package`` zip from *draft*.

    Returns the manifest, the raw zip bytes, and a suggested filename
    of the form ``<packageId>@<major>-<version>.curio-package``.

    The function never touches the filesystem outside a temporary
    directory used by the manifest validator.
    """
    if not isinstance(draft, dict):
        raise FactoryError("draft must be an object")
    manifest_raw = draft.get("manifest")
    if not isinstance(manifest_raw, dict):
        raise FactoryError("draft.manifest is required and must be an object")
    sources = draft.get("sources") or {}
    if not isinstance(sources, dict):
        raise FactoryError("draft.sources must be an object of {kindId: {file: code}}")
    readme = draft.get("readme")
    license_text = draft.get("license_text") or draft.get("licenseText")

    manifest_authoring = _stamp_manifest_created_at_when_absent(dict(manifest_raw))
    manifest = _validate_manifest_dict(manifest_authoring)
    validated_sources = _validate_sources(manifest, sources)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        # 1. manifest.json — canonical ``createdAt`` may be stamped here if absent.
        _add_entry(
            zf, "manifest.json",
            json.dumps(manifest_authoring, indent=2, sort_keys=True).encode("utf-8"),
        )

        # 2. sources/<filename> — one starter per kind, deterministic ordering.
        for kind_id in sorted(validated_sources):
            entry = validated_sources[kind_id]
            arcname = f"sources/{entry['filename']}"
            _add_entry(zf, arcname, entry["code"].encode("utf-8"))

        # 3. README.md / LICENSE — optional.
        if isinstance(readme, str) and readme.strip():
            _add_entry(zf, "README.md", readme.encode("utf-8"))
        if isinstance(license_text, str) and license_text.strip():
            _add_entry(zf, "LICENSE", license_text.encode("utf-8"))

    filename = f"{manifest.dir_name}-{manifest.version}.curio-package"
    return BuildResult(manifest=manifest, archive=buf.getvalue(), filename=filename)
