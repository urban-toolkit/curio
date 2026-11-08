"""scripts/ci-requirements.txt, the list CI's image installs before its source.

The Dockerfile's CURIO_CI_SETUP layer pip-installs that file, and the image
build caches the layer on the file's content, so a commit that changes no
dependency reuses it. scripts/ci_requirements.py writes the file from setup's
own walk (``manifest_requirements``), over the whole shipped catalog: CI's
suites run every shipped package's code, one no example uses among them. A
stale file still builds a working image for the examples, since setup installs
what it left out in a later layer, so this test is what says it is stale.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

from utk_curio.cli import dependencies

REPO = Path(__file__).resolve().parents[4]
PACKAGES = REPO / "packages"


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


def test_the_list_walks_the_examples_and_the_whole_catalog_in_an_empty_state_directory(tmp_path, monkeypatch):
    """What the image build's setup installs, the shipped catalog and the
    examples' packages, with every other package Curio ships, and no store a
    user of this machine installed."""
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("CURIO_SEED_EXAMPLES", "0")
    seen = {}

    def walk(*, whole_catalog=False):
        seen.update(
            seed=os.environ.get("CURIO_SEED_EXAMPLES"), state=os.environ.get("CURIO_STATE_DIR"), whole=whole_catalog,
        )
        return ["one>=1", "two~=2.0"]

    monkeypatch.setattr(dependencies, "manifest_requirements", walk)

    text = _script().expected()

    assert text.startswith("#") and text.endswith("one>=1\ntwo~=2.0\n")
    assert seen["seed"] == "1", "the examples' packages were left out"
    assert seen["whole"] is True, "the packages no example uses were left out"
    assert seen["state"] and seen["state"] != str(tmp_path), "the walk read this machine's state directory"
    assert (os.environ["CURIO_SEED_EXAMPLES"], os.environ["CURIO_STATE_DIR"]) == ("0", str(tmp_path)), (
        "the script left its environment changed"
    )


def _name(requirement: str) -> str:
    """A pip requirement's project name, as pip compares names."""
    return re.split(r"[<>=!~;\s\[]", requirement, maxsplit=1)[0].strip().lower().replace("_", "-")


def _declared() -> dict[str, set[str]]:
    """The libraries each shipped package declares, by its id."""
    found = {}
    for path in sorted(PACKAGES.glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        python = (manifest.get("dependencies") or {}).get("python") or {}
        found[manifest["id"]] = {_name(library) for library in python}
    return found


def test_the_list_holds_every_shipped_packages_libraries_and_setup_still_takes_only_the_examples(
    tmp_path, monkeypatch,
):
    """CI's image can run any shipped package's node, whether an example uses
    the package or not; a deployment's setup still installs at launch only the
    built-in's libraries and those of the packages the examples declare,
    and every other package's when someone adds it."""
    from utk_curio.backend.app.packages.application.seeding import example_dep_package_ids

    script = _script()
    listed = {
        _name(line) for line in script.LIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    declared = _declared()
    for package_id, libraries in declared.items():
        assert libraries <= listed, (package_id, sorted(libraries - listed))

    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("CURIO_SEED_EXAMPLES", "1")
    at_launch = {_name(line) for line in dependencies.manifest_requirements()}
    seeded = {"curio.builtin", *example_dep_package_ids()}
    allowed = set().union(*(libraries for package_id, libraries in declared.items() if package_id in seeded))
    assert at_launch <= allowed, sorted(at_launch - allowed)
    only_added = set().union(*declared.values()) - allowed
    assert not only_added & at_launch, sorted(only_added & at_launch)
    assert {_name(line) for line in dependencies.manifest_requirements(whole_catalog=True)} >= only_added
