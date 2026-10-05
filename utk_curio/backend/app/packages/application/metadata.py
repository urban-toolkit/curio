"""Human-authored package metadata: the allowlisted PATCH over ``manifest.json`` and ``README.md``, atomic and re-validated (identity-bearing keys are never editable here).

Application layer of the packages package (memo dev/143, B2-b): lifted out of ``routes.py`` so handlers
parse, call and serialize and carry no rules; every function keeps its body.
"""

from __future__ import annotations

import json as _json
import logging
from pathlib import Path

from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain.manifest import (
    ManifestError,
    PackageManifest,
)
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.repositories import seed_state
from utk_curio.backend.app.packages.repositories.archive import refresh_package_integrity
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import package_dir

log = logging.getLogger(__name__)


_PATCH_ALLOWED_TOP_KEYS: frozenset[str] = frozenset({
    "name", "description", "publisher", "license", "permissions",
})
_PATCH_ALLOWED_COMPAT_KEYS: frozenset[str] = frozenset({"curioRuntime"})


def patch_package_metadata(user_key: str, dir_name: str, body: object) -> tuple[PackageManifest, Path]:
    """Partial-update human-authored package metadata; returns the re-validated manifest and the package path.

    Every refusal is a :class:`PackageServiceError` carrying the status the route answers with (400 unless said otherwise).

    Replaces the Node Factory wizard's metadata fields for installed packages.
    Read-only packages (``curio.builtin@1`` and similar) reject with ``403``.
    Identity-bearing keys (``id``, ``version``, ``major``, ``kinds``,
    ``lineage``, ``readOnly``, ``createdAt``, ``distribution``,
    ``dependencies``) cannot be mutated through this endpoint - ``dependencies``
    in particular comes from source-scan now.
    """
    pkg_path = package_dir(user_key, dir_name)  # PackageIdError propagates: the route answers 400
    if not pkg_path.is_dir():
        raise PackageServiceError("package not installed", 404)

    manifest_path = pkg_path / "manifest.json"
    if not manifest_path.is_file():
        raise PackageServiceError("manifest.json missing", 404)

    try:
        original_bytes = manifest_path.read_bytes()
        raw = _json.loads(original_bytes.decode("utf-8"))
    except (OSError, _json.JSONDecodeError) as exc:
        raise PackageServiceError(f"cannot read manifest: {exc}")
    if not isinstance(raw, dict):
        raise PackageServiceError("manifest.json root must be an object")

    if raw.get("readOnly") is True:
        raise PackageServiceError("this package is read-only", 403)

    if not isinstance(body, dict):
        raise PackageServiceError("request body must be a JSON object")

    # Validate the allowlist before touching disk.
    readme_update = body.get("readme") if "readme" in body else None
    readme_supplied = "readme" in body
    compat_update = body.get("compatibility")
    if compat_update is not None and not isinstance(compat_update, dict):
        raise PackageServiceError("compatibility must be an object")
    if compat_update:
        bad = set(compat_update) - _PATCH_ALLOWED_COMPAT_KEYS
        if bad:
            raise PackageServiceError(
                f"compatibility keys not editable here: {sorted(bad)}; "
                f"allowed: {sorted(_PATCH_ALLOWED_COMPAT_KEYS)}",
            )

    rejected = (set(body) - _PATCH_ALLOWED_TOP_KEYS) - {"compatibility", "readme"}
    if rejected:
        raise PackageServiceError(
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

    # Everything from the first write to the record runs under the store lock
    # (memo dev/99), the one the seeder swaps under, so a seeding pass cannot
    # read the copy as an untouched catalog copy mid-edit and swap it back.
    with package_seed_lock(user_key):
        # Atomic manifest write, then re-validate; restore originals on validation failure.
        serialized = (_json.dumps(raw, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        tmp_path = manifest_path.with_name("manifest.json.tmp")
        try:
            tmp_path.write_bytes(serialized)
            tmp_path.replace(manifest_path)
        except OSError as exc:
            raise PackageServiceError(f"cannot write manifest: {exc}")

        try:
            manifest = load_package_manifest(pkg_path)
        except ManifestError as exc:
            manifest_path.write_bytes(original_bytes)
            raise PackageServiceError(f"patch rejected by validator: {exc}")

        # README is a sibling file; write/unlink it atomically only after the manifest
        # validates so a bad metadata patch doesn't half-mutate the package.
        readme_path = pkg_path / "README.md"
        if readme_supplied:
            if isinstance(readme_update, str) and readme_update.strip():
                try:
                    tmp_readme = readme_path.with_name("README.md.tmp")
                    # newline="" disables the platform line-ending translation that
                    # write_text applies by default. Without it a README authored on
                    # Windows lands on disk with CRLF, and export_package_archive
                    # ships those bytes to every consumer of the archive -- so the
                    # same edit would produce a different package per author OS.
                    tmp_readme.write_text(readme_update, encoding="utf-8", newline="")
                    tmp_readme.replace(readme_path)
                except OSError as exc:
                    raise PackageServiceError(f"cannot write README: {exc}")
            elif readme_update is None or readme_update == "":
                try:
                    readme_path.unlink(missing_ok=True)
                except OSError as exc:
                    raise PackageServiceError(f"cannot remove README: {exc}")
            else:
                raise PackageServiceError("readme must be a string or null")

        # The copy's own map has to describe the copy, and the copy is now the
        # user's: without both, it still read as the catalog's, and the next
        # catalog change replaced the edit (#564). Bookkeeping, as on install: the
        # edit is already on disk, so a failure here is logged, not answered.
        try:
            refresh_package_integrity(pkg_path)
            seed_state.mark_installed(user_key, dir_name, catalog_copy=None)
        except Exception:  # noqa: BLE001
            log.exception("Failed to record the metadata edit of %s/%s", user_key, dir_name)
    return manifest, pkg_path
