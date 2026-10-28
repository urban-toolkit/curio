"""Curio's skills pass agentskills.io's reference validator, and Curio's strict reader agrees with it.

``skills-ref`` (https://github.com/agentskills/agentskills, the reference
library the specification names for validation) is pinned in
``requirements.txt`` for the tests alone: its README says it is for
demonstration, so no module of Curio imports it. Here it validates every
skill Curio ships, and it reads small skill folders made from the
specification's own examples, valid and invalid, beside ``skills.parse`` in
strict mode: the two give the same verdict on each.

Where the two readers differ by design, no case here asks them to agree:
``skills-ref`` lets a name hold any letter Unicode calls lowercase, reads
every YAML scalar as text, accepts ``skill.md`` in lowercase and counts no
lines, where Curio's strict reader takes ``a-z``, ``0-9`` and hyphens, wants
strings in ``metadata``, reads ``SKILL.md`` alone and refuses a file of 500
lines or more.

The folders are made in the test's own folder, so no ``SKILL.md`` sits in
``utk_curio/``. The library is imported inside each test, so a missing one
fails the test, never skips it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

#: Folders made from the specification's examples: the folder's name, its
#: frontmatter, and whether the specification takes the skill.
CASES = [
    ("pdf-processing", "name: pdf-processing\ndescription: Extract PDF text, fill forms, merge files. Use when "
     "handling PDFs.\nlicense: Apache-2.0\nmetadata:\n  author: example-org\n  version: \"1.0\"\n", True),
    ("skill-name", "name: skill-name\ndescription: A description of what this skill does and when to use it.\n",
     True),
    ("data-analysis", "name: data-analysis\ndescription: Analyze datasets, generate charts, and create summary "
     "reports.\ncompatibility: Requires git, docker, jq, and access to the internet\n", True),
    ("code-review", "name: code-review\ndescription: Reviews code.\nlicense: Proprietary. LICENSE.txt has "
     "complete terms\nallowed-tools: Bash(git:*) Bash(jq:*) Read\n", True),
    ("PDF-Processing", "name: PDF-Processing\ndescription: Uppercase.\n", False),
    ("-pdf", "name: -pdf\ndescription: A leading hyphen.\n", False),
    ("pdf-", "name: pdf-\ndescription: A trailing hyphen.\n", False),
    ("pdf--processing", "name: pdf--processing\ndescription: Two hyphens.\n", False),
    ("pdf_processing", "name: pdf_processing\ndescription: An underscore.\n", False),
    ("pdf-tools", "name: pdf-processing\ndescription: Another folder's name.\n", False),
    ("a" * 65, f"name: {'a' * 65}\ndescription: A name of 65 characters.\n", False),
    ("no-description", "name: no-description\n", False),
    ("empty-description", 'name: empty-description\ndescription: ""\n', False),
    ("long-description", f"name: long-description\ndescription: {'a' * 1025}\n", False),
    ("no-name", "description: No name.\n", False),
    ("extra-field", "name: extra-field\ndescription: An extra field.\nauthor: example-org\n", False),
    ("long-compatibility", f"name: long-compatibility\ndescription: x.\ncompatibility: {'c' * 501}\n", False),
]


def test_skills_ref_validates_every_skill_curio_ships():
    import skills_ref

    from utk_curio.backend.app.agents.domain import skills

    assert skills_ref.__version__ == "0.1.1"
    folders = skills.shipped_folders()
    assert len(folders) == 16, folders
    problems = {folder.name: skills_ref.validate(folder) for folder in folders}
    assert problems == {folder.name: [] for folder in folders}
    for folder in folders:
        read = skills_ref.read_properties(folder)
        ours = skills.parse(folder)
        assert (read.name, read.description, read.license, read.compatibility, read.metadata) == (
            ours.name, ours.description, ours.license, ours.compatibility, dict(ours.metadata),
        ), folder.name


@pytest.mark.parametrize("folder, front, valid", CASES, ids=[case[0][:24] for case in CASES])
def test_curios_strict_reader_and_skills_ref_give_the_same_verdict(tmp_path, folder, front, valid):
    import skills_ref

    from utk_curio.backend.app.agents.domain import skills

    where = tmp_path / folder
    where.mkdir()
    (where / "SKILL.md").write_text(f"---\n{front}---\n## Body\n\nText.\n", encoding="utf-8")
    problems = skills_ref.validate(where)
    try:
        skills.parse(where)
    except skills.SkillError as exc:
        ours = str(exc)
    else:
        ours = None
    assert (not problems, ours is None) == (valid, valid), (problems, ours)


def test_only_the_tests_import_skills_ref():
    """The app never imports the reference library: no module of
    ``utk_curio/`` but its test suites does."""
    imports = re.compile(r"^\s*(?:import|from)\s+skills_ref\b", re.MULTILINE)
    found = []
    for path in sorted((REPO_ROOT / "utk_curio").rglob("*.py")):
        parts = path.relative_to(REPO_ROOT).parts
        if "tests" in parts or "node_modules" in parts:
            continue
        if imports.search(path.read_text(encoding="utf-8", errors="replace")):
            found.append(path.relative_to(REPO_ROOT).as_posix())
    assert not found, f"these modules of Curio import skills_ref, which only the tests may: {found}"
