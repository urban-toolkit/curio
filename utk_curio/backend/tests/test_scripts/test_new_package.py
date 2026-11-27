"""Smoke tests for the package scaffolder.

``scripts/new_package.py`` is the documented entry point for authoring a node
(see docs/AUTHORING-NODES.md). It validates ids, writes a package tree, and then
calls the backend's own manifest loader and integrity hasher, so a change to
either of those can break scaffolding without breaking anything else. Nothing
else in the suite imports it.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


new_package = _load("new_package")


def test_scaffolds_a_package_that_the_backend_can_load(tmp_path):
    rc = new_package.main(["me.roughness", "--dest", str(tmp_path)])
    assert rc == 0

    root = tmp_path / "me.roughness@1"
    assert (root / "manifest.json").is_file()
    assert (root / "README.md").is_file()
    assert (root / "LICENSE").is_file()
    assert (root / "integrity.json").is_file()
    assert (root / "sources" / "roughness.py").is_file()

    # The scaffolder validates through the real loader, so a passing run means
    # the emitted manifest is installable, not merely well-formed JSON.
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    manifest = load_package_manifest(root)
    assert manifest is not None

    raw = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert raw["id"] == "me.roughness"
    assert [t["id"] for t in raw["templates"]] == ["roughness"]
    # A Tier 1 package reuses the built-in editor and ships no bundle.
    assert "behaviorScript" not in raw


def test_integrity_covers_every_shipped_file_but_itself(tmp_path):
    assert new_package.main(["me.thing", "--dest", str(tmp_path)]) == 0
    root = tmp_path / "me.thing@1"

    hashes = json.loads((root / "integrity.json").read_text(encoding="utf-8"))["sha256"]
    on_disk = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != "integrity.json"
    }
    assert set(hashes) == on_disk


def test_with_ui_emits_a_behavior_bundle_entry(tmp_path):
    rc = new_package.main(["me.heatmap", "--with-ui", "--dest", str(tmp_path)])
    assert rc == 0

    root = tmp_path / "me.heatmap@1"
    raw = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    # The three things AUTHORING-NODES.md warns must agree.
    assert raw["behaviorScript"] == "scripts/behaviors.js"
    behavior = raw["templates"][0]["behavior"]
    index = (root / "sources" / "index.tsx").read_text(encoding="utf-8")
    assert f"'{behavior}'" in index or f'"{behavior}"' in index

    assert (root / "sources" / "index.tsx").is_file()
    assert list(root.glob("sources/*Behavior.tsx")), "expected a behavior hook source"


def test_with_ui_reads_its_input_with_the_canvas_reader(tmp_path):
    """A node made with ``--with-ui`` reads an output with
    ``window.curio.fetchData``, as the canvas does, and
    fetches ``/get`` itself only on a host without it: ``/get`` reads under
    the sign-in's session alone, so after a new sign-in a saved input reads
    only on the dataflow's route."""
    assert new_package.main(["me.heatmap", "--with-ui", "--dest", str(tmp_path)]) == 0
    source = next((tmp_path / "me.heatmap@1" / "sources").glob("*Behavior.tsx")).read_text(encoding="utf-8")
    resolve = source[source.index("async function resolveInput"):]
    resolve = resolve[: resolve.index("\n}\n")]

    assert "(window as any).curio?.fetchData" in source
    assert "return unwrap(await fetchData(ref.trim()))" in resolve
    assert resolve.index("hostFetchData()") < resolve.index("/get?fileName=")


def test_with_ui_stores_its_output_and_hands_on_the_reference(tmp_path):
    """A node made with ``--with-ui`` stores its rows with
    ``window.curio.storeOutput`` and hands on what that answers, a reference,
    as every other node does. Rows handed on as they are reach a chart, which
    reads them in the browser, but never a Python or JS node, and are not
    saved with the dataflow (#1333)."""
    assert new_package.main(["me.heatmap", "--with-ui", "--dest", str(tmp_path)]) == 0
    source = next((tmp_path / "me.heatmap@1" / "sources").glob("*Behavior.tsx")).read_text(encoding="utf-8")
    emit = source[source.index("const emit = useCallback("):]
    emit = emit[: emit.index("}, [")]

    assert "(window as any).curio?.storeOutput" in source
    assert "await store(" in emit, emit
    assert emit.index("await store(") < emit.index("data.outputCallback(data.nodeId, stored)")
    assert "outputCallback(data.nodeId, {" not in emit, "the rows are handed on as they are"


def test_major_and_template_id_overrides(tmp_path):
    rc = new_package.main(
        ["me.thing", "--major", "2", "--template-id", "my-thing", "--dest", str(tmp_path)]
    )
    assert rc == 0
    root = tmp_path / "me.thing@2"
    assert (root / "sources" / "my-thing.py").is_file()
    raw = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert raw["compatibility"]["major"] == 2
    assert raw["templates"][0]["id"] == "my-thing"


@pytest.mark.parametrize("package_id", [
    "9lives", "me..thing-", "me thing", "",
    # The package loader's ids are two to six segments, each a letter, then
    # letters, digits or '-' (``packages.domain.package_id.PACKAGE_DIR_RE``).
    "roughness", "me.my_node", "me..x", "me.a.b.c.d.e.f", "me.x-", "me." + "a" * 64,
])
def test_invalid_package_ids_exit_2(tmp_path, package_id):
    assert new_package.main([package_id, "--dest", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == [], "nothing should be written for a bad id"


def test_an_id_whose_part_starts_with_a_digit_exits_2(tmp_path):
    """With a template id of its own, the package id's check alone refuses it."""
    assert new_package.main(["me.9lives", "--template-id", "lives", "--dest", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == [], "nothing should be written for a bad id"


def test_a_major_the_loader_refuses_exits_2(tmp_path):
    """The loader reads a major of at most four digits."""
    assert new_package.main(["me.thing", "--major", "10000", "--dest", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == [], "nothing should be written for a bad major"


@pytest.mark.parametrize("package_id", [
    "me.roughness", "edu.uic.cs529.alice", "me.my-node", "me.a.b.c.d.e", "a.b",
    "me." + "a" * 63,
])
def test_an_id_the_loader_takes_is_scaffolded_and_loads(tmp_path, package_id):
    assert new_package.main([package_id, "--dest", str(tmp_path)]) == 0

    manifest = new_package.load_package_manifest(tmp_path / f"{package_id}@1")
    assert manifest.package_id == package_id


def test_the_refusal_says_what_an_id_is_made_of(tmp_path, capsys):
    assert new_package.main(["me.my_node", "--dest", str(tmp_path)]) == 2

    said = capsys.readouterr().err
    assert "'_'" not in said, said
    assert "two to six" in said, said
    assert "63" in said, said


@pytest.mark.parametrize("template_id", ["9lives", "has_underscore", "x" * 64])
def test_invalid_template_ids_exit_2(tmp_path, template_id):
    rc = new_package.main(
        ["me.thing", "--template-id", template_id, "--dest", str(tmp_path)]
    )
    assert rc == 2


def test_ids_are_normalised_rather_than_rejected(tmp_path):
    """Case and surrounding whitespace are forgiven, not fatal.

    Both ids are ``.strip().lower()``-ed before validation, so a user who types
    a capitalised id gets a working package rather than an error.
    """
    rc = new_package.main(
        ["  Me.Roughness  ", "--template-id", "Rough-Ness", "--dest", str(tmp_path)]
    )
    assert rc == 0
    root = tmp_path / "me.roughness@1"
    assert root.is_dir()
    assert (root / "sources" / "rough-ness.py").is_file()


def test_a_leading_dash_id_is_rejected_by_argparse(tmp_path):
    # argparse claims it as an option before the id validator ever sees it, so
    # this exits through SystemExit rather than returning a status.
    with pytest.raises(SystemExit) as excinfo:
        new_package.main(["-leading", "--dest", str(tmp_path)])
    assert excinfo.value.code == 2


def test_existing_directory_is_refused_without_force(tmp_path):
    assert new_package.main(["me.thing", "--dest", str(tmp_path)]) == 0
    assert new_package.main(["me.thing", "--dest", str(tmp_path)]) == 1
    # --force overwrites in place.
    assert new_package.main(["me.thing", "--force", "--dest", str(tmp_path)]) == 0
