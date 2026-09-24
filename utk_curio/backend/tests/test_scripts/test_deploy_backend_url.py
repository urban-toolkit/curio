"""The deployed bundle must keep the backend URL its image was built for.

curio-dev served a frontend that called ``http://localhost:5002`` for every
request: the health banner reported the backend down, and guest sign-in failed
outright because an HTTPS page may not post to plain http (mixed content). The
image had built the bundle correctly; the container replaced it seconds after
boot, because ``dist/`` shipped without a stamp (so the launcher judged it
stale) and the rebuild ran with ``BACKEND_URL`` unset (so the launcher's own
localhost default got baked in).

The Dockerfile half of that lives in ``scripts/check_deploy_backend_url.py``,
for the same reason as ``check_node_pins.py``: this suite runs inside the
container image, which ships ``utk_curio/`` and not the Dockerfile around it.
What is left here is the launcher behaviour the image has to work with, which
does run in the image -- the localhost default, and the stamp rule that makes an
unstamped bundle a rebuild.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

import utk_curio.main as main

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_the_image_keeps_the_backend_url_it_was_built_for():
    """Delegates to the script, which CI also runs on the checkout."""
    if not (REPO_ROOT / "Dockerfile").is_file():
        pytest.skip("the image ships utk_curio/ without the checkout around it")

    path = REPO_ROOT / "scripts" / "check_deploy_backend_url.py"
    spec = importlib.util.spec_from_file_location("_scripts_check_backend_url", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.problems(REPO_ROOT) == []


@pytest.fixture
def checkout(monkeypatch, tmp_path):
    """A built frontend at tmp_path, as the image's COPY leaves one."""
    monkeypatch.setattr(main, "_frontend_dir", lambda: str(tmp_path))
    monkeypatch.delenv("BACKEND_URL", raising=False)
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"build": "webpack --mode production && npm run x"}}),
        encoding="utf-8",
    )
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    return tmp_path


def test_an_unstamped_bundle_is_rebuilt(checkout):
    """Why the image has to stamp: this is what it shipped, and it rebuilds.

    Harmless from a checkout, where the rebuild produces the same bundle. In the
    container it was the whole bug: the rebuild ran in an environment that no
    longer knew the URL the image had been built for.
    """
    assert main._frontend_needs_build() is True
    assert "unrecorded" in main._build_stamp_reason()


def test_a_stamped_bundle_is_served_as_built(checkout, monkeypatch):
    url = "https://curio-dev.urbantk.org/api/"
    (checkout / "dist" / ".curio-backend-url").write_text(
        f"production\n{url}\n", encoding="utf-8"
    )
    monkeypatch.setenv("BACKEND_URL", url)
    assert main._build_stamp_reason() is None
    assert main._frontend_needs_build() is False

    # And the half the runtime ENV supplies: without it the launcher wants its
    # own default instead, which is the rebuild that rebaked localhost.
    monkeypatch.delenv("BACKEND_URL")
    assert main._frontend_needs_build() is True
    assert f"built for {url}" in main._build_stamp_reason()


def test_an_unset_backend_url_becomes_localhost(monkeypatch):
    """The default that overwrote the deployed address. Pins the mechanism."""
    monkeypatch.delenv("BACKEND_URL", raising=False)
    main.set_environment_variables("0.0.0.0", 5002, "127.0.0.1", 2000)
    assert os.environ["BACKEND_URL"] == "http://localhost:5002"


def test_an_explicit_backend_url_survives_a_launch(monkeypatch):
    """What the runtime ENV buys: the image's address is not second-guessed."""
    monkeypatch.setenv("BACKEND_URL", "https://curio-dev.urbantk.org/api")
    main.set_environment_variables("0.0.0.0", 5002, "127.0.0.1", 2000)
    assert os.environ["BACKEND_URL"] == "https://curio-dev.urbantk.org/api"
