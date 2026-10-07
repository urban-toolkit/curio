#!/usr/bin/env python3
"""Record the files the pip package leaves out, for the release being built.

    python scripts/record_left_out_files.py --commit <40-hex commit> [--out PATH]

The release workflow (``publish-pip-to-pypi.yml``) runs this before
``python -m build``, with the commit it builds from. It reads the list of the
files the package leaves out
(``utk_curio/backend/app/datasets/infrastructure/left_out_files.json``) and
writes each file's size and sha256, with the commit, to
``left_out_files.record.json`` beside the list, which the package ships. A pip
install downloads each file from GitHub, at that commit, the first time Curio
needs it, and checks it against this record
(``utk_curio/backend/app/datasets/infrastructure/left_out_files.py``).

Fails, writing nothing, when the commit is not a full commit hash or a listed
file is missing from the checkout.

Reads the list by path and imports nothing from Curio: the release job
installs only the build tools.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INFRASTRUCTURE = REPO / "utk_curio" / "backend" / "app" / "datasets" / "infrastructure"
LIST_PATH = INFRASTRUCTURE / "left_out_files.json"
RECORD_PATH = INFRASTRUCTURE / "left_out_files.record.json"
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_record(repo: Path, commit: str) -> dict:
    """The record of the listed files as *repo* holds them, built from *commit*."""
    listed = json.loads((repo / LIST_PATH.relative_to(REPO)).read_text(encoding="utf-8"))["files"]
    files = {}
    for repo_path in listed:
        path = repo / repo_path
        if not path.is_file():
            raise FileNotFoundError(f"{repo_path} is listed but not in the checkout")
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
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    for repo_path, entry in record["files"].items():
        print(f"{repo_path}: {entry['size']:,} bytes, sha256 {entry['sha256']}")
    print(f"wrote {args.out} for commit {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
