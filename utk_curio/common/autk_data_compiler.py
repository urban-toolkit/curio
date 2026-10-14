"""The Autark data compiler a run on the server uses: the browser's own.

An Autark node whose document only loads data runs, in the browser, as the
autk-db JavaScript ``compileDataSpecToAutkDbJs`` (``adapters/node/
autkDataCompile.ts``) writes for its ``data`` section. A run on the server
compiles it with that same TypeScript: ``webpack.autk-data.config.js`` bundles
it into ``dist/autk-data-compile.cjs``, built with the frontend and shipped
beside it, which :func:`compile_data_spec` runs in Node.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

#: The bundle's name in the built frontend's ``dist/``.
COMPILER_NAME = "autk-data-compile.cjs"

#: How long one compile may take, in seconds. It reads a document and writes
#: text; Node's start is most of it.
COMPILE_TIMEOUT = 60


class AutkCompileError(RuntimeError):
    """The data section could not be compiled. ``payload`` carries the message
    the run shows on the node, as a sandbox failure's does."""

    def __init__(self, message: str):
        super().__init__(message)
        self.payload = {"message": message}


def frontend_dir() -> Path:
    """``utk_curio/frontend/urban-workflows``, in a clone and in a pip install."""
    return Path(__file__).resolve().parent.parent / "frontend" / "urban-workflows"


def compiler_path(root: Path | str | None = None) -> Path:
    """Where the built frontend under *root* (default: :func:`frontend_dir`)
    keeps the compiler."""
    return Path(root or frontend_dir()) / "dist" / COMPILER_NAME


def compile_data_spec(spec_text: str) -> str:
    """The autk-db JavaScript the browser posts for the Autark document
    *spec_text*, whose references are already resolved: its data section's
    relative file URLs resolved against the sandbox's backend token, then
    compiled. Raises :class:`AutkCompileError`."""
    bundle = compiler_path()
    if not bundle.is_file():
        raise AutkCompileError(
            f"The Autark data compiler is missing from the built frontend ({bundle}). "
            "Start Curio again to build the frontend."
        )
    node = shutil.which("node")
    if node is None:
        raise AutkCompileError(
            "Node.js is not installed, and an Autark data node needs it to run on the server."
        )
    try:
        done = subprocess.run(
            [node, str(bundle)],
            input=spec_text, capture_output=True, text=True, encoding="utf-8",
            timeout=COMPILE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise AutkCompileError(
            f"Compiling the Autark data section took more than {COMPILE_TIMEOUT} s."
        ) from exc
    if done.returncode != 0 or not done.stdout.strip():
        # Node prints the stack, then its version: the error's own line says why.
        lines = [line.strip() for line in (done.stderr or "").splitlines() if line.strip()]
        reason = next((line for line in lines if "Error" in line.split(":", 1)[0]), None)
        raise AutkCompileError(
            f"The Autark data section could not be compiled: {reason or (lines[-1] if lines else 'no output')}"
        )
    return done.stdout
