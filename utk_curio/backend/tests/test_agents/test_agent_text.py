"""Everything an agent reads lives in agents/, and the backend renders it when it starts.

The base entry, ``agents/agent.curio.builtin@1`` (its manifest says ``kind:
base``), holds the pages every agent Curio ships reads, and each agent's
folder holds its own prompts. Each is a hand-written source whose markers the
backend fills when it starts (``agent_text``). Nothing is generated or
committed, and ``utk_curio/`` holds none of it. An agent names a page as
``curio:<path>``, and no such path leads out of the base entry. The base
entry is no agent: no roster, catalog, palette or delegation lists it.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS = REPO_ROOT / "agents"
#: The base entry: the pages every agent Curio ships reads.
BASE = AGENTS / "agent.curio.builtin@1"
BASE_ID = "agent.curio.builtin"
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


def test_no_prompt_is_generated():
    """The generator writes the frontend's TypeScript and no prompt, no prompt
    has a template beside it, and a prompt that states a fact from code holds
    the fact's marker, which an agent never reads."""
    from utk_curio.backend.app.agents.domain import builtin, contracts

    written = sorted(contracts.GENERATED_OUTPUTS)
    assert written, "the generator writes nothing; this test would be vacuous"
    prompts = [path for path in written if not path.startswith("utk_curio/frontend/urban-workflows/src/generated/")]
    assert not prompts, f"the generator writes prompts: {prompts}"
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
    """Starting the backend renders each page the base entry lists and each
    prompt each agent names, once: every file in ``agents/`` but the base
    entry's README, no marker left in any. A run reads those renders and no
    file, and each is its source rendered."""
    from utk_curio.backend.app import create_app
    from utk_curio.backend.app.agents.domain import builtin
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    agent_text = _fresh_loader(monkeypatch)
    create_app(TestConfig)
    rendered = agent_text.rendered()
    on_disk = sorted(path.resolve() for path in AGENTS.rglob("*.md") if path != BASE / "README.md")
    assert sorted(path.resolve() for path in rendered) == on_disk
    for file, text in rendered.items():
        assert text and "{{" not in text, file
        assert text == agent_text.render(file), file
    reads = []
    monkeypatch.setattr(agent_text, "_source", lambda file: reads.append(file) or "")
    for m in builtin.list_builtin_manifests():
        for key in m.prompts:
            assert builtin.read_prompt_text(m.dir_name, key) in rendered.values(), (m.dir_name, key)
    assert reads == [], f"a run read {reads} again"


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
                "/etc/passwd.md", "rules/../default_preamble.md"):
        with pytest.raises(contracts.PromptTemplateError, match="include"):
            contracts.render_template("{{include:" + bad + "}}")


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
