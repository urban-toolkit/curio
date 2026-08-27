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

from utk_curio.backend.app.agents import builtin

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestPromptFilesResolve:
    @pytest.mark.parametrize("spec", builtin.BUILTIN_AGENTS, ids=lambda s: s.agent_id)
    def test_every_declared_prompt_file_exists(self, spec):
        for filename in (spec.prompt_file, spec.preamble_file):
            assert (builtin.PROMPT_SOURCE_DIR / filename).is_file(), (
                f"{spec.agent_id} names {filename!r}, which is not in "
                f"{builtin.PROMPT_SOURCE_DIR}"
            )

    @pytest.mark.parametrize("spec", builtin.BUILTIN_AGENTS, ids=lambda s: s.agent_id)
    def test_every_agent_materializes_with_prompt_bytes(self, spec):
        coord = f"{spec.agent_id}@{builtin.BUILTIN_VERSION}"
        for name in ("instruction", "system"):
            text = builtin.read_prompt_text(coord, name)
            assert text, f"{coord} resolved no {name} prompt"


class TestPromptsArePackaged:
    """The declarations that carry ``llm-prompts/`` into a built distribution.

    Asserted against the packaging config rather than by building an sdist,
    which keeps this in the unit suite. The plan's end-to-end check (build an
    sdist and a wheel, confirm the .txt files are inside both) stays a manual
    release step.
    """

    def test_manifest_in_includes_the_prompts(self):
        manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        assert re.search(
            r"^recursive-include\s+utk_curio/llm-prompts\s", manifest, re.MULTILINE
        ), "MANIFEST.in must carry utk_curio/llm-prompts into the sdist"

    def test_pyproject_ships_them_in_the_wheel(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "llm-prompts/*.txt" in pyproject, (
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
