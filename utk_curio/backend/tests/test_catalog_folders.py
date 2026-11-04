"""Every catalog folder Curio ships holds entries of one shape.

``packages/``, ``datasets/``, ``discovery/`` and ``agents/`` each hold one
directory per entry, named ``<id>@<major>``: the id the entry's manifest
gives, which names its publisher after the catalog's kind prefix
(``data.utk.chicago-boundary``, ``source.osm.openstreetmap``,
``agent.curio.node-builder``), and the major of the manifest's version. The
manifest keeps the whole version. A loose Markdown note may sit beside the
entries (``discovery/ICONS.md``).
"""

from __future__ import annotations

import json
import re

import pytest

from utk_curio import shipped

_SEG = r"[a-z][a-z0-9-]{0,62}"
#: ``<id>@<major>``, the id two to six dot-separated segments.
ENTRY_RE = re.compile(rf"^(?P<id>{_SEG}(?:\.{_SEG}){{1,5}})@(?P<major>0|[1-9][0-9]{{0,3}})$")

#: Each catalog folder, and the kind prefix its entries' ids start with: none
#: for a node package (``curio.scout``), ``model.`` for a model package.
FOLDERS = {
    "packages": None,
    "datasets": "data.",
    "discovery": "source.",
    "agents": "agent.",
}


def _entries(folder: str) -> list:
    root = shipped.path(folder)
    entries = sorted(path for path in root.iterdir() if path.is_dir())
    assert entries, f"no entries in {root}"
    return entries


def _prefix(folder: str, manifest: dict) -> str | None:
    if folder == "packages" and manifest.get("kind") == "model":
        return "model."
    return FOLDERS[folder]


@pytest.mark.parametrize("folder", sorted(FOLDERS))
def test_each_entry_is_named_by_its_id_and_its_major(folder):
    wrong = []
    for entry in _entries(folder):
        match = ENTRY_RE.match(entry.name)
        if not match:
            wrong.append(f"{folder}/{entry.name}: not <id>@<major>")
            continue
        manifest = json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("id") != match["id"]:
            wrong.append(f"{folder}/{entry.name}: its manifest's id is {manifest.get('id')!r}")
        major = str(manifest.get("version", "")).split(".")[0]
        if major != match["major"]:
            wrong.append(f"{folder}/{entry.name}: its manifest's version is {manifest.get('version')!r}")
    assert not wrong, "\n".join(wrong)


@pytest.mark.parametrize("folder", sorted(FOLDERS))
def test_each_id_names_its_publisher_after_its_kind(folder):
    wrong = []
    for entry in _entries(folder):
        manifest = json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
        entry_id = str(manifest.get("id", ""))
        prefix = _prefix(folder, manifest)
        if prefix is not None and not entry_id.startswith(prefix):
            wrong.append(f"{folder}/{entry.name}: {entry_id!r} does not start with {prefix!r}")
            continue
        rest = entry_id[len(prefix):] if prefix else entry_id
        if len(rest.split(".")) < 2:
            wrong.append(f"{folder}/{entry.name}: {entry_id!r} names no publisher before its name")
    assert not wrong, "\n".join(wrong)


def test_a_catalog_folder_holds_entries_and_notes_only():
    stray = []
    for folder in FOLDERS:
        for path in shipped.path(folder).iterdir():
            if path.is_file() and path.suffix != ".md" and path.name != ".DS_Store":
                stray.append(f"{folder}/{path.name}")
    assert not stray, "\n".join(stray)
