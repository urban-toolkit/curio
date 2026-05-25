"""Catalog grouping keys and collision detection.

``family_key_for_manifest`` aligns with manifest ``lineage.root``.
See ``docs/CATALOG.md`` (Sharing > Fork lineage).
"""

from __future__ import annotations

from dataclasses import dataclass

from utk_curio.backend.app.packages.manifest import PackageManifest


def family_key_for_manifest(manifest: PackageManifest) -> str:
    """Stable catalog / fork-family key.

    Forked packages group under ``root`` coordinate; lineage-free packages are each
    their own singleton family (dir name equals coordinate).
    """
    lin = manifest.lineage
    if lin is None:
        return manifest.dir_name
    return f"{lin.root.package_id}@{lin.root.major}"


@dataclass(frozen=True)
class CatalogReleaseTriple:
    family_key: str
    channel: str
    version: str


def catalog_release_collision_groups(
    entries: list[tuple[str, CatalogReleaseTriple]],
) -> list[dict[str, object]]:
    """Find duplicate semantic releases among catalog rows.

    *entries* is ``(dirName, CatalogReleaseTriple)`` per fixture or package row.

    Returns a JSON-friendly list describing each colliding triple and the dirs
    that claim it — empty when uniques_only.
    """
    bucket: dict[CatalogReleaseTriple, list[str]] = {}
    for dir_name, triple in entries:
        bucket.setdefault(triple, []).append(dir_name)
    out: list[dict[str, object]] = []
    for triple, dirs in sorted(bucket.items(), key=lambda kv: kv[0].family_key):
        if len(dirs) < 2:
            continue
        out.append(
            {
                "familyKey": triple.family_key,
                "channel": triple.channel,
                "version": triple.version,
                "dirNames": sorted(dirs),
            }
        )
    return out


def families_summary(packages_payload: list[dict]) -> list[dict[str, object]]:
    """Build ``{familyKey, dirNames}[]`` sorted by familyKey from catalog payloads."""
    by_key: dict[str, list[str]] = {}
    for p in packages_payload:
        fk = p.get("familyKey")
        dn = p.get("dirName")
        if not isinstance(fk, str) or not isinstance(dn, str):
            continue
        by_key.setdefault(fk, []).append(dn)
    return [
        {"familyKey": k, "dirNames": sorted(v)}
        for k, v in sorted(by_key.items(), key=lambda kv: kv[0])
    ]
