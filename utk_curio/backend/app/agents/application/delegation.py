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
- **Independent accounting**: the child reserves and settles its own ledger
  pair; the parent's attachment is recorded for attribution only. A child
  failure (provider error, missing prompt) is data the parent recovers from,
  never a parent-run error.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass

from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.agents.domain.manifest import AgentManifest, coord_order, version_order
from utk_curio.backend.app.agents.infrastructure.providers import (
    ChatTurn,
    ReplySchemaRefused,
)
from utk_curio.backend.app.agents.application import catalog
from utk_curio.backend.app.agents.application import dataflow_block as agents_dataflow_block
from utk_curio.backend.app.agents.application.turns import examples as worked_examples
from utk_curio.backend.app.agents.application.turns import policy
from utk_curio.backend.app.agents.application.turns import prompts
from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.repositories import catalog_settings
from utk_curio.backend.app.agents.repositories import ledger
from utk_curio.backend.app.agents.repositories import publications
from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.agents.domain import contracts
from utk_curio.backend.app.agents.application import reply_schemas
from utk_curio.backend.app.agents.infrastructure import provider_config
from utk_curio.backend.app.agents.domain import document_validation

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
    """Installed lockfile coords for one delegate agent id, sorted by major
    for determinism (a project normally installs one major)."""
    return sorted((c for c in installed if c.split("@", 1)[0] == agent_id), key=coord_order)


def resolve(user_key: str, project_id: str, parent: AgentManifest, capability: str) -> Resolution:
    """Resolve *capability* against this project's installed templates —
    capability-first with ``delegatesTo`` as preference (dev/03:366; the
    dev/49-recorded widening landed in memo dev/52).

    Order: (1) the parent's ``delegatesTo`` entries, in declaration order
    (dev/15: order = preference); (2) any other template installed in THIS
    project that declares the capability and that ``delegatesTo`` does not
    name, in sorted-coord order (deterministic tie-break). Never consults
    other projects. When nothing installed matches but a ``delegatesTo``
    entry is visible in the catalog, the outcome is ``not-installed`` (the
    missing-specialist proposal path); a capability nobody declares is
    ``unresolvable``.

    An agent an entry names takes only the capabilities its entry delegates
    (a scoped entry names them): neither fallback reaches it for another.
    The parent's own capabilities reach it the same way, only through an
    entry naming itself (its modes). An internal built-in is never
    installed: it resolves from the roster, so it is ``ok`` wherever the walk
    reaches it, and never an install proposal.
    """
    from utk_curio.backend.app.projects import storage as projects_storage

    spec = projects_storage.read_spec(user_key, project_id)
    installed = set(project_agents.project_agents(spec)) if spec else set()
    return resolve_among(user_key, installed, parent, capability)


def resolve_among(
    user_key: str | None, installed: set[str], parent: AgentManifest, capability: str
) -> Resolution:
    """:func:`resolve` over the lockfile *installed* (its coords), for a caller
    that holds the spec it is writing, such as a plan's apply."""
    missing: Resolution | None = None
    preferred_ids = list(parent.delegates_to)
    for agent_id in preferred_ids:
        if not parent.delegates(agent_id, capability):
            continue  # this entry delegates other capabilities of that agent
        for coord in _candidate_coords(agent_id, installed):
            m = catalog._resolve_definition(user_key, coord)
            if m is not None and capability in m.capability_ids:
                return Resolution("ok", coord, m)
        internal = _internal_resolution(user_key, agent_id, capability)
        if internal is not None:
            return internal
        if missing is None:
            visible_coord, visible_m = find_visible(user_key, agent_id)
            if visible_m is not None and capability in visible_m.capability_ids:
                missing = Resolution("not-installed", visible_coord, visible_m)
    # Capability-first fallback: any other installed template declaring it.
    # An agent delegatesTo names was walked above for what its entry
    # delegates, and takes nothing else; the parent takes only its modes.
    named = {*preferred_ids, parent.agent_id}
    for coord in sorted(installed, key=coord_order):
        if coord.split("@", 1)[0] in named:
            continue
        m = catalog._resolve_definition(user_key, coord)
        if m is not None and capability in m.capability_ids:
            return Resolution("ok", coord, m)
    if missing is None:
        # Nothing installed matches anywhere: the missing-specialist proposal
        # targets a VISIBLE definition declaring the capability (dev/03:366:
        # "a definition already visible to that actor"), in the roster's order.

        for m in builtin.list_builtin_manifests():
            # An internal agent is reached only through a parent that
            # delegates it that capability, which the walk above covers, and
            # so is an agent delegatesTo names.
            if (
                capability in m.capability_ids and not builtin.is_internal(m.dir_name)
                and m.agent_id not in named
            ):
                missing = Resolution("not-installed", m.dir_name, m)
                break
    return missing or Resolution("unresolvable")


def _internal_resolution(user_key: str, agent_id: str, capability: str) -> Resolution | None:
    """The shipped definition of an internal built-in, when it declares
    *capability*."""

    if not builtin.is_internal(agent_id):
        return None
    coord = builtin.builtin_coord(agent_id)
    m = catalog._resolve_definition(user_key, coord)
    if m is not None and capability in m.capability_ids:
        return Resolution("ok", coord, m)
    return None


def find_visible(user_key: str, agent_id: str) -> tuple[str | None, AgentManifest | None]:
    """A visible definition for one agent id, or ``(None, None)``.

    The coordinate Curio ships the id at first (``builtin.builtin_coord``; an
    owned import of that coordinate may shadow it, as everywhere else), so a
    shipped agent is found as it always is. Then the account's own definitions
    of that id and the published ones, at whatever version they have: the
    highest wins."""

    coord = builtin.builtin_coord(agent_id)
    m = catalog._resolve_definition(user_key, coord) if coord is not None else None
    if m is not None:
        return coord, m
    candidates = [
        *(d for d in storage.list_installed_agent_definitions(user_key) if d.agent_id == agent_id),
        *(d for d in publications.list_published() if d.agent_id == agent_id),
    ]
    if not candidates:
        return None, None
    best = max(candidates, key=lambda d: version_order(d.version)).dir_name
    return best, catalog._resolve_definition(user_key, best)


def visible_capability_entries(user_key: str, parent: AgentManifest) -> list[tuple[str, str]]:
    """``(capability_id, delegate name)`` pairs for the run's delegation
    paragraph — only delegates that resolve to a visible definition are
    offered (memo dev/48: the tail names delegation only when resolvable)."""
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for agent_id in parent.delegates_to:
        # An entry for the agent itself names its own modes: it is visible.
        _, m = (None, parent) if agent_id == parent.agent_id else find_visible(user_key, agent_id)
        if m is None:
            continue
        for cap in m.capability_ids:
            if cap not in seen and parent.delegates(agent_id, cap):
                seen.add(cap)
                entries.append((cap, m.name))
    return entries


def offered_capability_entries(
    user_key: str, installed: set[str], parent: AgentManifest
) -> list[tuple[str, str]]:
    """``(capability_id, agent name)`` pairs for a run's delegation paragraph,
    in a dataflow whose lockfile is *installed*: every capability the run can
    hand off, under the name of the agent :func:`resolve_among` would run.

    First the capabilities :func:`visible_capability_entries` offers, in its
    order; a delegate that is visible but not installed keeps its own name,
    since asking for it proposes its install. Then those the capability-first
    fallback reaches: the capabilities of the installed agents ``delegatesTo``
    does not name. An agent an entry names is offered only what its entry
    delegates, and the parent only its own modes."""
    entries: list[tuple[str, str]] = []
    offered: set[str] = set()
    for capability, name in visible_capability_entries(user_key, parent):
        resolved = resolve_among(user_key, installed, parent, capability)
        if resolved.outcome == "ok" and resolved.manifest is not None:
            name = resolved.manifest.name
        offered.add(capability)
        entries.append((capability, name))
    named = {*parent.delegates_to, parent.agent_id}
    for coord in sorted(installed, key=coord_order):
        if coord.split("@", 1)[0] in named:
            continue
        m = catalog._resolve_definition(user_key, coord)
        for capability in (m.capability_ids if m is not None else ()):
            if capability in offered:
                continue
            resolved = resolve_among(user_key, installed, parent, capability)
            if resolved.outcome == "ok" and resolved.manifest is not None:
                offered.add(capability)
                entries.append((capability, resolved.manifest.name))
    return entries


def delegate_name(user_key: str, parent: AgentManifest, capability: str) -> str | None:
    """The name of the visible agent *parent*'s ``delegatesTo`` hands
    *capability* to, the first in its preference order, or None: the entry
    :func:`visible_capability_entries` gives that capability, reading only the
    delegates that may take it."""
    for agent_id in parent.delegates_to:
        if not parent.delegates(agent_id, capability):
            continue
        _, m = (None, parent) if agent_id == parent.agent_id else find_visible(user_key, agent_id)
        if m is not None and capability in m.capability_ids:
            return m.name
    return None


#: The run values the delegated task's frame names, each once: the
#: delegating agent and the capability it asked for.
_FRAME_VALUES = ("parent", "capability")


def _frame_inputs(parent_coord: str, capability: str, inputs: dict) -> str:
    """The parent-supplied inputs as ONE bounded untrusted context message
    (the dev/44 framing pattern: data, never instructions), under the section
    ``delegated-task`` of the base entry's ``frames.md``."""
    import json

    body = json.dumps(inputs, ensure_ascii=False, indent=2) if inputs else "{}"
    frame = _fill_frame(
        agent_text.section(builtin.FRAMES_FILE, "delegated-task"),
        {"parent": parent_coord, "capability": capability},
    )
    return f"{frame}\n{body}"


def _fill_frame(frame: str, values: dict[str, str]) -> str:
    """*frame* with ``{parent}`` and ``{capability}`` each replaced by its run
    value, in one pass, so a value is never read as a placeholder. Raises
    ``agent_text.AgentTextError`` when the frame names either other than once:
    a frame that lost one would drop who asked, or what for."""
    for name in _FRAME_VALUES:
        if frame.count("{" + name + "}") != 1:
            raise agent_text.AgentTextError(
                f"{agent_text.PAGE_PREFIX}{builtin.FRAMES_FILE}, section delegated-task, names "
                f"{{{name}}} {frame.count('{' + name + '}')} times, where it names it once"
            )
    return re.sub(r"\{(" + "|".join(_FRAME_VALUES) + r")\}", lambda match: values[match.group(1)], frame)


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
    dataflow_block: str | None = None,
) -> tuple[str, str, dict]:
    """One synchronous, depth-1 child run (DEC-046 — direct provider-port code).

    *config* is the caller's configuration. The child runs on its own, resolved
    here when it starts (``provider_config.resolve_llm``), so a choice changed
    in API Settings reaches the delegates a running Solve starts after it.

    *dataflow_block*, the block a run that writes code is given
    (``application/dataflow_block.py``), rides a message of its own before the
    task, as a chat run's does before its canvas context. The caller composes
    it, so nothing in *inputs*, which a model may write, becomes it.

    Returns ``(status, result_text, child_record)``: ``status`` is
    ``"ok"``/``"error"``, ``result_text`` is the bounded child reply (or the
    failure reason), and ``child_record`` is the child's execution record —
    own pins, own ledger reserve→settle under the child's effective policy,
    ``parentExecutionId`` link — which the caller stores under the parent
    record's ``delegations``. Never raises: a child failure is data.
    """
    child_id = uuid.uuid4().hex
    started = time.monotonic()

    def _record(status: str, usage: dict, pins: dict) -> dict:
        record = policy._execution_record(child_id, pins, usage, started, status)
        record["parentExecutionId"] = parent_execution_id
        record["coord"] = coord
        record["capability"] = capability
        return record

    try:
        # The child's own choice in API Settings, else its caller's
        # configuration; an internal agent always runs on its caller's.
        config = provider_config.resolve_llm(user_key, coord.split("@", 1)[0], caller=config)
    except provider_config.ProviderConfigError as exc:
        return ("error", f"delegate {coord} could not start: {exc}", _record("error", {}, {"coord": coord}))
    pins: dict = {"coord": coord, "provider": config.api_type, "model": config.model,
                  "llm": provider_config.llm_pin(config)}
    try:
        child = _prepare_child(user_key, project_id, coord, capability, inputs, config,
                               attachment_id=attachment_id, child_id=child_id)
    except _NoInstruction:
        return (
            "error",
            f"delegate {coord} has no instruction prompt available",
            _record("error", {}, pins),
        )
    except Exception as exc:  # resolution/policy failure - data, not an error
        return ("error", f"delegate {coord} could not start: {exc}", _record("error", {}, pins))
    pins = child.pins

    usage_sink: dict = {}
    task = {"role": "user", "content": _frame_inputs(parent_coord, capability, inputs)}
    turns = [*([agents_dataflow_block.message(dataflow_block)] if dataflow_block else []), task]
    try:
        turn = _ask_child(child, turns, usage_sink)
    except Exception as exc:
        ledger.settle(user_key, child.reservation, usage=usage_sink or None, status="error")
        return (
            "error",
            f"delegate {coord} failed: {provider_config.redact_error(exc, config)}",
            _record("error", usage_sink, pins),
        )
    ledger.settle(user_key, child.reservation, usage=usage_sink or None, status="ok")
    text = child.reply.decode(turn.text) if child.reply is not None else turn.text
    if len(text) > DELEGATE_RESULT_MAX_CHARS:
        text = text[:DELEGATE_RESULT_MAX_CHARS] + _TRUNCATION_MARKER
    # The child's reply is returned verbatim as data — NEVER parsed for
    # toolRequest/delegateRequest (depth-1 by construction).
    return ("ok", text, _record("ok", usage_sink, pins))


class _NoInstruction(Exception):
    """The delegate has no instruction prompt materialized: the one start failure with its own wording."""


@dataclass
class _ChildRun:
    """What one depth-1 child run resolved before it asked the provider (memo dev/142 B3): the
    system message builder, the reply schema (if any), the effective policy, its pins and the
    ledger reservation. ``pins`` and ``reply`` are what the schema-refusal retry rewrites."""
    config: object
    manifest: object
    instruction: str
    capability: str
    system_of: object          # (instruction text) -> system message
    system: dict
    reply: object              # ReplySchema | None
    run_policy: dict
    pins: dict
    reservation: object


def _prepare_child(user_key: str, project_id: str, coord: str, capability: str, inputs: dict, config,
                   *, attachment_id: str | None, child_id: str) -> _ChildRun:
    """Resolve the child: its definition and instruction (the capability is the mode: a merged
    agent runs that capability's own instruction), the reply schema when the document has one
    and the provider takes it, the effective policy, the DEC-031 pins, and the ledger
    reservation under the child's own policy. Raises what the caller records as
    "could not start"; :class:`_NoInstruction` when the prompt is not materialized."""
    manifest = catalog._resolve_definition(user_key, coord)
    instruction = prompts._resolve_instruction_text(user_key, coord, capability=capability)
    if instruction is None:
        raise _NoInstruction()
    configuration = (
        catalog_settings.configuration_for(user_key, manifest.config_keys(capability))
        if manifest is not None else None
    )
    preamble = prompts._resolve_prompt_text(user_key, coord, "system")
    spec = projects_storage.read_spec(user_key, project_id)
    examples_block = worked_examples.delegated_block(coord, capability, spec, inputs)

    def _system(text: str) -> dict:
        # Depth-1 structurally: the delegate's own prompts and
        # configuration, NO tool protocol. Its one runtime block is the
        # worked examples, for a mode that takes them, under whichever
        # instruction it runs.
        return contracts.system_message(contracts.compose_system(
            preamble=preamble, instruction=text, configuration=configuration,
            runtime=(examples_block,),
        ))

    # A document with a schema, on a provider that takes one: the reply is
    # held to it, under the instruction written for that.
    reply = _reply_schema(user_key, project_id, manifest, capability, inputs, config)
    constrained = (
        prompts._resolve_prompt_text(user_key, coord, reply_schemas.AUTK_PROMPT_KEY)
        if reply is not None else None
    )
    if not constrained:
        reply = None
    system = _system(constrained or instruction)
    run_policy = policy._run_policy(user_key, project_id, coord, spec or {})
    admit = dict(run_policy["admit"])
    # Attribution only: the parent's attachment key, never its limits.
    admit["attachment_key"] = attachment_id
    pins = {
        "coord": coord,
        # The coordinate names a major; the version says which one ran.
        "version": manifest.version if manifest is not None else None,
        "promptSha256": prompts._prompt_digest(manifest, capability=capability),
        "intentEdited": False,
        "provider": config.api_type,
        "model": config.model,
        "llm": provider_config.llm_pin(config),
        "tools": [],  # structurally tool-less (DEC-046)
        "policy": run_policy["policy_pins"],
        **prompts._configuration_pin(configuration),
    }
    if reply is not None:
        asset = manifest.prompts.get(reply_schemas.AUTK_PROMPT_KEY)
        pins["promptSha256"] = asset.sha256 if asset is not None else None
        pins["replySchema"] = reply.name
    reservation = ledger.reserve(
        user_key, reservation_id=child_id, llm_config_id=config.config_id, **admit
    )
    return _ChildRun(config=config, manifest=manifest, instruction=instruction, capability=capability,
                     system_of=_system, system=system, reply=reply, run_policy=run_policy,
                     pins=pins, reservation=reservation)


def _ask_child(child: _ChildRun, turns: list[dict], usage_sink: dict) -> ChatTurn:
    """One provider call for the child, its *turns* after its system turn (the task last), and,
    when the endpoint takes no reply schema for this model, the same call again, free, under the
    delegate's own instruction (the pins say so)."""

    def _ask(system_message: dict, schema) -> ChatTurn:
        # Through the services-bound provider symbol so the whole run shares
        # one port (and one test seam). No reply schema, no keyword: the call
        # is then exactly what it was before reply schemas.
        extra = {"reply_schema": schema.request()} if schema is not None else {}
        return ChatTurn.of(providers.run_chat_turn(
            child.config, [system_message, *turns],
            max_output_tokens=child.run_policy["max_output_tokens"],
            usage_out=usage_sink, **extra,
        ))

    try:
        return _ask(child.system, child.reply)
    except ReplySchemaRefused:
        reply_schemas.note_refused(child.config)
        child.reply = None
        child.pins["promptSha256"] = prompts._prompt_digest(child.manifest, capability=child.capability)
        child.pins.pop("replySchema", None)
        child.pins["replySchemaRefused"] = True
        return _ask(child.system_of(child.instruction), None)


def _reply_schema(user_key: str, project_id: str, manifest, capability: str, inputs: dict, config):
    """The reply schema a delegated run sends, or None: only a content
    generation run for a node whose document has one, by a definition that
    declares the instruction for writing it, on a provider that takes it
    (``reply_schemas.for_run``)."""

    if capability != "node.content.generate" or manifest is None:
        return None
    if reply_schemas.AUTK_PROMPT_KEY not in manifest.prompts:
        return None
    return reply_schemas.for_run(config, user_key, _document_grammar(user_key, project_id, inputs))


def _document_grammar(user_key: str, project_id: str, inputs: dict) -> str | None:
    """The grammar of the node a content generation run writes for: the
    template roster's ``grammarId``, else the offline table, else None."""
    from utk_curio.backend.app.execution import workflow_spec
    from utk_curio.backend.app.packages import service as packages_services

    node_type = (inputs or {}).get("nodeType") or ((inputs or {}).get("nodeContext") or {}).get("nodeType")
    if not isinstance(node_type, str) or not node_type:
        return None
    try:
        templates = {t["id"]: t for t in packages_services.available_templates(user_key, project_id)}
    except Exception:  # noqa: BLE001 - an unreadable roster falls to the offline table
        templates = None
    return document_validation.grammar_of(node_type, workflow_spec.grammar_id_of(node_type, templates))


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

    agent_id = coord.split("@", 1)[0]
    dependents: list[str] = []
    for other in sorted(installed):
        if other == coord:
            continue
        m = catalog._resolve_definition(user_key, other)
        if m is not None and agent_id in m.requires_agents:
            dependents.append(other)
    return dependents
