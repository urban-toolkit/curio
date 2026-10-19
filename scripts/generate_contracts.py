#!/usr/bin/env python3
"""Write every generated contract output from its single source.

The contracts live in ``utk_curio/backend/app/agents/domain/contracts.py``;
this is a thin CLI over its ``GENERATED_OUTPUTS`` registry: the TypeScript
under ``src/generated/`` and every prompt rendered from a ``.template.md`` in
``utk_curio/llm-prompts/``, written into the folder of the agent in
``agents/`` whose manifest names it, else beside its template (the shared
preamble and fragments). Run it after changing that module, a prompt
template, an agent's manifest, or a source a prompt field reads, and commit
the outputs with the change.

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

from utk_curio.backend.app.agents.domain import contracts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true",
        help="write nothing; exit non-zero and list every stale output",
    )
    args = parser.parse_args(argv)

    outputs = contracts.GENERATED_OUTPUTS
    stale = contracts.stale_outputs(REPO_ROOT)
    if args.check:
        for relative in stale:
            print(f"stale: {relative}")
        if stale:
            print(f"run: python {contracts.GENERATOR}")
            return 1
        print(f"{len(outputs)} generated output(s) up to date")
        return 0

    for relative, render in outputs.items():
        if relative not in stale:
            continue
        path = REPO_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(), encoding="utf-8")
        print(f"wrote: {relative}")
    if not stale:
        print(f"{len(outputs)} generated output(s) up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
