#!/usr/bin/env python3
"""Fail when a built distribution is over PyPI's limit for one file.

    python scripts/check_dist_sizes.py dist

Prints each file in the folder with its size, and exits 1 when any is over
104,857,600 bytes (100 MiB), the largest file PyPI takes, or when the folder
holds no file. The release workflow (``publish-pip-to-pypi.yml``) runs it on
``dist/`` before the upload step, so an oversized wheel or sdist stops the
release there instead of failing the upload.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: PyPI's limit for one file: 100 MiB.
LIMIT = 104_857_600


def sizes(folder: Path) -> list[tuple[str, int]]:
    """``(name, size in bytes)`` of each file in *folder*, by name."""
    return [(path.name, path.stat().st_size) for path in sorted(folder.iterdir()) if path.is_file()]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    folder = Path(argv[0])
    found = sizes(folder) if folder.is_dir() else []
    if not found:
        print(f"no file in {folder} to check", file=sys.stderr)
        return 1
    over = 0
    for name, size in found:
        line = f"{name}: {size:,} bytes ({size / 1048576:.1f} MiB)"
        if size > LIMIT:
            over += 1
            line += f", over PyPI's limit of {LIMIT:,} bytes"
        print(line)
    if over:
        print(f"{over} of {len(found)} files are too big to upload to PyPI", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
