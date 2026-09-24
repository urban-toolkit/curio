"""Compile the Autark data sections of an example, outside the browser.

An autk-grammar node's data section is compiled to autk-db JavaScript by the
frontend and posted to ``/processJavaScriptCode``; only the rendering half
needs a browser. To load the server side of Autark without one, this shells out
to the frontend's own compiler (``scripts/compile-autk-data.mts``, run by Node's
type stripping) rather than keeping a second copy of that emitter in Python.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

FRONTEND_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "frontend", "urban-workflows",
    )
)
COMPILER = os.path.join(FRONTEND_DIR, "scripts", "compile-autk-data.mts")


class AutkCompileError(RuntimeError):
    pass


def compile_autk_data(example_path: str, node_bin: str | None = None) -> dict[str, str]:
    """Return ``{node_id: autk-db JavaScript}`` for one dataflow file.

    Nodes whose spec has no data section are absent from the result: they
    render from upstream input and post nothing to the backend.
    """
    node = node_bin or os.environ.get("CURIO_NODE_BIN") or shutil.which("node")
    if not node:
        raise AutkCompileError(
            "no node executable found - set CURIO_NODE_BIN to a Node 26 binary"
        )

    proc = subprocess.run(
        [node, "--disable-warning=MODULE_TYPELESS_PACKAGE_JSON",
         COMPILER, os.path.abspath(example_path)],
        capture_output=True, text=True, cwd=FRONTEND_DIR,
    )
    if proc.returncode != 0:
        raise AutkCompileError(
            f"compiling autk data for {os.path.basename(example_path)} failed "
            f"(exit {proc.returncode}): {proc.stderr.strip()[:2000]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AutkCompileError(
            f"autk compiler printed non-JSON for {os.path.basename(example_path)}: "
            f"{exc}; stdout={proc.stdout[:500]!r}"
        ) from exc
