"""Every shipped agent's prompt files exist and are packaged.

The agents Curio ships read their prompts from files: each agent's own in its
folder, ``agents/<id>@<major>/prompts/``, and the preamble they share from
``utk_curio/llm-prompts/``. ``read_prompt_text`` returns ``None`` for a
missing file, so a rename or a packaging gap costs an agent its entire system
and task prompt with no symptom except worse answers and a logged error.

That is not hypothetical: ``llm-prompts`` is not a Python package (the hyphen
makes it unimportable, so ``packages.find`` cannot see it) and was absent from
``MANIFEST.in``, which meant an sdist or wheel shipped all 21 agents promptless
while the repo checkout worked perfectly.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.tests._support.prompt_files import prompt_files, prompt_path

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestPromptFilesResolve:
    @pytest.mark.parametrize("m", builtin.list_builtin_manifests(), ids=lambda m: m.agent_id)
    def test_every_declared_prompt_file_exists(self, m):
        for asset in m.prompts.values():
            path = (
                builtin.PROMPT_SOURCE_DIR / asset.shared if asset.shared
                else builtin.agents_dir() / m.dir_name / asset.path
            )
            assert path.is_file(), f"{m.agent_id} names {asset.path!r}, which is not at {path}"

    @pytest.mark.parametrize("m", builtin.list_builtin_manifests(), ids=lambda m: m.agent_id)
    def test_every_agent_materializes_with_prompt_bytes(self, m):
        coord = m.dir_name
        for name in m.prompts:
            text = builtin.read_prompt_text(coord, name)
            assert text, f"{coord} resolved no {name} prompt"


#: Which instruction a call of each card that took other agents over reads:
#: a chat message carries no capability and reads the chat prompt, and a
#: delegated call reads its capability's mode, else the chat prompt. Every
#: call composes the shared preamble with exactly one of these.
PROMPT_TABLE = {
    "agent.curio.node-builder": {
        None: "node_build_instruction.md",
        "node.build": "node_build_instruction.md",
        "dataset.fetch.author": "node_build_instruction.md",
        "node.content.generate": "new_content_prompt.md",
        "package.recommend": "package_recommendation_instruction.md",
        "package.build": "package_build_instruction.md",
        "package.extend": "package_build_instruction.md",
        "node.kind.author": "package_build_instruction.md",
    },
    "agent.curio.researcher": {
        None: "researcher_instruction.md",
        "research.notes.compose": "researcher_notes_instruction.md",
        "research.verify": "research_instruction.md",
    },
}

#: Any account key: nothing is installed, so every read is the roster's.
_KEY = "5151"


def _file(filename: str) -> str:
    return prompt_path(filename).read_text(encoding="utf-8")


class TestWhichPromptRuns:
    """The table in code, read the way a run reads it (``turns/prompts``)."""

    @pytest.mark.parametrize("agent_id", sorted(PROMPT_TABLE))
    def test_a_chat_and_each_capability_read_the_prompt_the_table_names(self, agent_id, tmp_curio):
        from utk_curio.backend.app.agents.application.turns import prompts

        coord = builtin.builtin_coord(agent_id)
        m = builtin.get_builtin_manifest(coord)
        assert set(PROMPT_TABLE[agent_id]) - {None} == set(m.capability_ids)
        for capability, filename in PROMPT_TABLE[agent_id].items():
            text = prompts._resolve_instruction_text(_KEY, coord, capability=capability)
            assert text == _file(filename), (agent_id, capability, filename)
        assert prompts._resolve_prompt_text(_KEY, coord, "system") == _file(builtin.PREAMBLE_FILE)

    def test_content_on_an_autark_node_reads_the_autark_prompt(self, tmp_curio):
        from utk_curio.backend.app.agents.application import reply_schemas
        from utk_curio.backend.app.agents.application.turns import prompts

        coord = builtin.builtin_coord("agent.curio.node-builder")
        text = prompts._resolve_prompt_text(_KEY, coord, reply_schemas.AUTK_PROMPT_KEY)
        assert text == _file("new_content_autk_prompt.md")
        # Only the Node Builder writes node content, so only it has one.
        holders = {m.agent_id for m in builtin.list_builtin_manifests()
                   if reply_schemas.AUTK_PROMPT_KEY in m.prompts}
        assert holders == {"agent.curio.node-builder"}


class TestTheResearchersCheckingRules:
    def test_they_are_written_once_and_ride_both_researcher_prompts(self):
        from utk_curio.backend.app.agents.domain import contracts
        from utk_curio.backend.app.common.egress_policy import MAX_CALLS_PER_RUN

        stem = contracts.RESEARCH_VERIFY_RULES
        fragment = builtin.PROMPT_SOURCE_DIR / f"{stem}.template.md"
        lines = [line for line in fragment.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 4, "verify first, a failure is a finding, the labels, the budget"
        # One template holds them: no other template repeats a line of them,
        # and each Researcher template includes them by their field, once.
        for path in sorted(builtin.PROMPT_SOURCE_DIR.glob("*.template.md")):
            if path != fragment:
                text = path.read_text(encoding="utf-8")
                assert not [line for line in lines if line in text], path.name
        for template in ("research_instruction", "researcher_instruction"):
            text = (builtin.PROMPT_SOURCE_DIR / f"{template}.template.md").read_text(encoding="utf-8")
            assert text.count("{{research.verify_rules}}") == 1, template
        # Both rendered prompts carry them whole: the chat and the mode.
        rules = contracts.render_prompt(stem).rstrip("\n")
        coord = builtin.builtin_coord("agent.curio.researcher")
        chat = builtin.read_prompt_text(coord, "instruction")
        mode = builtin.read_prompt_text(coord, "research.verify")
        assert chat and chat.count(rules) == 1
        assert mode and mode.count(rules) == 1
        low = rules.lower()
        assert "verify before you assert" in low
        assert "report failure to verify as a finding" in low
        for label in ("VERIFIED", "REPORTED", "UNVERIFIED"):
            assert label in rules
        assert f"at most {MAX_CALLS_PER_RUN} web calls per run" in rules
        # Findings first, one per line, stays in the mode: the chat answers
        # in prose.
        assert "findings first, one per line" in mode.lower()
        assert "findings first, one per line" not in chat.lower()
        # The notes mode checks nothing, so it carries none of them.
        notes = builtin.read_prompt_text(coord, "research.notes.compose")
        assert notes and rules not in notes


class TestTheResearchersNotesRules:
    def test_they_are_written_once_and_ride_both_notes_prompts(self):
        """The notes format, written once: the chat that answers a web
        question with notes and the mode that composes notes from search
        results include the same fragment, ``{{research.notes_rules}}``."""
        from utk_curio.backend.app.agents.domain import contracts

        stem = contracts.RESEARCH_NOTES_RULES
        fragment = builtin.PROMPT_SOURCE_DIR / f"{stem}.template.md"
        lines = [line for line in fragment.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 5, (
            "the pattern, the question note, the answer notes, the markdown, one note per finding"
        )
        # One template holds them: no other template repeats a line of them,
        # and each notes template includes them by their field, once.
        for path in sorted(builtin.PROMPT_SOURCE_DIR.glob("*.template.md")):
            if path != fragment:
                text = path.read_text(encoding="utf-8")
                assert not [line for line in lines if line in text], path.name
        for template in ("researcher_instruction", "researcher_notes_instruction"):
            text = (builtin.PROMPT_SOURCE_DIR / f"{template}.template.md").read_text(encoding="utf-8")
            assert text.count("{{research.notes_rules}}") == 1, template
        # Both rendered prompts carry them whole.
        rules = contracts.render_prompt(stem).rstrip("\n")
        coord = builtin.builtin_coord("agent.curio.researcher")
        chat = builtin.read_prompt_text(coord, "instruction")
        mode = builtin.read_prompt_text(coord, "research.notes.compose")
        assert chat and chat.count(rules) == 1
        assert mode and mode.count(rules) == 1
        low = rules.lower()
        assert "yellow note carrying the user's question verbatim" in low
        assert "one green note per answer" in low
        assert "as clean markdown" in low
        assert "one note per finding" in low
        assert "never invent facts" in low


class TestTheRecommendationMode:
    def test_it_asks_for_no_tool(self):
        """It runs only as a delegate, with no tools: it names no tool a run
        could call and shows no request syntax, and says to reply in text."""
        import re

        from utk_curio.backend.app.agents.application.tools import REGISTRY

        text = builtin.read_prompt_text(builtin.builtin_coord("agent.curio.node-builder"), "package.recommend")
        assert text, "the Node Builder has no package.recommend prompt"
        named = sorted(t for t in REGISTRY if re.search(rf"(?<![\w.]){re.escape(t)}(?![\w])", text))
        assert named == []
        for syntax in ("toolRequest", "delegateRequest", "curio.v1", "```"):
            assert syntax not in text, syntax
        assert "never with a tool request" in text
        assert '"existingPackages"' in text


class TestTheJsonModes:
    @pytest.mark.parametrize("agent_id, capability", [
        ("agent.curio.node-builder", "package.build"),
        ("agent.curio.researcher", "research.notes.compose"),
    ])
    def test_a_mode_that_answers_in_json_asks_for_no_tool(self, agent_id, capability):
        """Each runs only as a delegate, with no tools, and answers in one
        JSON object the runtime turns into reviewed proposals: it names no
        tool a run could call and shows no request syntax."""
        import re

        from utk_curio.backend.app.agents.application.tools import REGISTRY

        text = builtin.read_prompt_text(builtin.builtin_coord(agent_id), capability)
        assert text, (agent_id, capability)
        named = sorted(t for t in REGISTRY if re.search(rf"(?<![\w.]){re.escape(t)}(?![\w])", text))
        assert named == [], (agent_id, capability)
        for syntax in ("toolRequest", "delegateRequest", "curio.v1"):
            assert syntax not in text, (agent_id, capability, syntax)
        assert "EXACTLY ONE JSON object" in text


class TestUserOwnedValuesStayOutOfPrompts:
    """A value the user owns is a catalog setting, rendered into the run that
    reads it. A copy in a prompt file would be a second source that edits in
    the Agent Catalog never reach."""

    def test_no_prompt_file_carries_a_keyword_type(self):
        from utk_curio.backend.app.agents.domain import contracts

        lines = set(contracts.KEYWORD_TYPES.render(contracts.KEYWORD_TYPES.default).splitlines())
        for path in prompt_files("*.md"):
            found = lines & set(path.read_text(encoding="utf-8").splitlines())
            assert not found, f"{path.name} carries keyword types: {sorted(found)[:2]}"


class TestPromptsArePackaged:
    """The declarations that carry ``llm-prompts/`` into a built distribution.

    Asserted against the packaging config rather than by building an sdist,
    which keeps this in the unit suite. The plan's end-to-end check (build an
    sdist and a wheel, confirm the .md files are inside both) stays a manual
    release step.
    """

    def test_manifest_in_includes_the_prompts(self):
        manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        assert re.search(
            r"^recursive-include\s+utk_curio/llm-prompts\s+\*\.md\s*$", manifest, re.MULTILINE
        ), "MANIFEST.in must carry utk_curio/llm-prompts into the sdist"

    def test_pyproject_ships_them_in_the_wheel(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "llm-prompts/*.md" in pyproject, (
            "pyproject must declare llm-prompts as package-data, or the wheel "
            "ships without it even when the sdist has it"
        )


class TestMissingPromptIsLoud:
    def test_a_missing_file_is_logged_rather_than_silently_none(self, caplog, monkeypatch, tmp_path):
        coord = builtin.list_builtin_manifests()[0].dir_name
        # The preamble every agent shares, from llm-prompts/.
        monkeypatch.setattr(builtin, "PROMPT_SOURCE_DIR", Path("/nonexistent-prompts"))

        with caplog.at_level("ERROR"):
            assert builtin.read_prompt_text(coord, "system") is None

        assert any("llm-prompts" in r.getMessage() for r in caplog.records), (
            "a missing prompt file must say so; silence is how this shipped"
        )
        # The agent's own instruction, from its folder in agents/.
        caplog.clear()
        shutil.copytree(builtin.agents_dir(), tmp_path / "agents", ignore=shutil.ignore_patterns("*.md"))
        monkeypatch.setattr(builtin, "agents_dir", lambda: tmp_path / "agents")

        with caplog.at_level("ERROR"):
            assert builtin.read_prompt_text(coord, "instruction") is None

        assert any("agents/" in r.getMessage() for r in caplog.records), (
            "a missing prompt file must say so; silence is how this shipped"
        )
