"""A skill's file is ``SKILL.md`` by its exact name, on every file system.

The format names the file ``SKILL.md``. The reader asked ``(folder /
"SKILL.md").is_file()``, which macOS's and Windows's file systems answer yes
for a ``skill.md`` too, and Linux's no. So a skill or a package whose file is
``skill.md`` read, installed and served on a Mac, then went missing on a Linux
deploy, where a package install refused it as holding "no SKILL.md" though it
held one by another case. The reader now looks for the exact name everywhere,
and names the file a folder holds instead.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.app.agents.domain import skills
from utk_curio.backend.app.packages.repositories import archive
from utk_curio.backend.app.packages.repositories.archive import InstallerError

SKILL = (
    "---\n"
    "name: street-trees\n"
    "description: Use this skill when a node reads a city's street trees.\n"
    "---\n"
    "## Street trees\n"
)

#: Names a file system that ignores case takes for ``SKILL.md``.
OTHER_CASES = ["skill.md", "Skill.md", "SKILL.MD"]


def _folder(root: Path, file_name: str) -> Path:
    """``street-trees/`` under *root*, holding the skill as *file_name*."""
    folder = root / "street-trees"
    folder.mkdir(parents=True)
    (folder / file_name).write_text(SKILL, encoding="utf-8")
    return folder


@pytest.mark.parametrize("name", OTHER_CASES)
@pytest.mark.parametrize("strict", [True, False], ids=["strict", "lenient"])
def test_a_skill_whose_file_is_named_in_another_case_is_refused_naming_it(name, strict, tmp_path):
    folder = _folder(tmp_path, name)

    with pytest.raises(skills.SkillError) as refused:
        skills.parse(folder, strict=strict)

    assert f"holds {name}" in str(refused.value)
    assert "SKILL.md" in str(refused.value)


def test_a_skill_whose_file_is_skill_md_is_read(tmp_path):
    folder = _folder(tmp_path, "SKILL.md")

    assert skills.parse(folder).name == "street-trees"
    assert skills.folders_in(tmp_path) == (folder,)


@pytest.mark.parametrize("name", OTHER_CASES)
def test_a_folder_of_skills_holds_no_skill_whose_file_is_named_in_another_case(name, tmp_path):
    _folder(tmp_path, name)

    assert skills.folders_in(tmp_path) == ()


@pytest.mark.parametrize("name", OTHER_CASES)
def test_a_package_whose_skill_file_is_named_in_another_case_is_refused_naming_it(name, tmp_path):
    _folder(tmp_path / "skills", name)

    with pytest.raises(InstallerError) as refused:
        archive.refuse_unreadable_skills(tmp_path)

    assert f"skills/street-trees holds {name}" in str(refused.value)


def test_a_package_whose_skill_file_is_skill_md_is_taken(tmp_path):
    _folder(tmp_path / "skills", "SKILL.md")

    archive.refuse_unreadable_skills(tmp_path)


@pytest.mark.parametrize("name", ["SKILL.md", *OTHER_CASES])
def test_an_account_holds_a_skill_whose_file_is_skill_md_alone(name, tmp_path, monkeypatch):
    from utk_curio.backend.app.agents.repositories import user_skills

    monkeypatch.setattr(user_skills, "skills_dir", lambda user_key: tmp_path)
    _folder(tmp_path, name)

    assert user_skills.holds("guest", "street-trees") is (name == "SKILL.md")


@pytest.mark.parametrize("name", OTHER_CASES)
def test_curio_ships_no_skill_whose_file_is_named_in_another_case(name, tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "skills_dir", lambda: tmp_path)
    _folder(tmp_path, name)

    with pytest.raises(skills.SkillError, match="Curio ships no skill named street-trees"):
        skills.shipped_skill_file("street-trees")


def test_curio_ships_a_skill_whose_file_is_skill_md(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "skills_dir", lambda: tmp_path)
    folder = _folder(tmp_path, "SKILL.md")

    assert skills.shipped_skill_file("street-trees") == folder / "SKILL.md"
