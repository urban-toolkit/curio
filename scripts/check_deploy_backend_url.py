#!/usr/bin/env python3
"""Fail when the image could rebake the backend URL its bundle was built for.

``BACKEND_URL`` is substituted into the frontend bundle at BUILD time. The
Dockerfile passes the deployment's address in as a build arg, so the image ships
a bundle that calls the right backend -- and then the container used to throw it
away seconds after boot:

* ``dist/`` shipped without the ``.curio-backend-url`` stamp, because only
  ``check_install_build`` writes one and the build stage runs webpack directly.
  ``_build_stamp_reason`` reads a missing stamp as "an unrecorded mode", so the
  launcher rebuilt the whole bundle on every start.
* Build args do not cross stages, so that rebuild ran with ``BACKEND_URL``
  unset and ``set_environment_variables`` applied its ``http://localhost:5002``
  default. ``dotenv-webpack`` is configured ``systemvars: true``, so that
  environment variable beat the ``.env`` the build stage had rewritten.

curio-dev therefore served a frontend calling ``http://localhost:5002`` for
every request: the health banner reported the backend down, and guest sign-in
failed as mixed content because an HTTPS page may not post to plain http.

Lives here rather than only in the test suite because the suite runs inside the
container image, which carries ``utk_curio/`` and not the Dockerfile around it.
CI runs this on the checkout instead, where there is something to check.

Usage::

    python scripts/check_deploy_backend_url.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

RUNTIME_MARKER = "FROM runtime_base AS runtime"
BUILDER_MARKER = "AS frontend_builder"
STAMP = ".curio-backend-url"


def _stamp_command(dockerfile: str) -> str | None:
    """The Dockerfile's own RUN line that writes the stamp, minus the ``RUN``."""
    for line in dockerfile.splitlines():
        if STAMP in line and line.startswith("RUN "):
            return line[len("RUN "):]
    return None


def _handshake_problem(root: Path, dockerfile: str) -> str | None:
    """Run the Dockerfile's stamp command, then read it back with the launcher.

    The writer is a node one-liner in a build stage and the reader is Python in
    the launcher; they agree only by convention (two lines, webpack mode then
    URL). Executing the real writer against the real ``package.json`` and
    handing the result to the real reader is the only way to catch a change to
    either side that quietly breaks the handshake -- the failure mode is not an
    error but a silent rebuild, which is the whole bug.
    """
    command = _stamp_command(dockerfile)
    if command is None:
        return None  # already reported by the structural checks
    if shutil.which("node") is None:
        # Not a failure. The self-hosted CI runner keeps node inside the runner's
        # own externals rather than on PATH, and the real proof runs there
        # anyway: the "Assert the container serves the bundle it shipped" step
        # reads the stamp out of the built image and asks the actual launcher
        # whether it would rebuild. This half is for a developer's checkout.
        print(
            "note: node is not on PATH; skipping the stamp handshake "
            "(the CI step against the built image covers it).",
            file=sys.stderr,
        )
        return None

    package = root / "utk_curio" / "frontend" / "urban-workflows" / "package.json"
    if not package.is_file():
        return None

    url = "https://example.invalid/api/"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copy(package, work / "package.json")
        (work / "dist").mkdir()
        (work / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")

        done = subprocess.run(
            ["/bin/sh", "-c", command],
            cwd=work,
            env={**os.environ, "BACKEND_URL": url},
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            return f"the Dockerfile's stamp command failed: {done.stderr.strip()}"

        written = work / "dist" / STAMP
        if not written.is_file():
            return f"the Dockerfile's stamp command wrote no {STAMP}"

        sys.path.insert(0, str(root))
        from utk_curio.main import _build_stamp_reason

        os.environ["BACKEND_URL"] = url
        reason = _build_stamp_reason(str(work))
        if reason is not None:
            return (
                f"the launcher rejects the stamp the image writes ({reason!r}), "
                f"so the container would rebuild the bundle and rebake the URL"
            )

        # And the stamp must actually carry the URL, not merely parse.
        lines = written.read_text(encoding="utf-8").splitlines()
        if lines[1:2] != [url]:
            return f"the stamp records {lines[1:2]!r}, expected {url!r}"
    return None


def problems(root: Path = REPO_ROOT) -> list[str]:
    """Everything that would let the container rebake the URL, one line each."""
    found: list[str] = []
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    if RUNTIME_MARKER not in dockerfile:
        return [f"no {RUNTIME_MARKER!r} stage; this check needs updating"]
    runtime = dockerfile.split(RUNTIME_MARKER, 1)[1]
    builder = dockerfile.split(BUILDER_MARKER, 1)[-1].split(RUNTIME_MARKER)[0]

    # 1. The runtime stage must republish the build arg, or the launcher's
    #    setdefault supplies http://localhost:5002 instead.
    if not re.search(r"^ARG BACKEND_URL\s*$", runtime, re.M):
        found.append(
            "the runtime stage does not re-declare ARG BACKEND_URL "
            "(build args do not cross stages)"
        )
    if not re.search(r"^ENV BACKEND_URL=\$BACKEND_URL\s*$", runtime, re.M):
        found.append(
            "the runtime stage does not export ENV BACKEND_URL=$BACKEND_URL, so "
            "set_environment_variables() would default it to http://localhost:5002"
        )
    elif "CMD [" in runtime and runtime.index("ENV BACKEND_URL") > runtime.index("CMD ["):
        found.append("BACKEND_URL is exported after the CMD that reads it")

    # 2. The build stage must stamp what it built, or every boot rebuilds.
    if STAMP not in builder:
        found.append(
            f"the frontend build stage never writes dist/{STAMP}, so the launcher "
            f"reads the shipped bundle as stale and rebuilds it at every start"
        )
    elif builder.index("npm run build") > builder.index(STAMP):
        found.append("the stamp is written before the build it describes")

    # 3. The two sides of the stamp must actually agree.
    handshake = _handshake_problem(root, dockerfile)
    if handshake:
        found.append(handshake)

    return found


def main() -> int:
    found = problems()
    if found:
        print("The image could rebake the frontend's backend URL:", file=sys.stderr)
        for line in found:
            print(f"  - {line}", file=sys.stderr)
        print(
            "See the module docstring: a deployment would serve a frontend "
            "calling http://localhost:5002.",
            file=sys.stderr,
        )
        return 1
    print("The image keeps the backend URL it was built for.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
