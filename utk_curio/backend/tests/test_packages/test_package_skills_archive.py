"""A package's skills travel with it, and one that breaks the Agent Skills format is refused.

A package ships skills for Curio's agents in ``skills/<name>/SKILL.md``, with
the format's other files beside it (``references/``). The archive takes
``skills/`` as it takes ``sources/``: an import installs it, an export carries
it, publishing puts it in the shared catalog, adding the catalog's copy brings
it, and each copy's ``integrity.json`` covers its files. An import and a
publish read each skill strictly, as the skills Curio ships are read, and
refuse a package whose ``skills/`` breaks the format, naming what is wrong.
Scout ships the first, ``scout``.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCOUT_DIR = REPO_ROOT / "packages" / "curio.scout@1"
#: The archive helper's package (``conftest._manifest_dict``).
DIR = "ai.test.demo@1"
SKILL = (
    "---\nname: street-trees\ndescription: Use this skill when a node reads a city's street trees.\n"
    "license: MIT\nmetadata:\n  author: test\n  version: \"1.0.0\"\n  curio-templates: demo-kind\n---\n"
    "## Street trees\n\nA tree's species is in its row; [species](references/species.md) lists them.\n"
)
#: A package's skill, with a file beside its ``SKILL.md``, by their paths in
#: the package.
FILES = {
    "skills/street-trees/SKILL.md": SKILL,
    "skills/street-trees/references/species.md": "Oak, elm, maple.\n",
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _skill_files(root: Path) -> dict[str, str]:
    """Each file under *root*'s ``skills/``, by its path in the package."""
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((root / "skills").rglob("*")) if path.is_file()
    }


def _covered(root: Path) -> dict[str, str | None]:
    """What *root*'s ``integrity.json`` records of each of :data:`FILES`."""
    recorded = json.loads((root / "integrity.json").read_text(encoding="utf-8"))["sha256"]
    return {path: recorded.get(path) for path in FILES}


def _archive(make_archive, files: dict[str, str]) -> bytes:
    return make_archive(extra_files={path: text.encode("utf-8") for path, text in files.items()})


def _accepted(call):
    """What *call*, an install or a publish, returns. One that refuses the
    package fails here, at an assertion that says why."""
    from utk_curio.backend.app.packages.repositories.archive import InstallerError

    try:
        return call()
    except InstallerError as exc:
        refused = str(exc)
    assert not refused, f"Curio refused a package that ships skills: {refused}"


def test_import_export_publish_and_add_keep_a_packages_skills(tmp_curio, tmp_path, monkeypatch, make_archive):
    """An import installs the package's skill and its reference where the
    archive has them, and the store copy's integrity map covers both; the
    export carries them; publishing puts them in the shared catalog with its
    own map; and another account's add of the catalog's copy brings them."""
    from utk_curio.backend.app.packages.application.publishing import publish_installed_to_catalog
    from utk_curio.backend.app.packages.application.store_install import (
        export_package_archive,
        install_package_from_archive,
        install_package_from_directory,
    )
    from utk_curio.backend.app.packages.repositories.store import package_dir

    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(tmp_path / "catalog"))
    hashes = {path: _sha256(text) for path, text in FILES.items()}

    archive = _archive(make_archive, FILES)
    _accepted(lambda: install_package_from_archive("guest", archive))
    installed = package_dir("guest", DIR)
    assert _skill_files(installed) == FILES
    assert _covered(installed) == hashes

    with zipfile.ZipFile(io.BytesIO(export_package_archive("guest", DIR))) as zf:
        exported = {name: zf.read(name).decode("utf-8") for name in zf.namelist() if name.startswith("skills/")}
    assert exported == FILES

    _result, published = _accepted(lambda: publish_installed_to_catalog("guest", DIR, replace=False))
    assert published.resolve() == (tmp_path / "catalog" / DIR).resolve()
    assert _skill_files(published) == FILES
    assert _covered(published) == hashes

    _accepted(lambda: install_package_from_directory("7", published))
    added = package_dir("7", DIR)
    assert _skill_files(added) == FILES
    assert _covered(added) == hashes


@pytest.mark.parametrize("files, said", [
    ({"skills/street-trees/SKILL.md": SKILL.replace("name: street-trees", "name: Street-Trees")},
     "skills/street-trees/SKILL.md: its name 'Street-Trees' is not lowercase letters"),
    ({"skills/street-trees/SKILL.md": SKILL.replace("license: MIT\n", "license: MIT\nauthor: test\n")},
     "skills/street-trees/SKILL.md: it holds author, which the format does not define"),
    ({"skills/street-trees/SKILL.md": SKILL.replace(
        "description: Use this skill when a node reads a city's street trees.\n", "")},
     "skills/street-trees/SKILL.md: it gives no description"),
    ({"skills/street-trees/skill.md": SKILL}, "skills/street-trees holds no SKILL.md"),
    ({"skills/README.md": "Our skills.\n"}, "skills/README.md is no skill's folder"),
], ids=["name", "field", "description", "file-name", "loose-file"])
def test_a_package_whose_skills_break_the_format_is_refused_and_leaves_nothing(
    tmp_curio, tmp_path, make_archive, files, said,
):
    """Each skill is read strictly, as the skills Curio ships are: a name
    that is not lowercase and its folder's, a field the format does not
    define, no description, a ``SKILL.md`` under another name, and a file
    that is no skill's folder each refuse the package. An import and a
    publish both name what is wrong, and leave nothing behind."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_archive
    from utk_curio.backend.app.packages.repositories.archive import InstallerError
    from utk_curio.backend.app.packages.repositories.catalog_dir import publish_package_archive_to_catalog_dir
    from utk_curio.backend.app.packages.repositories.store import package_dir

    archive = _archive(make_archive, files)
    with pytest.raises(InstallerError) as refused:
        install_package_from_archive("guest", archive)
    assert said in str(refused.value), str(refused.value)
    assert "agentskills.io" in str(refused.value)
    assert not package_dir("guest", DIR).exists()

    with pytest.raises(InstallerError) as refused:
        publish_package_archive_to_catalog_dir(archive, tmp_path / "catalog")
    assert said in str(refused.value), str(refused.value)
    assert not (tmp_path / "catalog" / DIR).exists()


def test_scout_ships_its_skill_its_integrity_map_covers_it_and_an_add_brings_it(tmp_curio):
    """Scout's ``skills/`` holds one skill, ``scout``, which Curio's strict
    reader takes; the package's ``integrity.json`` records its file; and an
    account's add of Scout from the catalog puts it in the account's copy,
    whose map records it too."""
    from utk_curio.backend.app.agents.domain import skills
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.skills import skill_folders
    from utk_curio.backend.app.packages.repositories.store import package_dir

    (folder,) = skill_folders(SCOUT_DIR)
    assert (folder.name, skills.parse(folder).name) == ("scout", "scout")
    shipped = (folder / "SKILL.md").read_bytes()
    digest = hashlib.sha256(shipped).hexdigest()
    recorded = json.loads((SCOUT_DIR / "integrity.json").read_text(encoding="utf-8"))["sha256"]
    assert recorded["skills/scout/SKILL.md"] == digest

    install_package_from_directory("guest", SCOUT_DIR)
    added = package_dir("guest", "curio.scout@1")
    assert (added / "skills" / "scout" / "SKILL.md").read_bytes() == shipped
    copied = json.loads((added / "integrity.json").read_text(encoding="utf-8"))["sha256"]
    assert copied["skills/scout/SKILL.md"] == digest
