#!/usr/bin/env python3
"""Write scripts/ci-requirements.txt, or check that it is current.

    python scripts/ci_requirements.py          # write it
    python scripts/ci_requirements.py --check  # exit 1 when it is stale

The file lists the libraries ``curio.py setup --with-examples`` installs from
the package manifests, one pip requirement per line, as setup's own walk lists
them (``manifest_requirements`` in utk_curio/cli/dependencies.py). CI's image
installs it in a layer of its own before the source is copied (the
Dockerfile's CURIO_CI_SETUP), and the image build's cache keys that layer on
the file's content, so it is rebuilt only when the list changes.

The walk runs over the shipped catalog and the examples' packages alone, in an
empty state directory as in the image build, so no user's store on this
machine changes the list.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIST = REPO / "scripts" / "ci-requirements.txt"
HEADER = (
    "# What `curio.py setup --with-examples` installs from the package manifests,\n"
    "# which CI's image installs before its source (the Dockerfile's CURIO_CI_SETUP).\n"
    "# Written by scripts/ci_requirements.py; a unit test checks it is current.\n"
)


def expected() -> str:
    """The file's content for this checkout's manifests and examples."""
    sys.path.insert(0, str(REPO))
    from utk_curio.cli.dependencies import manifest_requirements

    names = ("CURIO_SEED_EXAMPLES", "CURIO_STATE_DIR")
    saved = {name: os.environ.get(name) for name in names}
    with tempfile.TemporaryDirectory() as state:
        os.environ["CURIO_SEED_EXAMPLES"] = "1"
        os.environ["CURIO_STATE_DIR"] = state
        try:
            requirements = manifest_requirements()
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
    return HEADER + "".join(f"{line}\n" for line in requirements)


def main(argv: list[str]) -> int:
    text = expected()
    if argv == ["--check"]:
        if LIST.is_file() and LIST.read_text(encoding="utf-8") == text:
            print(f"{LIST.relative_to(REPO)} is current")
            return 0
        print(f"{LIST.relative_to(REPO)} is stale: run python scripts/ci_requirements.py", file=sys.stderr)
        return 1
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    LIST.write_text(text, encoding="utf-8")
    print(f"wrote {LIST.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
