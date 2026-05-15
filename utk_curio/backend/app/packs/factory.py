"""Node-factory builder: turn a wizard draft into a ``.curio-nodepack`` archive.

The Node Factory wizard (see ``docs/nodesfactory@docs/frontend.md`` — Node Factory)
posts a single JSON draft to the backend. This module materialises that
draft into a self-contained zip whose layout matches what
:mod:`utk_curio.backend.app.packs.installer` will accept.

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
        "dependencies": { "packs": {}, "python": {...}, "js": {} },
        "permissions": ["filesystem.read"],
        "kinds": [
          {
            "id": "uhvi-load",
            "label": "UHVI Loader",
            "category": "data",
            "engine": "python",
            "editor": "code",
            "inputPorts": [],
            "outputPorts": [{"types": ["RASTER"], "cardinality": "1"}],
            "templateDir": "templates/uhvi-load",
            "defaultTemplate": "templates/uhvi-load/UHVI_Load_Basic.py",
            ...
          }
        ]
      },
      "sources": {
        "uhvi-load": {
          "UHVI_Load_Basic.py": "import rasterio\n..."
        }
      },
      "readme": "...",        # optional; goes to README.md
      "license_text": "..."   # optional; goes to LICENSE
    }

The builder:

* validates the manifest through :class:`PackManifest` (the same code
  path the installer uses) so the artifact can only be created if it
  would also install,
* lays out template sources under ``templates/<kindId>/<filename>.py``
  (POSIX paths, validated against the storage-layer safe-segment rules),
* refuses any source filename that is not a safe single segment ending
  in ``.py``, and
* writes a deterministic ZIP — entries sorted, stable mtime — so two
  identical drafts always produce byte-identical archives.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from utk_curio.backend.app.packs.manifest import (
    ManifestError,
    PackManifest,
)
from utk_curio.backend.app.packs.storage import KIND_ID_RE


# Each ``sources`` filename must be a single safe segment ending in
# ``.py``. We do not allow nested paths under a kind — the wizard
# surfaces a flat list per kind, and refusing nesting keeps the
# templateDir contract identical to the built-in templates layout.
_TEMPLATE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.py$")

# Deterministic mtime for every zip entry. Pinned to 2024-01-01 UTC so
# two byte-identical drafts produce byte-identical archives — useful for
# integrity hashing and CDN caches.
_FIXED_DATE = (2024, 1, 1, 0, 0, 0)


class FactoryError(ValueError):
    """Raised when a draft fails validation."""


@dataclass(frozen=True)
class BuildResult:
    manifest: PackManifest
    archive: bytes
    filename: str  # suggested download name


def _validate_sources(
    manifest: PackManifest, sources: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    """Ensure every kind's ``sources`` are well-formed and referenceable.

    Specifically:

    * Every key in *sources* must be a known kind id from the manifest.
    * Every filename must match ``_TEMPLATE_FILENAME_RE`` (single safe
      segment, ``.py`` suffix).
    * Every source body must be a string (UTF-8 encoded on write).
    * If a kind declares ``defaultTemplate``, the referenced filename
      must be present in *sources* under that kind.

    Returns a copy with stable iteration order. Unknown kind ids fail
    fast.
    """
    valid_kinds = {k.kind_id for k in manifest.kinds}
    out: dict[str, dict[str, str]] = {}
    for kind_id, files in sources.items():
        if kind_id not in valid_kinds:
            raise FactoryError(
                f"sources references unknown kind id {kind_id!r}; valid: "
                f"{sorted(valid_kinds)}"
            )
        if not KIND_ID_RE.match(kind_id):
            raise FactoryError(f"sources key {kind_id!r} is not a valid kind id")
        if not isinstance(files, dict):
            raise FactoryError(
                f"sources[{kind_id!r}] must be an object of "
                f"{{filename: code}}, got {type(files).__name__}"
            )
        per_kind: dict[str, str] = {}
        for filename, body in files.items():
            if not _TEMPLATE_FILENAME_RE.match(filename):
                raise FactoryError(
                    f"sources[{kind_id!r}].{filename!r} is not a safe "
                    f"single-segment '.py' filename"
                )
            if not isinstance(body, str):
                raise FactoryError(
                    f"sources[{kind_id!r}].{filename!r} body must be a string"
                )
            per_kind[filename] = body
        out[kind_id] = per_kind

    # Cross-check defaultTemplate references.
    for kind in manifest.kinds:
        if not kind.default_template:
            continue
        expected = kind.default_template.rsplit("/", 1)[-1]
        files = out.get(kind.kind_id, {})
        if expected not in files:
            raise FactoryError(
                f"kind {kind.kind_id!r} defaultTemplate references "
                f"{kind.default_template!r} but sources[{kind.kind_id!r}] "
                f"does not provide {expected!r}"
            )
    return out


def _validate_manifest_dict(raw: dict[str, Any]) -> PackManifest:
    """Round-trip the manifest dict through the on-disk validator.

    We don't have a "validate dict" entry point yet — the on-disk loader
    in :mod:`utk_curio.backend.app.packs.manifest` reads from a temp file.
    Reusing it (vs duplicating validation logic here) keeps the
    factory artifact 1:1 with the install path: anything the factory
    produces will install, and anything that won't install fails here.
    """
    import tempfile
    from pathlib import Path
    from utk_curio.backend.app.packs.manifest import load_pack_manifest

    pack_id = raw.get("id")
    major = (raw.get("compatibility") or {}).get("major")
    if not isinstance(pack_id, str) or not isinstance(major, int):
        raise FactoryError(
            "manifest must declare string 'id' and integer "
            "'compatibility.major'"
        )

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / f"{pack_id}@{major}"
        root.mkdir()
        (root / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
        try:
            return load_pack_manifest(root)
        except ManifestError as exc:
            raise FactoryError(str(exc)) from exc


def _add_entry(zf: zipfile.ZipFile, name: str, body: bytes) -> None:
    info = zipfile.ZipInfo(filename=name, date_time=_FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, body)


def build_pack_archive(draft: dict[str, Any]) -> BuildResult:
    """Build a deterministic ``.curio-nodepack`` zip from *draft*.

    Returns the manifest, the raw zip bytes, and a suggested filename
    of the form ``<packId>@<major>-<version>.curio-nodepack``.

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

    manifest = _validate_manifest_dict(manifest_raw)
    validated_sources = _validate_sources(manifest, sources)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        # 1. manifest.json — re-serialised through the validator's view,
        # not the caller's raw bytes, so optional / defaulted fields are
        # normalised consistently.
        _add_entry(
            zf, "manifest.json",
            json.dumps(manifest_raw, indent=2, sort_keys=True).encode("utf-8"),
        )

        # 2. templates/<kindId>/<file>.py — deterministic ordering.
        for kind_id in sorted(validated_sources):
            files = validated_sources[kind_id]
            for filename in sorted(files):
                arcname = f"templates/{kind_id}/{filename}"
                _add_entry(zf, arcname, files[filename].encode("utf-8"))

        # 3. README.md / LICENSE — optional.
        if isinstance(readme, str) and readme.strip():
            _add_entry(zf, "README.md", readme.encode("utf-8"))
        if isinstance(license_text, str) and license_text.strip():
            _add_entry(zf, "LICENSE", license_text.encode("utf-8"))

    filename = f"{manifest.dir_name}-{manifest.version}.curio-nodepack"
    return BuildResult(manifest=manifest, archive=buf.getvalue(), filename=filename)
