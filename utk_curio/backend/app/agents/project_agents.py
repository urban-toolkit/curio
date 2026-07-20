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
