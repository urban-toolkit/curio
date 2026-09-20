"""The deployed bundle must keep the backend URL its image was built for.

curio-dev served a frontend that called ``http://localhost:5002`` for every
request: the health banner reported the backend down, and guest sign-in failed
outright because an HTTPS page may not post to plain http (mixed content).

The image built the bundle correctly. The break happened at container start:

1. ``dist/`` shipped without the ``.curio-backend-url`` stamp, because only
   ``check_install_build`` writes one and the Dockerfile runs webpack directly.
   ``_build_stamp_reason`` reads a missing stamp as "an unrecorded mode", so the
   launcher rebuilt the whole bundle on every boot.
2. That rebuild ran with ``BACKEND_URL`` unset -- build args do not cross build
   stages -- so ``set_environment_variables`` applied its
   ``http://localhost:5002`` default, and ``systemvars: true`` made that
   environment variable beat the ``.env`` the build stage had rewritten.

So the correct bundle was overwritten by a wrong one seconds after the image
that contained it was deployed. Both halves are pinned here: the stamp the image
writes, and the ENV that stops the launcher's default from replacing it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import utk_curio.main as main

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = REPO_ROOT / "Dockerfile"


def _dockerfile() -> str:
    """The Dockerfile text, or a skip.

    This suite also runs inside the built image, which ships ``utk_curio/``
    without the checkout around it (same reason as test_launcher_node_version).
    """
    if not DOCKERFILE.is_file():
        pytest.skip("the image ships utk_curio/ without the Dockerfile beside it")
    return DOCKERFILE.read_text(encoding="utf-8")


def _runtime_stage(text: str) -> str:
    """Everything from the final stage's FROM to the end of the file."""
    marker = "FROM runtime_base AS runtime"
    assert marker in text, "the final stage was renamed; update this test"
    return text.split(marker, 1)[1]


def _stamp_command(text: str) -> str:
    """The Dockerfile's own line that writes the stamp, minus the RUN."""
    for line in text.splitlines():
        if ".curio-backend-url" in line and line.startswith("RUN "):
            return line[len("RUN "):]
    pytest.fail("no RUN line in the Dockerfile writes dist/.curio-backend-url")


def test_runtime_stage_publishes_the_backend_url():
    """Without this ENV the launcher's localhost default wins at container start."""
    stage = _runtime_stage(_dockerfile())
    assert re.search(r"^ARG BACKEND_URL\s*$", stage, re.M), (
        "the runtime stage must re-declare ARG BACKEND_URL; build args do not "
        "cross stages"
    )
    assert re.search(r"^ENV BACKEND_URL=\$BACKEND_URL\s*$", stage, re.M), (
        "the runtime stage must export BACKEND_URL, or "
        "set_environment_variables() defaults it to http://localhost:5002"
    )


def test_the_url_is_exported_before_the_launcher_runs():
    """ENV has to precede CMD to be in the environment curio.py starts with."""
    stage = _runtime_stage(_dockerfile())
    assert stage.index("ENV BACKEND_URL") < stage.index("CMD ["), (
        "BACKEND_URL is exported after the CMD that reads it"
    )


def test_the_image_stamps_what_it_built():
    """The build stage must record the bundle, or every boot rebuilds it."""
    text = _dockerfile()
    builder = text.split("AS frontend_builder", 1)[1].split("FROM runtime_base AS runtime")[0]
    assert ".curio-backend-url" in builder, (
        "the frontend build stage must write the stamp the launcher reads"
    )
    assert builder.index("npm run build") < builder.index(".curio-backend-url"), (
        "the stamp must be written after the build it describes"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_stamp_the_image_writes_is_one_the_launcher_accepts(tmp_path, monkeypatch):
    """Run the Dockerfile's own command, then read it back with the launcher.

    The two live in different languages and different stages, and agree only by
    convention: two lines, webpack mode then URL. This executes the real writer
    against the real ``package.json`` and hands the result to the real reader,
    so a change to either side that breaks the handshake fails here.
    """
    url = "https://curio-dev.urbantk.org/api/"
    frontend = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows"
    if not (frontend / "package.json").is_file():
        pytest.skip("no frontend package.json in this tree")

    # The layout the build stage runs in: package.json, and the dist it made.
    shutil.copy(frontend / "package.json", tmp_path / "package.json")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")

    subprocess.run(
        ["/bin/sh", "-c", _stamp_command(_dockerfile())],
        cwd=tmp_path,
        env={**os.environ, "BACKEND_URL": url},
        check=True,
    )

    stamp = (tmp_path / "dist" / ".curio-backend-url").read_text(encoding="utf-8")
    assert stamp.splitlines() == ["production", url], stamp

    # What the container does next: the launcher decides whether to rebuild.
    monkeypatch.setattr(main, "_frontend_dir", lambda: str(tmp_path))
    monkeypatch.setenv("BACKEND_URL", url)
    assert main._build_stamp_reason() is None
    assert main._frontend_needs_build() is False

    # And the regression itself: drop the runtime ENV and the launcher rebuilds,
    # which is what rebaked localhost:5002 over the deployed address.
    monkeypatch.delenv("BACKEND_URL")
    assert main._frontend_needs_build() is True
    assert f"built for {url}" in main._build_stamp_reason()


def test_launcher_default_is_what_broke_the_deployment(monkeypatch):
    """Pins the mechanism: unset BACKEND_URL becomes localhost, set is kept."""
    monkeypatch.delenv("BACKEND_URL", raising=False)
    main.set_environment_variables("0.0.0.0", 5002, "127.0.0.1", 2000)
    assert os.environ["BACKEND_URL"] == "http://localhost:5002"

    monkeypatch.setenv("BACKEND_URL", "https://curio-dev.urbantk.org/api")
    main.set_environment_variables("0.0.0.0", 5002, "127.0.0.1", 2000)
    assert os.environ["BACKEND_URL"] == "https://curio-dev.urbantk.org/api"
