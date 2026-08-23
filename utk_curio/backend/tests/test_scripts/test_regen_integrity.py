"""Smoke tests for the integrity regenerator.

``scripts/regen_integrity.py`` is what AUTHORING-NODES.md tells authors to run
after editing a package by hand. Nothing verifies these hashes at load time
today, so a silent failure here is invisible until someone starts checking them.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


new_package = _load("new_package")
regen_integrity = _load("regen_integrity")


def _scaffold(tmp_path: Path, package_id: str = "me.thing") -> Path:
    assert new_package.main([package_id, "--dest", str(tmp_path)]) == 0
    return tmp_path / f"{package_id}@1"


def _hashes(root: Path) -> dict[str, str]:
    return json.loads((root / "integrity.json").read_text(encoding="utf-8"))["sha256"]


def test_rehashes_an_edited_source_file(tmp_path):
    root = _scaffold(tmp_path)
    source = next(root.glob("sources/*.py"))
    before = _hashes(root)

    source.write_text("# edited\nreturn arg\n", encoding="utf-8")
    assert regen_integrity.main([str(root)]) == 0

    after = _hashes(root)
    rel = source.relative_to(root).as_posix()
    assert after[rel] != before[rel]
    assert set(after) == set(before), "file set should be unchanged by an edit"


def test_picks_up_added_and_removed_files(tmp_path):
    root = _scaffold(tmp_path)
    (root / "EXTRA.md").write_text("notes\n", encoding="utf-8")
    (root / "LICENSE").unlink()

    assert regen_integrity.main([str(root)]) == 0

    after = _hashes(root)
    assert "EXTRA.md" in after
    assert "LICENSE" not in after


def test_integrity_never_hashes_itself(tmp_path):
    root = _scaffold(tmp_path)
    assert regen_integrity.main([str(root)]) == 0
    assert "integrity.json" not in _hashes(root)


def test_is_idempotent(tmp_path):
    root = _scaffold(tmp_path)
    assert regen_integrity.main([str(root)]) == 0
    first = (root / "integrity.json").read_text(encoding="utf-8")
    assert regen_integrity.main([str(root)]) == 0
    assert (root / "integrity.json").read_text(encoding="utf-8") == first


def test_handles_several_packages_in_one_run(tmp_path):
    a = _scaffold(tmp_path, "me.alpha")
    b = _scaffold(tmp_path, "me.beta")
    assert regen_integrity.main([str(a), str(b)]) == 0
    assert _hashes(a) and _hashes(b)


def test_reports_an_invalid_manifest_but_still_writes_hashes(tmp_path):
    # Hashes are refreshed first and the manifest validated after, so an author
    # mid-edit still gets correct hashes alongside a non-zero status.
    root = _scaffold(tmp_path)
    (root / "manifest.json").write_text('{"id": "me.thing"}', encoding="utf-8")

    assert regen_integrity.main([str(root)]) == 1

    after = _hashes(root)
    manifest_hash = after["manifest.json"]
    assert manifest_hash, "hashes should still have been rewritten"


def test_all_with_no_packages_exits_1(tmp_path, monkeypatch):
    monkeypatch.setattr(regen_integrity, "_catalog_root", lambda: tmp_path)
    assert regen_integrity.main(["--all"]) == 1


def test_all_discovers_scaffolded_packages(tmp_path, monkeypatch):
    _scaffold(tmp_path, "me.alpha")
    _scaffold(tmp_path, "me.beta")
    monkeypatch.setattr(regen_integrity, "_catalog_root", lambda: tmp_path)
    assert regen_integrity.main(["--all"]) == 0
