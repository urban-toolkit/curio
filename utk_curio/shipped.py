"""Where the folders Curio ships beside its code are on this machine.

The repository keeps them beside ``utk_curio/``: the Data Catalog's datasets
(``datasets/``), the Discovery Catalog's sources (``discovery/``), the
packages of the Node and Model Catalogs (``packages/``, a model package with
its weights), the scripts (``scripts/``) and DuckDB's extensions (``vendor/``), and
``docs/``, of which Curio reads the dataflows it ships, the example data their
nodes read, the Example storage source's folder, the agent evaluation's prompt
fixtures and two schemas. A clone, the Docker image and CI read them there.

The pip package carries them inside ``utk_curio/``, at
``utk_curio/_shipped/<folder>/`` (``setup.py`` maps them there), so a pip
install puts nothing in site-packages but ``utk_curio/`` and its dist-info.
Of ``docs/`` it carries only what Curio reads (``MANIFEST.in`` names it).
The sdist keeps the repository's layout.

Every reader asks :func:`path`. The layout is decided once, by whether
``utk_curio/_shipped/`` exists, never folder by folder: in a pip install,
``datasets/`` beside ``utk_curio/`` is Hugging Face's package.

The pip package leaves out the files that a manifest in ``datasets/`` or
``packages/`` names in ``downloadOnFirstUse``, and a pip install downloads
each the first time Curio needs it (:func:`downloaded_on_first_use`). The
release reads them here (``setup.py``, ``scripts/record_left_out_files.py``),
and so does a running Curio
(``backend/app/datasets/infrastructure/left_out_files.py``). This module
imports nothing but the standard library, so the build reads it by its path.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

#: The folder that holds ``utk_curio/``: the repository root in a clone, the
#: Docker image and CI; site-packages in a pip install.
CODE_ROOT = Path(__file__).resolve().parents[1]

#: Where the pip package carries the shipped folders, under the folder that
#: holds ``utk_curio/``.
IN_THE_PACKAGE = PurePosixPath("utk_curio", "_shipped")

#: The folders Curio ships beside its code, by their name in the repository.
FOLDERS = ("datasets", "discovery", "docs", "packages", "scripts", "vendor")

#: The manifest field that names, by their paths in the folder of a dataset or
#: model package, the files the pip package leaves out.
DOWNLOAD_ON_FIRST_USE = "downloadOnFirstUse"
#: The folders whose entries' manifests may name them.
CATALOGS = ("datasets", "packages")


def root(code_root=None) -> Path:
    """The folder that holds the shipped folders: ``utk_curio/_shipped/`` in a
    pip install, else the folder that holds ``utk_curio/``.

    *code_root* is the folder that holds ``utk_curio/`` (``CODE_ROOT`` when
    None)."""
    code_root = Path(CODE_ROOT if code_root is None else code_root)
    inside = code_root / IN_THE_PACKAGE
    return inside if inside.is_dir() else code_root


def path(repo_path, code_root=None) -> Path:
    """Where *repo_path*, a repository path in one of :data:`FOLDERS` (such as
    ``datasets`` or ``packages/<id>@<major>/manifest.json``), is on this
    machine. *code_root* is as for :func:`root`."""
    relative = PurePosixPath(repo_path)
    if relative.is_absolute() or not relative.parts or relative.parts[0] not in FOLDERS or ".." in relative.parts:
        raise ValueError(f"{repo_path!r} is not in a folder Curio ships beside its code ({', '.join(FOLDERS)})")
    return root(code_root) / relative


def downloaded_on_first_use(folder=None, *, strict=True) -> tuple[str, ...]:
    """The repository paths the pip package leaves out: each path a manifest
    in ``datasets/`` or ``packages/`` names in ``downloadOnFirstUse``, under
    its entry's folder. A path names a file, or a folder whose files it
    covers (:func:`covers`).

    *folder* holds ``datasets/`` and ``packages/``: the repository, for the
    release, or :func:`root` when None. With *strict*, a manifest that cannot
    be read, or that names anything but paths inside its folder, raises
    ``ValueError``; without, it names nothing."""
    base = Path(root() if folder is None else folder)
    paths: list[str] = []
    for catalog in CATALOGS:
        for manifest in sorted((base / catalog).glob("*/manifest.json")):
            try:
                named = _named_in(manifest)
            except ValueError:
                if strict:
                    raise
                continue
            paths += [f"{catalog}/{manifest.parent.name}/{rel}" for rel in named]
    return tuple(paths)


def covers(paths, repo_path: str) -> bool:
    """Whether *repo_path* is one of *paths*, or is in a folder one names."""
    return any(repo_path == path or repo_path.startswith(f"{path}/") for path in paths)


def _named_in(manifest: Path) -> list[str]:
    """What *manifest* names in ``downloadOnFirstUse``: paths inside its folder."""
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{manifest} cannot be read: {exc}") from exc
    named = raw.get(DOWNLOAD_ON_FIRST_USE) if isinstance(raw, dict) else None
    if named is None:
        return []
    if not isinstance(named, list) or not all(_inside_its_folder(rel) for rel in named):
        raise ValueError(f"{manifest}: {DOWNLOAD_ON_FIRST_USE} must list paths inside its folder, not {named!r}")
    return named


def _inside_its_folder(rel) -> bool:
    return (
        isinstance(rel, str)
        and not rel.startswith("/")
        and "\\" not in rel
        and all(part not in ("", ".", "..") for part in rel.split("/"))
    )
