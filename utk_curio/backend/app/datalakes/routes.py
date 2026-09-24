"""HTTP surface for the Data Lake Catalog.

Conventions follow ``datasets/routes.py``: one blueprint, ``@require_auth`` on
every route, and a single error-mapping decorator applied BELOW the auth
decorator so an auth failure is never swallowed and reported as a catalog
problem.
"""

from __future__ import annotations

import functools
import hashlib

from urllib.parse import unquote

from flask import Blueprint, g, jsonify, request, send_file, url_for

from utk_curio.backend.app.agents import egress
from utk_curio.backend.app.common.safe_paths import is_within
from utk_curio.backend.app.datalakes.domain.errors import DataLakeError, SourceNotFound
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest
from utk_curio.backend.app.datalakes.infrastructure import storage
from utk_curio.backend.app.datalakes.service import DataLakeService
from utk_curio.backend.app.users.dependencies import require_auth

datalakes_bp = Blueprint("datalakes_api", __name__, url_prefix="/api/datalakes")

#: An icon is page furniture. A portal mark that needs more than this is not a
#: mark, and serving arbitrary bytes from our own origin is not free.
MAX_ICON_BYTES = 256 * 1024


def _map_lake_errors(view):
    """Turn a typed failure into its own status.

    Applied BELOW ``@require_auth`` so an auth failure is never swallowed and
    reported as a catalog problem.
    """

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except DataLakeError as exc:
            return jsonify({"error": str(exc)}), getattr(exc, "status", 400)
        except egress.EgressRefused as exc:
            # 502: the failure is about a host we were asked to reach, not
            # about the request. The policy reason is included because it is
            # actionable ("not https", "resolves to a private address"); a
            # resolved ADDRESS never is, and is not in the message.
            return jsonify({"error": f"refused by the egress policy: {exc}"}), 502

    return wrapper


def _icon_url_for(manifest: LakeSourceManifest) -> str | None:
    """The icon endpoint for *manifest*, or None when there is no icon file.

    Resolved here rather than in the domain because whether a file exists is a
    storage question and what the URL looks like is a routing one. The client
    gets a URL or a null, and renders the shared lake glyph for the null - so
    a source with no icon and a source whose icon was deleted look the same,
    which is the honest outcome.
    """
    path = _icon_path(manifest)
    if path is None:
        return None
    return url_for("datalakes_api.source_icon", source_dir=manifest.dir_name)


def _icon_path(manifest: LakeSourceManifest):
    name = manifest.icon
    if not name:
        return None
    try:
        root = storage.source_dir(manifest.dir_name)
    except ValueError:
        return None
    candidate = (root / name).resolve()
    # ``_parse_icon`` already refused separators and traversal; this is the
    # check that stays correct if that grammar is ever loosened.
    if not is_within(candidate, root.resolve()) or not candidate.is_file():
        return None
    if candidate.stat().st_size > MAX_ICON_BYTES:
        return None
    return candidate


def _service() -> DataLakeService:
    """The per-request service, carrying who is asking.

    The user is needed for two things and nothing else: the per-source rate
    limit is per account, and a portal token is an account credential. Both
    come from ``g.user``, which ``@require_auth`` has already resolved.
    """
    from utk_curio.backend.app.projects.services import _user_dir_key

    user = getattr(g, "user", None)
    return DataLakeService(
        _user_dir_key(user) if user is not None else None,
        user=user,
        icon_url_for=_icon_url_for,
    )


@datalakes_bp.route("/catalog", methods=["GET"])
@require_auth
@_map_lake_errors
def list_datalake_catalog():
    """The source roster. Disk only - this route makes no outbound request."""
    payload = _service().list_catalog(
        q=request.args.get("q"),
        provider=request.args.get("provider"),
        auth=request.args.get("auth"),
    )
    return jsonify(payload), 200


@datalakes_bp.route("/sources/<source_dir>", methods=["GET"])
@require_auth
@_map_lake_errors
def get_datalake_source(source_dir: str):
    return jsonify(_service().get_source(source_dir)), 200


@datalakes_bp.route("/sources/<source_dir>/icon", methods=["GET"])
@require_auth
@_map_lake_errors
def source_icon(source_dir: str):
    """Serve the portal's own mark.

    ``mimetype`` is fixed by this route rather than sniffed from the file, and
    ``nosniff`` is set, so the bytes cannot be re-interpreted as anything but
    an image no matter what they contain.
    """
    manifest = _service().get_manifest(source_dir)
    path = _icon_path(manifest)
    if path is None:
        raise SourceNotFound(f"data lake source {source_dir!r} has no icon")
    stat = path.stat()
    etag = hashlib.sha256(f"{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:32]
    response = send_file(path, mimetype="image/png", conditional=True)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Disposition"] = "inline"
    response.set_etag(etag)
    return response


def _int_arg(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@datalakes_bp.route("/search", methods=["GET"])
@require_auth
@_map_lake_errors
def search_datalakes():
    """Search every searchable portal at once. **Live.**

    A leg that fails is reported in ``sources[]`` and does not fail the
    request: one slow portal must not make the whole search look broken.
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "a search needs a query"}), 400
    payload = _service().search_all(
        q=q,
        fmt=request.args.get("format"),
        limit=_int_arg("limit"),
        provider=request.args.get("provider"),
    )
    return jsonify(payload), 200


@datalakes_bp.route("/sources/<source_dir>/search", methods=["GET"])
@require_auth
@_map_lake_errors
def search_datalake_source(source_dir: str):
    """Search one portal. **Live.** The only paginated search - a fan-out has
    no coherent cursor across five independently paginating portals."""
    payload = _service().search_source(
        source_dir,
        q=(request.args.get("q") or "").strip(),
        fmt=request.args.get("format"),
        limit=_int_arg("limit"),
        cursor=request.args.get("cursor"),
    )
    return jsonify(payload), 200


@datalakes_bp.route("/sources/<source_dir>/resources/<path:resource_id>", methods=["GET"])
@require_auth
@_map_lake_errors
def describe_datalake_resource(source_dir: str, resource_id: str):
    """One resource in full. **Live.**

    ``<path:>`` because a direct-URL source's resource id IS a URL. It is
    unquoted here and validated against the provider's own ``resource_id_re``
    before any URL is built from it.
    """
    payload = _service().describe_resource(source_dir, unquote(resource_id))
    return jsonify(payload), 200
