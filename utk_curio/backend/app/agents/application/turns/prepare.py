"""Preparing one turn (messages, grants, context) and persisting the exchange.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging

from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import tools
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import contracts
from utk_curio.backend.app.agents.infrastructure import chat_capabilities
from utk_curio.backend.app.agents.infrastructure import provider_config
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import catalog_settings
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import lifecycle as agents_lifecycle
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.turns import policy as agents_policy
from utk_curio.backend.app.agents.application.turns import prompts as agents_prompts
from utk_curio.backend.app.agents.application.turns import roster as agents_roster

log = logging.getLogger(__name__)


def _prepare_run(
    user_key: str,
    project_id: str,
    attachment_id: str,
    message: str,
    config: ProviderConfig,
    run_context: str | None = None,
) -> tuple[str, str | None, list, dict, bool, dict]:
    """Shared run/stream setup: resolve the attachment, its instruction (intent
    override → prompt source, dev/19), the provider messages including the
    bounded session context (dev/20), and the effective run policy (dev/24).
    Returns ``(coord, session_id, messages, run_policy, wants_title, pins,
    loop_ctx)``; ``session_id`` is None for a record without one (stateless
    fallback), ``wants_title`` is True when this message is the conversation's
    first — an untitled, never-manually-renamed attachment with no prior user
    turn — so a title should be auto-generated after the reply (memo dev/25),
    ``pins`` are the DEC-031 reproducibility pins resolved from what actually
    dispatches (memo dev/37): coord, prompt digest, intent-edited flag,
    provider/model, granted tools (dev/39), and the effective-policy snapshot
    (no secrets), and ``loop_ctx`` carries what the dev/41 tool loop needs
    (granted ids + the attachment target). A required manifest tool that
    resolves no grant refuses the run here — validation stage, before
    admission, so it consumes no quota."""
    spec, record, coord = _resolve_run_target(user_key, project_id, attachment_id)
    manifest = agents_catalog._resolve_definition(user_key, coord)
    requested_tools = manifest.tools if manifest is not None else []
    missing = tools.missing_required(requested_tools)
    if missing:
        raise AgentServiceError(
            f"required tool(s) not available for this agent: {', '.join(sorted(missing))}", 422
        )
    instruction = record.get("intent") or agents_prompts._resolve_instruction_text(user_key, coord)
    if instruction is None:
        raise AgentServiceError(
            f"no instruction prompt available for {coord!r} (not materialized)", 422
        )
    # An edited intent replaces the instruction slot only, so the preamble,
    # the configuration and every runtime-owned slot still apply
    # (contracts.compose_system).
    preamble = agents_prompts._resolve_prompt_text(user_key, coord, "system")
    configuration = (
        catalog_settings.configuration_for(user_key, manifest.config_keys())
        if manifest is not None else None
    )
    # Grant-less runs keep the T2 tail byte-identical; granted runs get the
    # toolRequest paragraph (memos dev/39/41).
    granted = tools.resolve_grants(requested_tools)
    runtime_blocks = _roster_blocks(user_key, project_id, manifest, granted)
    # Delegation (dev/48, DEC-046): offered only when the manifest names
    # delegates that resolve to visible definitions — server-resolved, never
    # the manifest's raw list.
    entries: list = []
    if manifest is not None and manifest.delegates_to:
        entries = delegation.visible_capability_entries(user_key, manifest)
    native_tools = _native_tools_for(config, user_key, granted, entries)

    fenced_system = _system_content(preamble, instruction, configuration, granted, runtime_blocks, entries, native=False)
    system = (
        _system_content(preamble, instruction, configuration, granted, runtime_blocks, entries, native=True)
        if native_tools else fenced_system
    )
    session_id = record.get("sessionId")
    if not isinstance(session_id, str):
        session_id = None
    prior = sessions.read_turns(user_key, project_id, session_id) if session_id else []
    messages = _messages(system, prior, run_context, message)
    wants_title = (
        not record.get("title")
        and not record.get("titleEdited")
        and not any(t.get("role") == "user" for t in prior)
    )
    run_policy = agents_policy._run_policy(user_key, project_id, coord, spec, record)
    pins = _run_pins(coord, manifest, record, config, granted, run_policy, configuration,
                     protocol=("native" if native_tools else "fenced") if granted or entries else None)
    loop_ctx = {
        "granted": granted,
        "target": record.get("target"),
        "attachment_id": attachment_id,
        "session_id": session_id,
        # Delegation context (dev/48): the parent's identity + manifest for
        # delegatesTo resolution inside the loop.
        "coord": coord,
        "manifest": manifest,
        # The tool protocol (_RunConversation): the native tools offered, and
        # the fenced system turn a refusal of them falls back to.
        "native_tools": native_tools,
        "fenced_system": fenced_system,
    }
    return coord, session_id, messages, run_policy, wants_title, pins, loop_ctx


def _resolve_run_target(user_key: str, project_id: str, attachment_id: str) -> tuple[dict, dict, str]:
    """The spec, the attachment record and its coord — after DEC-080 (dev/126): a project whose
    lockfile predates this agent's requiresAgents declaration gets it completed HERE, before the
    messages are composed, so the run resolves its required delegates instead of stalling on a
    reviewed install for one of them."""
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    coord = record.get("coord", "")
    if agents_lifecycle._repair_required_closure(user_key, project_id, coord, attachment_id=attachment_id):
        spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
        record = agents_spec_reads._record_or_404(spec, attachment_id)
    return spec, record, coord


def _roster_blocks(user_key: str, project_id: str, manifest, granted: list) -> list:
    """The runtime blocks a run's grants earn: the live template roster (dev/48, dev/52, dev/93)
    and, for a run that can enlist, what the user owns but this project has not enlisted (dev/93 D4)."""
    runtime_blocks: list[str | None] = []
    # Reuse-first (dev/48; plans too, dev/52): a grant that can put a template
    # on the canvas, into the project, or author a new one carries the live
    # template roster, composed fresh per run from the packages registry — the
    # prompt bytes never bake in template ids, and the model is never left to
    # guess. dev/93 commit 4 widened this from node.create/dataflow.plan.write
    # to package.install and package.draft.apply so it covers every agent that
    # declares the `installedTemplates` read, which let the duplicate
    # client-side roster be retired: an authoring agent especially needs to see
    # what already exists, since not seeing it is how one weather question
    # produced two near-identical note packages.
    if not agents_roster._ROSTER_GRANTS.isdisjoint(granted):
        # dev/99 R1.1: ONE snapshot feeds both halves of the roster. Fetching
        # them separately left the two lists able to describe different
        # instants — a package could appear as "not enlisted" in one and be
        # missing from the other — which is the tear the composite exists to
        # remove.
        from utk_curio.backend.app.packages import service as packages_services

        try:
            landscape = packages_services.template_landscape(user_key, project_id)
        except Exception as exc:  # a broken registry degrades to no listing, not a 500
            # dev/105: but never SILENTLY — a vanished roster is the dev/93 D2
            # failure shape (a swallowed cause surfacing layers away as "that
            # template is not available"), so the cause is logged here.
            log.warning(
                "Template roster unavailable for project %s (%s: %s) — run "
                "proceeds without it", project_id, type(exc).__name__, exc,
            )
            landscape = None
        templates_block = agents_roster._available_templates_block(
            project_id, landscape,
            notes_agent="research.notes.compose" in (
                getattr(manifest, "capability_ids", None) or []
            ),
        )
        runtime_blocks.append(templates_block)
        # dev/93 D4: the second half of the roster — what the user owns but
        # this project has not enlisted — goes only to a run that can act on
        # it. Offering it without the grant would name a door the model
        # cannot open, which is how the Researcher ended up authoring a
        # duplicate package instead.
        if "package.install" in granted:
            runtime_blocks.append(agents_roster._enlistable_templates_block(
                project_id, landscape, agents_roster._TEMPLATES_BLOCK_MAX_ENTRIES
            ))
    return runtime_blocks


def _system_content(preamble, instruction, configuration, granted: list, runtime_blocks: list, entries: list,
                    *, native: bool) -> dict:
    """The system message for one protocol — the two differ only in how a tool or a delegate is asked for."""
    blocks = list(runtime_blocks)
    if entries:
        blocks.append(content.delegation_instruction(entries, native_tools=native))
    return contracts.system_message(contracts.compose_system(
        preamble=preamble,
        instruction=instruction,
        configuration=configuration,
        tool_protocol=content.tail_instruction(
            tools.grant_descriptions(granted), native_tools=native
        ),
        runtime=blocks,
    ))


def _messages(system: dict, prior: list, run_context: str | None, message: str) -> list[dict]:
    """The provider messages: the system turn, the bounded session context, the ephemeral grounded
    context (memo dev/44 — the client-composed live-canvas inputs ride ONE provider message per
    send, recomputed fresh each time, never persisted, never replayed; absent → byte-identical to
    before), and the message."""
    context_block = agents_policy._bounded_context(run_context)
    return [
        system,
        *sessions.context_messages(prior),
        *(
            [{"role": "user", "content": f"{agents_policy._CONTEXT_FRAME}{context_block}"}]
            if context_block
            else []
        ),
        {"role": "user", "content": message},
    ]


def _run_pins(coord: str, manifest, record: dict, config: ProviderConfig, granted: list, run_policy: dict,
              configuration, *, protocol: str | None) -> dict:
    """The DEC-031 reproducibility pins resolved from what actually dispatches (memo dev/37)."""
    return {
        "coord": coord,
        "promptSha256": agents_prompts._prompt_digest(manifest),
        "intentEdited": bool(record.get("intent")),
        "provider": config.api_type,
        "model": config.model,
        # Which LLM configuration answered, never its key.
        "llm": provider_config.llm_pin(config),
        # Granted tool ids (dev/39): requested ∩ registry ∩ policy.
        "tools": granted,
        "policy": run_policy["policy_pins"],
        **agents_prompts._configuration_pin(configuration),
        # How the run asks for a tool or a delegate, when it can ask at all.
        **({"toolProtocol": protocol} if protocol else {}),
    }


def _native_tools_for(
    config: ProviderConfig, user_key: str, granted: list, entries: list
) -> list | None:
    """The run's tools and delegates as native tools, when its LLM
    configuration calls tools natively (``chat_capabilities``); None puts the
    run on the fenced protocol. A run with nothing to call asks nothing."""
    if not granted and not entries:
        return None
    try:
        protocol = chat_capabilities.chat_capabilities(config, user_key).protocol
    except Exception as exc:  # the question never fails a run: it runs fenced
        log.warning("Could not tell whether %s calls tools natively (%s: %s); using the fenced protocol",
                    config.model, type(exc).__name__, exc)
        return None
    if protocol != "native":
        return None
    return tools.native_tools(granted, [capability for capability, _ in entries])


def _persist_exchange(
    user_key: str,
    project_id: str,
    session_id: str | None,
    attachment_id: str,
    message: str,
    reply: str,
    *,
    error: bool = False,
    execution: dict | None = None,
    parts: list | None = None,
) -> None:
    """Persist one exchange to the session (no-op without a session id). Error
    markers are display-only history, excluded from future context (dev/20).
    The execution record (dev/37) and content parts (dev/39) ride the agent
    turn."""
    if session_id is None:
        return
    sessions.append_turns(
        user_key,
        project_id,
        session_id,
        attachment_id,
        [
            sessions.make_turn("user", message),
            sessions.make_turn("agent", reply, error=error, execution=execution, content=parts),
        ],
    )
