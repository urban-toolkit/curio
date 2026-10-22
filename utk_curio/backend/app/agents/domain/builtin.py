"""The agents Curio ships: one folder each in ``agents/``, read as a user's agent is.

Each folder is ``agents/<agentId>@<major>/``: a ``manifest.json``
(``docs/schemas/agent-package.v1.json``) and a ``prompts/`` folder, the layout
of an agent a user uploads, read by the same loader
(``manifest.load_agent_manifest``). Their manifests also carry the fields only
Curio's own agents use: ``catalog`` (a card, or a helper that runs only as
other agents' delegate, and the roster's order), ``workedExamples``, a
capability's ``label`` and a prompt's ``runs``. Each names the preamble every
agent shares as ``curio:default_preamble.md``: a page of the base entry, the
folder in ``agents/`` whose manifest says ``kind: base``, which holds the
pages the agents share (``agent_text``). The base entry is no agent, so the
roster leaves it out.

This module is the loader: the roster, a shipped agent's manifest and prompt
text, which agents are helpers, and the shape an export or an install of one
carries. A prompt's text is its render (``agent_text.read``): every file is a
hand-written source whose markers the backend fills when it starts.

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from utk_curio import shipped
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain.manifest import (
    SHARED_PROMPT_FOLDER,
    SHARED_PROMPT_PREFIX,
    AgentManifest,
    AgentManifestError,
    PromptAsset,
    load_agent_manifest,
    parse_agent_manifest,
)

log = logging.getLogger(__name__)

#: The agents Curio ships, one folder each, by their repository path
#: (``utk_curio/shipped.py`` finds it).
AGENTS_DIR = agent_text.AGENTS_DIR
#: The page of the base entry every agent Curio ships composes before its
#: instruction, its preamble (``curio:default_preamble.md``).
PREAMBLE_FILE = "default_preamble.md"
#: The page of the package backend contract: the Node Builder's
#: package-writing prompt includes it, and a delegated call of that mode
#: receives it as an input.
PACKAGE_CONTRACT_FILE = "rules/package_contract.md"
#: The pages of the base entry the runtime composes a run's turns from, each
#: read by its sections (``agent_text.section``): what a run is told of each
#: tool, how it replies, and the lines that frame what it is given.
TOOLS_FILE = "tools.md"
PROTOCOL_FILE = "protocol.md"
FRAMES_FILE = "frames.md"
#: The page of the reply contracts a delegated run receives in its inputs.
DELEGATE_CONTRACTS_FILE = "delegate-contracts.md"
#: The page of the title call's system prompt.
TITLE_FILE = "conversation-title.md"
#: What only the agents Curio ships carry: an export or an install's copy of
#: one leaves these out, at the top and on each capability and prompt.
_SHIPPED_ONLY = ("catalog", "workedExamples")
_SHIPPED_ONLY_ON_A_CAPABILITY = ("label", "workedExamples")
_SHIPPED_ONLY_ON_A_PROMPT = ("runs",)


def agents_dir() -> Path:
    """Where the agents Curio ships are on this machine."""
    return shipped.path(AGENTS_DIR)


@lru_cache(maxsize=8)
def _read_folders(root: Path) -> tuple[tuple[Path, str], ...]:
    """Each agent folder in *root* and its manifest's text, in the roster's
    order (``catalog.order``), leaving out the base entry, which is no agent
    (``agent_text.is_base``). Every folder is read and checked once: as a
    user's agent is (its name is its id and version), plus what an agent Curio
    ships declares: built-in trust and a place in the catalog, no two in the
    same place."""
    if not root.is_dir():
        log.error(
            "Curio ships its agents in %s, which is missing, so no agent runs. If this is an "
            "installed Curio, the package is missing agents/ (see MANIFEST.in).", root,
        )
        return ()
    found: list[tuple[int, Path, str]] = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.name.startswith(".") or agent_text.is_base(folder):
            continue
        manifest = load_agent_manifest(folder)
        if manifest.provenance.trust != "built-in":
            raise AgentManifestError(f"{folder}: an agent Curio ships has provenance.trust 'built-in'")
        if manifest.catalog is None:
            raise AgentManifestError(
                f"{folder}: an agent Curio ships says where it stands in the catalog "
                "(catalog: listed and order)"
            )
        found.append((manifest.catalog.order, folder, (folder / "manifest.json").read_text(encoding="utf-8")))
    orders = [order for order, _folder, _text in found]
    taken = sorted({order for order in orders if orders.count(order) > 1})
    if taken:
        raise AgentManifestError(f"{root}: two agents Curio ships share catalog.order {taken}")
    return tuple((folder, text) for _order, folder, text in sorted(found, key=lambda entry: entry[0]))


def _folders() -> tuple[tuple[Path, str], ...]:
    return _read_folders(agents_dir())


def _parse(folder: Path, text: str) -> AgentManifest:
    # A fresh manifest on every call: callers own what they are given.
    return parse_agent_manifest(json.loads(text), where=str(folder / "manifest.json"))


def _entry(coord: str) -> tuple[Path, str] | None:
    return next(((folder, text) for folder, text in _folders() if folder.name == coord), None)


def list_builtin_manifests() -> list[AgentManifest]:
    """Every agent Curio ships, validated, in the roster's order."""
    return [_parse(folder, text) for folder, text in _folders()]


def get_builtin_manifest(coord: str) -> AgentManifest | None:
    """The agent Curio ships at ``<agentId>@<major>`` *coord*, or None."""
    entry = _entry(str(coord or ""))
    return _parse(*entry) if entry is not None else None


def builtin_coord(agent_id: str) -> str | None:
    """The coordinate Curio ships *agent_id* at, or None when it ships no such agent."""
    return next((folder.name for folder, _text in _folders() if folder.name.split("@", 1)[0] == agent_id), None)


def manifest_dict(coord: str) -> dict | None:
    """The shipped ``manifest.json`` of *coord* as it is on disk, a fresh dict, or None."""
    entry = _entry(str(coord or ""))
    return json.loads(entry[1]) if entry is not None else None


def internal_agent_ids() -> frozenset[str]:
    """The agents Curio ships that are helpers (``catalog.listed`` false):
    they run only as other agents' delegates, and are never listed,
    installed or attached."""
    return frozenset(m.agent_id for m in list_builtin_manifests() if not m.catalog.listed)


def is_internal(coord: object) -> bool:
    """Whether *coord* (or a bare agent id) is a helper Curio ships. A
    definition of the same id at another major is the owner's own, and is not."""
    agent_id, _, major = str(coord or "").partition("@")
    shipped_coord = builtin_coord(agent_id)
    if shipped_coord is None:
        return False
    m = get_builtin_manifest(shipped_coord)
    return not m.catalog.listed and major in ("", str(m.major))


def gets_worked_examples(coord: str, capability: str | None = None) -> bool:
    """Whether a run of the agent Curio ships at *coord* gets worked examples:
    in the mode of *capability* when it has one (its ``workedExamples``), else
    as the agent says (``workedExamples``). Any other definition gets none."""
    m = get_builtin_manifest(coord)
    if m is None:
        return False
    declared = m.capability(capability) if capability else None
    if declared is not None and declared.instruction:
        return declared.worked_examples
    return m.worked_examples


def read_prompt_text(coord: str, name: str) -> str | None:
    """A shipped agent's prompt text, by manifest prompt key, or None.

    ``name`` is ``"instruction"`` (the agent's task prompt), ``"system"`` (its
    preamble), a mode's capability id or another key its manifest declares.
    A missing file is logged.
    """
    entry = _entry(str(coord or ""))
    if entry is None:
        return None
    asset = _parse(*entry).prompts.get(name)
    if asset is None:
        return None
    return read_asset_text(entry[0], asset, wanted_by=f"built-in agent {coord}, prompt {name!r},")


def read_asset_text(folder: Path, asset: PromptAsset, *, wanted_by: str) -> str | None:
    """The text an agent reads of *asset*, a prompt of the agent Curio ships
    whose folder is *folder*, rendered (``agent_text.read``): a page of the
    base entry when the manifest names it as ``curio:<path>``, else the
    agent's own file. A missing file is logged and reads None."""
    if asset.shared is not None:
        return read_page(asset.shared, wanted_by=wanted_by)
    path = folder / asset.path
    if path.is_file():
        return agent_text.read(path)
    log.error(
        "%s reads %s but %s is missing, so it runs without it. If this is an installed "
        "Curio, the package is missing its agents/ folder (see MANIFEST.in).",
        wanted_by, asset.path, path,
    )
    return None


def read_page(page: str, *, wanted_by: str) -> str | None:
    """A page of the base entry, by its path there (``curio:<page>`` names
    it), rendered (``agent_text.read``), or None when it is missing or no
    page.

    A missing page is logged: returning None silently would ship an agent
    with no system or task prompt and no symptom beyond worse answers, which
    is precisely what an sdist without its prompts once did.
    """
    try:
        path = agent_text.page_file(page)
    except agent_text.AgentTextError as exc:
        log.error("%s reads %s%s, which it cannot, so it runs without it: %s",
                  wanted_by, SHARED_PROMPT_PREFIX, page, exc)
        return None
    if path.is_file():
        return agent_text.read(path)
    log.error(
        "%s reads %s%s but %s is missing, so it runs without it. If this is an "
        "installed Curio, the package is missing its agents/ folder (see MANIFEST.in).",
        wanted_by, SHARED_PROMPT_PREFIX, page, path,
    )
    return None


def read_instruction_text(coord: str) -> str | None:
    """A shipped agent's instruction prompt text, or None."""
    return read_prompt_text(coord, "instruction")


def exported_manifest(raw: dict) -> dict:
    """*raw*, the manifest of an agent Curio ships, as an export or an
    install's copy of it carries it: without the fields only Curio's own agents
    use, and with each shared prompt named by the file the bundle holds it as
    (``PromptAsset.file``)."""
    manifest = {key: value for key, value in raw.items() if key not in _SHIPPED_ONLY}
    manifest["capabilities"] = [
        {key: value for key, value in capability.items() if key not in _SHIPPED_ONLY_ON_A_CAPABILITY}
        for capability in raw.get("capabilities", [])
    ]
    manifest["prompts"] = {
        key: {
            **{k: v for k, v in asset.items() if k not in _SHIPPED_ONLY_ON_A_PROMPT},
            "path": _bundle_path(asset.get("path")),
        }
        for key, asset in (raw.get("prompts") or {}).items()
    }
    return manifest


def carry_shared_prompts(manifest: dict, prompts: dict[str, str]) -> dict:
    """The bundle ``{manifest, prompts}`` of a definition whose *manifest*
    may name pages of the base entry (``curio:<path>``), carrying each as a
    file of its own, its rendered text, as an export carries every prompt: the
    manifest names the file, and the prompts hold its text. Leaves *manifest*
    and *prompts* unchanged."""
    entries = manifest.get("prompts")
    if not isinstance(entries, dict):
        return {"manifest": manifest, "prompts": prompts}
    carried, files = {}, dict(prompts)
    for key, asset in entries.items():
        path = asset.get("path") if isinstance(asset, dict) else None
        shared = _shared_name(path)
        text = read_page(shared, wanted_by=f"an export, prompt {key!r},") if shared else None
        if text is None:
            carried[key] = asset
            continue
        carried[key] = {**asset, "path": _bundle_path(path)}
        files[carried[key]["path"]] = text
    return {"manifest": {**manifest, "prompts": carried}, "prompts": files}


def _shared_name(path: object) -> str | None:
    """The page of the base entry *path* names (``curio:<page>``), else None."""
    if isinstance(path, str) and path.startswith(SHARED_PROMPT_PREFIX):
        name = path[len(SHARED_PROMPT_PREFIX):]
        return name if name in agent_text.pages() else None
    return None


def _bundle_path(path: object):
    """Where a bundle holds the prompt at *path* (``PromptAsset.file``)."""
    shared = _shared_name(path)
    return path if shared is None else f"{SHARED_PROMPT_FOLDER}/{shared}"
