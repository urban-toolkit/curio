"""``manifest.json`` on disk: read one from a package directory and hand it to the domain
validator; stamp a missing ``createdAt``. (Memo dev/143, B2: the file read left ``domain/manifest.py``.)
"""

from __future__ import annotations

import json
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path

from utk_curio.backend.app.packages.domain.manifest import (
    ManifestError,
    package_manifest_from_dict,
    PackageManifest,
    _parse_created_at_from_manifest,
)


def load_package_manifest(package_dir_path: Path) -> PackageManifest:
    """Read ``<package_dir>/manifest.json`` and validate the supported subset.

    Cross-checks the directory name against the manifest's ``id`` and
    ``compatibility.major`` (the on-disk dir is authoritative for which
    package is being loaded; the manifest must agree).
    """
    manifest_path = package_dir_path / "manifest.json"
    if not manifest_path.is_file():
        raise ManifestError(f"missing manifest.json in {package_dir_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{manifest_path}: invalid JSON: {exc}") from exc
    return package_manifest_from_dict(
        raw, manifest_path=manifest_path, dir_name=package_dir_path.name,
    )


def merge_missing_manifest_created_at(package_root: Path) -> bool:
    """Persist ``manifest.json`` ``createdAt`` (UTC ISO) when absent or unparsable as zero-ms.

    Returns ``True`` if the manifest file was rewritten. Intended for installers
    so older archives without canonical ordering timestamps still serialize a
    stable ``createdAt`` on disk once.
    """
    manifest_path = package_root / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(raw, dict):
        return False
    _, existing_ms = _parse_created_at_from_manifest(
        raw.get("createdAt"), where=str(manifest_path)
    )
    if existing_ms > 0:
        return False
    raw["createdAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_path.write_text(
        json.dumps(raw, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _, check = _parse_created_at_from_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8")).get("createdAt"),
        where=str(manifest_path),
    )
    if check <= 0:
        raise ManifestError(f"{manifest_path}: failed to stamp canonical createdAt")
    return True
