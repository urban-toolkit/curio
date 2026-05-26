"""Flask blueprint mounted at ``/api/packages``.

Endpoint matrix (every route is ``@require_auth``; user storage key
derives from ``app.projects.services._user_dir_key`` just like
``/api/projects``):

+-------------------------------------------+--------------------------------+
| Endpoint                                  | Plan todo                      |
+===========================================+================================+
| ``GET /api/packages``                        | spike (already shipped)        |
| ``POST /api/packages/upload``                | catalog-api-ui (this commit)   |
| ``DELETE /api/packages/<dir>``               | catalog-api-ui (this commit)   |
| ``GET /api/packages/<dir>/archive``          | catalog-api-ui (this commit)   |
| ``GET /api/packages/catalog``                | catalog-api-ui (this commit)   |
| ``POST /api/packages/factory/build``         | factory-impl (this commit)     |
| ``POST /api/packages/factory/install``       | factory-impl (this commit)     |
| ``GET /api/packages/factory/capabilities``  | wizard — publish gated flags   |
| ``POST /api/packages/factory/publish-catalog`` | dev catalog fixture write (on by default; env to disable) |
| ``DELETE /api/packages/catalog/<dir>``       | dev catalog fixture remove (same env gate as publish) |
| ``POST /api/packages/resolve``               | dep-resolver (this commit)     |
+-------------------------------------------+--------------------------------+

``GET /api/packages/catalog`` is **catalog-backed**: it scans committed packages
under ``<repo_root>/packages/`` and returns package rows plus a family index and
collision report. A **separate remote package-registry** service is still future work.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from pathlib import Path

import json as _json

import requests
from flask import Blueprint, Response, g, jsonify, request

from utk_curio.backend.app.packages.factory import (
    FactoryError,
    build_packageage_archive,
    preserve_unedited_sources,
)
from utk_curio.backend.app.packages.installer import (
    InstallerError,
    export_packageage_archive,
    install_packageage_from_archive,
    install_packageage_from_directory,
    publish_packageage_archive_to_catalog_dir,
    remove_packageage_from_catalog_dir,
    uninstall_packageage,
)
from utk_curio.backend.app.packages.catalog_family import (
    CatalogReleaseTriple,
    catalog_release_collision_groups,
    families_summary,
    family_key_for_manifest,
)
from utk_curio.backend.app.packages.manifest import (
    ManifestError,
    PackageManifest,
    load_packageage_manifest,
)
from utk_curio.backend.app.packages.resolver import (
    ResolverError,
    resolve_for_project,
)
from utk_curio.backend.app.packages.seed import BUILTIN_PACKAGE_ID
from utk_curio.backend.app.packages.storage import (
    PackageIdError,
    list_user_packageages,
    package_dir,
    PACKAGE_DIR_RE,
)
from utk_curio.backend.app.packages import services as packages_services
from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.config import CURIO_ALLOW_FACTORY_CATALOG_PUBLISH

log = logging.getLogger(__name__)

packages_bp = Blueprint("packages_api", __name__, url_prefix="/api/packages")


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _lineage_to_payload(manifest: PackageManifest) -> dict | None:
    lin = manifest.lineage
    if lin is None:
        return None
    return {
        "forkedFrom": {
            "packageId": lin.forked_from.package_id,
            "major": lin.forked_from.major,
        },
        "root": {
            "packageId": lin.root.package_id,
            "major": lin.root.major,
        },
    }


def _manifest_json_mtime_ms(package_path: Path) -> int:
    """Epoch milliseconds of ``manifest.json`` mtime (0 if missing/unreadable).

    Exposed as ``installUpdatedAtMs`` for diagnostics (last write on disk).
    Canonical package ordering uses ``createdAtMs`` from the manifest.
    """
    try:
        return int((package_path / "manifest.json").stat().st_mtime * 1000)
    except OSError:
        return 0


def _manifest_to_payload(manifest: PackageManifest, *, package_mtime_path: Path | None = None) -> dict:
    templates = []
    for tpl in manifest.templates:
        templates.append(
            {
                "id": manifest.canonical_for(tpl.template_id),
                "templateId": tpl.template_id,
                "label": tpl.label,
                "category": tpl.category,
                "engine": tpl.engine,
                "description": tpl.description,
                "icon": tpl.icon,
                "iconRef": tpl.icon_ref,
                "lifecycle": tpl.lifecycle,
                "paletteOrder": tpl.palette_order,
                "editor": tpl.editor,
                "hasCode": tpl.has_code,
                "hasWidgets": tpl.has_widgets,
                "hasGrammar": tpl.has_grammar,
                "grammarId": tpl.grammar_id,
                "badge": tpl.badge,
                "inputPorts": [asdict(p) if is_dataclass(p) else p for p in tpl.input_ports],
                "outputPorts": [asdict(p) if is_dataclass(p) else p for p in tpl.output_ports],
                "source": tpl.source,
                "bidirectional": tpl.bidirectional,
                "containerStyle": tpl.container_style,
                "hasProvenance": tpl.has_provenance,
                "tutorialId": tpl.tutorial_id,
            }
        )
    payload = {
        "packageId": manifest.package_id,
        "major": manifest.major,
        "version": manifest.version,
        "name": manifest.name,
        "publisher": manifest.publisher,
        "description": manifest.description,
        "license": manifest.license,
        "permissions": manifest.permissions,
        "dependencies": {
            "packages": dict(manifest.package_deps),
            "python": dict(manifest.python_deps),
            "js": dict(manifest.js_deps),
        },
        "templates": templates,
        "dirName": manifest.dir_name,
        "lineage": _lineage_to_payload(manifest),
        "familyKey": family_key_for_manifest(manifest),
        "channel": manifest.channel,
        **({"readOnly": True} if manifest.read_only else {}),
        "createdAtMs": manifest.created_at_ms,
        **({"lifecycleScript": manifest.lifecycle_script} if manifest.lifecycle_script else {}),
    }
    if manifest.created_at_iso:
        payload["createdAt"] = manifest.created_at_iso
    if package_mtime_path is not None:
        payload["installUpdatedAtMs"] = _manifest_json_mtime_ms(package_mtime_path)
        # Surface README contents (capped) so the metadata editor can pre-populate.
        readme_path = package_mtime_path / "README.md"
        if readme_path.is_file():
            try:
                raw = readme_path.read_text(encoding="utf-8")
                payload["readme"] = raw[:_README_MAX_BYTES]
            except OSError:
                pass
    return payload


_README_MAX_BYTES = 64 * 1024  # 64 KiB cap on README content surfaced via payload.


def _catalog_root() -> Path:
    """``<repo_root>/packages/`` — committed package catalog root.

    Resolved relative to this file's location so the seeder finds the
    catalog regardless of the launch CWD. This is the dev catalog
    source — production deployments rely on user installs via the
    catalog drawer (and the future remote registry).
    """
    # routes.py -> packages/ -> app/ -> backend/ -> utk_curio/ -> repo_root/packages/
    return Path(__file__).resolve().parents[4] / "packages"


def _resolver_overrides_for(user_key: str, packages: list[str]) -> dict[str, Path]:
    """Build the ``overrides`` map for :func:`resolve_for_project`.

    The pre-install conflict probe in the catalog UI passes the
    candidate's ``dirName`` alongside the already-installed packages so it
    can show the InstallDialog with a precise conflict report. The
    candidate is by definition *not yet installed* — its manifest lives
    in the committed catalog at ``<repo_root>/packages/<dirName>/``,
    not in ``<user>/packages/<dirName>/``. Without an override, the
    resolver would raise ``package <name> is malformed: missing
    manifest.json`` and the user could never get past the dialog.

    For each requested package that is not currently installed, we point
    the resolver at the catalog directory iff a well-formed manifest is
    present there. Unknown packages are left alone so the resolver still
    surfaces a precise "not installed" error.
    """
    catalog_root = _catalog_root()
    if not catalog_root.is_dir():
        return {}
    out: dict[str, Path] = {}
    for name in packages:
        try:
            user_path = package_dir(user_key, name)
        except PackageIdError:
            continue
        if (user_path / "manifest.json").is_file():
            continue
        candidate = catalog_root / name
        if (candidate / "manifest.json").is_file():
            out[name] = candidate
    return out


def _error(message: str, status: int = 400) -> tuple[Response, int]:
    return jsonify({"error": message}), status


# ---------------------------------------------------------------------------
# GET /api/packages — list installed
# ---------------------------------------------------------------------------

@packages_bp.route("", methods=["GET"])
@require_auth
def list_installed_packageages():
    user_key = _user_dir_key(g.user)
    out: list[dict] = []
    for package_path in list_user_packageages(user_key):
        try:
            manifest = load_packageage_manifest(package_path)
        except ManifestError as exc:
            log.warning("Skipping malformed package %s: %s", package_path.name, exc)
            continue
        out.append(_manifest_to_payload(manifest, package_mtime_path=package_path))
    # Newest ``manifest.createdAt`` first — canonical authoring time / ordering.
    out.sort(
        key=lambda p: (-int(p.get("createdAtMs") or 0), p.get("dirName") or ""),
    )
    return jsonify({"packages": out}), 200


# ---------------------------------------------------------------------------
# GET /api/packages/catalog — fixture-backed catalog index
# ---------------------------------------------------------------------------

@packages_bp.route("/catalog", methods=["GET"])
@require_auth
def list_catalog_packageages():
    """Return the catalog scan from ``<repo_root>/packages/``.

    Items share the same shape as ``list_installed_packageages`` (the catalog UI
    can render either feed identically), plus an ``installed`` flag. The
    JSON body also includes ``families`` and ``catalogCollisions``.
    """
    user_key = _user_dir_key(g.user)
    installed_coords = {p.name for p in list_user_packageages(user_key)}

    root = _catalog_root()
    if not root.is_dir():
        return jsonify({"packages": [], "families": [], "catalogCollisions": []}), 200

    out: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not PACKAGE_DIR_RE.match(entry.name):
            continue
        try:
            manifest = load_packageage_manifest(entry)
        except ManifestError as exc:
            log.warning("Skipping malformed fixture %s: %s", entry.name, exc)
            continue
        payload = _manifest_to_payload(manifest, package_mtime_path=entry)
        payload["installed"] = manifest.dir_name in installed_coords
        out.append(payload)

    out.sort(
        key=lambda p: (-int(p.get("createdAtMs") or 0), p.get("dirName") or ""),
    )

    triples: list[tuple[str, CatalogReleaseTriple]] = []
    for p in out:
        fk = p["familyKey"]
        if not isinstance(fk, str):
            continue
        ch = p.get("channel")
        ver = p.get("version")
        if not isinstance(ch, str) or not isinstance(ver, str):
            continue
        dn = p["dirName"]
        if not isinstance(dn, str):
            continue
        triples.append((dn, CatalogReleaseTriple(fk, ch, ver)))

    return jsonify(
        {
            "packages": out,
            "families": families_summary(out),
            "catalogCollisions": catalog_release_collision_groups(triples),
        }
    ), 200


# ---------------------------------------------------------------------------
# POST /api/packages/upload — sideload a .curio.zip
# ---------------------------------------------------------------------------

@packages_bp.route("/upload", methods=["POST"])
@require_auth
def upload_packageage():
    """Sideload a ``.curio.zip`` zip for the current user.

    The archive is read into memory once (capped by the installer at
    128 MiB total uncompressed). Multipart form field name is ``file``
    to mirror the existing ``/upload`` endpoint shape.
    """
    user_key = _user_dir_key(g.user)
    if "file" not in request.files:
        return _error("missing 'file' form field with a .curio.zip archive")
    upload = request.files["file"]
    if not upload.filename:
        return _error("uploaded file is empty (no filename)")
    replace = request.args.get("replace", "false").lower() == "true"
    try:
        result = install_packageage_from_archive(
            user_key, upload.stream.read(), replace=replace
        )
    except InstallerError as exc:
        return _error(str(exc))
    except PackageIdError as exc:
        return _error(str(exc))
    user_packageage = package_dir(user_key, result.manifest.dir_name)
    return jsonify({
        "package": _manifest_to_payload(result.manifest, package_mtime_path=user_packageage),
        "integrity": result.integrity,
        "replacedExisting": result.replaced_existing,
    }), 201


# ---------------------------------------------------------------------------
# POST /api/packages/catalog/install — install a catalog package by dirName
# ---------------------------------------------------------------------------

@packages_bp.route("/catalog/install", methods=["POST"])
@require_auth
def install_from_catalog():
    """Install a catalog package by its on-disk directory name.

    The body is ``{"dirName": "<packageId>@<major>", "replace": false}``;
    the route copies the catalog directory into the user's package store
    via :func:`install_packageage_from_directory`. The catalog set is the
    committed packages shipped in ``<repo_root>/packages/`` — same data the
    ``GET /api/packages/catalog`` route advertises.
    """
    user_key = _user_dir_key(g.user)
    body = request.get_json(silent=True) or {}
    dir_name = body.get("dirName")
    if not isinstance(dir_name, str) or not PACKAGE_DIR_RE.match(dir_name):
        return _error("body must include a valid 'dirName' (<packageId>@<major>)")
    replace = bool(body.get("replace", False))

    src = _catalog_root() / dir_name
    if not src.is_dir():
        return _error(f"catalog has no package {dir_name}", 404)
    try:
        result = install_packageage_from_directory(user_key, src, replace=replace)
    except InstallerError as exc:
        return _error(str(exc))
    user_packageage = package_dir(user_key, result.manifest.dir_name)
    return jsonify({
        "package": _manifest_to_payload(result.manifest, package_mtime_path=user_packageage),
        "integrity": result.integrity,
        "replacedExisting": result.replaced_existing,
    }), 201


# ---------------------------------------------------------------------------
# DELETE /api/packages/catalog/<dir_name> — remove fixture from dev catalog
# ---------------------------------------------------------------------------


@packages_bp.route("/catalog/<dir_name>", methods=["DELETE"])
@require_auth
def unpublish_from_catalog(dir_name: str):
    """Remove a package directory from ``<repo_root>/packages/`` (developer catalog only).

    Does **not** uninstall from the user's package store — use
    ``DELETE /api/packages/<dir_name>`` for that. Gated by the same env flag as
    ``factory/publish-catalog``.
    """
    if not CURIO_ALLOW_FACTORY_CATALOG_PUBLISH:
        return jsonify(
            {
                "error": (
                    "Catalog fixture publish is disabled on this server. "
                    "Unset CURIO_ALLOW_FACTORY_CATALOG_PUBLISH or set it to 1, "
                    "true, yes, or on to enable; restart the backend after changes."
                ),
            },
        ), 403

    if not PACKAGE_DIR_RE.match(dir_name):
        return _error("dir_name must match <packageId>@<major>")

    try:
        removed = remove_packageage_from_catalog_dir(_catalog_root(), dir_name)
    except InstallerError as exc:
        return _error(str(exc))
    if not removed:
        return _error(f"catalog has no package {dir_name}", 404)
    return "", 204


# ---------------------------------------------------------------------------
# DELETE /api/packages/<dir_name> — uninstall
# ---------------------------------------------------------------------------

@packages_bp.route("/<dir_name>", methods=["DELETE"])
@require_auth
def remove_packageage(dir_name: str):
    if dir_name.startswith(f"{BUILTIN_PACKAGE_ID}@"):
        return _error(f"{BUILTIN_PACKAGE_ID} is built-in and cannot be uninstalled", 400)
    user_key = _user_dir_key(g.user)
    try:
        removed = uninstall_packageage(user_key, dir_name)
    except PackageIdError as exc:
        return _error(str(exc))
    if not removed:
        return _error("package not installed", 404)
    return "", 204


# ---------------------------------------------------------------------------
# PATCH /api/packages/<dir_name> — partial metadata edit
# ---------------------------------------------------------------------------

_PATCH_ALLOWED_TOP_KEYS: frozenset[str] = frozenset({
    "name", "description", "publisher", "license", "permissions",
})
_PATCH_ALLOWED_COMPAT_KEYS: frozenset[str] = frozenset({"curioRuntime"})


@packages_bp.route("/<dir_name>", methods=["PATCH"])
@require_auth
def patch_package_metadata(dir_name: str):
    """Partial-update human-authored package metadata.

    Replaces the Node Factory wizard's metadata fields for installed packages.
    Read-only packages (``curio.builtin@1`` and similar) reject with ``403``.
    Identity-bearing keys (``id``, ``version``, ``major``, ``kinds``,
    ``lineage``, ``readOnly``, ``createdAt``, ``distribution``,
    ``dependencies``) cannot be mutated through this endpoint — ``dependencies``
    in particular comes from source-scan now.
    """
    user_key = _user_dir_key(g.user)
    try:
        pkg_path = package_dir(user_key, dir_name)
    except PackageIdError as exc:
        return _error(str(exc))
    if not pkg_path.is_dir():
        return _error("package not installed", 404)

    manifest_path = pkg_path / "manifest.json"
    if not manifest_path.is_file():
        return _error("manifest.json missing", 404)

    try:
        original_bytes = manifest_path.read_bytes()
        raw = _json.loads(original_bytes.decode("utf-8"))
    except (OSError, _json.JSONDecodeError) as exc:
        return _error(f"cannot read manifest: {exc}")
    if not isinstance(raw, dict):
        return _error("manifest.json root must be an object")

    if raw.get("readOnly") is True:
        return _error("this package is read-only", 403)

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("request body must be a JSON object")

    # Validate the allowlist before touching disk.
    readme_update = body.get("readme") if "readme" in body else None
    readme_supplied = "readme" in body
    compat_update = body.get("compatibility")
    if compat_update is not None and not isinstance(compat_update, dict):
        return _error("compatibility must be an object")
    if compat_update:
        bad = set(compat_update) - _PATCH_ALLOWED_COMPAT_KEYS
        if bad:
            return _error(
                f"compatibility keys not editable here: {sorted(bad)}; "
                f"allowed: {sorted(_PATCH_ALLOWED_COMPAT_KEYS)}",
            )

    rejected = (set(body) - _PATCH_ALLOWED_TOP_KEYS) - {"compatibility", "readme"}
    if rejected:
        return _error(
            f"fields not editable through PATCH: {sorted(rejected)}; "
            f"allowed: {sorted(_PATCH_ALLOWED_TOP_KEYS | {'compatibility', 'readme'})}",
        )

    # Apply top-level allowlisted keys.
    for key in _PATCH_ALLOWED_TOP_KEYS:
        if key in body:
            raw[key] = body[key]

    # Merge compatibility shallowly so untouched sibling keys (e.g. `major`) survive.
    if compat_update:
        existing_compat = dict(raw.get("compatibility") or {})
        existing_compat.update(compat_update)
        raw["compatibility"] = existing_compat

    # Atomic manifest write, then re-validate; restore originals on validation failure.
    serialized = (_json.dumps(raw, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    tmp_path = manifest_path.with_name("manifest.json.tmp")
    try:
        tmp_path.write_bytes(serialized)
        tmp_path.replace(manifest_path)
    except OSError as exc:
        return _error(f"cannot write manifest: {exc}")

    try:
        manifest = load_packageage_manifest(pkg_path)
    except ManifestError as exc:
        manifest_path.write_bytes(original_bytes)
        return _error(f"patch rejected by validator: {exc}")

    # README is a sibling file; write/unlink it atomically only after the manifest
    # validates so a bad metadata patch doesn't half-mutate the package.
    readme_path = pkg_path / "README.md"
    if readme_supplied:
        if isinstance(readme_update, str) and readme_update.strip():
            try:
                tmp_readme = readme_path.with_name("README.md.tmp")
                tmp_readme.write_text(readme_update, encoding="utf-8")
                tmp_readme.replace(readme_path)
            except OSError as exc:
                return _error(f"cannot write README: {exc}")
        elif readme_update is None or readme_update == "":
            try:
                readme_path.unlink(missing_ok=True)
            except OSError as exc:
                return _error(f"cannot remove README: {exc}")
        else:
            return _error("readme must be a string or null")

    return jsonify({
        "package": _manifest_to_payload(manifest, package_mtime_path=pkg_path),
    }), 200


# ---------------------------------------------------------------------------
# GET /api/packages/<dir_name>/archive — re-export
# ---------------------------------------------------------------------------

@packages_bp.route("/<dir_name>/archive", methods=["GET"])
@require_auth
def download_packageage_archive(dir_name: str):
    user_key = _user_dir_key(g.user)
    try:
        body = export_packageage_archive(user_key, dir_name)
    except (InstallerError, PackageIdError) as exc:
        return _error(str(exc), 404)
    response = Response(body, mimetype="application/zip")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{dir_name}.curio.zip"'
    )
    return response


# ---------------------------------------------------------------------------
# GET /api/packages/<dir_name>/file/<path:filename>
# ---------------------------------------------------------------------------
# Serves a static file from a user's installed copy of a package. Used by the
# dynamic-lifecycle loader on the frontend to fetch each package's compiled
# `lifecycles.js` bundle (declared in the manifest via `lifecycleScript`).
# Path resolution flows through `safe_join` so traversal payloads can't escape
# the package directory, and the result is always rooted in the user's own
# `<instance>/.curio/users/<user_key>/packages/<dir>/` tree.

_PACKAGE_FILE_MIMETYPES: dict[str, str] = {
    ".js":   "application/javascript; charset=utf-8",
    ".mjs":  "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".geojson": "application/geo+json; charset=utf-8",
    ".md":   "text/markdown; charset=utf-8",
    ".txt":  "text/plain; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".map":  "application/json; charset=utf-8",
}


@packages_bp.route("/<dir_name>/file/<path:filename>", methods=["GET"])
@require_auth
def get_package_file(dir_name: str, filename: str):
    """Serve a static file from the user's installed copy of ``<dir_name>``.

    Mounted at ``GET /api/packages/<dir_name>/file/<path:filename>``. The
    frontend's dynamic lifecycle loader hits this to fetch each package's
    compiled ``lifecycles.js`` bundle (when its manifest declares
    ``lifecycleScript``). Any package-shipped asset (overlay imagery,
    starter source, …) can be retrieved via the same route.
    """
    from utk_curio.backend.app.common.safe_paths import (
        PathTraversalError,
        safe_join,
    )

    user_key = _user_dir_key(g.user)
    try:
        base = package_dir(user_key, dir_name)
    except (PackageIdError, PathTraversalError) as exc:
        return _error(str(exc), 404)

    try:
        # `validate=False` because the request can legitimately span subdirs
        # (e.g. `sources/index.js`). The final `is_within` check still
        # guarantees containment.
        target = safe_join(base, filename, validate=False, field="filename")
    except PathTraversalError as exc:
        return _error(str(exc), 400)

    if not target.is_file():
        return _error(f"package file not found: {filename}", 404)

    suffix = target.suffix.lower()
    mimetype = _PACKAGE_FILE_MIMETYPES.get(suffix, "application/octet-stream")
    try:
        body = target.read_bytes()
    except OSError as exc:
        return _error(f"could not read package file: {exc}", 500)

    response = Response(body, mimetype=mimetype)
    # Package files are content-addressed via integrity.json — once a sha
    # matches, the file is immutable for this install. A short browser
    # cache is safe and keeps the dynamic loader fast on repeat boots.
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


# ---------------------------------------------------------------------------
# GET /api/packages/factory/capabilities
# ---------------------------------------------------------------------------


@packages_bp.route("/factory/capabilities", methods=["GET"])
@require_auth
def factory_capabilities():
    """Return which factory features are usable (controlled by deployment env)."""
    return jsonify({"catalogPublish": CURIO_ALLOW_FACTORY_CATALOG_PUBLISH}), 200


# ---------------------------------------------------------------------------
# POST /api/packages/factory/publish-catalog (opt-in fixture write)
# ---------------------------------------------------------------------------


@packages_bp.route("/factory/publish-catalog", methods=["POST"])
@require_auth
def factory_publish_catalog():
    """Build draft and publish into ``<repo_root>/packages/`` — **developers only**.

    Allowed by default; set ``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`` to ``0``,
    ``false``, ``no``, or ``off`` to disable.

    Writes the same directory layout Sideload installs use; may trigger hot
    reload of the Flask process when watchers observe the catalog.
    """
    if not CURIO_ALLOW_FACTORY_CATALOG_PUBLISH:
        return jsonify(
            {
                "error": (
                    "Catalog fixture publish is disabled on this server. "
                    "Unset CURIO_ALLOW_FACTORY_CATALOG_PUBLISH or set it to 1, "
                    "true, yes, or on to enable; restart the backend after changes."
                ),
            },
        ), 403

    body = dict(request.get_json(silent=True) or {})
    replace = bool(body.pop("replace", False))
    catalog = _catalog_root()
    # Same trap as /factory/install: a draft built from
    # ``draftFromInstalledPackagePayload`` only carries real source for the
    # template the user actively edited; every other template ships the
    # STARTER_CODE placeholder. Read the user's installed sources from disk
    # before the rebuild so we don't publish placeholders to the catalog.
    user_key = _user_dir_key(g.user)
    existing_dir: Path | None = None
    manifest_raw = body.get("manifest")
    if isinstance(manifest_raw, dict):
        package_id_raw = manifest_raw.get("id")
        major_raw = (manifest_raw.get("compatibility") or {}).get("major")
        if isinstance(package_id_raw, str) and isinstance(major_raw, int):
            try:
                candidate = package_dir(user_key, f"{package_id_raw}@{major_raw}")
            except PackageIdError:
                candidate = None
            if candidate is not None and candidate.is_dir():
                existing_dir = candidate
    body = preserve_unedited_sources(body, existing_dir)
    try:
        built = build_packageage_archive(body)
        result = publish_packageage_archive_to_catalog_dir(
            built.archive,
            catalog,
            replace=replace,
        )
    except FactoryError as exc:
        return _error(str(exc))
    except InstallerError as exc:
        return _error(str(exc))
    catalog_path = catalog / result.manifest.dir_name
    return jsonify({
        "package": _manifest_to_payload(result.manifest, package_mtime_path=catalog_path),
        "integrity": result.integrity,
        "replacedExisting": result.replaced_existing,
        "filename": built.filename,
        "catalogDir": str(catalog_path),
    }), 201


@packages_bp.route("/factory/build", methods=["POST"])
@require_auth
def factory_build():
    """Validate a draft and return the produced ``.curio.zip`` bytes."""
    draft = request.get_json(silent=True) or {}
    try:
        result = build_packageage_archive(draft)
    except FactoryError as exc:
        return _error(str(exc))
    response = Response(result.archive, mimetype="application/zip")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{result.filename}"'
    )
    response.headers["X-Curio-Package-Dir"] = result.manifest.dir_name
    response.headers["X-Curio-Package-Version"] = result.manifest.version
    return response


# ---------------------------------------------------------------------------
# POST /api/packages/factory/install — wizard -> install in one shot
# ---------------------------------------------------------------------------

@packages_bp.route("/factory/install", methods=["POST"])
@require_auth
def factory_install():
    """Build a draft and immediately install it for the current user.

    Convenience for the "Save and install" affordance in the wizard's
    Step 5; equivalent to POST /factory/build + POST /upload back to
    back, without the byte round-trip through the browser.
    """
    user_key = _user_dir_key(g.user)
    draft = request.get_json(silent=True) or {}
    manifest_raw = draft.get("manifest")
    if isinstance(manifest_raw, dict):
        if manifest_raw.get("readOnly") is True:
            return _error("this package is read-only — save changes as a new package")
        # Defense-in-depth: a forged draft can omit readOnly, so also check the
        # installed package at the target coord. Catches any attempt to overwrite a
        # read-only package that's already installed (e.g. curio.builtin).
        package_id_raw = manifest_raw.get("id")
        major_raw = (manifest_raw.get("compatibility") or {}).get("major")
        if isinstance(package_id_raw, str) and isinstance(major_raw, int):
            try:
                installed_dir = package_dir(user_key, f"{package_id_raw}@{major_raw}")
            except PackageIdError:
                installed_dir = None
            if installed_dir is not None and installed_dir.is_dir():
                try:
                    if load_packageage_manifest(installed_dir).read_only:
                        return _error("this package is read-only — save changes as a new package")
                except ManifestError:
                    pass  # Let the install path surface a more specific error.
    replace = bool(draft.get("replace", False))
    # Save-As over an existing package only carries real source bytes for the
    # template the user actively edited; every other template comes through
    # with the STARTER_CODE placeholder. Read the unedited templates' real
    # source from disk before the rebuild so we don't clobber them.
    existing_dir: Path | None = None
    if isinstance(manifest_raw, dict):
        package_id_raw = manifest_raw.get("id")
        major_raw = (manifest_raw.get("compatibility") or {}).get("major")
        if isinstance(package_id_raw, str) and isinstance(major_raw, int):
            try:
                candidate = package_dir(user_key, f"{package_id_raw}@{major_raw}")
            except PackageIdError:
                candidate = None
            if candidate is not None and candidate.is_dir():
                existing_dir = candidate
    draft = preserve_unedited_sources(draft, existing_dir)
    try:
        built = build_packageage_archive(draft)
        result = install_packageage_from_archive(
            user_key, built.archive, replace=replace,
        )
    except FactoryError as exc:
        return _error(str(exc))
    except InstallerError as exc:
        return _error(str(exc))
    user_packageage = package_dir(user_key, result.manifest.dir_name)
    return jsonify({
        "package": _manifest_to_payload(result.manifest, package_mtime_path=user_packageage),
        "integrity": result.integrity,
        "replacedExisting": result.replaced_existing,
        "filename": built.filename,
    }), 201


# ---------------------------------------------------------------------------
# POST /api/packages/resolve — dep resolution
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Sandbox install helper
# ---------------------------------------------------------------------------

def _forward_to_sandbox_install(packages: list[str]) -> tuple[dict, int]:
    """POST the merged package list to the sandbox ``/install`` route.

    Mirrors the shape of :func:`api.routes.install_packageages` so the
    behaviour stays in lockstep with the existing ``/installPackages``
    endpoint — same Flask address resolution, same timeout policy. Lives
    in this module (rather than importing from ``api.routes``) so the
    test suite can monkey-patch without booting the sandbox.
    """
    from utk_curio.backend.app.api import routes as api_routes  # local: no cycle
    response = api_routes._sandbox_call(
        "post", "/install",
        label="/api/packages/install-deps",
        timeout=api_routes.SANDBOX_INSTALL_TIMEOUT,
        data=_json.dumps({"packages": packages}),
        headers={"Content-Type": "application/json"},
    )
    if isinstance(response, tuple):
        flask_resp, status = response
        try:
            return flask_resp.get_json(), status
        except Exception:  # noqa: BLE001
            return {"error": "sandbox_unreachable"}, status
    try:
        return response.json(), response.status_code
    except (ValueError, requests.JSONDecodeError):
        return {
            "error": "sandbox_returned_non_json",
            "status": response.status_code,
            "body": response.text[:512],
        }, 502


# ---------------------------------------------------------------------------
# POST /api/packages/install-deps — resolve + push to sandbox
# ---------------------------------------------------------------------------

@packages_bp.route("/install-deps", methods=["POST"])
@require_auth
def install_packageage_deps():
    """Resolve a set of package dirs and install the merged python deps.

    Body shape: ``{"packages": ["ai.urbanlab.uhvi@1", ...]}``.

    Returns ``{lockfile, conflicts, sandboxStatus, sandboxBody}``:

    * On conflict (409) the resolver returns ``conflicts``; the sandbox
      is never touched.
    * On success the resolver hands the **merged** python deps over to
      the existing ``/install`` route on the shared sandbox interpreter
      (this is the same path the legacy ``/installPackages`` route
      uses). The lockfile is returned so the frontend can persist it in
      the project's ``spec.trill.json``.
    """
    user_key = _user_dir_key(g.user)
    body = request.get_json(silent=True) or {}
    packages = body.get("packages")
    if not isinstance(packages, list) or not all(isinstance(p, str) for p in packages):
        return _error("body must be {'packages': [<dirName>, ...]}")
    overrides = _resolver_overrides_for(user_key, packages)
    try:
        result = resolve_for_project(user_key, packages, overrides=overrides)
    except ResolverError as exc:
        return _error(str(exc))
    except PackageIdError as exc:
        return _error(str(exc))

    if result.conflicts:
        return jsonify({
            "lockfile": result.to_lockfile(),
            "conflicts": [
                {
                    "package": c.package,
                    "ranges": [
                        {"packageDir": p, "range": r} for (p, r) in c.ranges
                    ],
                }
                for c in result.conflicts
            ],
            "sandboxStatus": None,
        }), 409

    # ``resolver._format_range`` only ever emits ``"*"`` (no constraint),
    # ``">=X.Y.Z"`` or ``">=X.Y.Z,<A.B.C"`` — all directly understood by
    # pip. ``"*"`` becomes a bare package name (install latest).
    pip_requirements = [
        pkg if rng == "*" else f"{pkg}{rng}"
        for pkg, rng in sorted(result.python_deps.items())
    ]
    sandbox_body, sandbox_status = (
        _forward_to_sandbox_install(pip_requirements) if pip_requirements else ({"installed": []}, 200)
    )

    return jsonify({
        "lockfile": result.to_lockfile(),
        "conflicts": [],
        "sandboxStatus": sandbox_status,
        "sandboxBody": sandbox_body,
        "pipRequirements": pip_requirements,
    }), 200 if sandbox_status < 400 else sandbox_status


# ---------------------------------------------------------------------------
# POST /api/packages/resolve — dep resolution only (no sandbox install)
# ---------------------------------------------------------------------------

@packages_bp.route("/resolve", methods=["POST"])
@require_auth
def resolve_deps():
    """Resolve the dep graph for a set of package directory names.

    Body shape: ``{"packages": ["ai.urbanlab.uhvi@1", ...]}``.

    * 200 — fully resolved; returns ``{lockfile, conflicts: []}``.
    * 409 — at least one Python (or JS) range conflict across packages;
      returns ``{lockfile: {...}, conflicts: [{package, ranges: [{packageDir,
      range}, ...]}, ...]}`` so the UI can show a precise error.
    * 400 — malformed body, cycle, missing package dep.
    """
    user_key = _user_dir_key(g.user)
    body = request.get_json(silent=True) or {}
    packages = body.get("packages")
    if not isinstance(packages, list) or not all(isinstance(p, str) for p in packages):
        return _error("body must be {'packages': [<dirName>, ...]}")
    overrides = _resolver_overrides_for(user_key, packages)
    try:
        result = resolve_for_project(user_key, packages, overrides=overrides)
    except ResolverError as exc:
        return _error(str(exc))
    except PackageIdError as exc:
        return _error(str(exc))

    payload = {
        "lockfile": result.to_lockfile(),
        "conflicts": [
            {
                "package": c.package,
                "ranges": [
                    {"packageDir": p, "range": r} for (p, r) in c.ranges
                ],
            }
            for c in result.conflicts
        ],
    }
    return jsonify(payload), (409 if result.conflicts else 200)


# ---------------------------------------------------------------------------
# Per-project lockfile + per-user defaults
# ---------------------------------------------------------------------------
#
# These five endpoints implement the project-scoped install/uninstall and the
# per-user defaults list from [docs/CATALOG.md]. The drawer in the canvas
# uses the `/projects/<id>/...` endpoints; the `/catalog` page uses
# `/defaults`. There is deliberately no `DELETE /defaults/<dir>` — the only
# way a package leaves the defaults list is via `prune_unreferenced_packages`,
# which fires when the last project drops a dep.

def _packages_error(exc: packages_services.PackageServiceError):
    return jsonify({"error": str(exc)}), exc.status


@packages_bp.route("/projects/<project_id>", methods=["GET"])
@require_auth
def get_project_packages(project_id: str):
    """Return ``{"packages": [...dirNames]}`` for the project's lockfile."""
    user_key = _user_dir_key(g.user)
    try:
        # Ownership check happens via the repo (raises NotFoundError → 404).
        projects_repo.get_for_user(project_id, g.user.id)
        dirs = packages_services.get_project_lockfile(user_key, project_id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except packages_services.PackageServiceError as exc:
        return _packages_error(exc)
    return jsonify({"packages": sorted(dirs)}), 200


@packages_bp.route("/projects/<project_id>/install", methods=["POST"])
@require_auth
def install_to_project_route(project_id: str):
    """Install a catalog package into one project's lockfile."""
    user_key = _user_dir_key(g.user)
    body = request.get_json(silent=True) or {}
    dir_name = body.get("dirName")
    if not isinstance(dir_name, str):
        return _error("body must include 'dirName'")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = packages_services.install_to_project(user_key, project_id, dir_name)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except packages_services.PackageServiceError as exc:
        return _packages_error(exc)
    return jsonify(payload), 201


@packages_bp.route("/projects/<project_id>/<dir_name>", methods=["DELETE"])
@require_auth
def uninstall_from_project_route(project_id: str, dir_name: str):
    """Drop a package from one project's lockfile; auto-prune the user store."""
    user_key = _user_dir_key(g.user)
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = packages_services.uninstall_from_project(
            user_key, project_id, dir_name,
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except packages_services.PackageServiceError as exc:
        return _packages_error(exc)
    return jsonify(payload), 200


@packages_bp.route("/defaults", methods=["GET"])
@require_auth
def get_defaults_route():
    """Return ``{"packages": [...dirNames]}`` for the user's defaults list."""
    from utk_curio.backend.app.packages import defaults as defaults_io

    user_key = _user_dir_key(g.user)
    return jsonify({"packages": sorted(defaults_io.load_defaults(user_key))}), 200


@packages_bp.route("/defaults", methods=["POST"])
@require_auth
def install_to_defaults_route():
    """Install a catalog package for every existing project + future ones."""
    body = request.get_json(silent=True) or {}
    dir_name = body.get("dirName")
    if not isinstance(dir_name, str):
        return _error("body must include 'dirName'")
    try:
        payload = packages_services.install_to_defaults(g.user, dir_name)
    except packages_services.PackageServiceError as exc:
        return _packages_error(exc)
    return jsonify(payload), 201
