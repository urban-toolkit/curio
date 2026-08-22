#!/usr/bin/env python3
"""Regenerate ``integrity.json`` for one or more node packages.

WHY
---
Every package directory carries an ``integrity.json`` listing the SHA-256 of
each shipped file. The installer writes it automatically on install / import,
but a package you edit **in place** — the normal loop when authoring one under
``packages/`` — goes stale until something rewrites it. Hand-rolling the hashes
is easy to get wrong: the map is keyed by POSIX-style paths *relative to the
package root*, so ``sources/my-node.py`` and ``scripts/behaviors.js`` must be
included, not just the files sitting at the top level.

This script is the supported way to do it. It calls the same
``refresh_packageage_integrity`` the installer uses, so the output is identical
to what a fresh install would produce.

Note: nothing in Curio currently *verifies* these hashes at load time — a stale
``integrity.json`` will not stop a package from working. Keep it current anyway
so archives you export carry an honest manifest of their own contents.

Line endings matter to a SHA. On Windows, Git's ``core.autocrlf`` checks text
files out with CRLF, so re-hashing a package that was committed from a Unix
machine reports **every** file as changed. That is expected and harmless. Avoid
committing the resulting churn for packages you did not actually edit — the
committed hashes are the ones computed on LF.

HOW
---
    python scripts/regen_integrity.py packages/me.mynode@1
    python scripts/regen_integrity.py packages/a@1 packages/b@1
    python scripts/regen_integrity.py --all        # every package under packages/

After rewriting the hashes, each package's ``manifest.json`` is validated with
the same loader the backend uses. A manifest problem is reported and sets a
non-zero exit code, but the hashes are still written — you are usually running
this mid-edit and want both pieces of information.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend.app.packages.installer import (  # noqa: E402
    refresh_packageage_integrity,
)
from utk_curio.backend.app.packages.manifest import (  # noqa: E402
    ManifestError,
    load_packageage_manifest,
)
from utk_curio.backend.app.packages.storage import PACKAGE_DIR_RE  # noqa: E402


def _catalog_root() -> Path:
    return REPO_ROOT / "packages"


def _discover_all() -> list[Path]:
    root = _catalog_root()
    if not root.is_dir():
        return []
    return [
        entry
        for entry in sorted(root.iterdir())
        if entry.is_dir() and PACKAGE_DIR_RE.match(entry.name)
    ]


def _regen_one(package_root: Path) -> int:
    """Rewrite one package's integrity file. Returns an exit-code contribution."""
    label = package_root.name

    if not package_root.is_dir():
        print(f"  {label}: not a directory — skipped", file=sys.stderr)
        return 1
    if not (package_root / "manifest.json").is_file():
        print(f"  {label}: no manifest.json — skipped", file=sys.stderr)
        return 1

    before = {}
    integrity_path = package_root / "integrity.json"
    if integrity_path.is_file():
        try:
            import json

            before = json.loads(integrity_path.read_text(encoding="utf-8")).get(
                "sha256", {}
            )
        except (OSError, ValueError):
            before = {}

    after = refresh_packageage_integrity(package_root)

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        name for name in set(after) & set(before) if after[name] != before[name]
    )

    if not (added or removed or changed):
        print(f"  {label}: already up to date ({len(after)} files)")
    else:
        print(f"  {label}: {len(after)} files hashed")
        for name in added:
            print(f"      + {name}")
        for name in changed:
            print(f"      ~ {name}")
        for name in removed:
            print(f"      - {name}")

    # Validate after writing: a broken manifest is worth reporting, but it
    # should not stop the hashes from being refreshed.
    try:
        load_packageage_manifest(package_root)
    except ManifestError as exc:
        print(f"  {label}: manifest is INVALID — {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate integrity.json for one or more node packages.",
    )
    parser.add_argument(
        "packages",
        nargs="*",
        metavar="PACKAGE_DIR",
        help="Path to a package directory, e.g. packages/me.mynode@1",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=f"Process every package under {_catalog_root().name}/",
    )
    args = parser.parse_args(argv)

    if args.all:
        targets = _discover_all()
        if not targets:
            print(f"No packages found under {_catalog_root()}", file=sys.stderr)
            return 1
    elif args.packages:
        targets = [Path(p).resolve() for p in args.packages]
    else:
        parser.error("pass one or more package directories, or --all")
        return 2  # unreachable; keeps type checkers happy

    print(f"Regenerating integrity for {len(targets)} package(s):")
    status = 0
    for target in targets:
        status |= _regen_one(target)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
