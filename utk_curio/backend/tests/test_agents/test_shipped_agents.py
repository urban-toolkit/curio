"""Curio's own agents are manifest folders, read as a user's agent is.

Each agent Curio ships is a folder in ``agents/``, ``<id>@<version>/``, with a
``manifest.json`` (``docs/schemas/agent-package.v1.json``) and a ``prompts/``
folder: the layout of an agent a user uploads, read by the same loader
(``manifest.load_agent_manifest``). Seven ship: four catalog cards and three
helpers that run only as other agents' delegates. Their manifests also carry
what only Curio's own agents use: ``catalog`` (a card or a helper, and the
roster's order), ``workedExamples``, a capability's ``label`` and a prompt's
``runs``. Every one names the preamble all agents share as
``curio:default_preamble.md``, one file in ``utk_curio/llm-prompts/``.

``catalog`` counts only for a folder in ``agents/``: a copy of one in a user's
store is the user's own agent, and an upload cannot set it.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS = REPO_ROOT / "agents"
PROMPTS = REPO_ROOT / "utk_curio" / "llm-prompts"
SCHEMA = REPO_ROOT / "docs" / "schemas" / "agent-package.v1.json"

#: Every agent Curio ships, in the roster's order: who asks for a mode is
#: listed in this order in the agent details window.
ROSTER = (
    "agent.researcher",
    "agent.dataflow-planner",
    "agent.dataflow-reader",
    "agent.node-builder",
    "agent.dataset-finder",
    "agent.dataflow-builder",
    "agent.generated-content-evaluator",
)
#: The catalog's cards. The rest are helpers.
CARDS = {"agent.researcher", "agent.node-builder", "agent.dataset-finder", "agent.dataflow-builder"}
#: The version every shipped agent has: dataflow lockfiles, attachments and
#: imports hold it in their coordinates.
VERSION = "1.0.0"
#: The preamble every shipped agent names, and where an export carries it.
SHARED_PREAMBLE = "curio:default_preamble.md"
PREAMBLE_FILE = "prompts/default_preamble.md"
#: Any account key: ``tmp_curio`` gives it a store of its own.
UKEY = "7"


def _folders() -> list[Path]:
    return sorted(path for path in AGENTS.iterdir() if path.is_dir() and not path.name.startswith("."))


def _raw(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def _preamble() -> str:
    return (PROMPTS / "default_preamble.md").read_text(encoding="utf-8")


def _copy_into_store(shipped: str, coord: str) -> Path:
    """Copy the shipped folder *shipped* into ``UKEY``'s agent store as *coord*,
    an import of the user's own: the manifest takes the copy's id and version
    and the trust an import has, and every other byte is as shipped."""
    from utk_curio.backend.app.agents.repositories import imports, storage

    target = storage.agent_definition_dir(UKEY, coord)
    shutil.copytree(AGENTS / shipped, target)
    raw = _raw(target)
    agent_id, version = coord.split("@", 1)
    raw.update(id=agent_id, version=version)
    raw["provenance"] = {**raw["provenance"], "trust": "imported"}
    (target / "manifest.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    imports.add_imported_agent(UKEY, coord)
    return target


def _upload_payload(**manifest_over) -> tuple[dict, dict]:
    manifest = {
        "id": "agent.my-summarizer",
        "name": "My Summarizer",
        "category": "node",
        "version": "1.0.0",
        "capabilities": [{"id": "node.explain", "contractVersion": "1"}],
        "compatibleTargets": [{"kind": "node", "requires": []}],
        "prompts": {
            "system": {"path": SHARED_PREAMBLE, "variables": []},
            "instruction": {"path": "prompts/instruction.md", "variables": []},
        },
        "provenance": {"publisher": "karla"},
    }
    manifest.update(manifest_over)
    return manifest, {"prompts/instruction.md": "Summarize the node in three bullets."}


class TestTheFolders:
    def test_seven_agents_ship_each_in_a_folder_of_its_own(self):
        assert [folder.name for folder in _folders()] == sorted(f"{agent_id}@{VERSION}" for agent_id in ROSTER)
        for folder in _folders():
            assert (folder / "manifest.json").is_file(), folder.name
            assert (folder / "prompts").is_dir(), folder.name

    def test_each_loads_as_a_users_agent_does(self):
        from utk_curio.backend.app.agents.domain.manifest import load_agent_manifest

        for folder in _folders():
            m = load_agent_manifest(folder)
            assert m.dir_name == folder.name
            assert m.provenance.trust == "built-in", folder.name
            assert m.catalog is not None, f"{folder.name} does not say where it stands in the catalog"

    def test_four_cards_three_helpers_in_the_rosters_order(self):
        from utk_curio.backend.app.agents.domain import builtin
        from utk_curio.backend.app.agents.domain.manifest import load_agent_manifest

        manifests = [load_agent_manifest(folder) for folder in _folders()]
        orders = [m.catalog.order for m in manifests]
        assert len(set(orders)) == len(orders), orders
        assert [m.agent_id for m in sorted(manifests, key=lambda m: m.catalog.order)] == list(ROSTER)
        assert {m.agent_id for m in manifests if m.catalog.listed} == CARDS
        # The roster Curio serves is these folders, in that order.
        assert [m.agent_id for m in builtin.list_builtin_manifests()] == list(ROSTER)
        assert builtin.internal_agent_ids() == set(ROSTER) - CARDS

    def test_no_folder_holds_a_retired_agent(self):
        from utk_curio.backend.tests.test_agents.test_retired_agent_ids import RETIRED

        shipped = {folder.name.split("@", 1)[0] for folder in _folders()}
        assert shipped, "no agent folder; this test would be vacuous"
        assert not shipped & set(RETIRED)

    def test_each_manifest_is_valid_against_the_schema(self):
        from jsonschema import Draft202012Validator

        validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
        for folder in _folders():
            errors = [error.message for error in validator.iter_errors(_raw(folder))]
            assert not errors, (folder.name, errors[:3])

    def test_every_prompt_file_is_named_and_every_name_is_a_file(self):
        """An export carries every file of a folder, and an upload refuses a
        file its manifest does not name: a folder holds exactly its prompts."""
        from utk_curio.backend.app.agents.domain.manifest import load_agent_manifest

        for folder in _folders():
            m = load_agent_manifest(folder)
            named = {asset.path for asset in m.prompts.values() if not asset.path.startswith("curio:")}
            held = {
                path.relative_to(folder).as_posix()
                for path in folder.rglob("*")
                if path.is_file() and path.name != "manifest.json"
            }
            assert held == named, folder.name
            assert all(path.startswith("prompts/") and path.endswith(".md") for path in named), folder.name


class TestTheSharedPreamble:
    def test_every_agent_names_the_one_preamble_curio_shares(self):
        from utk_curio.backend.app.agents.domain import builtin

        for m in builtin.list_builtin_manifests():
            assert m.prompts["system"].path == SHARED_PREAMBLE, m.agent_id
            assert builtin.read_prompt_text(m.dir_name, "system") == _preamble(), m.agent_id
        # One file: no agent folder holds a copy.
        assert not list(AGENTS.glob("*/prompts/default_preamble*"))

    def test_an_export_carries_it_as_a_file_and_no_field_only_curio_reads(self):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.domain import builtin

        for m in builtin.list_builtin_manifests():
            bundle = catalog.builtin_definition_bundle(m.dir_name)
            manifest = bundle["manifest"]
            assert manifest["prompts"]["system"]["path"] == PREAMBLE_FILE, m.agent_id
            assert bundle["prompts"][PREAMBLE_FILE] == _preamble(), m.agent_id
            assert {asset["path"] for asset in manifest["prompts"].values()} == set(bundle["prompts"]), m.agent_id
            assert "curio:" not in json.dumps(manifest), m.agent_id
            assert "catalog" not in manifest and "workedExamples" not in manifest, m.agent_id
            for capability in manifest["capabilities"]:
                assert not {"label", "workedExamples"} & set(capability), (m.agent_id, capability["id"])
            for key, asset in manifest["prompts"].items():
                assert "runs" not in asset, (m.agent_id, key)

    def test_a_users_agent_may_name_it_too(self, tmp_curio):
        from utk_curio.backend.app.agents.application import upload_import
        from utk_curio.backend.app.agents.application.turns import prompts
        from utk_curio.backend.app.agents.repositories import storage

        manifest, files = _upload_payload()
        card = upload_import.upload_import(UKEY, manifest, files)
        coord = card["dirName"]
        stored_dir = storage.agent_definition_dir(UKEY, coord)
        stored = _raw(stored_dir)
        # Kept by its name, with no digest and no file: the text is Curio's.
        assert stored["prompts"]["system"] == {"path": SHARED_PREAMBLE, "variables": []}
        assert not [path for path in stored_dir.rglob("*") if "curio:" in path.name or path.name == "default_preamble.md"]
        assert prompts._resolve_prompt_text(UKEY, coord, "system") == _preamble()
        assert prompts._resolve_instruction_text(UKEY, coord) == files["prompts/instruction.md"]
        # Its export carries the preamble as a file, as a shipped agent's does.
        bundle = storage.read_definition_bundle(UKEY, coord)
        assert bundle["manifest"]["prompts"]["system"]["path"] == PREAMBLE_FILE
        assert bundle["prompts"][PREAMBLE_FILE] == _preamble()

    def test_a_published_one_keeps_the_name_in_the_catalog_and_in_an_added_copy(self, tmp_curio):
        """Inside Curio the preamble stays a name: publishing copies the folder
        as it is, and an account that adds the published agent runs Curio's
        preamble from its own copy, after the publisher unpublishes too. Read
        from the catalog for an export, it carries the file."""
        from utk_curio.backend.app.agents.application import catalog, lifecycle, upload_import
        from utk_curio.backend.app.agents.application.turns import prompts
        from utk_curio.backend.app.agents.repositories import publications, storage

        manifest, files = _upload_payload()
        coord = upload_import.upload_import(UKEY, manifest, files)["dirName"]
        lifecycle.publish_agent(UKEY, coord)
        assert _raw(publications.published_agent_dir(coord))["prompts"]["system"]["path"] == SHARED_PREAMBLE
        reader = "8"
        exported = catalog.read_definition_bundle_anywhere(reader, coord)
        assert exported["manifest"]["prompts"]["system"]["path"] == PREAMBLE_FILE
        assert exported["prompts"][PREAMBLE_FILE] == _preamble()
        adder = "9"
        catalog._materialize_definition(adder, coord)
        added = _raw(storage.agent_definition_dir(adder, coord))
        assert added["provenance"]["trust"] == "global"
        assert added["prompts"]["system"]["path"] == SHARED_PREAMBLE
        assert not (storage.agent_definition_dir(adder, coord) / PREAMBLE_FILE).exists()
        lifecycle.unpublish_agent(UKEY, coord)
        assert prompts._resolve_prompt_text(adder, coord, "system") == _preamble()
        assert prompts._resolve_instruction_text(adder, coord) == files["prompts/instruction.md"]

    def test_a_shared_name_curio_does_not_have_is_refused(self, tmp_curio):
        from utk_curio.backend.app.agents.application import upload_import
        from utk_curio.backend.app.agents.application.errors import AgentServiceError
        from utk_curio.backend.app.agents.domain.manifest import AgentManifestError, parse_agent_manifest

        manifest, files = _upload_payload()
        for path in ("curio:no_such_prompt.md", "curio:../secrets.md", "curio:default_preamble.template.md"):
            bad = {**manifest, "prompts": {**manifest["prompts"], "system": {"path": path}}}
            with pytest.raises(AgentManifestError, match="curio"):
                parse_agent_manifest(bad)
            with pytest.raises(AgentServiceError) as refused:
                upload_import.upload_import(UKEY, bad, files)
            assert refused.value.status == 400, path


class TestTheCatalogIsCuriosAlone:
    def test_an_upload_cannot_set_it(self, tmp_curio):
        from utk_curio.backend.app.agents.application import upload_import
        from utk_curio.backend.app.agents.application.errors import AgentServiceError
        from utk_curio.backend.app.agents.repositories import storage

        manifest, files = _upload_payload(catalog={"listed": False, "order": 2})
        with pytest.raises(AgentServiceError, match="catalog") as refused:
            upload_import.upload_import(UKEY, manifest, files)
        assert refused.value.status == 400
        assert storage.load_installed_agent_definition(UKEY, "agent.my-summarizer@1.0.0") is None

    def test_a_copy_of_a_shipped_folder_loads_through_the_same_path(self, tmp_curio):
        """A helper's folder copied into a user's store under another id is
        read by the same loader into the same manifest, runs its own prompt
        files and Curio's preamble, and is the user's own card: its
        ``catalog`` says helper and counts for nothing."""
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.turns import prompts
        from utk_curio.backend.app.agents.domain import builtin
        from utk_curio.backend.app.agents.domain.manifest import load_agent_manifest
        from utk_curio.backend.app.agents.repositories import storage

        shipped = AGENTS / f"agent.dataflow-planner@{VERSION}"
        coord = "agent.my-planner@1.0.0"
        target = _copy_into_store(shipped.name, coord)
        copy = storage.load_installed_agent_definition(UKEY, coord)
        original = load_agent_manifest(shipped)
        assert copy == dataclasses.replace(
            original, agent_id="agent.my-planner",
            provenance=dataclasses.replace(original.provenance, trust="imported"),
        )
        assert copy.catalog is not None and copy.catalog.listed is False
        for key, asset in copy.prompts.items():
            text = prompts._resolve_prompt_text(UKEY, coord, key)
            if asset.path == SHARED_PREAMBLE:
                assert text == _preamble(), key
            else:
                assert text == (target / asset.path).read_text(encoding="utf-8"), key
                assert text == (shipped / asset.path).read_text(encoding="utf-8"), key
        # Not a helper: it is listed as the user's import and gets the
        # user's own LLM choice, and the roster is the shipped folders alone.
        assert not builtin.is_internal(coord)
        assert not builtin.is_internal("agent.my-planner")
        assert "agent.my-planner" not in builtin.internal_agent_ids()
        assert [m.agent_id for m in builtin.list_builtin_manifests()] == list(ROSTER)
        cards = catalog.list_my_imports(UKEY)
        assert [card["dirName"] for card in cards] == [coord]
        assert cards[0]["inCatalog"] is True

    @pytest.mark.parametrize("bad", [
        "helper",
        {"listed": True},
        {"order": 1},
        {"listed": "yes", "order": 1},
        {"listed": 1, "order": 1},
        {"listed": True, "order": True},
        {"listed": True, "order": -1},
        {"listed": True, "order": 1.5},
        {"listed": True, "order": "1"},
        {"listed": True, "order": 1, "card": True},
    ])
    def test_its_parser_refuses_anything_but_listed_and_order(self, bad):
        from utk_curio.backend.app.agents.domain.manifest import AgentManifestError, parse_agent_manifest

        manifest, _files = _upload_payload(catalog=bad)
        with pytest.raises(AgentManifestError, match="catalog"):
            parse_agent_manifest(manifest)

    def test_its_parser_reads_listed_and_order(self):
        from utk_curio.backend.app.agents.domain.manifest import parse_agent_manifest

        manifest, _files = _upload_payload(catalog={"listed": False, "order": 0})
        placement = parse_agent_manifest(manifest).catalog
        assert (placement.listed, placement.order) == (False, 0)
        assert parse_agent_manifest(_upload_payload()[0]).catalog is None

    def test_the_loader_refuses_a_shipped_folder_without_a_place_or_with_anothers(self, tmp_path, monkeypatch):
        from utk_curio.backend.app.agents.domain import builtin
        from utk_curio.backend.app.agents.domain.manifest import AgentManifestError

        def ship(*names: str, edit=None) -> Path:
            root = tmp_path / f"agents-{len(list(tmp_path.iterdir()))}"
            for name in names:
                shutil.copytree(AGENTS / name, root / name)
            if edit:
                raw = _raw(root / names[-1])
                edit(raw)
                (root / names[-1] / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
            return root

        reader, planner = f"agent.dataflow-reader@{VERSION}", f"agent.dataflow-planner@{VERSION}"
        good = ship(reader, planner)
        monkeypatch.setattr(builtin, "agents_dir", lambda: good)
        assert [m.agent_id for m in builtin.list_builtin_manifests()] == ["agent.dataflow-planner", "agent.dataflow-reader"]

        no_place = ship(reader, planner, edit=lambda raw: raw.pop("catalog"))
        monkeypatch.setattr(builtin, "agents_dir", lambda: no_place)
        with pytest.raises(AgentManifestError, match="catalog"):
            builtin.list_builtin_manifests()

        same_place = ship(reader, planner, edit=lambda raw: raw["catalog"].update(order=_raw(AGENTS / reader)["catalog"]["order"]))
        monkeypatch.setattr(builtin, "agents_dir", lambda: same_place)
        with pytest.raises(AgentManifestError, match="order"):
            builtin.list_builtin_manifests()


class TestTheFieldsOnlyCuriosAgentsUse:
    def test_a_copy_gets_none_of_them(self, tmp_curio):
        """Labels, the Autark prompt's line and worked examples describe the
        agent Curio ships: a copy of the Node Builder is the user's agent,
        each capability a mode named by its id, as for any agent of theirs."""
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.domain import builtin

        coord = "agent.my-builder@1.0.0"
        _copy_into_store(f"agent.node-builder@{VERSION}", coord)
        copy = catalog._resolve_definition(UKEY, coord)
        shipped = builtin.get_builtin_manifest(f"agent.node-builder@{VERSION}")
        assert [c.label for c in copy.capabilities] == [c.label for c in shipped.capabilities]
        modes = catalog.agent_modes(copy)
        assert [mode["label"] for mode in modes] == copy.capability_ids
        runs = {row["path"]: row["runs"] for row in catalog.prompt_runs(copy, modes)}
        assert runs["prompts/new_content_autk_prompt.md"] == ["autk-grammar"]
        assert builtin.gets_worked_examples(f"agent.node-builder@{VERSION}")
        assert not builtin.gets_worked_examples(coord)
        assert not builtin.gets_worked_examples(coord, "node.content.generate")

    def test_a_shipped_agent_reads_each_of_them(self):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.domain import builtin

        nb = builtin.get_builtin_manifest(f"agent.node-builder@{VERSION}")
        assert nb.worked_examples is True
        assert nb.capability("node.content.generate").worked_examples is True
        assert nb.capability("package.recommend").worked_examples is False
        assert nb.capability("node.content.generate").label == "Write a node's content"
        assert nb.capability("node.build").label is None
        assert nb.prompts["autk-grammar"].runs == "Write a node's content, for an Autark node"
        modes = catalog.agent_modes(nb)
        runs = {row["path"]: row["runs"] for row in catalog.prompt_runs(nb, modes)}
        assert runs["prompts/new_content_autk_prompt.md"] == ["Write a node's content, for an Autark node"]
        assert runs[PREAMBLE_FILE] == ["every call"]

    @pytest.mark.parametrize("edit, field", [
        # Only a mode decides for itself: any other run follows the agent.
        (lambda m: m["capabilities"][0].update(workedExamples=True), "workedExamples"),
        (lambda m: m["capabilities"][0].update(instruction="instruction", workedExamples="yes"), "workedExamples"),
        (lambda m: m.update(workedExamples="always"), "workedExamples"),
        (lambda m: m["capabilities"][0].update(label=""), "label"),
        (lambda m: m["capabilities"][0].update(label=7), "label"),
        # The preamble, the instruction and a mode's prompt run when the
        # details window says; only another prompt says when it runs.
        (lambda m: m["prompts"]["system"].update(runs="always"), "runs"),
        (lambda m: m["prompts"]["instruction"].update(runs="on a message"), "runs"),
        (lambda m: m["prompts"].update(extra={"path": "prompts/extra.md", "runs": ""}), "runs"),
    ])
    def test_their_parser_refuses_a_value_that_cannot_count(self, edit, field):
        from utk_curio.backend.app.agents.domain.manifest import AgentManifestError, parse_agent_manifest

        manifest, _files = _upload_payload()
        manifest = json.loads(json.dumps(manifest))
        edit(manifest)
        with pytest.raises(AgentManifestError, match=field):
            parse_agent_manifest(manifest)


class TestTheGenerator:
    def test_each_rendered_prompt_is_written_into_the_folder_that_names_it(self):
        from utk_curio.backend.app.agents.domain import contracts
        from utk_curio.backend.app.agents.domain.manifest import load_agent_manifest

        outputs = set(contracts.GENERATED_OUTPUTS)
        owned = set()
        for folder in _folders():
            for asset in load_agent_manifest(folder).prompts.values():
                stem = Path(asset.path).name.removesuffix(".md")
                if asset.path.startswith("curio:") or stem not in contracts.PROMPT_TEMPLATES:
                    continue
                owned.add(stem)
                assert f"agents/{folder.name}/{asset.path}" in outputs, (folder.name, asset.path)
                assert f"{contracts.PROMPTS_DIR}/{stem}.md" not in outputs, stem
        assert len(owned) == 11, sorted(owned)
        # The shared preamble and the fragments other prompts include stay
        # beside their templates.
        for stem in set(contracts.PROMPT_TEMPLATES) - owned:
            assert f"{contracts.PROMPTS_DIR}/{stem}.md" in outputs, stem
        assert f"{contracts.PROMPTS_DIR}/default_preamble.md" in outputs
        # Every template stays in llm-prompts/, and no agent folder holds one.
        assert not list(AGENTS.rglob("*.template.md"))
        assert len(list(PROMPTS.glob("*.template.md"))) == len(contracts.PROMPT_TEMPLATES)

    def test_a_prompt_with_no_template_lives_only_in_its_agents_folder(self):
        from utk_curio.backend.app.agents.domain import contracts

        held = [path for path in AGENTS.glob("*/prompts/*.md")]
        handwritten = [path.name for path in held if path.stem not in contracts.PROMPT_TEMPLATES]
        assert len(handwritten) == 8, handwritten
        for name in handwritten:
            assert not (PROMPTS / name).exists(), name
        # A file name is one prompt's, wherever it is.
        names = [path.name for path in held] + [path.name for path in PROMPTS.glob("*.md")]
        assert len(names) == len(set(names)), sorted(n for n in names if names.count(n) > 1)


class TestTheFolderShips:
    """The Docker image's copy and the CI and deploy filters are held to each
    other by the Jest suites that read the checkout (fullStackBuildPaths,
    deployPaths); the image these tests run in holds the rest."""

    def test_agents_is_a_shipped_folder_in_every_build(self):
        from utk_curio import shipped

        assert "agents" in shipped.FOLDERS
        assert shipped.path("agents") == AGENTS
        setup = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
        assert re.search(r"^SHIPPED_FOLDERS = \([^)]*\"agents\"", setup, re.MULTILINE), "setup.py"
        manifest_in = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        assert re.search(r"^recursive-include\s+agents\s+\*\s*$", manifest_in, re.MULTILINE), "MANIFEST.in"
