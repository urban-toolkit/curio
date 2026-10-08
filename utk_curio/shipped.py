"""Where the folders Curio ships beside its code are on this machine.

The repository keeps them beside ``utk_curio/``: the Data Catalog's datasets
(``datasets/``), the Discovery Catalog's sources (``discovery/``), the Model
Catalog's models (``models/``), the Node Catalog's packages (``packages/``),
the scripts (``scripts/``) and DuckDB's extensions (``vendor/``), and
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
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

#: The folder that holds ``utk_curio/``: the repository root in a clone, the
#: Docker image and CI; site-packages in a pip install.
CODE_ROOT = Path(__file__).resolve().parents[1]

#: Where the pip package carries the shipped folders, under the folder that
#: holds ``utk_curio/``.
IN_THE_PACKAGE = PurePosixPath("utk_curio", "_shipped")

#: The folders Curio ships beside its code, by their name in the repository.
FOLDERS = ("datasets", "discovery", "docs", "models", "packages", "scripts", "vendor")


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
    ``datasets`` or ``packages/curio.builtin@1/manifest.json``), is on this
    machine. *code_root* is as for :func:`root`."""
    relative = PurePosixPath(repo_path)
    if relative.is_absolute() or not relative.parts or relative.parts[0] not in FOLDERS or ".." in relative.parts:
        raise ValueError(f"{repo_path!r} is not in a folder Curio ships beside its code ({', '.join(FOLDERS)})")
    return root(code_root) / relative
