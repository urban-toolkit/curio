"""Flask blueprint mounted at ``/api/packs``.

Endpoint matrix (every route is ``@require_auth``; user storage key
derives from ``app.projects.services._user_dir_key`` just like
``/api/projects``):

+-------------------------------------------+--------------------------------+
| Endpoint                                  | Plan todo                      |
+===========================================+================================+
| ``GET /api/packs``                        | spike (already shipped)        |
| ``POST /api/packs/upload``                | warehouse-api-ui (this commit) |
| ``DELETE /api/packs/<dir>``               | warehouse-api-ui (this commit) |
| ``GET /api/packs/<dir>/archive``          | warehouse-api-ui (this commit) |
| ``GET /api/packs/catalog``                | warehouse-api-ui (this commit) |
| ``POST /api/packs/factory/build``         | factory-impl (this commit)     |
| ``POST /api/packs/factory/install``       | factory-impl (this commit)     |
| ``GET /api/packs/factory/capabilities``  | wizard — publish gated flags   |
| ``POST /api/packs/factory/publish-catalog`` | dev catalog fixture write (on by default; env to disable) |
| ``DELETE /api/packs/catalog/<dir>``       | dev catalog fixture remove (same env gate as publish) |
| ``POST /api/packs/resolve``               | dep-resolver (this commit)     |
| ``POST /api/packs/palette-dock/fork-parents`` | fork-parent dock hide/reveal |
| ``POST /api/packs/<dir>/palette-dock-visible`` | per-pack palette dock toggle |
+-------------------------------------------+--------------------------------+

``GET /api/packs/catalog`` is **catalog-backed**: it scans committed packs
under ``<repo_root>/packs/`` and returns pack rows plus a family index and
collision report. A **separate remote pack-registry** service is still future work.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path

import json as _json

import requests
from flask import Blueprint, Response, g, jsonify, request

from utk_curio.backend.app.packs.factory import (
    FactoryError,
    build_pack_archive,
)
from utk_curio.backend.app.packs.installer import (
    InstallerError,
    export_pack_archive,
    install_pack_from_archive,
    install_pack_from_directory,
    publish_pack_archive_to_catalog_dir,
    remove_pack_from_catalog_dir,
    uninstall_pack,
)
from utk_curio.backend.app.packs.catalog_family import (
    CatalogReleaseTriple,
    catalog_release_collision_groups,
    families_summary,
    family_key_for_manifest,
)
from utk_curio.backend.app.packs.manifest import (
    ManifestError,
    PackManifest,
    load_pack_manifest,
)
from utk_curio.backend.app.packs.palette_dock_manifest import (
    merge_manifest_palette_dock_fork_hidden,
    set_all_fork_parents_palette_visibility,
)
from utk_curio.backend.app.packs.resolver import (
    ResolverError,
    resolve_for_project,
)
from utk_curio.backend.app.packs.seed import BUILTIN_PACK_ID
from utk_curio.backend.app.packs.storage import (
    PackIdError,
    list_user_packs,
    pack_dir,
    PACK_DIR_RE,
)
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth

log = logging.getLogger(__name__)

packs_bp = Blueprint("packs_api", __name__, url_prefix="/api/packs")


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _lineage_to_payload(manifest: PackManifest) -> dict | None:
    lin = manifest.lineage
    if lin is None:
        return None
    return {
        "forkedFrom": {
            "packId": lin.forked_from.pack_id,
            "major": lin.forked_from.major,
        },
        "root": {
            "packId": lin.root.pack_id,
            "major": lin.root.major,
        },
    }


def _manifest_json_mtime_ms(pack_path: Path) -> int:
    """Epoch milliseconds of ``manifest.json`` mtime (0 if missing/unreadable).

    Exposed as ``installUpdatedAtMs`` for diagnostics (last write on disk).
    Canonical pack ordering uses ``createdAtMs`` from the manifest.
    """
    try:
        return int((pack_path / "manifest.json").stat().st_mtime * 1000)
    except OSError:
        return 0


def _manifest_to_payload(manifest: PackManifest, *, pack_mtime_path: Path | None = None) -> dict:
    kinds = []
    for kind in manifest.kinds:
        kinds.append(
            {
                "id": manifest.canonical_for(kind.kind_id),
                "kindId": kind.kind_id,
                "label": kind.label,
                "category": kind.category,
                "engine": kind.engine,
                "description": kind.description,
                "icon": kind.icon,
                "iconRef": kind.icon_ref,
                "lifecycle": kind.lifecycle,
                "paletteOrder": kind.palette_order,
                "editor": kind.editor,
                "hasCode": kind.has_code,
                "hasWidgets": kind.has_widgets,
                "hasGrammar": kind.has_grammar,
                "grammarId": kind.grammar_id,
                "badge": kind.badge,
                "inputPorts": [asdict(p) if is_dataclass(p) else p for p in kind.input_ports],
                "outputPorts": [asdict(p) if is_dataclass(p) else p for p in kind.output_ports],
                "source": kind.source,
                "bidirectional": kind.bidirectional,
                "containerStyle": kind.container_style,
                "hasProvenance": kind.has_provenance,
                "tutorialId": kind.tutorial_id,
            }
        )
    payload = {
        "packId": manifest.pack_id,
        "major": manifest.major,
        "version": manifest.version,
        "name": manifest.name,
        "publisher": manifest.publisher,
        "description": manifest.description,
        "license": manifest.license,
        "permissions": manifest.permissions,
        "dependencies": {
            "packs": dict(manifest.pack_deps),
            "python": dict(manifest.python_deps),
            "js": dict(manifest.js_deps),
        },
        "kinds": kinds,
        "dirName": manifest.dir_name,
        "lineage": _lineage_to_payload(manifest),
        "familyKey": family_key_for_manifest(manifest),
        "channel": manifest.channel,
        **(
            {"paletteDock": {"hiddenFromForkPaletteDock": True}}
            if manifest.hidden_from_fork_palette_dock
            else {}
        ),
        **({"readOnly": True} if manifest.read_only else {}),
        "createdAtMs": manifest.created_at_ms,
    }
    if manifest.created_at_iso:
        payload["createdAt"] = manifest.created_at_iso
    if pack_mtime_path is not None:
        payload["installUpdatedAtMs"] = _manifest_json_mtime_ms(pack_mtime_path)
    return payload


def _catalog_root() -> Path:
    """``<repo_root>/packs/`` — committed pack catalog root.

    Resolved relative to this file's location so the seeder finds the
    catalog regardless of the launch CWD. This is the dev catalog
    source — production deployments rely on user installs via the
    warehouse drawer (and the future remote registry).
    """
    # routes.py -> packs/ -> app/ -> backend/ -> utk_curio/ -> repo_root/packs/
    return Path(__file__).resolve().parents[4] / "packs"


_FALSEY_PUBLISH_ENV = frozenset({"0", "false", "no", "off"})


def factory_catalog_publish_allowed() -> bool:
    """When true, wizard may POST ``factory/publish-catalog`` (writes fixtures).

    **Default:** allowed (unset or empty). Set ``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH``
    to ``0``, ``false``, ``no``, or ``off`` to disable in locked-down deployments.
    """
    raw = os.environ.get("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", "")
    stripped = raw.strip().lower()
    if stripped == "":
        return True
    if stripped in _FALSEY_PUBLISH_ENV:
        return False
    return stripped in {"1", "true", "yes", "on"}


def _resolver_overrides_for(user_key: str, packs: list[str]) -> dict[str, Path]:
    """Build the ``overrides`` map for :func:`resolve_for_project`.

    The pre-install conflict probe in the warehouse UI passes the
    candidate's ``dirName`` alongside the already-installed packs so it
    can show the InstallDialog with a precise conflict report. The
    candidate is by definition *not yet installed* — its manifest lives
    in the committed catalog at ``<repo_root>/packs/<dirName>/``,
    not in ``<user>/packs/<dirName>/``. Without an override, the
    resolver would raise ``pack <name> is malformed: missing
    manifest.json`` and the user could never get past the dialog.

    For each requested pack that is not currently installed, we point
    the resolver at the catalog directory iff a well-formed manifest is
    present there. Unknown packs are left alone so the resolver still
    surfaces a precise "not installed" error.
    """
    catalog_root = _catalog_root()
    if not catalog_root.is_dir():
        return {}
    out: dict[str, Path] = {}
    for name in packs:
        try:
            user_path = pack_dir(user_key, name)
        except PackIdError:
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
# GET /api/packs — list installed
# ---------------------------------------------------------------------------

@packs_bp.route("", methods=["GET"])
@require_auth
def list_installed_packs():
    user_key = _user_dir_key(g.user)
    out: list[dict] = []
    for pack_path in list_user_packs(user_key):
        try:
            manifest = load_pack_manifest(pack_path)
        except ManifestError as exc:
            log.warning("Skipping malformed pack %s: %s", pack_path.name, exc)
            continue
        out.append(_manifest_to_payload(manifest, pack_mtime_path=pack_path))
    # Newest ``manifest.createdAt`` first — canonical authoring time / ordering.
    out.sort(
        key=lambda p: (-int(p.get("createdAtMs") or 0), p.get("dirName") or ""),
    )
    return jsonify({"packs": out}), 200


# ---------------------------------------------------------------------------
# POST /api/packs/palette-dock/fork-parents — batch reveal/suppress dock entries
# ---------------------------------------------------------------------------

@packs_bp.route("/palette-dock/fork-parents", methods=["POST"])
@require_auth
def fork_parents_palette_dock_visibility():
    """Reveal or suppress installed fork-source packs in the nodes palette dock.

    Mutates ``curio.paletteDock.hiddenFromForkPaletteDock`` in each installed parent
    manifest referenced by ``lineage.forkedFrom`` from another installed fork.
    """
    user_key = _user_dir_key(g.user)
    body = request.get_json(silent=True) or {}
    visible_raw = body.get("visible")
    if visible_raw is not True and visible_raw is not False:
        return _error("body must include boolean 'visible'")
    set_all_fork_parents_palette_visibility(user_key, visible=visible_raw)
    return "", 204


# ---------------------------------------------------------------------------
# POST /api/packs/<dir_name>/palette-dock-visible — one install's dock section
# ---------------------------------------------------------------------------

@packs_bp.route("/<dir_name>/palette-dock-visible", methods=["POST"])
@require_auth
def pack_palette_dock_visibility(dir_name: str):
    """Set ``curio.paletteDock.hiddenFromForkPaletteDock`` for one installed coordinate."""
    user_key = _user_dir_key(g.user)
    if not PACK_DIR_RE.match(dir_name):
        return _error("invalid pack directory name", 404)
    body = request.get_json(silent=True) or {}
    visible_raw = body.get("visible")
    if visible_raw is not True and visible_raw is not False:
        return _error("body must include boolean 'visible'")
    try:
        root = pack_dir(user_key, dir_name)
    except PackIdError as exc:
        return _error(str(exc))
    if not (root / "manifest.json").is_file():
        return _error("pack not installed", 404)
    try:
        merge_manifest_palette_dock_fork_hidden(root, hidden=not visible_raw)
    except ManifestError as exc:
        return _error(str(exc))
    return "", 204


# ---------------------------------------------------------------------------
# GET /api/packs/catalog — fixture-backed catalog index
# ---------------------------------------------------------------------------

@packs_bp.route("/catalog", methods=["GET"])
@require_auth
def list_catalog_packs():
    """Return the catalog scan from ``<repo_root>/packs/``.

    Items share the same shape as ``list_installed_packs`` (the warehouse UI
    can render either feed identically), plus an ``installed`` flag. The
    JSON body also includes ``families`` and ``catalogCollisions``.
    """
    user_key = _user_dir_key(g.user)
    installed_coords = {p.name for p in list_user_packs(user_key)}

    root = _catalog_root()
    if not root.is_dir():
        return jsonify({"packs": [], "families": [], "catalogCollisions": []}), 200

    out: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not PACK_DIR_RE.match(entry.name):
            continue
        try:
            manifest = load_pack_manifest(entry)
        except ManifestError as exc:
            log.warning("Skipping malformed fixture %s: %s", entry.name, exc)
            continue
        payload = _manifest_to_payload(manifest, pack_mtime_path=entry)
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
            "packs": out,
            "families": families_summary(out),
            "catalogCollisions": catalog_release_collision_groups(triples),
        }
    ), 200


# ---------------------------------------------------------------------------
# POST /api/packs/upload — sideload a .curio-nodepack
# ---------------------------------------------------------------------------

@packs_bp.route("/upload", methods=["POST"])
@require_auth
def upload_pack():
    """Sideload a ``.curio-nodepack`` zip for the current user.

    The archive is read into memory once (capped by the installer at
    128 MiB total uncompressed). Multipart form field name is ``file``
    to mirror the existing ``/upload`` endpoint shape.
    """
    user_key = _user_dir_key(g.user)
    if "file" not in request.files:
        return _error("missing 'file' form field with a .curio-nodepack archive")
    upload = request.files["file"]
    if not upload.filename:
        return _error("uploaded file is empty (no filename)")
    replace = request.args.get("replace", "false").lower() == "true"
    try:
        result = install_pack_from_archive(
            user_key, upload.stream.read(), replace=replace
        )
    except InstallerError as exc:
        return _error(str(exc))
    except PackIdError as exc:
        return _error(str(exc))
    user_pack = pack_dir(user_key, result.manifest.dir_name)
    return jsonify({
        "pack": _manifest_to_payload(result.manifest, pack_mtime_path=user_pack),
        "integrity": result.integrity,
        "replacedExisting": result.replaced_existing,
    }), 201


# ---------------------------------------------------------------------------
# POST /api/packs/catalog/install — install a catalog pack by dirName
# ---------------------------------------------------------------------------

@packs_bp.route("/catalog/install", methods=["POST"])
@require_auth
def install_from_catalog():
    """Install a catalog pack by its on-disk directory name.

    The body is ``{"dirName": "<packId>@<major>", "replace": false}``;
    the route copies the catalog directory into the user's pack store
    via :func:`install_pack_from_directory`. The catalog set is the
    committed packs shipped in ``<repo_root>/packs/`` — same data the
    ``GET /api/packs/catalog`` route advertises.
    """
    user_key = _user_dir_key(g.user)
    body = request.get_json(silent=True) or {}
    dir_name = body.get("dirName")
    if not isinstance(dir_name, str) or not PACK_DIR_RE.match(dir_name):
        return _error("body must include a valid 'dirName' (<packId>@<major>)")
    replace = bool(body.get("replace", False))

    src = _catalog_root() / dir_name
    if not src.is_dir():
        return _error(f"catalog has no pack {dir_name}", 404)
    try:
        result = install_pack_from_directory(user_key, src, replace=replace)
    except InstallerError as exc:
        return _error(str(exc))
    user_pack = pack_dir(user_key, result.manifest.dir_name)
    return jsonify({
        "pack": _manifest_to_payload(result.manifest, pack_mtime_path=user_pack),
        "integrity": result.integrity,
        "replacedExisting": result.replaced_existing,
    }), 201


# ---------------------------------------------------------------------------
# DELETE /api/packs/catalog/<dir_name> — remove fixture from dev catalog
# ---------------------------------------------------------------------------


@packs_bp.route("/catalog/<dir_name>", methods=["DELETE"])
@require_auth
def unpublish_from_catalog(dir_name: str):
    """Remove a pack directory from ``<repo_root>/packs/`` (developer catalog only).

    Does **not** uninstall from the user's pack store — use
    ``DELETE /api/packs/<dir_name>`` for that. Gated by the same env flag as
    ``factory/publish-catalog``.
    """
    if not factory_catalog_publish_allowed():
        return jsonify(
            {
                "error": (
                    "Catalog fixture publish is disabled on this server. "
                    "Unset CURIO_ALLOW_FACTORY_CATALOG_PUBLISH or set it to 1, "
                    "true, yes, or on to enable; restart the backend after changes."
                ),
            },
        ), 403

    if not PACK_DIR_RE.match(dir_name):
        return _error("dir_name must match <packId>@<major>")

    try:
        removed = remove_pack_from_catalog_dir(_catalog_root(), dir_name)
    except InstallerError as exc:
        return _error(str(exc))
    if not removed:
        return _error(f"catalog has no pack {dir_name}", 404)
    return "", 204


# ---------------------------------------------------------------------------
# DELETE /api/packs/<dir_name> — uninstall
# ---------------------------------------------------------------------------

@packs_bp.route("/<dir_name>", methods=["DELETE"])
@require_auth
def remove_pack(dir_name: str):
    if dir_name.startswith(f"{BUILTIN_PACK_ID}@"):
        return _error(f"{BUILTIN_PACK_ID} is built-in and cannot be uninstalled", 400)
    user_key = _user_dir_key(g.user)
    try:
        removed = uninstall_pack(user_key, dir_name)
    except PackIdError as exc:
        return _error(str(exc))
    if not removed:
        return _error("pack not installed", 404)
    return "", 204


# ---------------------------------------------------------------------------
# GET /api/packs/<dir_name>/archive — re-export
# ---------------------------------------------------------------------------

@packs_bp.route("/<dir_name>/archive", methods=["GET"])
@require_auth
def download_pack_archive(dir_name: str):
    user_key = _user_dir_key(g.user)
    try:
        body = export_pack_archive(user_key, dir_name)
    except (InstallerError, PackIdError) as exc:
        return _error(str(exc), 404)
    response = Response(body, mimetype="application/zip")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{dir_name}.curio-nodepack"'
    )
    return response



# ---------------------------------------------------------------------------
# GET /api/packs/factory/capabilities
# ---------------------------------------------------------------------------


@packs_bp.route("/factory/capabilities", methods=["GET"])
@require_auth
def factory_capabilities():
    """Return which factory features are usable (controlled by deployment env)."""
    return jsonify({"catalogPublish": factory_catalog_publish_allowed()}), 200


# ---------------------------------------------------------------------------
# POST /api/packs/factory/publish-catalog (opt-in fixture write)
# ---------------------------------------------------------------------------


@packs_bp.route("/factory/publish-catalog", methods=["POST"])
@require_auth
def factory_publish_catalog():
    """Build draft and publish into ``<repo_root>/packs/`` — **developers only**.

    Allowed by default; set ``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`` to ``0``,
    ``false``, ``no``, or ``off`` to disable.

    Writes the same directory layout Sideload installs use; may trigger hot
    reload of the Flask process when watchers observe the catalog.
    """
    if not factory_catalog_publish_allowed():
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
    try:
        built = build_pack_archive(body)
        result = publish_pack_archive_to_catalog_dir(
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
        "pack": _manifest_to_payload(result.manifest, pack_mtime_path=catalog_path),
        "integrity": result.integrity,
        "replacedExisting": result.replaced_existing,
        "filename": built.filename,
        "catalogDir": str(catalog_path),
    }), 201


@packs_bp.route("/factory/build", methods=["POST"])
@require_auth
def factory_build():
    """Validate a draft and return the produced ``.curio-nodepack`` bytes."""
    draft = request.get_json(silent=True) or {}
    try:
        result = build_pack_archive(draft)
    except FactoryError as exc:
        return _error(str(exc))
    response = Response(result.archive, mimetype="application/zip")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{result.filename}"'
    )
    response.headers["X-Curio-Pack-Dir"] = result.manifest.dir_name
    response.headers["X-Curio-Pack-Version"] = result.manifest.version
    return response


# ---------------------------------------------------------------------------
# POST /api/packs/factory/install — wizard -> install in one shot
# ---------------------------------------------------------------------------

@packs_bp.route("/factory/install", methods=["POST"])
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
            return _error("this pack is read-only — save changes as a new pack")
        # Defense-in-depth: a forged draft can omit readOnly, so also check the
        # installed pack at the target coord. Catches any attempt to overwrite a
        # read-only pack that's already installed (e.g. curio.builtin).
        pack_id_raw = manifest_raw.get("id")
        major_raw = (manifest_raw.get("compatibility") or {}).get("major")
        if isinstance(pack_id_raw, str) and isinstance(major_raw, int):
            try:
                installed_dir = pack_dir(user_key, f"{pack_id_raw}@{major_raw}")
            except PackIdError:
                installed_dir = None
            if installed_dir is not None and installed_dir.is_dir():
                try:
                    if load_pack_manifest(installed_dir).read_only:
                        return _error("this pack is read-only — save changes as a new pack")
                except ManifestError:
                    pass  # Let the install path surface a more specific error.
    replace = bool(draft.get("replace", False))
    try:
        built = build_pack_archive(draft)
        result = install_pack_from_archive(
            user_key, built.archive, replace=replace,
        )
    except FactoryError as exc:
        return _error(str(exc))
    except InstallerError as exc:
        return _error(str(exc))
    user_pack = pack_dir(user_key, result.manifest.dir_name)
    return jsonify({
        "pack": _manifest_to_payload(result.manifest, pack_mtime_path=user_pack),
        "integrity": result.integrity,
        "replacedExisting": result.replaced_existing,
        "filename": built.filename,
    }), 201


# ---------------------------------------------------------------------------
# POST /api/packs/resolve — dep resolution
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Sandbox install helper
# ---------------------------------------------------------------------------

def _forward_to_sandbox_install(packages: list[str]) -> tuple[dict, int]:
    """POST the merged pack list to the sandbox ``/install`` route.

    Mirrors the shape of :func:`api.routes.install_packages` so the
    behaviour stays in lockstep with the existing ``/installPackages``
    endpoint — same Flask address resolution, same timeout policy. Lives
    in this module (rather than importing from ``api.routes``) so the
    test suite can monkey-patch without booting the sandbox.
    """
    from utk_curio.backend.app.api import routes as api_routes  # local: no cycle
    response = api_routes._sandbox_call(
        "post", "/install",
        label="/api/packs/install-deps",
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
# POST /api/packs/install-deps — resolve + push to sandbox
# ---------------------------------------------------------------------------

@packs_bp.route("/install-deps", methods=["POST"])
@require_auth
def install_pack_deps():
    """Resolve a set of pack dirs and install the merged python deps.

    Body shape: ``{"packs": ["ai.urbanlab.uhvi@1", ...]}``.

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
    packs = body.get("packs")
    if not isinstance(packs, list) or not all(isinstance(p, str) for p in packs):
        return _error("body must be {'packs': [<dirName>, ...]}")
    overrides = _resolver_overrides_for(user_key, packs)
    try:
        result = resolve_for_project(user_key, packs, overrides=overrides)
    except ResolverError as exc:
        return _error(str(exc))
    except PackIdError as exc:
        return _error(str(exc))

    if result.conflicts:
        return jsonify({
            "lockfile": result.to_lockfile(),
            "conflicts": [
                {
                    "package": c.package,
                    "ranges": [
                        {"packDir": p, "range": r} for (p, r) in c.ranges
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
# POST /api/packs/resolve — dep resolution only (no sandbox install)
# ---------------------------------------------------------------------------

@packs_bp.route("/resolve", methods=["POST"])
@require_auth
def resolve_deps():
    """Resolve the dep graph for a set of pack directory names.

    Body shape: ``{"packs": ["ai.urbanlab.uhvi@1", ...]}``.

    * 200 — fully resolved; returns ``{lockfile, conflicts: []}``.
    * 409 — at least one Python (or JS) range conflict across packs;
      returns ``{lockfile: {...}, conflicts: [{package, ranges: [{packDir,
      range}, ...]}, ...]}`` so the UI can show a precise error.
    * 400 — malformed body, cycle, missing pack dep.
    """
    user_key = _user_dir_key(g.user)
    body = request.get_json(silent=True) or {}
    packs = body.get("packs")
    if not isinstance(packs, list) or not all(isinstance(p, str) for p in packs):
        return _error("body must be {'packs': [<dirName>, ...]}")
    overrides = _resolver_overrides_for(user_key, packs)
    try:
        result = resolve_for_project(user_key, packs, overrides=overrides)
    except ResolverError as exc:
        return _error(str(exc))
    except PackIdError as exc:
        return _error(str(exc))

    payload = {
        "lockfile": result.to_lockfile(),
        "conflicts": [
            {
                "package": c.package,
                "ranges": [
                    {"packDir": p, "range": r} for (p, r) in c.ranges
                ],
            }
            for c in result.conflicts
        ],
    }
    return jsonify(payload), (409 if result.conflicts else 200)
