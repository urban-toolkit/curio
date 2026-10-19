"""scripts/ci-requirements.txt, the list CI's image installs before its source.

The Dockerfile's CURIO_CI_SETUP layer pip-installs that file, and the image
build caches the layer on the file's content, so a commit that changes no
dependency reuses it. scripts/ci_requirements.py writes the file from setup's
own walk (``manifest_requirements``). A stale file still builds a working
image, since setup installs what it left out in a later layer, so this test is
what says it is stale.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from utk_curio.cli import dependencies

REPO = Path(__file__).resolve().parents[4]


def _script():
    spec = importlib.util.spec_from_file_location("ci_requirements", REPO / "scripts" / "ci_requirements.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_list_is_current():
    script = _script()
    assert script.LIST.is_file(), f"{script.LIST} is missing: run python scripts/ci_requirements.py"
    assert script.LIST.read_text(encoding="utf-8") == script.expected(), (
        "scripts/ci-requirements.txt is stale, so CI's image installs those libraries "
        "again on every build: run python scripts/ci_requirements.py"
    )


def test_the_list_walks_the_examples_in_an_empty_state_directory(tmp_path, monkeypatch):
    """What the image build's setup installs: the shipped catalog and the
    examples' packages, with no store a user of this machine installed."""
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("CURIO_SEED_EXAMPLES", "0")
    seen = {}

    def walk():
        seen.update(seed=os.environ.get("CURIO_SEED_EXAMPLES"), state=os.environ.get("CURIO_STATE_DIR"))
        return ["one>=1", "two~=2.0"]

    monkeypatch.setattr(dependencies, "manifest_requirements", walk)

    text = _script().expected()

    assert text.startswith("#") and text.endswith("one>=1\ntwo~=2.0\n")
    assert seen["seed"] == "1", "the examples' packages were left out"
    assert seen["state"] and seen["state"] != str(tmp_path), "the walk read this machine's state directory"
    assert (os.environ["CURIO_SEED_EXAMPLES"], os.environ["CURIO_STATE_DIR"]) == ("0", str(tmp_path)), (
        "the script left its environment changed"
    )
