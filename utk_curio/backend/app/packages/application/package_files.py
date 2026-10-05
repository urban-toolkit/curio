"""Serving a file out of a user's installed copy of a package — the frontend's
dynamic behavior loader fetches each package's compiled ``behaviors.js`` this
way (declared in the manifest via ``behaviorScript``), and any package-shipped
asset can be read through the same path. Resolution flows through
``safe_join`` so a traversal payload cannot escape the package directory.
"""

from __future__ import annotations

from utk_curio.backend.app.common.safe_paths import PathTraversalError, safe_join
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain.package_id import PackageIdError
from utk_curio.backend.app.packages.repositories.store import package_dir

PACKAGE_FILE_MIMETYPES: dict[str, str] = {
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


def package_file(user_key: str, dir_name: str, filename: str) -> tuple[bytes, str]:
    """``(bytes, mimetype)`` of *filename* inside the user's installed *dir_name*.

    A malformed package name or one that escapes the store is a 404 (there is
    no such package); a filename that escapes the package is a 400; a missing
    file a 404; an unreadable one a 500 — each a :class:`PackageServiceError`.
    """
    try:
        base = package_dir(user_key, dir_name)
    except (PackageIdError, PathTraversalError) as exc:
        raise PackageServiceError(str(exc), 404) from exc
    try:
        # `validate=False` because the request can legitimately span subdirs
        # (e.g. `sources/index.js`). The final `is_within` check still
        # guarantees containment.
        target = safe_join(base, filename, validate=False, field="filename")
    except PathTraversalError as exc:
        raise PackageServiceError(str(exc), 400) from exc
    if not target.is_file():
        raise PackageServiceError(f"package file not found: {filename}", 404)
    mimetype = PACKAGE_FILE_MIMETYPES.get(target.suffix.lower(), "application/octet-stream")
    try:
        return target.read_bytes(), mimetype
    except OSError as exc:
        raise PackageServiceError(f"could not read package file: {exc}", 500) from exc
