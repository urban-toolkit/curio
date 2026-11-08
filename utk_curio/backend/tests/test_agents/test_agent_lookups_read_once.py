"""Looking an agent up reads what it needs once, not at every lookup.

A turn looks agents up many times: the delegation walk asks for each
delegate's definition and whether it is a helper, a run asks which file each
of its prompts is, and the worked examples ask whether the agent takes them.
With 100 agent turns at once (``tests/stress``, run 42528241074 of the stage
with agents), py-spy's record of the GIL's holder had:

- a parse of a shipped agent's manifest in 9.3% of its samples, most of it
  checking each prompt's ``curio:`` path again;
- the account store's ``agent_definition_dir`` in 7.7%: it resolved the store
  and the agent's folder, then ``is_within`` resolved both again, each walk an
  lstat of every component, letting the GIL go at each one.

So ``builtin``'s own reads (``is_internal``, ``internal_agent_ids``,
``gets_worked_examples``, ``read_prompt_text``) read one parse of each
manifest's text, kept, and hand none of it out. A manifest
``get_builtin_manifest`` and ``list_builtin_manifests`` hand out is still a
fresh one, which its caller owns. ``agent_definition_dir`` resolves the store
and the folder once each, and still refuses a folder that leads out of the
store.

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
#: A helper Curio ships: it runs only as other agents' delegate.
EVALUATOR = "agent.curio.generated-content-evaluator@1"
#: An agent Curio ships that takes worked examples.
BUILDER = "agent.curio.node-builder@1"
#: Any account key: ``tmp_curio`` gives it a store of its own.
UKEY = "11"


def _parses(monkeypatch) -> list:
    """The manifests ``builtin`` parses from now on, by id."""
    from utk_curio.backend.app.agents.domain import builtin

    parsed: list = []
    original = builtin.parse_agent_manifest

    def counted(raw, *args, **kwargs):
        parsed.append(raw.get("id") if isinstance(raw, dict) else raw)
        return original(raw, *args, **kwargs)

    monkeypatch.setattr(builtin, "parse_agent_manifest", counted)
    return parsed


def _resolves(monkeypatch) -> list:
    """The paths resolved from now on."""
    resolved: list = []
    original = Path.resolve

    def counted(self, *args, **kwargs):
        resolved.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counted)
    return resolved


def _reads():
    """What a turn asks of the agents Curio ships, again and again."""
    from utk_curio.backend.app.agents.domain import builtin

    return (
        builtin.is_internal(EVALUATOR),
        builtin.internal_agent_ids(),
        builtin.gets_worked_examples(BUILDER),
        builtin.read_prompt_text(BUILDER, "instruction"),
    )


def test_a_shipped_agents_own_reads_parse_its_manifest_once(monkeypatch):
    first = _reads()
    parses = _parses(monkeypatch)

    again = _reads()
    parsed = list(parses)

    assert again == first
    assert first[0] is True and first[2] is True and first[3], first
    assert parsed == [], f"the shipped agents' own reads parsed {parsed} again"


def test_a_manifest_handed_out_is_still_a_fresh_one():
    """``get_builtin_manifest`` and ``list_builtin_manifests`` keep their
    promise: a caller owns what it is given, so no two calls share one."""
    from utk_curio.backend.app.agents.domain import builtin

    _reads()
    one, other = builtin.get_builtin_manifest(BUILDER), builtin.get_builtin_manifest(BUILDER)
    assert one == other
    assert one is not other and one.prompts is not other.prompts and one.capabilities is not other.capabilities
    listed, again = builtin.list_builtin_manifests(), builtin.list_builtin_manifests()
    assert listed == again and all(a is not b for a, b in zip(listed, again))


def test_another_copy_of_the_agents_is_read_as_it_is(tmp_path, monkeypatch):
    """The parse is kept per manifest text: a copy of ``agents/`` in which the
    evaluator is listed is read so, though the shipped one was read first."""
    from utk_curio.backend.app.agents.domain import builtin

    assert builtin.is_internal(EVALUATOR) is True
    root = tmp_path / "agents"
    shutil.copytree(AGENTS, root)
    manifest = root / EVALUATOR / "manifest.json"
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["catalog"]["listed"] = True
    manifest.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    monkeypatch.setattr(builtin, "agents_dir", lambda: root)

    assert builtin.is_internal(EVALUATOR) is False
    assert EVALUATOR.split("@", 1)[0] not in builtin.internal_agent_ids()


def test_an_agent_in_the_accounts_store_is_found_with_two_walks(tmp_curio, monkeypatch):
    """The store, then the agent's folder: each resolved once."""
    from utk_curio.backend.app.agents.repositories import storage

    storage.agent_definition_dir(UKEY, BUILDER)
    resolved = _resolves(monkeypatch)

    folder = storage.agent_definition_dir(UKEY, BUILDER)
    walks = list(resolved)

    assert folder.name == BUILDER and folder.parent.name == "agents"
    assert len(walks) == 2, f"an agent's folder in the store took {len(walks)} walks: {walks}"


def test_an_agent_folder_that_leads_out_of_the_store_is_still_refused(tmp_curio, tmp_path):
    from utk_curio.backend.app.agents.repositories import storage
    from utk_curio.backend.app.common.safe_paths import PathTraversalError

    base = storage.user_agents_dir(UKEY)
    base.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (base / BUILDER).symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathTraversalError):
        storage.agent_definition_dir(UKEY, BUILDER)
    assert storage.load_installed_agent_definition(UKEY, EVALUATOR) is None
