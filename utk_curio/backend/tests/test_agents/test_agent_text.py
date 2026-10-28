"""Everything an agent reads lives in agents/ and skills/, and the backend renders it when it starts.

The base entry, ``agents/agent.curio.builtin@1`` (its manifest says ``kind:
base``), holds the pages every agent Curio ships reads, and each agent's
folder holds its own prompts. What the agents know of each feature of Curio
is a skill, ``skills/<name>/SKILL.md``, which the preamble places through
``{{skill:<name>}}``, its body without its frontmatter. Each is a
hand-written source whose markers the backend fills when it starts
(``agent_text``). Nothing is generated or committed, and ``utk_curio/`` holds
none of it. An agent names a page as ``curio:<path>``, and no such path leads
out of the base entry. The base entry is no agent: no roster, catalog, palette
or delegation lists it.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS = REPO_ROOT / "agents"
#: The base entry: the pages every agent Curio ships reads.
BASE = AGENTS / "agent.curio.builtin@1"
BASE_ID = "agent.curio.builtin"
#: The skills Curio ships, one folder each.
SKILLS = REPO_ROOT / "skills"
#: Any account key: ``tmp_curio`` gives it a store of its own.
UKEY = "11"


def _fresh_loader(monkeypatch):
    """The loader as in a process that has not started: nothing rendered,
    and no ``--dev``. The test's end restores the process's own renders."""
    from utk_curio.backend.app.agents.domain import agent_text

    monkeypatch.delenv("CURIO_DEV", raising=False)
    monkeypatch.setattr(agent_text, "_TEXTS", {})
    monkeypatch.setattr(agent_text, "_STARTED", False)
    return agent_text


def _agents_copy(tmp_path, monkeypatch) -> Path:
    """A copy of ``agents/`` the test may edit, which the roster and the base
    entry are read from."""
    from utk_curio.backend.app.agents.domain import agent_text, builtin

    root = tmp_path / "agents"
    shutil.copytree(AGENTS, root)
    monkeypatch.setattr(builtin, "agents_dir", lambda: root)
    monkeypatch.setattr(agent_text, "base_dir", lambda: root / BASE.name)
    return root


def _skills_copy(tmp_path, monkeypatch) -> Path:
    """A copy of ``skills/`` the test may edit, which the skills are read from."""
    from utk_curio.backend.app.agents.domain import skills

    root = tmp_path / "skills"
    shutil.copytree(SKILLS, root)
    monkeypatch.setattr(skills, "skills_dir", lambda: root)
    return root


def _user_manifest(system: str, **over) -> dict:
    manifest = {
        "id": "agent.test.my-checker",
        "name": "My Checker",
        "category": "node",
        "version": "1.0.0",
        "capabilities": [{"id": "node.explain", "contractVersion": "1"}],
        "compatibleTargets": [{"kind": "node", "requires": []}],
        "prompts": {
            "system": {"path": system, "variables": []},
            "instruction": {"path": "prompts/instruction.md", "variables": []},
        },
        "provenance": {"publisher": "karla"},
    }
    manifest.update(over)
    return manifest


def test_no_prompt_lives_under_utk_curio():
    """``utk_curio/`` is the plumbing that reads agent text and holds none of
    it: no prompt folder, and no Markdown file but its READMEs and the credits
    of its test fixtures."""
    assert not (REPO_ROOT / "utk_curio" / "llm-prompts").exists()
    stray = []
    for here, dirs, files in os.walk(REPO_ROOT / "utk_curio"):
        dirs[:] = [name for name in dirs if name not in ("node_modules", "dist", "__pycache__") and not name.startswith(".")]
        stray += [
            (Path(here) / name).relative_to(REPO_ROOT).as_posix()
            for name in files
            if name.endswith(".md") and name not in ("README.md", "ATTRIBUTION.md")
        ]
    assert not stray, f"utk_curio/ holds text that belongs in agents/: {sorted(stray)}"


def test_no_prompt_is_generated():
    """Nothing is generated: ``contracts.py`` keeps no registry of files to
    write, no prompt has a template beside it, and a prompt that states a fact
    from code holds the fact's marker, which an agent never reads."""
    from utk_curio.backend.app.agents.domain import builtin, contracts

    assert not hasattr(contracts, "GENERATED_OUTPUTS"), "contracts.py registers files to write"
    assert not hasattr(contracts, "stale_outputs"), "contracts.py checks written files"
    assert not sorted(AGENTS.rglob("*.template.md"))
    source = (AGENTS / "agent.curio.dataflow-builder@1" / "prompts" / "orchestration_instruction.md").read_text(
        encoding="utf-8")
    assert source.startswith("# {{agent.name:agent.curio.dataflow-builder}}\n")
    read = builtin.read_prompt_text("agent.curio.dataflow-builder@1", "instruction")
    assert read.startswith("# Dataflow Builder\n") and "{{" not in read
    preamble = (BASE / "default_preamble.md").read_text(encoding="utf-8")
    assert "{{trill.schema}}" in preamble
    assert "{{" not in builtin.read_prompt_text("agent.curio.dataflow-builder@1", "system")


def test_the_backend_renders_every_page_and_prompt_when_it_starts(tmp_curio, monkeypatch):
    """Starting the backend renders each page the base entry lists, each
    skill Curio ships and each prompt each agent names, once: every file in
    ``agents/`` but the base entry's README, and every ``SKILL.md`` in
    ``skills/``, no marker left in any. A skill renders as its body, without
    its frontmatter. A run reads those renders and no file, and each is its
    source rendered."""
    from utk_curio.backend.app import create_app
    from utk_curio.backend.app.agents.domain import builtin, skills
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    agent_text = _fresh_loader(monkeypatch)
    create_app(TestConfig)
    rendered = agent_text.rendered()
    on_disk = sorted(path.resolve() for path in AGENTS.rglob("*.md") if path != BASE / "README.md")
    skill_files = sorted(path.resolve() for path in SKILLS.glob("*/SKILL.md"))
    assert len(skill_files) == 16, skill_files
    assert sorted(path.resolve() for path in rendered) == sorted(on_disk + skill_files)
    for file, text in rendered.items():
        assert text and "{{" not in text, file
        assert text == agent_text.render(file), file
    by_file = {file.resolve(): text for file, text in rendered.items()}
    for file in skill_files:
        skill = skills.parse(file.parent)
        text = by_file[file]
        assert text.startswith("## ") and not text.startswith(skills.DELIMITER), file
        assert skill.description not in text and f"name: {skill.name}\n" not in text, file
    reads = []
    monkeypatch.setattr(agent_text, "_source", lambda file: reads.append(file) or "")
    for m in builtin.list_builtin_manifests():
        for key in m.prompts:
            assert builtin.read_prompt_text(m.dir_name, key) in rendered.values(), (m.dir_name, key)
    for file in skill_files:
        assert agent_text.skill_text(file.parent.name) == by_file[file].rstrip("\n"), file
    assert reads == [], f"a run read {reads} again"


def test_every_folder_of_skills_holds_a_skill_and_no_page_sits_outside_one():
    """``skills/`` holds one folder per skill, each with a ``SKILL.md`` the
    strict reader takes, named as its folder, and no Markdown file of its
    own: a loose page there is no skill and no agent reads it."""
    from utk_curio.backend.app.agents.domain import skills

    folders = sorted(path for path in SKILLS.iterdir() if path.is_dir() and not path.name.startswith("."))
    assert len(folders) == 16, folders
    for folder in folders:
        assert (folder / skills.SKILL_FILE).is_file(), f"skills/{folder.name}/ holds no {skills.SKILL_FILE}"
        skill = skills.parse(folder)
        assert skill.name == folder.name and skill.warnings == (), folder.name
    loose = sorted(path.name for path in SKILLS.iterdir() if path.is_file() and path.suffix == ".md")
    assert not loose, f"skills/ holds pages outside a skill's folder: {loose}"
    assert [skill.folder for skill in skills.shipped_skills()] == folders


def test_with_dev_an_edit_shows_on_the_next_read_and_without_it_the_start_up_render_stays(tmp_path, monkeypatch):
    """``curio.py start --dev`` (``CURIO_DEV=1``) renders a page or a prompt
    at each read, so an edit shows on the next run; otherwise a read returns
    what the backend rendered when it started."""
    from utk_curio.backend.app.agents.domain import builtin

    agent_text = _fresh_loader(monkeypatch)
    root = _agents_copy(tmp_path, monkeypatch)
    agent_text.render_at_start()
    page = root / BASE.name / "default_preamble.md"
    prompt = root / "agent.curio.dataflow-builder@1" / "prompts" / "orchestration_instruction.md"
    preamble = builtin.read_page("default_preamble.md", wanted_by="the test")
    instruction = builtin.read_prompt_text("agent.curio.dataflow-builder@1", "instruction")
    assert preamble and instruction
    page.write_text(page.read_text(encoding="utf-8") + "One more line.\n", encoding="utf-8")
    prompt.write_text("# {{agent.name:agent.curio.dataflow-builder}}, edited\n", encoding="utf-8")

    assert builtin.read_page("default_preamble.md", wanted_by="the test") == preamble
    assert builtin.read_prompt_text("agent.curio.dataflow-builder@1", "instruction") == instruction
    monkeypatch.setenv("CURIO_DEV", "1")
    assert builtin.read_page("default_preamble.md", wanted_by="the test") == preamble + "One more line.\n"
    assert builtin.read_prompt_text("agent.curio.dataflow-builder@1", "instruction") == "# Dataflow Builder, edited\n"


def test_a_marker_no_field_defines_stops_the_start(tmp_path, monkeypatch):
    """A page that names a marker no field defines fails the start-up render,
    naming the page and the marker, and nothing of it is kept."""
    from utk_curio.backend.app.agents.domain import contracts

    agent_text = _fresh_loader(monkeypatch)
    root = _agents_copy(tmp_path, monkeypatch)
    page = root / BASE.name / "rules" / "research_notes_rules.md"
    page.write_text(page.read_text(encoding="utf-8") + "{{no.such.field}}\n", encoding="utf-8")
    with pytest.raises(contracts.PromptTemplateError) as refused:
        agent_text.render_at_start()
    assert "curio:rules/research_notes_rules.md" in str(refused.value)
    assert "{{no.such.field}}" in str(refused.value)
    assert agent_text.rendered() == {}


def test_a_page_includes_another_whole_and_never_itself(tmp_path, monkeypatch):
    """``{{include:<path>}}`` puts a page of the base entry in its place with
    its own markers filled and without its final line breaks, as the
    Researcher's prompts include its rules once each. A page that includes
    itself, a page the base entry does not list and a path out of it are
    refused."""
    from utk_curio.backend.app.agents.domain import builtin, contracts

    agent_text = _fresh_loader(monkeypatch)
    source = (BASE / "rules" / "research_verify_rules.md").read_text(encoding="utf-8")
    assert "{{" in source, "the rules state a fact from code; this test would not see it filled"
    rules = agent_text.render(BASE / "rules" / "research_verify_rules.md")
    assert rules.endswith("\n") and "{{" not in rules
    text = contracts.render_template("Before\n\n{{include:rules/research_verify_rules.md}}\n\nAfter\n")
    assert text == "Before\n\n" + rules.rstrip("\n") + "\n\nAfter\n"
    for prompt in ("researcher_instruction.md", "research_instruction.md"):
        written = (AGENTS / "agent.curio.researcher@1" / "prompts" / prompt).read_text(encoding="utf-8")
        assert written.count("{{include:rules/research_verify_rules.md}}") == 1, prompt
    for key in ("instruction", "research.verify"):
        read = builtin.read_prompt_text("agent.curio.researcher@1", key)
        assert read.count(rules.rstrip("\n")) == 1, key

    root = _agents_copy(tmp_path, monkeypatch)
    loop = root / BASE.name / "rules" / "research_notes_rules.md"
    loop.write_text("Notes.\n\n{{include:rules/research_notes_rules.md}}\n", encoding="utf-8")
    with pytest.raises(contracts.PromptTemplateError, match="cannot include itself"):
        agent_text.render(loop)
    for bad in ("rules/no_such_page.md", "../agent.curio.node-builder@1/prompts/node_build_instruction.md",
                "/etc/passwd.md", "rules/../default_preamble.md", "knowledge/nodes.md"):
        with pytest.raises(contracts.PromptTemplateError, match="include"):
            contracts.render_template("{{include:" + bad + "}}")


def test_a_skill_is_placed_as_its_body_and_never_in_itself(tmp_path, monkeypatch):
    """``{{skill:<name>}}`` puts the body of a skill Curio ships in its place,
    its frontmatter left out, its markers filled and without its final line
    breaks, as ``{{include:<path>}}`` puts a page. A skill that places
    itself, a name of no skill Curio ships, and a name that is no skill's
    are refused."""
    from utk_curio.backend.app.agents.domain import contracts, skills

    agent_text = _fresh_loader(monkeypatch)
    written = (SKILLS / "widgets" / "SKILL.md").read_text(encoding="utf-8")
    body = skills.parse(SKILLS / "widgets").body
    assert written.endswith(body) and written.startswith(skills.DELIMITER + "\n")
    assert "{{" in body, "the widgets skill states facts from code; this test would not see them filled"
    rendered = agent_text.render(SKILLS / "widgets" / "SKILL.md")
    assert rendered == contracts.render_template(body) and rendered.startswith("## Widgets\n")
    text = contracts.render_template("Before\n\n{{skill:widgets}}\n\nAfter\n")
    assert text == "Before\n\n" + rendered.rstrip("\n") + "\n\nAfter\n"
    preamble = (BASE / "default_preamble.md").read_text(encoding="utf-8")
    assert preamble.count("{{skill:nodes}}") == 1 and "{{include:knowledge/" not in preamble

    root = _skills_copy(tmp_path, monkeypatch)
    loop = root / "widgets" / "SKILL.md"
    loop.write_text(written.replace("## Widgets\n", "## Widgets\n\n{{skill:widgets}}\n", 1), encoding="utf-8")
    with pytest.raises(contracts.PromptTemplateError, match="cannot include itself"):
        agent_text.render(loop)
    for bad, said in (("no-such-skill", "Curio ships no skill named no-such-skill"),
                      *((name, "names no skill") for name in ("Widgets", "../widgets", "widgets/SKILL.md",
                                                              "-widgets", "wid--gets", "a" * 65))):
        with pytest.raises(contracts.PromptTemplateError, match=re.escape(said)):
            contracts.render_template("{{skill:" + bad + "}}")


def test_with_dev_a_skills_edit_shows_on_the_next_read_and_without_it_the_start_up_render_stays(
        tmp_path, monkeypatch):
    """A skill's render is kept as a page's is: under ``curio.py start --dev``
    an edit to its body shows on the next read, in the skill and in the
    preamble that places it; otherwise both stay as the start rendered them."""
    from utk_curio.backend.app.agents.domain import builtin

    agent_text = _fresh_loader(monkeypatch)
    _agents_copy(tmp_path, monkeypatch)
    root = _skills_copy(tmp_path, monkeypatch)
    agent_text.render_at_start()
    skill = root / "compatibility" / "SKILL.md"
    before = agent_text.skill_text("compatibility")
    preamble = builtin.read_page("default_preamble.md", wanted_by="the test")
    assert before and before in preamble
    skill.write_text(skill.read_text(encoding="utf-8") + "One more line.\n", encoding="utf-8")

    assert agent_text.skill_text("compatibility") == before
    assert builtin.read_page("default_preamble.md", wanted_by="the test") == preamble
    monkeypatch.setenv("CURIO_DEV", "1")
    assert agent_text.skill_text("compatibility") == before + "\nOne more line."
    assert before + "\nOne more line." in builtin.read_page("default_preamble.md", wanted_by="the test")


@pytest.mark.parametrize("change, said", [
    (("## Provenance\n", "## Provenance\n\n{{no.such.field}}\n"), "{{no.such.field}}"),
    (("name: provenance\n", "name: history\n"), "is not its folder's name"),
    (("license: MIT\n", "license: MIT\nauthor: curio\n"), "which the format does not define"),
])
def test_a_skill_that_breaks_a_rule_stops_the_start(tmp_path, monkeypatch, change, said):
    """A skill whose body names a marker no field defines, or whose
    frontmatter breaks the format's rules, fails the start-up render, naming
    the skill's file and the problem, and nothing of the start is kept."""
    from utk_curio.backend.app.agents.domain import contracts

    agent_text = _fresh_loader(monkeypatch)
    _agents_copy(tmp_path, monkeypatch)
    root = _skills_copy(tmp_path, monkeypatch)
    skill = root / "provenance" / "SKILL.md"
    old, new = change
    written = skill.read_text(encoding="utf-8")
    assert old in written
    skill.write_text(written.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(contracts.PromptTemplateError) as refused:
        agent_text.render_at_start()
    assert "skills/provenance/SKILL.md" in str(refused.value) and said in str(refused.value)
    assert agent_text.rendered() == {}


def test_a_curio_path_names_any_page_of_the_base_entry_and_nothing_outside_it(tmp_path, monkeypatch, caplog):
    """``curio:<path>`` names any page the base entry lists, its rules
    included, and reads it as Curio renders it. A path that climbs out, an
    absolute path, a file the base entry does not list, and a link that leads
    out of it though its manifest lists it are refused."""
    from utk_curio.backend.app.agents.domain import agent_text, builtin
    from utk_curio.backend.app.agents.domain.manifest import AgentManifestError, parse_agent_manifest

    listed = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))["pages"]
    assert {"default_preamble.md", "examples.md", "rules/research_verify_rules.md"} <= set(listed)
    for page in listed:
        system = parse_agent_manifest(_user_manifest(f"curio:{page}")).prompts["system"]
        assert (system.shared, system.file) == (page, f"prompts/{page}")
        assert builtin.read_page(page, wanted_by="the test") == agent_text.render(BASE / page), page
    for bad in (
        "curio:../agent.curio.node-builder@1/prompts/node_build_instruction.md",
        "curio:rules/../../agent.curio.node-builder@1/prompts/node_build_instruction.md",
        "curio:/etc/passwd",
        "curio:rules\\research_verify_rules.md",
        "curio:./default_preamble.md",
        "curio:manifest.json",
        "curio:README.md",
        "curio:rules",
        "curio:",
        "curio:knowledge/nodes.md",
        "curio:knowledge/node-functions.md",
    ):
        with pytest.raises(AgentManifestError, match="curio"):
            parse_agent_manifest(_user_manifest(bad))

    outside = tmp_path / "secret.md"
    outside.write_text("Not agent text.\n", encoding="utf-8")
    copy = tmp_path / BASE.name
    shutil.copytree(BASE, copy)
    (copy / "rules" / "escape.md").symlink_to(outside)
    raw = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    raw["pages"].append("rules/escape.md")
    (copy / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(agent_text, "base_dir", lambda: copy)
    with pytest.raises(AgentManifestError, match="leads out"):
        parse_agent_manifest(_user_manifest("curio:rules/escape.md"))
    with caplog.at_level("ERROR"):
        assert builtin.read_page("rules/escape.md", wanted_by="the test") is None
    assert any("leads out" in record.getMessage() for record in caplog.records)
    _fresh_loader(monkeypatch)
    with pytest.raises(agent_text.AgentTextError, match="leads out"):
        agent_text.render_at_start()


def test_the_base_entry_is_no_agent_and_no_list_shows_it(tmp_curio):
    """The base entry sits in ``agents/`` beside the agents, its manifest of
    kind base, with its README, and it is no agent: the roster, the catalog
    listing, the palette's imports, the LLM choice, the delegation paragraph
    and delegate resolution never name it, and it can be neither imported nor
    uploaded as an agent."""
    from utk_curio.backend.app.agents.application import catalog, delegation, lifecycle, upload_import
    from utk_curio.backend.app.agents.application.errors import AgentServiceError
    from utk_curio.backend.app.agents.domain import builtin, content
    from utk_curio.backend.app.agents.domain.manifest import AgentManifestError, parse_agent_manifest

    raw = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))
    assert (raw["id"], raw["kind"]) == (BASE_ID, "base")
    assert (BASE / "README.md").is_file()
    name, coord = raw["name"], BASE.name

    roster = builtin.list_builtin_manifests()
    assert len(roster) == 7 and BASE_ID not in {m.agent_id for m in roster}
    assert builtin.get_builtin_manifest(coord) is None
    assert builtin.builtin_coord(BASE_ID) is None
    assert builtin.manifest_dict(coord) is None
    assert BASE_ID not in builtin.internal_agent_ids()

    with pytest.raises(AgentServiceError):
        lifecycle.import_agent(UKEY, coord)
    for m in roster:
        if m.catalog.listed:
            lifecycle.import_agent(UKEY, m.dir_name)
    for listing in (catalog.list_global_catalog(UKEY), catalog.list_my_imports(UKEY), catalog.choosable_agents(UKEY)):
        shown = json.dumps(listing)
        assert listing and BASE_ID not in shown and name not in shown

    assert delegation.find_visible(UKEY, BASE_ID) == (None, None)
    capabilities = sorted({c for m in roster for c in m.capability_ids})
    for m in roster:
        entries = delegation.visible_capability_entries(UKEY, m)
        paragraph = content.delegation_instruction(entries) if entries else ""
        assert BASE_ID not in paragraph and name not in paragraph, m.agent_id
        for capability in capabilities:
            for installed in (set(), {coord}):
                found = delegation.resolve_among(UKEY, installed, m, capability)
                assert found.coord != coord, (m.agent_id, capability)

    with pytest.raises(AgentManifestError, match="kind"):
        parse_agent_manifest(raw)
    upload = _user_manifest("curio:default_preamble.md", kind="base")
    with pytest.raises(AgentServiceError) as refused:
        upload_import.upload_import(UKEY, upload, {"prompts/instruction.md": "Explain the node."})
    assert refused.value.status == 400 and "kind" in str(refused.value)


def test_a_users_agent_reads_its_own_text_as_written(tmp_curio, monkeypatch):
    """Markers are filled only in the text Curio ships: a user's agent whose
    prompt holds ``{{`` runs that prompt as written, beside the preamble it
    names as Curio's, rendered. Nothing in a user's store stops the backend
    starting. Main behaves the same; this keeps it so."""
    from utk_curio.backend.app import create_app
    from utk_curio.backend.app.agents.application import upload_import
    from utk_curio.backend.app.agents.application.turns import prompts
    from utk_curio.backend.app.agents.domain import builtin
    from utk_curio.backend.app.agents.repositories import storage
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    text = 'Fill {{name}} and {{agent.name:agent.curio.node-builder}} as written: {"a": {{1}}}.\n'
    coord = upload_import.upload_import(
        UKEY, _user_manifest("curio:default_preamble.md"), {"prompts/instruction.md": text},
    )["dirName"]
    assert prompts._resolve_instruction_text(UKEY, coord) == text
    preamble = builtin.read_prompt_text("agent.curio.node-builder@1", "system")
    assert preamble and "{{" not in preamble
    assert prompts._resolve_prompt_text(UKEY, coord, "system") == preamble

    broken = storage.agent_definition_dir(UKEY, "agent.test.broken@1")
    (broken / "prompts").mkdir(parents=True)
    (broken / "manifest.json").write_text("{ not json", encoding="utf-8")
    (broken / "prompts" / "instruction.md").write_text("{{no.such.field}}\n", encoding="utf-8")
    _fresh_loader(monkeypatch)
    create_app(TestConfig)
    assert prompts._resolve_instruction_text(UKEY, coord) == text
    assert prompts._resolve_prompt_text(UKEY, coord, "system") == preamble
