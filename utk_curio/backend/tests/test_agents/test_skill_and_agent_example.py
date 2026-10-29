"""The worked example of "Add skills and agents": a user's skill and agent, imported as a user imports them.

``docs/examples/skills/street-trees/`` is a skill in the Agent Skills format,
its ``SKILL.md`` and one file, ``references/species.md``, and
``docs/examples/agents/agent.you.tree-counter@1/`` an agent whose manifest
names it (AGENT-CATALOG, "Add skills and agents"). The skill goes through
**Import skill**'s review and import as a picked folder sends it
(``/api/agents/skills/imports/check`` and ``/api/agents/skills/imports``),
given to no agent, and the agent through **Import agent**
(``/api/agents/imports/upload``), its manifest and prompt files put together
as the Agent Catalog's import modal puts them (``buildUploadPayload.ts``: each
prompt file is ``prompts/<its name>``). Then the agent holds the skill by its
manifest alone, a chat of it on the canvas lists the skill in its catalog, and
a scripted chat that calls skill.read gets the skill's text, wrapped as
``<skill_content name="street-trees">``, then its species file. Runs go
through the scripted provider (``testing_provider``).

``skills-ref`` is imported inside the test that uses it, as
``test_skills_ref.py`` imports it, so a missing library fails the test, never
skips it. The example's files are read inside each test, so a checkout
without them fails each test at its first assertion.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from utk_curio.backend.app.agents.domain import skills
from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.tests.test_agents.test_agent_skills import (  # noqa: F401 - scripted is a fixture
    _attach,
    _listed,
    _project,
    _run,
    _run_calls,
    _tail,
    _turns,
    _wrapped,
    scripted,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLES = REPO_ROOT / "docs" / "examples"
SKILL = EXAMPLES / "skills" / "street-trees"
AGENT = EXAMPLES / "agents" / "agent.you.tree-counter@1"
NAME = "street-trees"
SPECIES = "references/species.md"
CHECK = "/api/agents/skills/imports/check"
IMPORT = "/api/agents/skills/imports"
UPLOAD = "/api/agents/imports/upload"
#: The skills the default preamble places, which every call of the agent holds.
CORE = ["compatibility", "node-control", "nodes"]
#: The prompt files the Agent Catalog's import modal takes beside a manifest.
PROMPT_SUFFIXES = (".md", ".txt")


def _example(folder: Path) -> Path:
    assert folder.is_dir(), f"the worked example has no {folder.relative_to(REPO_ROOT)}"
    return folder


def _files(folder: Path) -> dict[str, bytes]:
    """Every file of *folder* but hidden ones, by its path there."""
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(folder).parts)
    }


def _skill_form(**fields) -> dict:
    """The skill's folder as Import skill sends a picked folder: each file
    under the folder's name, with the form's other *fields*."""
    files = _files(_example(SKILL))
    paths = [f"{SKILL.name}/{path}" for path in files]
    form = {
        "files": [(io.BytesIO(data), path.rsplit("/", 1)[-1]) for path, data in zip(paths, files.values())],
        "paths": json.dumps(paths),
    }
    form.update({key: json.dumps(value) for key, value in fields.items()})
    return form


def _post_form(client, headers, url: str, form: dict):
    return client.post(url, data=form, content_type="multipart/form-data", headers=headers)


def _agent_upload() -> dict:
    """The agent's folder as Import agent sends it: its ``manifest.json``,
    and each file of its ``prompts/`` as ``prompts/<its name>``."""
    folder = _example(AGENT)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    prompts = {f"prompts/{path.name}": path.read_text(encoding="utf-8")
               for path in sorted((folder / "prompts").iterdir()) if path.is_file()}
    assert prompts and all(name.endswith(PROMPT_SUFFIXES) for name in prompts), prompts
    return {"manifest": manifest, "prompts": prompts}


def _body(text: str) -> str:
    """A ``SKILL.md``'s body as an agent reads it: the text after the line
    that closes its frontmatter, without the line breaks around it."""
    assert text.startswith("---\n"), text[:40]
    return text.split("\n---\n", 1)[1].strip("\n")


def _read(**params) -> str:
    return _tail({"toolRequest": {"tool": "skill.read", "params": {"name": NAME, **params}}})


def test_the_example_skill_is_in_the_format_with_one_file_its_body_names():
    """agentskills.io's ``skills-ref`` and Curio's strict reader both take the
    skill, its one file sits one level below its folder, and its body links
    it. It holds none of Curio's markers, which a skill a user imports keeps
    as written."""
    import skills_ref

    folder = _example(SKILL)
    assert skills_ref.validate(folder) == []
    skill = skills.parse(folder)
    assert skill.name == NAME == folder.name
    assert skill.files == (SPECIES,)
    assert f"({SPECIES})" in skill.body
    assert "{{" not in (folder / "SKILL.md").read_text(encoding="utf-8")


def test_the_example_imports_as_a_user_imports_it_and_its_chat_loads_the_skill(
    client, user_and_token, tmp_curio, scripted,
):
    # The skill, through Import skill: the review finds nothing to say of it,
    # and the import gives it to no agent.
    review = _post_form(client, scripted, CHECK, _skill_form())
    assert review.status_code == 200, review.get_data(as_text=True)
    review = review.get_json()
    assert (review["name"], review["problem"], review["warnings"], review["leftOut"]) == (NAME, None, [], [])
    assert review["files"] == [SPECIES]
    imported = _post_form(client, scripted, IMPORT, _skill_form(agents=[]))
    assert imported.status_code == 201, imported.get_data(as_text=True)
    assert imported.get_json()["agents"] == []

    # The agent, through Import agent: its coordinate is its folder's name.
    upload = _agent_upload()
    uploaded = client.post(UPLOAD, json=upload, headers=scripted)
    assert uploaded.status_code == 201, uploaded.get_data(as_text=True)
    coord = uploaded.get_json()["dirName"]
    assert coord == AGENT.name

    # It holds the skill by its manifest alone: the account added nothing to it.
    rows = client.get(f"/api/agents/definitions/{coord}/skills", headers=scripted).get_json()
    assert [row["name"] for row in rows["skills"]] == [*CORE, NAME]
    held = rows["skills"][-1]
    assert (held["core"], held["added"], held["chat"], held["modes"]) == (False, False, False, []), held
    assert rows["changed"] is False
    cards = client.get("/api/agents/skills", headers=scripted).get_json()["skills"]
    card = next(card for card in cards if card["name"] == NAME)
    assert card["source"] == "yours"
    assert [(agent["coord"], agent["added"]) for agent in card["agents"]] == [(coord, False)]

    # A chat of it on the canvas lists the skill, loads it, then reads its species file.
    pid = _project(client, scripted)
    att = _attach(client, scripted, pid, coord)
    testing_provider.push_replies(_read(), _read(path=SPECIES), "Done.")
    payload = _run(client, scripted, pid, att, "How many living trees does each block have?")
    first, second, third = _run_calls()
    system = first[0]
    assert _listed(system) == [NAME]
    assert _wrapped(system) == []

    loaded = second[-1]["content"]
    body = _body((SKILL / "SKILL.md").read_text(encoding="utf-8"))
    assert loaded.startswith(f'[tool result] skill.read: ok\n<skill_content name="{NAME}">\n{body}\n'), loaded[:300]
    assert f"<skill_resources>\n  <file>{SPECIES}</file>\n</skill_resources>\n</skill_content>" in loaded, loaded
    species = (SKILL / SPECIES).read_text(encoding="utf-8").rstrip("\n")
    read = third[-1]["content"]
    assert read.startswith(
        f'[tool result] skill.read: ok\n<skill_file name="{NAME}" path="{SPECIES}">\n{species}\n</skill_file>'
    ), read[:300]

    record = _turns(client, scripted, pid, att)[-1]["execution"]
    assert record["skillsLoaded"] == [NAME] and payload["skillsLoaded"] == [NAME]
    assert [call["tool"] for call in record["toolCalls"]] == ["skill.read", "skill.read"]
    assert record["pins"]["skills"] == {"catalog": [NAME]}
    assert record["pins"]["tools"] == [*(tool["id"] for tool in upload["manifest"]["tools"]), "skill.read"]
