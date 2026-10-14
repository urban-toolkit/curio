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
from utk_curio.backend.app.packages.application import prune as packages_prune
from utk_curio.backend.app.packages.application.model_packages import weights_on_first_use
from utk_curio.backend.app.packages.domain.manifest import ManifestError, PackageManifest
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories import (
    catalog_dir as packages_catalog_dir,
    publisher_record,
)
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.python_modules import module_names
from utk_curio.backend.app.packages.repositories.store import list_user_packages
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.schemas.responses import package_payload

log = logging.getLogger(__name__)


def _listing_payload(manifest: PackageManifest, folder) -> dict:
    """*manifest*'s payload as a listing shows it, read from its *folder*: the
    modules it ships, and for a model package whether its weights download
    on first use."""
    payload = package_payload(manifest, package_mtime_path=folder)
    payload["modules"] = sorted(module_names(folder, manifest))
    if manifest.model is not None:
        payload["model"]["downloadsOnFirstUse"] = weights_on_first_use(manifest, folder)
    return payload


def installed_package_payloads(user_key: str, kind: str | None = None, *, usage: bool = False) -> list[dict]:
    """Every readable package in the user's store as a payload, newest ``createdAt`` first;
    only the packages of *kind* (``node`` or ``model``) when it is given. With
    *usage*, each payload says ``inUse``: whether one of the user's dataflows
    uses it (``prune.packages_in_use``), which reads every project's spec."""
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
            if kind is not None and manifest.kind != kind:
                continue
            out.append(_listing_payload(manifest, package_path))
    # Newest ``manifest.createdAt`` first - canonical authoring time / ordering.
    out.sort(
        key=lambda p: (-int(p.get("createdAtMs") or 0), p.get("dirName") or ""),
    )
    if usage:
        in_use = packages_prune.packages_in_use(user_key)
        for payload in out:
            payload["inUse"] = payload.get("dirName") in in_use
    return out


def catalog_listing(user_key: str, kind: str | None = None) -> dict:
    """The catalog scan from ``<repo_root>/packages/``: ``{"packages", "families", "catalogCollisions"}``.

    Items share the shape of :func:`installed_package_payloads` (the catalog UI can
    render either feed identically), plus ``installed`` (is it in this user's store)
    and ``publishable`` (may THIS user withdraw it — the same question as "is this the
    user's own package"). Only the packages of *kind* when it is given.
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
        if kind is not None and manifest.kind != kind:
            continue
        payload = _listing_payload(manifest, entry)
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
