"""The reader of skills: a ``SKILL.md`` in the Agent Skills format, read strictly or leniently.

A skill is a folder holding a ``SKILL.md``: YAML frontmatter between two
``---`` lines, then its body (https://agentskills.io/specification).
``skills.parse`` reads one:

- strictly, for the skills Curio ships: any break of the specification's rules
  refuses the skill, naming the file and every problem;
- leniently, for a skill brought from elsewhere, as agentskills.io's guide
  for clients says: frontmatter that is no YAML mapping, and a missing or
  empty description, refuse it; every other break is a warning, and the skill
  is read anyway.

Curio ships its skills in ``skills/``, one folder each, and each carries the
same frontmatter fields: ``license``, ``compatibility`` and ``metadata``'s
``author`` and ``version``. ``test_skills_ref.py`` holds the strict mode to
agentskills.io's reference validator.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILLS = REPO_ROOT / "skills"

#: A frontmatter that holds every field the format defines.
GOOD = (
    "name: street-trees\n"
    "description: Use this skill when a node reads a city's street trees.\n"
    "license: MIT\n"
    "compatibility: Written for Curio's agents, their tools and node code.\n"
    "metadata:\n"
    "  author: curio\n"
    '  version: "1.0.0"\n'
    "allowed-tools: dataflow.read node.read\n"
)
BODY = "## Street trees\n\nA tree's species is in {{widgets.reference:species}}.\n"


def _skills():
    from utk_curio.backend.app.agents.domain import skills

    return skills


def _write(tmp_path: Path, folder: str, text: str) -> Path:
    """A folder named *folder* holding a ``SKILL.md`` of *text*."""
    where = tmp_path / folder
    where.mkdir(parents=True)
    (where / "SKILL.md").write_bytes(text.encode("utf-8"))
    return where


def _skill(tmp_path: Path, front: str = GOOD, body: str = BODY, folder: str = "street-trees") -> Path:
    return _write(tmp_path, folder, f"---\n{front}---\n{body}")


def test_a_skill_reads_as_its_fields_its_body_and_its_files(tmp_path):
    skills = _skills()
    folder = _skill(tmp_path)
    (folder / "references").mkdir()
    (folder / "references" / "REFERENCE.md").write_text("More.\n", encoding="utf-8")
    (folder / "assets").mkdir()
    (folder / "assets" / "starter.json").write_text("{}\n", encoding="utf-8")
    (folder / ".notes").write_text("hidden\n", encoding="utf-8")
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "x.pyc").write_bytes(b"")

    skill = skills.parse(folder)
    assert (skill.name, skill.description, skill.license, skill.compatibility, skill.allowed_tools) == (
        "street-trees", "Use this skill when a node reads a city's street trees.", "MIT",
        "Written for Curio's agents, their tools and node code.", "dataflow.read node.read",
    )
    assert dict(skill.metadata) == {"author": "curio", "version": "1.0.0"}
    assert skill.body == BODY, "the body is as written, its markers not filled"
    assert skill.body_line == GOOD.count("\n") + 3
    assert (skill.folder, skill.file) == (folder, folder / "SKILL.md")
    assert skill.files == ("assets/starter.json", "references/REFERENCE.md")
    assert skill.warnings == ()
    assert skills.parse(folder, text=f"---\n{GOOD}---\n## Other\n").body == "## Other\n"


def test_the_body_starts_at_its_first_line_after_the_frontmatter(tmp_path):
    """The blank lines between the frontmatter and the body are no part of it,
    and the line the body starts on counts them; its end is as written."""
    skills = _skills()
    skill = skills.parse(_skill(tmp_path, body="\n\n## Street trees\nNo final line break"))
    assert skill.body == "## Street trees\nNo final line break"
    assert skill.body_line == GOOD.count("\n") + 5
    assert skills.parse(_skill(tmp_path / "empty", body="")).body == ""


@pytest.mark.parametrize("folder, change, said", [
    ("street-trees", ("license: MIT\n", "license: MIT\nauthor: curio\n"), "it holds author, which the format does not"),
    ("Street-Trees", ("name: street-trees", "name: Street-Trees"), "is not lowercase letters, digits and single"),
    ("-street-trees", ("name: street-trees", "name: -street-trees"), "with no hyphen first or last"),
    ("street-trees-", ("name: street-trees", "name: street-trees-"), "with no hyphen first or last"),
    ("street--trees", ("name: street-trees", "name: street--trees"), "single hyphens"),
    ("street_trees", ("name: street-trees", "name: street_trees"), "single hyphens"),
    ("a" * 65, ("name: street-trees", "name: " + "a" * 65), "its name is 65 characters, not 1 to 64"),
    ("trees", ("name: street-trees", "name: street-trees"), "is not its folder's name, 'trees'"),
    ("street-trees", ("name: street-trees\n", ""), "it gives no name"),
    ("street-trees", ("name: street-trees", "name: 12"), "its name is no string"),
    ("street-trees", ("description: Use this skill when a node reads a city's street trees.\n", ""),
     "it gives no description"),
    ("street-trees", ("description: Use this skill when a node reads a city's street trees.", 'description: ""'),
     "it gives no description"),
    ("street-trees", ("description: Use this skill when a node reads a city's street trees.",
                      'description: "   "'), "it gives no description"),
    ("street-trees", ("description: Use this skill when a node reads a city's street trees.",
                      "description: " + "a" * 1025), "its description is 1025 characters, more than 1024"),
    ("street-trees", ("description: Use this skill when a node reads a city's street trees.",
                      "description: [a, b]"), "it gives no description"),
    ("street-trees", ("compatibility: Written for Curio's agents, their tools and node code.",
                      "compatibility: " + "c" * 501), "its compatibility is 501 characters, not 1 to 500"),
    ("street-trees", ("compatibility: Written for Curio's agents, their tools and node code.",
                      'compatibility: ""'), "its compatibility is 0 characters"),
    ("street-trees", ('version: "1.0.0"', "version: 1.0"), "its metadata holds 'version': 1.0, where it holds"),
    ("street-trees", ("metadata:\n  author: curio\n  version: \"1.0.0\"\n", "metadata: [curio]\n"),
     "its metadata is no mapping"),
    ("street-trees", ("license: MIT", "license: 2"), "its license is no string"),
    ("street-trees", ("allowed-tools: dataflow.read node.read", "allowed-tools: [dataflow.read]"),
     "its allowed-tools is no string"),
])
def test_strict_mode_refuses_each_break_of_the_specifications_rules(tmp_path, folder, change, said):
    skills = _skills()
    old, new = change
    assert old in GOOD
    where = _skill(tmp_path, GOOD.replace(old, new, 1), folder=folder)
    with pytest.raises(skills.SkillError, match=r"SKILL\.md") as refused:
        skills.parse(where)
    assert said in str(refused.value)


@pytest.mark.parametrize("text, said", [
    ("## Street trees\n", "starts with its frontmatter, a --- line"),
    ("---\nname: street-trees\n", "no --- line closes its frontmatter"),
    ("---\nname: [street-trees\n---\n", "its frontmatter is not YAML"),
    ("---\n- name\n- description\n---\n", "is no YAML mapping"),
    ("---\n---\n## Street trees\n", "is no YAML mapping"),
    ("--- \n" + GOOD + "---\n" + BODY, "starts with its frontmatter, a --- line"),
    ("﻿---\n" + GOOD + "---\n" + BODY, "starts with its frontmatter, a --- line"),
])
def test_strict_mode_refuses_a_file_that_is_no_frontmatter_and_body(tmp_path, text, said):
    skills = _skills()
    with pytest.raises(skills.SkillError, match="SKILL") as refused:
        skills.parse(_write(tmp_path, "street-trees", text))
    assert said in str(refused.value)


def test_either_mode_reads_a_skill_whose_lines_end_in_a_carriage_return_and_a_line_break(tmp_path):
    """A checkout on Windows writes each line's end as a carriage return and a
    line break; the skill reads as its twin whose lines end in a line break."""
    skills = _skills()
    twin = skills.parse(_skill(tmp_path / "twin"))
    text = f"---\n{GOOD}---\n{BODY}".replace("\n", "\r\n")
    for strict in (True, False):
        for skill in (skills.parse(_write(tmp_path / f"crlf-{strict}", "street-trees", text), strict=strict),
                      skills.parse(tmp_path / "twin" / "street-trees", strict=strict, text=text)):
            assert (skill.name, skill.description, skill.body, skill.body_line) == (
                twin.name, twin.description, twin.body, twin.body_line,
            ), strict
            assert "\r" not in skill.body and skill.warnings == ()


def test_strict_mode_refuses_a_skill_of_500_lines_or_more(tmp_path):
    skills = _skills()
    lines = 2 + GOOD.count("\n") + 2
    under = skills.parse(_skill(tmp_path / "under", body="## Street trees\n" + "Line.\n" * (500 - lines)))
    assert under.body.count("\n") == 500 - lines + 1
    over = _skill(tmp_path, body="## Street trees\n" + "Line.\n" * (500 - lines + 1), folder="street-trees")
    with pytest.raises(skills.SkillError, match="it is 500 lines, where a SKILL.md holds fewer than 500"):
        skills.parse(over)
    assert skills.parse(over, strict=False).warnings


def test_strict_mode_names_every_problem_it_finds(tmp_path):
    skills = _skills()
    where = _skill(tmp_path, GOOD.replace("name: street-trees", "name: Trees").replace("license: MIT", "notes: x"))
    with pytest.raises(skills.SkillError) as refused:
        skills.parse(where)
    for said in ("is not lowercase", "is not its folder's name", "it holds notes"):
        assert said in str(refused.value), said


@pytest.mark.parametrize("change, folder, check", [
    (("name: street-trees", "name: trees"), "street-trees", lambda s: s.name == "trees"),
    (("name: street-trees", "name: " + "a" * 65), "street-trees", lambda s: s.name == "a" * 65),
    (("name: street-trees", "name: Street_Trees"), "street-trees", lambda s: s.name == "Street_Trees"),
    (("name: street-trees\n", ""), "street-trees", lambda s: s.name == "street-trees"),
    (("license: MIT\n", "license: MIT\nauthor: someone\n"), "street-trees", lambda s: s.license == "MIT"),
    (('version: "1.0.0"', "version: 1.0"), "street-trees", lambda s: s.metadata["version"] == "1.0"),
    (("allowed-tools: dataflow.read node.read", "allowed-tools: [dataflow.read, node.read]"), "street-trees",
     lambda s: s.allowed_tools == "dataflow.read node.read"),
    (("description: Use this skill when a node reads a city's street trees.", "description: " + "d" * 1100),
     "street-trees", lambda s: len(s.description) == 1100),
])
def test_lenient_mode_warns_and_reads_the_skill(tmp_path, change, folder, check):
    """agentskills.io's guide for clients: a name that differs from its
    folder or runs past 64 characters warns, and so does every break of the
    format's rules that leaves the skill readable."""
    skills = _skills()
    old, new = change
    where = _skill(tmp_path, GOOD.replace(old, new, 1), folder=folder)
    with pytest.raises(skills.SkillError):
        skills.parse(where)
    skill = skills.parse(where, strict=False)
    assert check(skill), skill
    assert skill.warnings and all(warning.startswith(f"{folder}/SKILL.md: ") for warning in skill.warnings)
    assert skill.body == BODY


@pytest.mark.parametrize("front, said", [
    (GOOD.replace("description: Use this skill when a node reads a city's street trees.\n", ""),
     "gives no description"),
    (GOOD.replace("description: Use this skill when a node reads a city's street trees.", 'description: ""'),
     "gives no description"),
    (GOOD.replace("description: Use this skill when a node reads a city's street trees.",
                  "description: Use this skill when: the user asks"), "its frontmatter is not YAML"),
    ("- a list\n", "is no YAML mapping"),
])
def test_lenient_mode_refuses_a_skill_with_no_description_or_unreadable_yaml(tmp_path, front, said):
    """A description is how an agent knows when to use a skill, so a skill
    with none is refused, and so is frontmatter no YAML reader can read."""
    skills = _skills()
    with pytest.raises(skills.SkillError, match=said):
        skills.parse(_skill(tmp_path, front), strict=False)


def test_lenient_mode_reads_line_breaks_and_marks_other_editors_write(tmp_path):
    skills = _skills()
    text = "﻿--- \r\n" + GOOD.replace("\n", "\r\n") + "---\r\n\r\n" + BODY.replace("\n", "\r\n")
    skill = skills.parse(_write(tmp_path, "street-trees", text), strict=False)
    assert (skill.name, skill.body, skill.warnings) == ("street-trees", BODY, ())
    with pytest.raises(skills.SkillError, match="no SKILL.md"):
        skills.parse(tmp_path / "nowhere", strict=False)


def test_a_name_is_what_the_specification_says_one_is():
    skills = _skills()
    for good in ("pdf-processing", "data-analysis", "code-review", "a", "a" * 64, "v2-maps"):
        assert skills.is_name(good), good
    for bad in ("PDF-Processing", "-pdf", "pdf-", "pdf--processing", "pdf_processing", "a" * 65, "", "../pdf",
                "pdf/x", "café", None, 7):
        assert not skills.is_name(bad), bad


def test_the_skills_curio_ships_are_the_folders_of_skills_that_hold_one(tmp_path, monkeypatch):
    """Each folder of ``skills/`` holding a ``SKILL.md`` is a skill Curio
    ships, by name; a folder without one, a hidden folder and a loose file are
    not. A skill is found by its name alone, and never outside ``skills/``."""
    skills = _skills()
    root = tmp_path / "skills"
    _skill(root, GOOD.replace("street-trees", "bike-lanes", 1), folder="bike-lanes")
    _skill(root)
    (root / "drafts").mkdir()
    _skill(root, folder=".hidden")
    (root / "README.md").write_text("Not a skill.\n", encoding="utf-8")
    outside = _skill(tmp_path / "elsewhere", GOOD.replace("street-trees", "away", 1), folder="away")
    (root / "away").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(skills, "skills_dir", lambda: root)

    assert [folder.name for folder in skills.shipped_folders()] == ["away", "bike-lanes", "street-trees"]
    assert skills.shipped_skill_file("street-trees") == root / "street-trees" / "SKILL.md"
    for name, said in (("drafts", "Curio ships no skill named drafts"), ("Street-Trees", "names no skill"),
                       ("../street-trees", "names no skill"), ("away", "leads out of skills/")):
        with pytest.raises(skills.SkillError, match=said):
            skills.shipped_skill_file(name)
    (root / "away").unlink()
    assert [skill.name for skill in skills.shipped_skills()] == ["bike-lanes", "street-trees"]
    (root / "bike-lanes" / "SKILL.md").write_text(f"---\n{GOOD}---\n{BODY}", encoding="utf-8")
    with pytest.raises(skills.SkillError, match="is not its folder's name"):
        skills.shipped_skills()
    monkeypatch.setattr(skills, "skills_dir", lambda: tmp_path / "none")
    assert skills.shipped_folders() == ()


def test_every_skill_curio_ships_carries_curios_frontmatter():
    """Each skill Curio ships is read strictly with no warning, says when to
    use it in a description that starts as agentskills.io's examples do, and
    carries the license, the compatibility and the metadata Curio gives its
    skills: their author and their version, and what each serves
    (``curio-behaviors``, ``curio-features``, ``curio-refusals``, which
    ``test_skill_listing.py`` and ``test_skill_runs.py`` hold to the code), as
    strings."""
    skills = _skills()
    shipped = skills.shipped_skills()
    assert [skill.name for skill in shipped] == sorted(path.parent.name for path in SKILLS.glob("*/SKILL.md"))
    assert len(shipped) == 21
    for skill in shipped:
        assert skill.description.startswith("Use this skill when "), skill.name
        assert len(skill.description) <= skills.DESCRIPTION_MAX, skill.name
        assert (skill.license, skill.compatibility, skill.allowed_tools) == (
            "MIT", "Written for Curio's agents, their tools and node code.", None,
        ), skill.name
        assert {key: skill.metadata[key] for key in ("author", "version")} == {
            "author": "curio", "version": "1.0.0",
        }, skill.name
        assert set(skill.metadata) - {"author", "version"} <= {
            "curio-behaviors", "curio-features", "curio-refusals",
        }, skill.name
        assert all(value == " ".join(value.split()) and value for value in skill.metadata.values()), skill.name
        assert skill.files == () and skill.warnings == (), skill.name
        assert skill.body.startswith("## ") and skill.body.endswith("\n"), skill.name
