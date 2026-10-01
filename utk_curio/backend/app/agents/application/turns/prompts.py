"""Prompt and instruction text resolution for a definition, and the prompt digest.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import hashlib

from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain.manifest import AgentManifest
from utk_curio.backend.app.agents.repositories import publications
from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.agents.application import catalog as agents_catalog


def _resolve_prompt_text(user_key: str, coord: str, name: str) -> str | None:
    """A definition's prompt asset text, by prompts key: ``"instruction"``,
    ``"system"``, or a mode's own.

    **Built-in trust follows the ROSTER bytes** (dev/60) — the same rule
    ``_resolve_definition`` applies to metadata, for the same reason: an
    updated built-in prompt must take effect for existing installs (the store
    copy is a materialization cache, not an authority). Owned/imported
    definitions — including deliberate shadows of a built-in coordinate —
    run from their own on-disk bytes, store copy first, then the published
    catalog.
    """
    m = storage.load_installed_agent_definition(user_key, coord)
    base = storage.agent_definition_dir(user_key, coord) if m is not None else None
    if m is None:
        m = publications.get_published_manifest(coord)
        base = publications.published_agent_dir(coord) if m is not None else None
    if m is not None and m.provenance.trust == "built-in":
        roster = builtin.read_prompt_text(coord, name)
        if roster is not None:
            return roster
    if m is not None and base is not None:
        asset = m.prompts.get(name)
        if asset is not None:
            path = base / asset.path
            if path.is_file():
                return path.read_text(encoding="utf-8")
        elif name == "system":
            # A definition that declares no preamble runs without one — do NOT
            # fall back to the built-in default for a resolvable non-roster def.
            return builtin.read_prompt_text(coord, name)
    return builtin.read_prompt_text(coord, name)


def _resolve_instruction_text(
    user_key: str, coord: str, *, capability: str | None = None
) -> str | None:
    """The agent's instruction prompt text (see ``_resolve_prompt_text``), or
    *capability*'s own when the agent declares it as a mode."""
    return _resolve_prompt_text(user_key, coord, _instruction_key(user_key, coord, capability))


def _instruction_key(user_key: str, coord: str, capability: str | None) -> str:
    """The prompts key a run of *capability* reads: its mode's, else ``instruction``."""
    if capability:
        m = agents_catalog._resolve_definition(user_key, coord)
        declared = m.capability(capability) if m is not None else None
        if declared is not None and declared.instruction:
            return declared.instruction
    return "instruction"


def _configuration_pin(configuration: str | None) -> dict:
    """The run pin for the configuration slot: its sha256, when the run had one."""
    if not configuration:
        return {}

    return {"configurationSha256": hashlib.sha256(configuration.encode("utf-8")).hexdigest()}


def _prompt_digest(m: AgentManifest | None, *, capability: str | None = None) -> str | None:
    """The resolved definition's instruction-prompt sha256 (a DEC-031 pin):
    *capability*'s mode prompt when it declares one.

    Read from the manifest asset, not recomputed — the digest identifies the
    definition bytes that were dispatched. ``None`` when the manifest carries
    no digest (tolerated; pre-upload-import definitions may be unstamped)."""
    if m is None:
        return None
    declared = m.capability(capability) if capability else None
    asset = m.prompts.get(declared.instruction if declared and declared.instruction else "instruction")
    return asset.sha256 if asset is not None else None
