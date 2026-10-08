"""Node-factory builder: turn a wizard draft into a ``.curio.zip`` archive.

The Node Factory wizard posts a single JSON draft to the backend. This
module materialises that draft into a self-contained zip whose layout
matches what :mod:`utk_curio.backend.app.packages.repositories.archive` will accept.

A draft looks like::

    {
      "manifest": {                  # full manifest schema, validated below
        "id": "ai.utk.uhvi",
        "version": "1.0.0",
        "name": "UHVI",
        "publisher": "Curio",
        "description": "...",
        "license": "MIT",
        "compatibility": { "major": 1, "curioRuntime": ">=0.5.0" },
        "dependencies": { "packages": {}, "python": {...}, "js": {} },
        "permissions": ["filesystem.read"],
        "templates": [
          {
            "id": "uhvi-load",
            "label": "UHVI Loader",
            "category": "data",
            "engine": "python",
            "editor": "code",
            "behavior": "code",
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
* lays out each template's optional starter under ``sources/<filename>``
  (POSIX paths, validated against the storage-layer safe-segment rules),
* refuses any source filename that is not a single safe segment, and
* writes a deterministic ZIP — entries sorted, stable mtime — so two
  identical drafts always produce byte-identical archives.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utk_curio.backend.app.execution.code_references import references_as_names
from utk_curio.backend.app.packages.domain.dependency_scanner import (
    scan_imports_for_filename,
)
from utk_curio.backend.app.packages.domain.manifest import (
    ManifestError,
    PackageManifest,
)
from utk_curio.backend.app.packages.domain.package_id import TEMPLATE_ID_RE
import tempfile
from utk_curio.backend.app.packages.repositories.archive import is_non_content_filename
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.domain.python_modules import module_names_in

log = logging.getLogger(__name__)


# Each ``sources`` filename must be a single safe segment with an
# extension (e.g. ``uhvi-load.py``, ``chart.vl.json``, ``hook.js``).
# We do not allow nested paths — each template ships at most one starter,
# laid out at ``sources/<filename>`` in the archive.
_SOURCE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.[A-Za-z0-9]+$")

# Sentinel body the frontend uses for placeholder source code (kept in sync
# with ``STARTER_CODE`` in
# ``utk_curio/frontend/urban-workflows/src/services/packages/factoryDraft.ts``).
# When the Save-As flow targets an existing installed package, the draft
# carries this body for every template the user did not actively edit; the
# install route swaps it back to the real on-disk source so the rebuild does
# not clobber unedited templates.
_STARTER_CODE_SENTINEL = (
    "# `input_0` holds what the edge on input circle 0 delivers (input_1, input_2,\n"
    "# ... for more circles). Return the value to send downstream.\n"
    "return input_0\n"
)
# The sentinels as they read while a node's input was ``input``, and before
# that ``arg``: a draft made then still carries one.
_INPUT_STARTER_CODE_SENTINEL = (
    "# `input` holds the upstream input (a single value, or a list when\n"
    "# multiple input ports are wired). Return the value to send downstream.\n"
    "return input\n"
)
_OLD_STARTER_CODE_SENTINEL = (
    "# `arg` holds the upstream input (a single value, or a list when\n"
    "# multiple input ports are wired). Return the value to send downstream.\n"
    "return arg\n"
)


def _looks_like_placeholder_source(body: str) -> bool:
    """True when *body* is empty or matches the well-known starter sentinel."""
    if not body or not body.strip():
        return True
    return body in (_STARTER_CODE_SENTINEL, _INPUT_STARTER_CODE_SENTINEL, _OLD_STARTER_CODE_SENTINEL)


def preserve_unedited_sources(
    draft: dict[str, Any],
    existing_package_dir: Path | None,
) -> dict[str, Any]:
    """Return *draft* with placeholder source bodies replaced by on-disk bodies.

    The Save-As flow (``NodeSaveAsModal`` →
    ``POST /api/packages/factory/install``) rebuilds the **entire** installed
    package directory from one draft. The frontend only has the real edited
    source for the canvas node being saved; for every other template in the
    target package, it sends a ``STARTER_CODE`` placeholder because
    ``schemas.responses.package_payload`` does not surface source bodies.

    Without this preservation step, the rebuild would write placeholders over
    every unedited template, silently destroying real code (issue tracked in
    docs/NODE-CATALOG.md). This helper consults
    ``<existing_package_dir>/sources/<filename>`` for each draft template
    whose body is empty or matches the sentinel, substitutes the on-disk
    body, and returns a shallow-copied draft suitable for the builder.

    No-op when *existing_package_dir* is ``None`` or does not exist
    (fresh install — the draft body wins). Templates whose draft body is a
    real edit are also left untouched.
    """
    if existing_package_dir is None or not existing_package_dir.is_dir():
        return draft
    sources = draft.get("sources")
    if not isinstance(sources, dict) or not sources:
        return draft

    sources_dir = existing_package_dir / "sources"
    if not sources_dir.is_dir():
        return draft

    merged_sources: dict[str, Any] = {}
    for template_id, entry in sources.items():
        if not isinstance(entry, dict):
            merged_sources[template_id] = entry
            continue
        filename = entry.get("filename")
        body = entry.get("code")
        if not isinstance(filename, str) or not isinstance(body, str):
            merged_sources[template_id] = entry
            continue
        if not _looks_like_placeholder_source(body):
            merged_sources[template_id] = entry
            continue
        on_disk = sources_dir / filename
        try:
            existing = on_disk.read_text(encoding="utf-8") if on_disk.is_file() else None
        except OSError as exc:
            log.warning(
                "preserve_unedited_sources: cannot read %s: %s", on_disk, exc,
            )
            existing = None
        if existing is None:
            merged_sources[template_id] = entry
            continue
        merged_sources[template_id] = {**entry, "code": existing}

    out = dict(draft)
    out["sources"] = merged_sources
    return out


@dataclass(frozen=True)
class _InstalledBase:
    """What a Save As draft is laid over: the target package as installed."""
    files: dict[str, bytes]  # every content file but manifest.json, by package-relative path
    declared: dict[str, dict[str, str]]  # its declared python / js ranges


def _onto_installed_package(
    draft: dict[str, Any], installed_dir: Path | None,
) -> tuple[dict[str, Any], _InstalledBase | None]:
    """Lay a Save As draft over the installed package it is saved into (#432).

    The draft models a package's sources and the manifest keys the canvas can
    edit, nothing else, so a rebuild from it alone loses README, LICENSE,
    ``scripts/``, ``backend/``, ``behaviorScript`` and every template key it
    does not model. The installed manifest is the base here: the draft's keys
    win, a template merges with its installed namesake by id, and an installed
    template the draft does not name is kept. Every installed file the draft
    does not write is carried forward byte-identical, the same rule
    :mod:`.extension` applies to agent-built extensions.
    """
    if installed_dir is None or not (installed_dir / "manifest.json").is_file():
        return draft, None
    manifest = draft.get("manifest")
    try:
        base = json.loads((installed_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return draft, None
    if not isinstance(manifest, dict) or not isinstance(base, dict):
        return draft, None

    def by_id(templates: Any) -> dict[str, dict]:
        return {
            t["id"]: t for t in templates or []
            if isinstance(t, dict) and isinstance(t.get("id"), str)
        }

    base_templates = by_id(base.get("templates") or base.get("kinds"))
    draft_templates = by_id(manifest.get("templates") or manifest.get("kinds"))
    templates = [{**base_templates.get(tid, {}), **t} for tid, t in draft_templates.items()]
    templates += [t for tid, t in base_templates.items() if tid not in draft_templates]
    merged = {**base, **manifest, "templates": templates}
    merged.pop("kinds", None)

    files: dict[str, bytes] = {}
    for entry in sorted(installed_dir.rglob("*")):
        if not entry.is_file() or is_non_content_filename(entry.name):
            continue
        rel = entry.relative_to(installed_dir).as_posix()
        if rel != "manifest.json":
            files[rel] = entry.read_bytes()

    # An installed template the draft does not name keeps its source, which
    # the source validator needs to find among the draft's sources.
    sources = dict(draft.get("sources") or {})
    for t in templates:
        source = t.get("source")
        if t["id"] in sources or not isinstance(source, str):
            continue
        body = files.get(source)
        if body is not None:
            sources[t["id"]] = {"filename": source.rsplit("/", 1)[-1], "code": body.decode("utf-8")}

    deps = base.get("dependencies") or {}
    declared = {kind: dict(deps.get(kind) or {}) for kind in ("python", "js")}
    out = dict(draft)
    out["manifest"] = merged
    out["sources"] = sources
    return out, _InstalledBase(files=files, declared=declared)

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
    """Ensure every template's ``sources`` entry is well-formed and referenceable.

    Each entry is ``{"filename": "...", "code": "..."}`` — one starter
    per template. If a template manifest declares ``source: "sources/<X>"``,
    the entry under ``sources[template_id]`` must provide a matching
    ``filename``.

    Returns a copy with stable iteration order. Unknown template ids fail
    fast.
    """
    valid_kinds = {k.template_id for k in manifest.templates}
    out: dict[str, dict[str, str]] = {}
    for template_id, entry in sources.items():
        if template_id not in valid_kinds:
            raise FactoryError(
                f"sources references unknown template id {template_id!r}; valid: "
                f"{sorted(valid_kinds)}"
            )
        if not TEMPLATE_ID_RE.match(template_id):
            raise FactoryError(f"sources key {template_id!r} is not a valid template id")
        if not isinstance(entry, dict):
            raise FactoryError(
                f"sources[{template_id!r}] must be an object "
                f'{{"filename": "...", "code": "..."}}, got {type(entry).__name__}'
            )
        filename = entry.get("filename")
        code = entry.get("code")
        if not isinstance(filename, str) or not _SOURCE_FILENAME_RE.match(filename):
            raise FactoryError(
                f"sources[{template_id!r}].filename {filename!r} must be a single safe "
                f"segment with an extension"
            )
        if not isinstance(code, str):
            raise FactoryError(
                f"sources[{template_id!r}].code must be a string"
            )
        out[template_id] = {"filename": filename, "code": code}

    # Cross-check manifest `source` references.
    for template in manifest.templates:
        if not template.source:
            continue
        expected = template.source.rsplit("/", 1)[-1]
        entry = out.get(template.template_id)
        if entry is None or entry.get("filename") != expected:
            raise FactoryError(
                f"kind {template.template_id!r} source references "
                f"{template.source!r} but sources[{template.template_id!r}] "
                f"does not provide filename {expected!r}"
            )
    return out


def _detect_dependencies_from_sources(
    sources: dict[str, dict[str, str]], own_modules: frozenset[str] = frozenset(),
) -> dict[str, dict[str, str]]:
    """Scan every source body for top-level imports; return manifest-shaped deps.

    Replaces the manual Python/JS dependency entry that used to live in the
    Node Factory wizard. Each detected name is pinned to ``"*"`` — version
    pinning is a follow-up enhancement (no UI for it today since the wizard
    is gone). Inter-package (``packages``) deps are not source-derivable and
    must come from the draft. *own_modules* are left out, as the Package
    Builder leaves them out (#468). Each ``[!! ... !!]`` reference is read as
    a plain name, as the Package Builder reads it (#707).
    """
    py: set[str] = set()
    js: set[str] = set()
    for entry in sources.values():
        if not isinstance(entry, dict):
            continue
        filename = entry.get("filename")
        code = entry.get("code")
        if not isinstance(filename, str) or not isinstance(code, str):
            continue
        py_hits, js_hits = scan_imports_for_filename(filename, references_as_names(code), own_modules)
        py.update(py_hits)
        js.update(js_hits)
    return {
        "python": {name: "*" for name in sorted(py)},
        "js": {name: "*" for name in sorted(js)},
    }


def _apply_detected_dependencies(
    manifest_raw: dict[str, Any],
    sources: dict[str, dict[str, str]],
    declared: dict[str, dict[str, str]] | None = None,
    own_modules: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Overwrite manifest ``dependencies.python`` / ``.js`` with source-derived deps.

    *declared* is what the package being saved into already declares: every
    name in it stays, with its range, because the scan sees only the draft's
    sources and not the files carried forward with it (``backend/``, sources
    no template names). *own_modules* are that package's own modules, which
    its templates import and nobody installs. ``dependencies.packages``
    (inter-package deps) is preserved verbatim: it cannot be derived from
    source. The mutation happens on a shallow copy.
    """
    detected = _detect_dependencies_from_sources(sources, own_modules)
    for kind, ranges in (declared or {}).items():
        detected[kind] = dict(sorted({**detected[kind], **ranges}.items()))
    out = dict(manifest_raw)
    existing_deps = dict(out.get("dependencies") or {})
    existing_deps["python"] = detected["python"]
    existing_deps["js"] = detected["js"]
    if "packages" not in existing_deps:
        existing_deps["packages"] = {}
    out["dependencies"] = existing_deps
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
    in :mod:`utk_curio.backend.app.packages.repositories.manifests` reads from a temp file.
    Reusing it (vs duplicating validation logic here) keeps the
    factory artifact 1:1 with the install path: anything the factory
    produces will install, and anything that won't install fails here.
    """
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
            return load_package_manifest(root)
        except ManifestError as exc:
            raise FactoryError(str(exc)) from exc


def _add_entry(zf: zipfile.ZipFile, name: str, body: bytes) -> None:
    info = zipfile.ZipInfo(filename=name, date_time=_FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, body)


def build_package_archive(
    draft: dict[str, Any], *, onto: Path | None = None,
    imported_modules: frozenset[str] = frozenset(),
) -> BuildResult:
    """Build a deterministic ``.curio.zip`` zip from *draft*.

    Returns the manifest, the raw zip bytes, and a suggested filename
    of the form ``<packageId>@<major>-<version>.curio.zip``.

    *onto* is the installed directory of the package a Save As writes into:
    the draft is laid over it (:func:`_onto_installed_package`), so the
    archive is that package with the draft's changes, not the draft alone.

    *imported_modules* are the modules of the packages the draft depends on
    (``dependencies.packages``): its templates import them as they import the
    package's own, so neither becomes a detected Python dependency.

    The function only reads *onto*; it never writes outside a temporary
    directory used by the manifest validator.
    """
    if not isinstance(draft, dict):
        raise FactoryError("draft must be an object")
    draft, base = _onto_installed_package(draft, onto)
    manifest_raw = draft.get("manifest")
    if not isinstance(manifest_raw, dict):
        raise FactoryError("draft.manifest is required and must be an object")
    sources = draft.get("sources") or {}
    if not isinstance(sources, dict):
        raise FactoryError("draft.sources must be an object of {templateId: {file: code}}")
    readme = draft.get("readme")
    license_text = draft.get("license_text") or draft.get("licenseText")

    # Sources land *before* manifest validation so we can derive the
    # ``dependencies.python``/``.js`` fields from the actual imports and have
    # the validator see the final shape. ``packages`` (inter-package deps) is
    # not source-derivable and stays as the draft provided it.
    manifest_with_deps = _apply_detected_dependencies(
        dict(manifest_raw), sources, base.declared if base else None,
        # The modules the package being saved into carries forward (#468),
        # and those of the packages it depends on.
        module_names_in(base.files if base else (), [
            t.get("source") for t in manifest_raw.get("templates") or [] if isinstance(t, dict)
        ]) | frozenset(imported_modules),
    )
    manifest_authoring = _stamp_manifest_created_at_when_absent(manifest_with_deps)
    manifest = _validate_manifest_dict(manifest_authoring)
    validated_sources = _validate_sources(manifest, sources)

    written: set[str] = {"manifest.json"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        # 1. manifest.json — canonical ``createdAt`` may be stamped here if absent.
        _add_entry(
            zf, "manifest.json",
            json.dumps(manifest_authoring, indent=2, sort_keys=True).encode("utf-8"),
        )

        # 2. sources/<filename> — one starter per template, deterministic ordering.
        for template_id in sorted(validated_sources):
            entry = validated_sources[template_id]
            arcname = f"sources/{entry['filename']}"
            _add_entry(zf, arcname, entry["code"].encode("utf-8"))
            written.add(arcname)

        # 3. README.md / LICENSE — optional.
        if isinstance(readme, str) and readme.strip():
            _add_entry(zf, "README.md", readme.encode("utf-8"))
            written.add("README.md")
        if isinstance(license_text, str) and license_text.strip():
            _add_entry(zf, "LICENSE", license_text.encode("utf-8"))
            written.add("LICENSE")

        # 4. Everything else the package being saved into already had.
        for arcname, body in sorted((base.files if base else {}).items()):
            if arcname not in written:
                _add_entry(zf, arcname, body)

    filename = f"{manifest.dir_name}-{manifest.version}.curio.zip"
    return BuildResult(manifest=manifest, archive=buf.getvalue(), filename=filename)
