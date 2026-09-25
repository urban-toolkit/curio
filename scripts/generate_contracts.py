#!/usr/bin/env python3
"""Write every generated contract output from its single source.

The contracts live in ``utk_curio/backend/app/agents/contracts.py``; this is a
thin CLI over its ``GENERATED_OUTPUTS`` registry. Run it after changing that
module and commit the outputs with the change.

    python scripts/generate_contracts.py           # write every output
    python scripts/generate_contracts.py --check   # write nothing; exit 1 and
                                                   # list the stale outputs

``test_generated_contracts`` runs the same comparison as ``--check`` in the
backend suite.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend.app.agents import contracts  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true",
        help="write nothing; exit non-zero and list every stale output",
    )
    args = parser.parse_args(argv)

    stale = contracts.stale_outputs(REPO_ROOT)
    if args.check:
        for relative in stale:
            print(f"stale: {relative}")
        if stale:
            print(f"run: python {contracts.GENERATOR}")
            return 1
        print(f"{len(contracts.GENERATED_OUTPUTS)} generated output(s) up to date")
        return 0

    for relative, render in contracts.GENERATED_OUTPUTS.items():
        if relative not in stale:
            continue
        path = REPO_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(), encoding="utf-8")
        print(f"wrote: {relative}")
    if not stale:
        print(f"{len(contracts.GENERATED_OUTPUTS)} generated output(s) up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
