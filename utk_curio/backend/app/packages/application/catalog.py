"""The two package listings the catalog surfaces render: what this user has installed (``GET /api/packages``) and the shared catalog with its family index and collision report (``GET /api/packages/catalog``).

Application layer of the packages package (memo dev/143, B2-b): lifted out of ``routes.py`` so handlers
parse, call and serialize and carry no rules; every function keeps its body.
"""

from __future__ import annotations

import logging

from utk_curio.backend.app.packages.domain.catalog_family import (
    CatalogReleaseTriple,
    catalog_release_collision_groups,
    families_summary,
)
from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories import (
    catalog_dir as packages_catalog_dir,
    publisher_record,
)
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import list_user_packages
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.schemas.responses import package_payload

log = logging.getLogger(__name__)


def installed_package_payloads(user_key: str) -> list[dict]:
    """Every readable package in the user's store as a payload, newest ``createdAt`` first."""
    out: list[dict] = []
    # Enumeration + manifests + mtimes under ONE seed-lock hold (memo dev/99):
    # the payloads are detached dicts, so nothing live leaves the lock.
    with package_seed_lock(user_key):
        for package_path in list_user_packages(user_key):
            try:
                manifest = load_package_manifest(package_path)
            except ManifestError as exc:
                log.warning("Skipping malformed package %s: %s", package_path.name, exc)
                continue
            out.append(package_payload(manifest, package_mtime_path=package_path))
    # Newest ``manifest.createdAt`` first - canonical authoring time / ordering.
    out.sort(
        key=lambda p: (-int(p.get("createdAtMs") or 0), p.get("dirName") or ""),
    )
    return out


def catalog_listing(user_key: str) -> dict:
    """The catalog scan from ``<repo_root>/packages/``: ``{"packages", "families", "catalogCollisions"}``.

    Items share the shape of :func:`installed_package_payloads` (the catalog UI can
    render either feed identically), plus ``installed`` (is it in this user's store)
    and ``publishable`` (may THIS user withdraw it — the same question as "is this the
    user's own package").
    """
    with package_seed_lock(user_key):  # memo dev/99: no transient "not installed"
        installed_coords = {p.name for p in list_user_packages(user_key)}

    root = packages_catalog_dir.catalog_root()
    if not root.is_dir():
        return {"packages": [], "families": [], "catalogCollisions": []}

    out: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not PACKAGE_DIR_RE.match(entry.name):
            continue
        try:
            manifest = load_package_manifest(entry)
        except ManifestError as exc:
            log.warning("Skipping malformed fixture %s: %s", entry.name, exc)
            continue
        payload = package_payload(manifest, package_mtime_path=entry)
        payload["installed"] = manifest.dir_name in installed_coords
        # Whether THIS user may withdraw it, which is the same question as
        # "is this the user's own package". The agent catalog has carried a
        # `publishable` flag from the start; packages had nothing, so the UI
        # fell back to `readOnly !== true` and offered Unpublish on everything.
        payload["publishable"] = publisher_record.is_publisher(
            root, manifest.dir_name, user_key,
        )
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

    return {
        "packages": out,
        "families": families_summary(out),
        "catalogCollisions": catalog_release_collision_groups(triples),
    }
