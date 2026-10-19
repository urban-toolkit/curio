#!/usr/bin/env python3
"""Record the files the pip package leaves out, for the release being built.

    python scripts/record_left_out_files.py --commit <40-hex commit> [--out PATH]

The release workflow (``publish-pip-to-pypi.yml``) runs this before
``python -m build``, with the commit it builds from. The files are those the
manifests in ``datasets/`` and ``packages/`` name in ``downloadOnFirstUse``,
each file named and each file in a folder named (``utk_curio/shipped.py``),
which ``setup.py`` leaves out of the package. It writes each file's size and
sha256, with the commit, to ``left_out_files.record.json`` in
``utk_curio/backend/app/datasets/infrastructure/``, which the package ships.
A pip install downloads each file from GitHub, at that commit, the first time
Curio needs it, and checks it against this record
(``utk_curio/backend/app/datasets/infrastructure/left_out_files.py``).

Fails, writing nothing, when the commit is not a full commit hash, a manifest
names a path outside its folder, or a named file is missing from the checkout.

Reads ``utk_curio/shipped.py`` by its path and imports nothing else from
Curio: the release job installs only the build tools.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INFRASTRUCTURE = REPO / "utk_curio" / "backend" / "app" / "datasets" / "infrastructure"
RECORD_PATH = INFRASTRUCTURE / "left_out_files.record.json"
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _shipped():
    """``utk_curio/shipped.py``, which reads what the manifests name."""
    spec = importlib.util.spec_from_file_location("_curio_shipped", REPO / "utk_curio" / "shipped.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def left_out_files(repo: Path) -> list[str]:
    """The repository paths of the files the pip package leaves out, as
    *repo* holds them: each file a manifest names in ``downloadOnFirstUse``,
    and each file in a folder one names. Raises ``FileNotFoundError`` for a
    named path *repo* lacks, and ``ValueError`` for a manifest that names a
    path outside its folder."""
    repo = Path(repo)
    files: list[str] = []
    for repo_path in _shipped().downloaded_on_first_use(repo):
        path = repo / repo_path
        if path.is_dir():
            files += [inner.relative_to(repo).as_posix() for inner in path.rglob("*") if inner.is_file()]
        elif path.is_file():
            files.append(repo_path)
        else:
            raise FileNotFoundError(f"{repo_path} is named in downloadOnFirstUse but not in the checkout")
    return sorted(set(files))


def build_record(repo: Path, commit: str) -> dict:
    """The record of the files the pip package leaves out, as *repo* holds
    them, built from *commit*."""
    files = {}
    for repo_path in left_out_files(repo):
        path = Path(repo) / repo_path
        files[repo_path] = {"size": path.stat().st_size, "sha256": _sha256(path)}
    return {"commit": commit, "files": files}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", required=True, help="the full hash of the commit the package is built from")
    parser.add_argument("--out", type=Path, default=RECORD_PATH, help=f"where to write the record (default {RECORD_PATH.relative_to(REPO)})")
    args = parser.parse_args(argv)
    commit = args.commit.strip().lower()
    if not COMMIT.match(commit):
        print(f"--commit must be a full commit hash (40 hexadecimal digits), not {args.commit!r}", file=sys.stderr)
        return 2
    try:
        record = build_record(REPO, commit)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    for repo_path, entry in record["files"].items():
        print(f"{repo_path}: {entry['size']:,} bytes, sha256 {entry['sha256']}")
    print(f"wrote {args.out} for commit {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
