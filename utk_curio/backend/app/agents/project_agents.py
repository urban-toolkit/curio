"""Per-project installed-agent lockfile inside ``spec.trill.json``.

A project's installed agent templates live at ``spec["dataflow"]["agents"]`` as a
sorted list of ``<agentId>@<version>`` coordinates — the direct analogue of the
node-package lockfile ``spec["dataflow"]["packages"]`` (see
``app/packages/spec_packages.py``). Installing an agent into a project appends a
coordinate here; uninstalling removes it. Nothing else about the project spec is
touched, and there is no database row — the project file is the source of truth.

User-facing overview: ``docs/AGENTS.md``.
"""

from __future__ import annotations

from typing import Iterable

from utk_curio.backend.app.agents.storage import AGENT_DIR_RE


def project_agents(spec: dict | None) -> list[str]:
    """Return the project's installed-agent coordinates from the spec.

    Reads ``spec["dataflow"]["agents"]`` when present; returns an empty list
    otherwise. Only well-formed ``<agentId>@<version>`` entries are returned.
    """
    if not isinstance(spec, dict):
        return []
    dataflow = spec.get("dataflow")
    if not isinstance(dataflow, dict):
        return []
    declared = dataflow.get("agents")
    if not isinstance(declared, list):
        return []
    return sorted({a for a in declared if isinstance(a, str) and AGENT_DIR_RE.match(a)})


def set_project_agents(spec: dict, coords: Iterable[str]) -> dict:
    """Write the sorted, validated coordinate list into ``spec["dataflow"]["agents"]``.

    Mutates and returns *spec* for convenience. Creates the ``dataflow`` object
    if absent, mirroring ``spec_packages.set_project_packages``.
    """
    if not isinstance(spec, dict):
        raise TypeError("spec must be a dict")
    dataflow = spec.setdefault("dataflow", {})
    if not isinstance(dataflow, dict):
        raise TypeError("spec['dataflow'] must be a dict")
    cleaned = sorted({c for c in coords if isinstance(c, str) and AGENT_DIR_RE.match(c)})
    dataflow["agents"] = cleaned
    return spec


def agent_defaults(spec: dict | None) -> dict:
    """The project's per-template default records: ``{coord: {revision, settings}}``.

    ``spec["dataflow"]["agentDefaults"]`` — the project-agent-default scope of
    memo ``dev/11`` (materialized at install, one independent record per
    project). Missing/malformed reads as empty.
    """
    if not isinstance(spec, dict):
        return {}
    dataflow = spec.get("dataflow")
    if not isinstance(dataflow, dict):
        return {}
    records = dataflow.get("agentDefaults")
    if not isinstance(records, dict):
        return {}
    return {
        coord: rec
        for coord, rec in records.items()
        if isinstance(coord, str) and AGENT_DIR_RE.match(coord) and isinstance(rec, dict)
    }


def materialize_defaults(spec: dict, coord: str, seed: dict | None = None) -> dict:
    """Ensure *coord* has a defaults record; return it.

    Idempotent: an existing record is returned untouched (reinstalling never
    resets a project's profile — memo ``dev/23``). A new record starts at
    ``{"revision": 1, "settings": seed or {}}``. Mutates *spec*.
    """
    if not (isinstance(coord, str) and AGENT_DIR_RE.match(coord)):
        raise ValueError(f"invalid agent coordinate {coord!r}")
    dataflow = spec.setdefault("dataflow", {})
    if not isinstance(dataflow, dict):
        raise TypeError("spec['dataflow'] must be a dict")
    records = dataflow.setdefault("agentDefaults", {})
    if not isinstance(records, dict):
        records = {}
        dataflow["agentDefaults"] = records
    existing = records.get(coord)
    if isinstance(existing, dict):
        return existing
    record = {"revision": 1, "settings": dict(seed) if isinstance(seed, dict) else {}}
    records[coord] = record
    return record


def drop_defaults(spec: dict, coord: str) -> bool:
    """Remove *coord*'s defaults record (uninstall); True when one existed."""
    if not isinstance(spec, dict):
        return False
    dataflow = spec.get("dataflow")
    if not isinstance(dataflow, dict):
        return False
    records = dataflow.get("agentDefaults")
    if not isinstance(records, dict) or coord not in records:
        return False
    del records[coord]
    return True


# The backend-owned agent sections of the spec: the install lockfile, the
# private attachment instances, and the per-template default records. All are
# written only by the agent endpoints — the canvas save path (TrillGenerator)
# does not serialize them.
_AGENT_SPEC_KEYS = ("agents", "agentAttachments", "agentDefaults")


def strip_agent_state(spec: dict | None) -> dict | None:
    """A sanitized copy of *spec* without the backend-owned agent sections.

    The share surface (tracking rule 9; ``DEC-032``, memo ``dev/12``): the
    agents feature must introduce no agent-private data — the install lockfile,
    attachments (intents, titles, session ids), or project defaults — as a new
    shared surface. The shared-link route serves the spec, so it must serve
    this copy. Non-mutating; tolerates missing/malformed specs.
    """
    if not isinstance(spec, dict):
        return spec
    dataflow = spec.get("dataflow")
    if not isinstance(dataflow, dict):
        return spec
    return {
        **spec,
        "dataflow": {k: v for k, v in dataflow.items() if k not in _AGENT_SPEC_KEYS},
    }


def preserve_agent_state(effective_spec: dict | None, existing_spec: dict | None) -> dict | None:
    """Carry the backend-owned agent sections forward across a client save.

    A project save sends a spec built from the canvas (nodes/edges/packages/
    datasets) that omits ``dataflow.agents`` and ``dataflow.agentAttachments``.
    Writing it verbatim would wipe the install lockfile and attachments that the
    agent endpoints wrote. For each agent section absent from *effective_spec*'s
    dataflow, copy it from *existing_spec* (the on-disk truth). A section the
    client *does* send is left untouched, so a future authoritative client can
    still manage it. Mutates and returns *effective_spec*.
    """
    if not isinstance(effective_spec, dict) or not isinstance(existing_spec, dict):
        return effective_spec
    existing_df = existing_spec.get("dataflow")
    if not isinstance(existing_df, dict):
        return effective_spec
    to_carry = {
        key: existing_df[key]
        for key in _AGENT_SPEC_KEYS
        # Only carry a section the client omitted entirely; an explicitly-sent
        # value (even []) is honored so the client can uninstall/detach via save.
        if key in existing_df
        and not (isinstance(effective_spec.get("dataflow"), dict) and key in effective_spec["dataflow"])
    }
    if not to_carry:
        return effective_spec
    dataflow = effective_spec.setdefault("dataflow", {})
    if not isinstance(dataflow, dict):
        return effective_spec
    dataflow.update(to_carry)
    return effective_spec
