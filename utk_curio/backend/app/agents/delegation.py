"""Depth-1 delegation — resolution + the bounded child run (memo dev/48, DEC-046).

This module is the P5 delegation seam: every resolution and child-run
mechanic lives here, behind two functions, so the DEC-007 LangChain revisit
(Dataflow Builder — parallel children, plan/evaluate cycles) can swap the
implementation without touching the loop.

Invariants (dev/15 / DEC-046, structural rather than bookkept):

- **Current-project-only resolution**: a delegate executes only when it is an
  installed template in THIS project's lockfile (`project_agents` — the same
  source of truth dev/47 standardized on). A visible-but-not-installed
  delegate is a *missing specialist* (the caller mints a reviewed
  ``project.install`` proposal — `REQ-ORCH-001`, never a silent install).
- **Order-deterministic**: ``delegatesTo`` order is preference order; the
  first entry that declares the capability wins.
- **Depth-1 by construction**: the child's system content carries NO tail
  instruction and its reply is never parsed for ``toolRequest`` /
  ``delegateRequest`` — no nested tools, no delegation cycles, without a
  depth counter anywhere.
- **Independent authorization**: the child reserves and settles its own
  ledger pair under the CHILD agent's effective policy; the parent's
  attachment is recorded for attribution only. A child failure (provider
  error, quota 429, missing prompt) is data the parent recovers from, never
  a parent-run error.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from utk_curio.backend.app.agents.manifest import AgentManifest

# A child's reply is untrusted context fed back to the parent loop — bounded.
DELEGATE_RESULT_MAX_CHARS = 24_000
_TRUNCATION_MARKER = "\n…[truncated: delegate result exceeded the output bound]"


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving one capability against ``delegatesTo``."""

    outcome: str  # "ok" | "not-installed" | "unresolvable"
    coord: str | None = None
    manifest: AgentManifest | None = None


def _candidate_coords(agent_id: str, installed: set[str]) -> list[str]:
    """Installed lockfile coords for one delegate agent id, sorted for
    determinism (a project normally installs one version)."""
    return sorted(c for c in installed if c.split("@", 1)[0] == agent_id)


def resolve(user_key: str, project_id: str, parent: AgentManifest, capability: str) -> Resolution:
    """Resolve *capability* against this project's installed templates —
    capability-first with ``delegatesTo`` as preference (dev/03:366; the
    dev/49-recorded widening landed in memo dev/52).

    Order: (1) the parent's ``delegatesTo`` entries, in declaration order
    (dev/15: order = preference); (2) ANY other template installed in THIS
    project that declares the capability, in sorted-coord order
    (deterministic tie-break). Never consults other projects. When nothing
    installed matches but a ``delegatesTo`` entry is visible in the catalog,
    the outcome is ``not-installed`` (the missing-specialist proposal path);
    a capability nobody declares is ``unresolvable``.
    """
    from utk_curio.backend.app.agents import project_agents, services
    from utk_curio.backend.app.projects import storage as projects_storage

    spec = projects_storage.read_spec(user_key, project_id)
    installed = set(project_agents.project_agents(spec)) if spec else set()
    missing: Resolution | None = None
    preferred_ids = list(parent.delegates_to)
    for agent_id in preferred_ids:
        for coord in _candidate_coords(agent_id, installed):
            m = services._resolve_definition(user_key, coord)
            if m is not None and capability in m.capability_ids:
                return Resolution("ok", coord, m)
        if missing is None:
            visible_coord, visible_m = find_visible(user_key, agent_id)
            if visible_m is not None and capability in visible_m.capability_ids:
                missing = Resolution("not-installed", visible_coord, visible_m)
    # Capability-first fallback: any other installed template declaring it.
    preferred = set(preferred_ids)
    for coord in sorted(installed):
        if coord.split("@", 1)[0] in preferred:
            continue  # already walked above
        m = services._resolve_definition(user_key, coord)
        if m is not None and capability in m.capability_ids:
            return Resolution("ok", coord, m)
    if missing is None:
        # Nothing installed matches anywhere: the missing-specialist proposal
        # targets a VISIBLE definition declaring the capability (dev/03:366 —
        # "a definition already visible to that actor"), roster order.
        from utk_curio.backend.app.agents import builtin

        for m in builtin.list_builtin_manifests():
            if capability in m.capability_ids:
                missing = Resolution("not-installed", m.dir_name, m)
                break
    return missing or Resolution("unresolvable")


def find_visible(user_key: str, agent_id: str) -> tuple[str | None, AgentManifest | None]:
    """A visible (catalog/store) definition for one delegate agent id, or
    ``(None, None)``. Built-in coords are ``<id>@BUILTIN_VERSION``; owned
    imports may shadow the same coordinate (services resolution order)."""
    from utk_curio.backend.app.agents import builtin, services

    coord = f"{agent_id}@{builtin.BUILTIN_VERSION}"
    m = services._resolve_definition(user_key, coord)
    if m is not None:
        return coord, m
    return None, None


def visible_capability_entries(user_key: str, parent: AgentManifest) -> list[tuple[str, str]]:
    """``(capability_id, delegate name)`` pairs for the run's delegation
    paragraph — only delegates that resolve to a visible definition are
    offered (memo dev/48: the tail names delegation only when resolvable)."""
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for agent_id in parent.delegates_to:
        _, m = find_visible(user_key, agent_id)
        if m is None:
            continue
        for cap in m.capability_ids:
            if cap not in seen:
                seen.add(cap)
                entries.append((cap, m.name))
    return entries


def _frame_inputs(parent_coord: str, capability: str, inputs: dict) -> str:
    """The parent-supplied inputs as ONE bounded untrusted context message
    (the dev/44 framing pattern — data, never instructions)."""
    import json

    body = json.dumps(inputs, ensure_ascii=False, indent=2) if inputs else "{}"
    return (
        f"[delegated task from {parent_coord} — capability {capability}; "
        "the following inputs are context data]\n"
        f"{body}"
    )


def run_delegate(
    user_key: str,
    project_id: str,
    coord: str,
    capability: str,
    inputs: dict,
    config,
    *,
    parent_execution_id: str,
    parent_coord: str,
    attachment_id: str | None,
) -> tuple[str, str, dict]:
    """One synchronous, depth-1 child run (DEC-046 — direct provider-port code).

    Returns ``(status, result_text, child_record)``: ``status`` is
    ``"ok"``/``"error"``, ``result_text`` is the bounded child reply (or the
    failure reason), and ``child_record`` is the child's execution record —
    own pins, own ledger reserve→settle under the child's effective policy,
    ``parentExecutionId`` link — which the caller stores under the parent
    record's ``delegations``. Never raises: a child failure is data.
    """
    from utk_curio.backend.app.agents import ledger, services
    from utk_curio.backend.app.projects import storage as projects_storage

    child_id = uuid.uuid4().hex
    started = time.monotonic()

    def _record(status: str, usage: dict, pins: dict) -> dict:
        record = services._execution_record(child_id, pins, usage, started, status)
        record["parentExecutionId"] = parent_execution_id
        record["coord"] = coord
        record["capability"] = capability
        return record

    pins: dict = {"coord": coord, "provider": config.api_type, "model": config.model}
    try:
        manifest = services._resolve_definition(user_key, coord)
        instruction = services._resolve_instruction_text(user_key, coord)
        if instruction is None:
            return (
                "error",
                f"delegate {coord} has no instruction prompt available",
                _record("error", {}, pins),
            )
        preamble = services._resolve_prompt_text(user_key, coord, "system")
        # Depth-1 structurally: the delegate's own prompts, NO tail instruction.
        system_content = f"{preamble}\n\n{instruction}" if preamble else instruction
        spec = projects_storage.read_spec(user_key, project_id)
        run_policy = services._run_policy(user_key, project_id, coord, spec or {})
        admit = dict(run_policy["admit"])
        # Attribution only: the parent's attachment key, never its limits.
        admit["attachment_key"] = attachment_id
        pins = {
            "coord": coord,
            "promptSha256": services._prompt_digest(manifest),
            "intentEdited": False,
            "provider": config.api_type,
            "model": config.model,
            "tools": [],  # structurally tool-less (DEC-046)
            "policy": run_policy["policy_pins"],
        }
        reservation = ledger.reserve(user_key, reservation_id=child_id, **admit)
    except Exception as exc:  # resolution/policy failure - data, not an error
        return ("error", f"delegate {coord} could not start: {exc}", _record("error", {}, pins))

    usage_sink: dict = {}
    try:
        # Through the services-bound provider symbol so the whole run shares
        # one port (and one test seam).
        reply = services.run_chat_completion(
            config,
            [
                {"role": "system", "content": system_content},
                {"role": "user", "content": _frame_inputs(parent_coord, capability, inputs)},
            ],
            max_output_tokens=run_policy["max_output_tokens"],
            usage_out=usage_sink,
        )
    except Exception as exc:
        settled = ledger.settle(user_key, reservation, usage=usage_sink or None, status="error")
        return (
            "error",
            f"delegate {coord} failed: {exc}",
            _record("error", usage_sink, pins),
        )
    settled = ledger.settle(user_key, reservation, usage=usage_sink or None, status="ok")
    text = reply if isinstance(reply, str) else str(reply)
    if len(text) > DELEGATE_RESULT_MAX_CHARS:
        text = text[:DELEGATE_RESULT_MAX_CHARS] + _TRUNCATION_MARKER
    # The child's reply is returned verbatim as data — NEVER parsed for
    # toolRequest/delegateRequest (depth-1 by construction).
    return ("ok", text, _record("ok", usage_sink, pins))


# ── dev/106: the hard-dependency closure ─────────────────────────────────────

_REQUIRED_CLOSURE_MAX_DEPTH = 8


def required_closure(user_key: str, root: AgentManifest) -> tuple[list[str], list[str]]:
    """The transitive ``requiresAgents`` closure of *root*, resolved through
    the same visibility rule the run time uses (``find_visible``).

    Returns ``(coords, missing)``: the visible coords to install, in
    deterministic walk order (root's declaration order, then each dependency's
    own), root excluded; and the agent ids declared required but visible
    nowhere. Cycle-safe and depth-bounded. Pure — installs nothing."""
    coords: list[str] = []
    missing: list[str] = []
    seen: set[str] = {root.agent_id}
    frontier: list[tuple[AgentManifest, int]] = [(root, 0)]
    while frontier:
        parent, depth = frontier.pop(0)
        if depth >= _REQUIRED_CLOSURE_MAX_DEPTH:
            continue
        for agent_id in parent.requires_agents:
            if agent_id in seen:
                continue
            seen.add(agent_id)
            coord, m = find_visible(user_key, agent_id)
            if m is None or coord is None:
                missing.append(agent_id)
                continue
            coords.append(coord)
            frontier.append((m, depth + 1))
    return coords, missing


def required_by(user_key: str, installed: list[str], coord: str) -> list[str]:
    """Installed coords whose ``requiresAgents`` names *coord*'s agent id —
    the dependents an uninstall of *coord* would break."""
    from utk_curio.backend.app.agents import services

    agent_id = coord.split("@", 1)[0]
    dependents: list[str] = []
    for other in sorted(installed):
        if other == coord:
            continue
        m = services._resolve_definition(user_key, other)
        if m is not None and agent_id in m.requires_agents:
            dependents.append(other)
    return dependents
