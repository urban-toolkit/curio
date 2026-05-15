"""Persistence for ``curio.paletteDock`` in on-disk ``manifest.json``.

The Node Factory omits this subtree; fork install and Hub toggles mutate it
so the dock palette can hide fork-parent sections without browser storage.
"""

from __future__ import annotations

import json
from pathlib import Path

from utk_curio.backend.app.packs.manifest import ManifestError, PackLineageCoord, load_pack_manifest
from utk_curio.backend.app.packs.storage import pack_dir, user_packs_dir


def merge_manifest_palette_dock_fork_hidden(pack_dir_path: Path, hidden: bool) -> None:
    """Merge ``curio.paletteDock.hiddenFromForkPaletteDock`` and write ``manifest.json``.

    Preserves other ``curio`` / ``paletteDock`` keys. Re-loads to ensure file
    still validates as a pack manifest.
    """
    manifest_path = pack_dir_path / "manifest.json"
    if not manifest_path.is_file():
        raise ManifestError(f"missing manifest.json in {pack_dir_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{manifest_path}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"{manifest_path}: top-level must be an object")

    curio = raw.get("curio")
    if curio is not None and not isinstance(curio, dict):
        raise ManifestError(f"{manifest_path}.curio must be an object")
    if curio is None:
        raw["curio"] = {}
        curio = raw["curio"]

    dock = curio.get("paletteDock")
    if dock is not None and not isinstance(dock, dict):
        raise ManifestError(f"{manifest_path}.curio.paletteDock must be an object")
    if dock is None:
        curio["paletteDock"] = {}
        dock = curio["paletteDock"]

    if hidden:
        dock["hiddenFromForkPaletteDock"] = True
    else:
        dock.pop("hiddenFromForkPaletteDock", None)
        if not dock:
            curio.pop("paletteDock", None)
        if not curio:
            raw.pop("curio", None)

    manifest_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    load_pack_manifest(pack_dir_path)
    from utk_curio.backend.app.packs.installer import refresh_pack_integrity  # noqa: PLC0415

    refresh_pack_integrity(pack_dir_path)


def fork_parent_dir_names_referenced(user_key: str) -> set[str]:
    """``dirName`` of every installed manifest that is someone's ``lineage.forkedFrom``."""
    base = user_packs_dir(user_key)
    if not base.is_dir():
        return set()
    refs: set[str] = set()
    for p in base.iterdir():
        if not p.is_dir():
            continue
        try:
            m = load_pack_manifest(p)
        except (ManifestError, OSError):
            continue
        lin = m.lineage
        if lin is None:
            continue
        refs.add(_lineage_coord_dir(lin.forked_from))
    return refs


def _lineage_coord_dir(coord: PackLineageCoord) -> str:
    return f"{coord.pack_id}@{coord.major}"


def resync_fork_palette_parent_flags(user_key: str) -> None:
    """After installs/uninstalls: parents still referenced by forks stay hidden; others shown."""
    parents_needed = fork_parent_dir_names_referenced(user_key)
    base = user_packs_dir(user_key)
    if not base.is_dir():
        return
    for p in base.iterdir():
        if not p.is_dir():
            continue
        if not (p / "manifest.json").is_file():
            continue
        dn = p.name
        merge_manifest_palette_dock_fork_hidden(p, dn in parents_needed)


def set_all_fork_parents_palette_visibility(user_key: str, *, visible: bool) -> None:
    """Hub eye: reveal (``visible=True``) or suppress (``False``) dock entries for fork parents."""
    parents = fork_parent_dir_names_referenced(user_key)
    if not parents:
        return
    for dir_name in sorted(parents):
        try:
            path = pack_dir(user_key, dir_name)
        except OSError:
            continue
        if not (path / "manifest.json").is_file():
            continue
        merge_manifest_palette_dock_fork_hidden(path, hidden=not visible)
