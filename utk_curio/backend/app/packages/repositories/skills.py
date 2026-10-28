"""The skills a package ships for Curio's agents, in its ``skills/`` folder.

Repositories layer of the packages package: reads one package directory. A
skill is a folder of ``skills/`` that holds a ``SKILL.md`` in the Agent Skills
format, as Curio's own ``skills/`` holds its skills
(``agents/domain/skills.py``, which reads them). The agents on a dataflow that
uses the package hold its skills (``agents/application/skill_runs.py``), and
an install or a publish refuses a package whose ``skills/`` breaks the format
(``archive.refuse_unreadable_skills``).
"""

from __future__ import annotations

from pathlib import Path

from utk_curio.backend.app.agents.domain import skills as skill_format

#: The folder of a package that holds its skills, one folder each.
SKILLS_DIR = "skills"


def skill_folders(package_root: Path) -> tuple[Path, ...]:
    """The folders of the skills the package at *package_root* ships, by
    name: each folder of its ``skills/`` that holds a ``SKILL.md``
    (``skills.folders_in``). Links are not followed: a ``skills/``, a
    skill's folder or a ``SKILL.md`` that is a link holds no skill."""
    root = Path(package_root) / SKILLS_DIR
    if root.is_symlink():
        return ()
    return tuple(
        folder for folder in skill_format.folders_in(root)
        if not folder.is_symlink() and not (folder / skill_format.SKILL_FILE).is_symlink()
    )
