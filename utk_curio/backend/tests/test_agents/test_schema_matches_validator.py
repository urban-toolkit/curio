"""The published schema and the import validator have to agree.

`docs/schemas/agent-package.v1.json` is what an agent author writes against, and
`agents/manifest.py` is what decides whether their upload is accepted. Where the
two disagree, the schema is the one people trust and the validator is the one
that answers, so a manifest can validate green locally and 400 at import with no
explanation.

Three ways they had drifted:

- `requiresAgents` was parsed and constrained by the validator (each entry must
  also be in `delegatesTo`) and absent from the schema entirely.
- `tools[].id` was `{type: string, minLength: 1}` in the schema and a dotted
  capability grammar in the validator, so a plain `"web"` passed the schema and
  was refused at import.
- The prompt `path` pattern allowed `/etc/passwd` and `../x` while its own
  description said it must not, because the rule lived in the prose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.manifest import CAPABILITY_ID_RE

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[4] / "docs/schemas/agent-package.v1.json")
    .read_text(encoding="utf-8")
)
PROPS = SCHEMA["properties"]


class TestRequiresAgents:
    def test_the_schema_declares_it(self):
        assert "requiresAgents" in PROPS, (
            "the validator parses requiresAgents; an author reading the schema "
            "has no way to learn the field exists"
        )

    def test_the_subset_rule_is_written_down(self):
        text = PROPS["requiresAgents"]["description"].lower()
        assert "delegatesto" in text, (
            "the validator refuses an entry that is not also in delegatesTo, "
            "which is the rule an author is most likely to trip"
        )


class TestToolIds:
    def test_the_schema_uses_the_validator_grammar(self):
        pattern = PROPS["tools"]["items"]["properties"]["id"].get("pattern")
        assert pattern == CAPABILITY_ID_RE.pattern

    @pytest.mark.parametrize("bad", ["web", "Web.Search", "web_search", "web."])
    def test_ids_the_validator_refuses_fail_the_schema_pattern(self, bad):
        import re

        assert not re.match(PROPS["tools"]["items"]["properties"]["id"]["pattern"], bad)
        assert not CAPABILITY_ID_RE.match(bad)

    @pytest.mark.parametrize("good", ["web.search", "node.content.write"])
    def test_real_tool_ids_pass_both(self, good):
        import re

        assert re.match(PROPS["tools"]["items"]["properties"]["id"]["pattern"], good)
        assert CAPABILITY_ID_RE.match(good)


class TestPromptPaths:
    def _pattern(self) -> str:
        prompts = PROPS["prompts"]
        entry = prompts.get("additionalProperties") or prompts.get("properties")
        if "properties" in entry:
            return entry["properties"]["path"]["pattern"]
        for value in entry.values():
            if isinstance(value, dict) and "properties" in value:
                return value["properties"]["path"]["pattern"]
        raise AssertionError("no prompt path pattern in the schema")

    @pytest.mark.parametrize("bad", ["/etc/passwd", "-rf", "/abs.txt"])
    def test_escapes_the_validator_refuses_fail_the_pattern(self, bad):
        import re

        assert not re.match(self._pattern(), bad)

    def test_the_upload_path_convention_is_documented(self):
        prompts = PROPS["prompts"]
        entry = prompts.get("additionalProperties") or prompts.get("properties")
        blob = json.dumps(entry).lower()
        assert "prompts/" in blob, (
            "the only import UI writes every prompt as prompts/<name>.txt, so a "
            "manifest naming anything else cannot be imported through it"
        )


class TestReservedFields:
    @pytest.mark.parametrize("name", ["contracts", "configuration"])
    def test_fields_the_validator_ignores_say_so(self, name):
        assert "reserved" in PROPS[name]["description"].lower(), (
            f"{name} is in the schema but never read by parse_agent_manifest; "
            "saying so stops an author from relying on it"
        )
