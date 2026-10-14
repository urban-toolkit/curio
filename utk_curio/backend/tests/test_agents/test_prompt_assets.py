"""Every roster agent's prompt files exist and are packaged.

The built-in agents carry no prompt text of their own: ``builtin.py`` names a
file under ``utk_curio/llm-prompts/`` and reads the bytes at materialization
time. ``read_prompt_text`` returns ``None`` for a missing file, so a rename or a
packaging gap costs an agent its entire system and task prompt with no error,
no traceback, and no symptom except worse answers.

That is not hypothetical: ``llm-prompts`` is not a Python package (the hyphen
makes it unimportable, so ``packages.find`` cannot see it) and was absent from
``MANIFEST.in``, which meant an sdist or wheel shipped all 21 agents promptless
while the repo checkout worked perfectly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.domain import builtin

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestPromptFilesResolve:
    @pytest.mark.parametrize("spec", builtin.BUILTIN_AGENTS, ids=lambda s: s.agent_id)
    def test_every_declared_prompt_file_exists(self, spec):
        for filename in spec.prompt_files().values():
            assert (builtin.PROMPT_SOURCE_DIR / filename).is_file(), (
                f"{spec.agent_id} names {filename!r}, which is not in "
                f"{builtin.PROMPT_SOURCE_DIR}"
            )

    @pytest.mark.parametrize("spec", builtin.BUILTIN_AGENTS, ids=lambda s: s.agent_id)
    def test_every_agent_materializes_with_prompt_bytes(self, spec):
        coord = f"{spec.agent_id}@{builtin.BUILTIN_VERSION}"
        for name in spec.prompt_files():
            text = builtin.read_prompt_text(coord, name)
            assert text, f"{coord} resolved no {name} prompt"


#: Which instruction a call of each card that took another agent over reads:
#: a chat message carries no capability and reads the chat prompt, and a
#: delegated call reads its capability's mode, else the chat prompt. Every
#: call composes the shared preamble with exactly one of these.
PROMPT_TABLE = {
    "agent.node-builder": {
        None: "node_build_instruction.md",
        "node.build": "node_build_instruction.md",
        "dataset.fetch.author": "node_build_instruction.md",
        "node.content.generate": "new_content_prompt.md",
    },
    "agent.researcher": {
        None: "researcher_notes_instruction.md",
        "research.notes.compose": "researcher_notes_instruction.md",
        "research.verify": "research_instruction.md",
    },
    "agent.package-builder": {
        None: "package_build_instruction.md",
        "package.build": "package_build_instruction.md",
        "package.extend": "package_build_instruction.md",
        "node.kind.author": "package_build_instruction.md",
        "package.recommend": "package_recommendation_instruction.md",
    },
}

#: Any account key: nothing is installed, so every read is the roster's.
_KEY = "5151"


def _file(filename: str) -> str:
    return (builtin.PROMPT_SOURCE_DIR / filename).read_text(encoding="utf-8")


class TestWhichPromptRuns:
    """The table in code, read the way a run reads it (``turns/prompts``)."""

    @pytest.mark.parametrize("agent_id", sorted(PROMPT_TABLE))
    def test_a_chat_and_each_capability_read_the_prompt_the_table_names(self, agent_id, tmp_curio):
        from utk_curio.backend.app.agents.application.turns import prompts

        coord = f"{agent_id}@{builtin.BUILTIN_VERSION}"
        spec = builtin.get_builtin_spec(coord)
        assert set(PROMPT_TABLE[agent_id]) - {None} == set(spec.capabilities)
        for capability, filename in PROMPT_TABLE[agent_id].items():
            text = prompts._resolve_instruction_text(_KEY, coord, capability=capability)
            assert text == _file(filename), (agent_id, capability, filename)
        assert prompts._resolve_prompt_text(_KEY, coord, "system") == _file(builtin.PREAMBLE_FILE)

    def test_content_on_an_autark_node_reads_the_autark_prompt(self, tmp_curio):
        from utk_curio.backend.app.agents.application import reply_schemas
        from utk_curio.backend.app.agents.application.turns import prompts

        coord = f"agent.node-builder@{builtin.BUILTIN_VERSION}"
        text = prompts._resolve_prompt_text(_KEY, coord, reply_schemas.AUTK_PROMPT_KEY)
        assert text == _file("new_content_autk_prompt.md")
        # Only the Node Builder writes node content, so only it has one.
        holders = {s.agent_id for s in builtin.BUILTIN_AGENTS
                   if reply_schemas.AUTK_PROMPT_KEY in s.prompt_files()}
        assert holders == {"agent.node-builder"}


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
        for template in ("research_instruction", "researcher_notes_instruction"):
            text = (builtin.PROMPT_SOURCE_DIR / f"{template}.template.md").read_text(encoding="utf-8")
            assert text.count("{{research.verify_rules}}") == 1, template
        # Both rendered prompts carry them whole: the chat and the mode.
        rules = contracts.render_prompt(stem).rstrip("\n")
        coord = f"agent.researcher@{builtin.BUILTIN_VERSION}"
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


class TestTheRecommendationMode:
    def test_it_asks_for_no_tool(self):
        """It runs only as a delegate, with no tools: it names no tool a run
        could call and shows no request syntax, and says to reply in text."""
        import re

        from utk_curio.backend.app.agents.application.tools import REGISTRY

        text = builtin.read_prompt_text(f"agent.package-builder@{builtin.BUILTIN_VERSION}", "package.recommend")
        assert text, "the Package Builder has no package.recommend prompt"
        named = sorted(t for t in REGISTRY if re.search(rf"(?<![\w.]){re.escape(t)}(?![\w])", text))
        assert named == []
        for syntax in ("toolRequest", "delegateRequest", "curio.v1", "```"):
            assert syntax not in text, syntax
        assert "never with a tool request" in text
        assert '"existingPackages"' in text


class TestUserOwnedValuesStayOutOfPrompts:
    """A value the user owns is a catalog setting, rendered into the run that
    reads it. A copy in a prompt file would be a second source that edits in
    the Agent Catalog never reach."""

    def test_no_prompt_file_carries_a_keyword_type(self):
        from utk_curio.backend.app.agents.domain import contracts

        lines = set(contracts.KEYWORD_TYPES.render(contracts.KEYWORD_TYPES.default).splitlines())
        for path in sorted(builtin.PROMPT_SOURCE_DIR.glob("*.md")):
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
    def test_a_missing_file_is_logged_rather_than_silently_none(self, caplog, monkeypatch):
        monkeypatch.setattr(builtin, "PROMPT_SOURCE_DIR", Path("/nonexistent-prompts"))
        coord = f"{builtin.BUILTIN_AGENTS[0].agent_id}@{builtin.BUILTIN_VERSION}"

        with caplog.at_level("ERROR"):
            assert builtin.read_prompt_text(coord, "instruction") is None

        assert any("llm-prompts" in r.getMessage() for r in caplog.records), (
            "a missing prompt file must say so; silence is how this shipped"
        )
