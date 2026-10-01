"""Delegation inside a turn: resolving the delegate, running it traced, and minting candidates, reviews, notes, and drafts from its reply.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging
import json as _json
import re as _re2
import time
import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.application import tools
from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import node_context
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import lifecycle as agents_lifecycle
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application import tools as agents_tools
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)


def _extract_candidates_reply(child_text: str) -> dict | None:
    """dev/114: the child reply's ``datasetCandidates`` payload, or None —
    schema-only recognition (DEC-063): a JSON object, bare or inside ONE fence
    of any language tag (the #269 schema teaches a curio.v1 fence), whose
    ``datasetCandidates.lanes`` is a dict. Chat JSON never matches."""

    if not isinstance(child_text, str) or not child_text.strip():
        return None
    candidates = [child_text.strip()]
    candidates += [m.group(1).strip() for m in _re2.finditer(
        r"```[A-Za-z0-9_.-]*[ \t]*\n(.*?)\n?```", child_text, _re2.DOTALL)]
    for candidate in candidates:
        try:
            payload = _json.loads(candidate)
        except ValueError:
            continue
        block = payload.get("datasetCandidates") if isinstance(payload, dict) else None
        if isinstance(block, dict) and isinstance(block.get("lanes"), dict):
            return block
    return None


def _mint_candidates_from_delegate(
    loop_ctx: dict, child_text: str, catalog_rows: list
) -> tuple[dict | None, str, str]:
    """dev/114: a successful ``dataset.discover`` delegation becomes the
    two-lane ``datasetCandidates`` part on the PARENT's turn — runtime-minted:
    catalog rows not in the runtime's own catalog listing are dropped (tool-
    grounded, never model-claimed), external rows get the DEC-053 verdict, and
    the run is marked so a same-turn node.create is refused (the user reviews
    first). Returns ``(part | None, text_for_model, outcome)``."""
    block = _extract_candidates_reply(child_text)
    if block is None:
        return None, (
            "the Dataset Finder returned no recognizable datasetCandidates block — "
            "report that honestly; do not invent candidates or a source"
        ), "no-candidates"
    known = {str(r.get("id")) for r in catalog_rows if isinstance(r, dict) and r.get("id")}
    lanes = block.get("lanes") or {}
    catalog_raw = lanes.get("catalog") if isinstance(lanes.get("catalog"), list) else []
    kept = [r for r in catalog_raw if isinstance(r, dict) and str(r.get("datasetId")) in known]
    dropped = len(catalog_raw) - len(kept)
    for row in kept:
        # Installed state is the LISTING's, never the child's claim.
        listed = next((r for r in catalog_rows if str(r.get("id")) == str(row.get("datasetId"))), None)
        if listed is not None:
            row["installed"] = bool(listed.get("installed"))
            row.setdefault("name", listed.get("name"))
            row.setdefault("sourceType", "catalog")
    parsed = content._parse_dataset_candidates({"lanes": {
        "external": lanes.get("external") if isinstance(lanes.get("external"), list) else [],
        "catalog": kept,
    }})
    if parsed is None:
        note = f" ({dropped} catalog row(s) dropped — not in the Data Catalog)" if dropped else ""
        return None, (
            "the Dataset Finder returned no usable candidates" + note +
            " — report that honestly; ask the user for a path or URL instead of guessing"
        ), "no-candidates"
    agents_grounding._verify_candidate_parts([parsed], loop_ctx)
    loop_ctx["_candidates_pending_review"] = True
    total = sum(len(v) for v in parsed["lanes"].values())
    note = f" {dropped} catalog row(s) were dropped (not in the Data Catalog)." if dropped else ""
    return parsed, (
        f"{total} dataset candidate(s) are shown to the user for review; external rows "
        "carry the runtime's verification verdict." + note +
        " Do NOT propose a node in this turn — ask the user to select and confirm; "
        "you will build from the confirmed source on the next turn."
    ), "ok"


def _dataset_discover_inputs(user_key: str, project_id: str, inputs: dict) -> dict:
    """dev/114: the sixth DEC-063 application — a tool-less Dataset Finder
    child gets the catalog listing and the reply schema as INPUTS."""
    enriched = dict(inputs)
    if "catalog" not in enriched:
        try:
            rows = tools._catalog_search_rows(user_key, project_id, {})
        except Exception:
            log.warning("Could not list the Data Catalog for a dataset.discover "
                        "delegate (project %s)", project_id, exc_info=True)
            rows = []
        enriched["catalog"] = {
            "note": (
                "The project's Data Catalog as catalog.search returned it"
                if rows else
                "The Data Catalog listing was empty or unavailable — the catalog lane "
                "must stay empty; say so."
            ),
            "rows": rows,
        }
    if "discoveryReplyContract" not in enriched:
        enriched["discoveryReplyContract"] = agents_grounding._DISCOVERY_RULE + "\n\n" + content.CANDIDATES_INSTRUCTION
    return enriched


#: dev/126: capabilities whose node-scoped work homes at the DELEGATE's own
#: node attachment rather than dev/72's Node Builder default — discovery
#: belongs in the chat of the agent that owns it, which is also where the user
#: selects a source. One declaration; every other capability keeps dev/72's
#: behavior byte-for-byte, and so does this one when that agent cannot live on
#: the node (its manifest's compatibleTargets decide).
_HOME_AGENT_BY_CAPABILITY: dict[str, str] = {
    "dataset.discover": "agent.dataset-finder",
    "dataset.select": "agent.dataset-finder",
}


def _delegation_home(
    spec: dict,
    coord: str,
    capability: str,
    inputs: dict,
    *,
    node_id: str | None = None,
    create: bool = True,
    user_key: str | None = None,
) -> tuple[dict | None, bool]:
    """Where a delegated task LIVES (memo dev/72): node-scoped work → the
    target node's Node Builder attachment (dev/71's; best-effort created);
    everything else → an existing attachment of the DELEGATE's agent id
    (canvas-scoped preferred), else a new canvas attachment of the resolved
    coord. Returns ``(record | None, created)`` — best-effort throughout: a
    missing home never fails a delegation. dev/126: a capability in
    ``_HOME_AGENT_BY_CAPABILITY`` homes at its own agent's node attachment."""
    target_node = node_id or (inputs or {}).get("nodeId")
    if isinstance(target_node, str) and target_node:
        home_agent = _HOME_AGENT_BY_CAPABILITY.get(capability)
        if home_agent:
            existing = agents_spec_reads._node_attachment_of(spec, home_agent, target_node)
            if existing is not None:
                return existing, False
            if create:
                node_type = next(
                    (
                        n.get("type") for n in (spec.get("dataflow") or {}).get("nodes") or []
                        if isinstance(n, dict) and n.get("id") == target_node
                    ),
                    None,
                )
                row = agents_plans._attach_node_agent(
                    user_key, spec, home_agent, target_node, node_type
                )
                if row.get("attachmentId"):
                    return attachments.get_attachment(spec, row["attachmentId"]), True
            # That agent cannot live on this node — dev/72's default applies.
        for rec in attachments.list_attachments(spec):
            target = rec.get("target") or {}
            if (
                rec.get("coord", "").split("@", 1)[0] == "agent.node-builder"
                and target.get("kind") == "node"
                and target.get("targetId") == target_node
            ):
                return rec, False
        if create:
            att_id = agents_plans._attach_node_builder(spec, target_node)
            if att_id:
                return attachments.get_attachment(spec, att_id), True
        return None, False
    if builtin.is_internal(coord):
        # An internal agent is never attached, so its work has no home of its
        # own: the parent's trace carries it.
        return None, False
    agent_id = coord.split("@", 1)[0]
    fallback = None
    for rec in attachments.list_attachments(spec):
        if rec.get("coord", "").split("@", 1)[0] == agent_id:
            if (rec.get("target") or {}).get("kind") == "canvas":
                return rec, False
            fallback = fallback or rec
    if fallback is not None:
        return fallback, False
    if not create:
        return None, False
    try:
        rec = attachments.attach(
            spec, coord, {"kind": "canvas"},
            attachment_id=uuid.uuid4().hex, session_id=uuid.uuid4().hex,
        )
        return rec, True
    except Exception:
        return None, False


def _delegation_task_text(capability: str, inputs: dict) -> str:
    """A one-line task summary for the delegated agent's chat — the key
    intent, never the raw inputs dump."""
    parts = [capability]
    for key in ("intent", "question", "url", "endpoint", "nodeType"):
        value = (inputs or {}).get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()[:160]}")
    return " · ".join(parts)[:480]


def _run_delegate_traced(
    user_key: str,
    project_id: str,
    coord: str,
    capability: str,
    inputs: dict,
    config: ProviderConfig,
    *,
    parent_execution_id: str,
    parent_coord: str,
    attachment_id: str | None,
    parent_name: str | None = None,
    node_id: str | None = None,
    home_create: bool = True,
) -> tuple[str, str, dict, str | None]:
    """One delegated task, TRACED (memo dev/72): the DEC-046 seam stays pure —
    this wrapper resolves the task's home attachment, writes the framed task
    turn, runs the child, writes the result turn (bounded reply + a
    structured trace card + the child's execution record), and returns the
    home id alongside the classic tuple. Exactly two turns per task; every
    trace step is best-effort — no delegation ever fails over it."""
    home_attachment_id: str | None = None
    home_session_id: str | None = None
    try:
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is not None:
            home, created = _delegation_home(
                spec, coord, capability, inputs, node_id=node_id, create=home_create,
                user_key=user_key,
            )
            if home is not None:
                home_attachment_id = home.get("attachmentId")
                home_session_id = home.get("sessionId")
                if created:
                    projects_storage.write_spec(user_key, project_id, spec)
    except Exception:
        home_attachment_id = home_session_id = None
    parent_label = parent_name or parent_coord.split("@", 1)[0].replace("agent.", "")
    if isinstance(home_session_id, str):
        try:
            sessions.append_turns(
                user_key, project_id, home_session_id, home_attachment_id,
                [sessions.make_turn(
                    "user",
                    f"[Delegated by {parent_label}] "
                    f"{_delegation_task_text(capability, inputs)}",
                )],
            )
        except Exception:
            pass
    started = time.monotonic()
    status, text, child = delegation.run_delegate(
        user_key, project_id, coord, capability, inputs, config,
        parent_execution_id=parent_execution_id,
        parent_coord=parent_coord,
        attachment_id=attachment_id,
    )
    if isinstance(home_session_id, str):
        try:
            lines = [f"{capability} · {status}"]
            verification = (inputs or {}).get("verification")
            if isinstance(verification, dict):
                detail = verification.get("detail") or verification.get("datasetName") or ""
                lines.append(
                    f"runtime-verified: {verification.get('status')}"
                    + (f" — {detail}" if detail else "")
                )
            lines.append(f"{int((time.monotonic() - started) * 1000)} ms")
            sessions.append_turns(
                user_key, project_id, home_session_id, home_attachment_id,
                [sessions.make_turn(
                    "agent",
                    (text or "")[:2000],
                    error=status != "ok",
                    execution=child,
                    content=[{
                        "type": "card",
                        "kind": "result" if status == "ok" else "error",
                        "title": f"Delegated task · {status}",
                        "lines": [l[:300] for l in lines[:10]],
                    }],
                )],
            )
        except Exception:
            pass
    return status, text, child, home_attachment_id


def _delegation_part_for(resolution, capability: str, status: str, text: str,
                         home_attachment_id: str | None, child: dict | None = None) -> dict:
    manifest = getattr(resolution, "manifest", None)
    pins = (child or {}).get("pins") or {}
    return content.make_delegation_part(
        capability=capability,
        coord=getattr(resolution, "coord", "") or "",
        name=getattr(manifest, "name", None) or getattr(resolution, "coord", "") or capability,
        category=getattr(manifest, "category", "") or "",
        attachment_id=home_attachment_id,
        status=status,
        summary=(text or "")[:200],
        model=str(pins.get("model") or ""),
        llm_label=str((pins.get("llm") or {}).get("label") or ""),
    )


def _delegate_target_node_id(loop_ctx: dict, inputs: dict) -> str | None:
    """The node a content-generation delegation targets: the model's
    ``nodeId`` input, else the parent attachment's node target — the same
    resolution ``_enriched_delegate_inputs`` grounds the child with."""
    node_id = (inputs or {}).get("nodeId")
    if isinstance(node_id, str) and node_id:
        return node_id
    target = loop_ctx.get("target")
    if isinstance(target, dict) and target.get("kind") == "node":
        target_id = target.get("targetId")
        if isinstance(target_id, str) and target_id:
            return target_id
    return None


def _mint_content_review_from_delegate(
    user_key: str,
    project_id: str,
    *,
    node_id: str,
    generated_text: str,
    parent_attachment_id,
    parent_session_id,
    local_turn: bool = False,
    parent_loop_ctx: dict | None = None,
    validation: dict | None = None,
    grounding_base: dict | None = None,
) -> tuple[dict | None, str | None, str]:
    """dev/73: the ONE content→review sequence (the Solve drain's, extracted):
    a successful ``node.content.generate`` delegation becomes a reviewed
    ``node.content.write`` proposal minted by the RUNTIME — applyability
    never depends on the model re-emitting the content as a second
    toolRequest.

    Mints at the dev/72 delegation home (the node's own agent) when one
    exists — find-only; the traced delegation already created it when it
    could — else at the parent attachment. The review turn is written at a
    foreign home (the parent's composed turn carries the part locally);
    ``local_turn=True`` (the Solve drain, which composes no parent parts)
    writes it unconditionally. Returns ``(proposal_part | None,
    home_attachment_id, text_for_model)`` — on failure the text is the
    honest refusal to feed back.
    """
    text_out = content.extract_node_content(generated_text)
    home_att, home_sess = parent_attachment_id, parent_session_id
    node_label = node_id
    try:
        fresh_spec = projects_storage.read_spec(user_key, project_id)
        home, _ = _delegation_home(
            fresh_spec or {}, "agent.node-builder", "node.content.generate", {},
            node_id=node_id, create=False,
        )
        if home is not None:
            home_att = home.get("attachmentId")
            home_sess = home.get("sessionId")
        for node in ((fresh_spec or {}).get("dataflow") or {}).get("nodes") or []:
            if isinstance(node, dict) and node.get("id") == node_id:
                node_label = (node.get("goal") or node_id)[:60]
                break
    except Exception:
        pass
    # dev/114: the mint's grounding gate reads the PARENT run's evidence
    # (current message, verified rows, probe cache, grants) — the home
    # session alone would not know what the user just typed.
    mint_ctx = {
        k: v for k, v in (parent_loop_ctx or {}).items()
        if k in ("message", "_verified_urls", "_egress_budget", "_probe_cache", "granted", "manifest")
    }
    mint_ctx.update({"attachment_id": home_att, "session_id": home_sess})
    if grounding_base is not None:
        # dev/115: a job thread holds no request context — the gate grounds
        # against the batch's precomputed catalog refs, not a live listing.
        mint_ctx["_grounding_base"] = grounding_base
    p_status, p_error, part = agents_mint._mint_node_content_write(
        user_key, project_id,
        mint_ctx,
        {"tool": "node.content.write",
         "params": {"nodeId": node_id, "content": text_out}},
    )
    if part is None:
        return None, home_att, (
            "the generated content could not become a reviewed proposal "
            f"({(p_error or 'unknown error')[:200]}) — report this honestly: "
            "nothing was changed and nothing awaits review"
        )
    if validation:
        # dev/115: an EXECUTED review carries its verdict and attempt trail —
        # stamped before the turn is written so the persisted part has it.
        part["validation"] = dict(validation)
    if isinstance(home_sess, str) and (local_turn or home_att != parent_attachment_id):
        try:
            sessions.append_turns(
                user_key, project_id, home_sess, home_att,
                [sessions.make_turn(
                    "agent",
                    f"Proposed content for {node_label!r} — review and apply it below.",
                    content=[part],
                )],
            )
        except Exception:
            pass
    where = (
        "in this conversation"
        if home_att == parent_attachment_id
        else "at the node's own Node Builder agent"
    )
    return part, home_att, (
        f"the generated content was minted as reviewed proposal "
        f"{part['proposalId']} for node {node_id!r} ({where}); it awaits the "
        "user's explicit Apply — summarize the change in one or two "
        "sentences, do NOT restate the code, and do NOT say it was applied"
    )


# dev/90: the package-authoring capabilities whose delegation success feeds
# the delegate-draft mint below (the Package Builder's surface; the
# `package.create-or-extend` intent resolves to these). Canonical definition
# lives in content.py (dev/90 A6 — the tail contract sizes their inputs).
PACKAGE_AUTHORING_CAPABILITIES = content.PACKAGE_AUTHORING_CAPABILITIES


# dev/90 A8: the build-request contract, supplied to AUTHORING delegates as
# an input. DEC-046 children are tool-less and never see the grants paragraph
# where the tool schema lives — a live run showed the child inventing a
# plausible-but-wrong shape ("package"/"behaviors"/"behaviorKey") twice, and
# the parent cannot teach a schema it does not carry either. The runtime is
# the one place that always knows the contract (the dev/67-6 enrichment
# pattern: deterministic server-side inputs, never model-invented).
_BUILD_REQUEST_CONTRACT: dict = {
    "reply": (
        "Reply with ONE JSON object of exactly this shape (optionally inside "
        "a ```json fence), nothing after it. Do NOT invent other keys — "
        "there is no 'package', 'behaviors', or 'behaviorKey' key."
    ),
    # memo dev/94: the SECOND legal reply. "Reuse first" was previously a rule
    # with no reachable outcome on this path — the delegate had no shape in
    # which to say "one of these already does it", so the only reply the
    # runtime recognised was a draft, and authoring was the only way to answer
    # at all. Teaching the shape is the A8 lesson again: nobody emits a
    # protocol they were never shown.
    "insteadOfAuthoring": (
        "When one of inputs.existingPackages already satisfies the need, "
        "author NOTHING and reply with ONE JSON object of exactly this shape "
        "instead of a draft: {\"reuseExisting\": {\"dirName\": \"<its "
        "dirName>\", \"reason\": \"<one line: what it already does>\"}}. That "
        "is a complete, successful answer — the caller acts on it (enlisting "
        "the package if it is not yet in the project). Prefer extending an "
        "existing package (mode 'extend') over creating a near-duplicate."
    ),
    "shape": {
        "mode": "create | extend",
        "baseDigest": "<64-hex digest of the installed target — extend only>",
        "manifest": {
            "id": ("reverse-DNS: two or more dot-separated lowercase segments, "
                   "e.g. 'curio.notes' — single-segment ids are invalid"),
            "version": "1.0.0",
            "name": "<display name>",
            "publisher": "<author>",
            "description": "<one line>",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "<kebab-case template id>",
                "label": "<display label>",
                "category": "visualization",
                "engine": "python | javascript",
                "editor": "code | widgets | grammar | none",
                "behavior": "<the behavior key your source registers — custom looks only>",
                "hasCode": False,
                "hasWidgets": False,
                "hasGrammar": False,
                "inputPorts": [],
                "outputPorts": [],
                "backendHandler": ("<declared backend handler name this "
                                   "template's Run invokes — backend "
                                   "templates only>"),
            }],
            "backend": {
                "entry": "backend/handler.py",
                "handlers": [{"name": "<a-z0-9- name>",
                              "timeoutClass": "quick | standard"}],
            },
        },
        "files": {"sources/<name>.tsx": {"text": "<complete file body>"}},
        "behaviorEntries": ["sources/<name>.tsx"],
        "previewTemplates": ["<each template id with a custom behavior>"],
        "nodes": [{
            "templateId": "<template id>",
            "title": "<node title>",
            "content": "<the fixed note/body text>",
            "appearance": {"backgroundColor":
                           "yellow|pink|blue|green|orange|lavender|#rrggbb"},
        }],
    },
    "rules": [
        "a presentation-only template is engine 'javascript', editor 'none', "
        "hasCode false, empty ports",
        "the behavior source registers EXACTLY the template's behavior key: "
        "window.curio.registerBehavior(key, (data, nodeState) => "
        "({ contentComponent: <React element> })) — import react normally, "
        "render React elements only, never raw HTML",
        "field contract: the note text arrives as data.code (data.content is "
        "an equivalent alias), the title as data.title, the per-instance "
        "color as data.appearance.backgroundColor (also nodeState.appearance."
        "backgroundColor) — read THESE fields, never invented ones",
        "prefer ZERO JS dependencies — write small rendering logic yourself",
        "the caller's inputs.notes ARE the requested nodes: copy each "
        "{title, content, color} into nodes[] VERBATIM — never invent "
        "placeholder content, never leave content empty when the caller "
        "supplied findings (the runtime enforces this reconciliation)",
        # memo dev/91: the backend authoring contract, stated where the
        # delegate can see it (the A8 lesson — nobody invents a schema they
        # were shown).
        "server-side compute (dev/91): declare manifest.backend "
        "{entry: 'backend/<file>.py', handlers: [{name, timeoutClass}]} plus "
        "the 'server-code' permission in manifest.permissions ('server-network' "
        "too if and only if the code reaches the network); the entry exposes "
        "def handle(payload) (or a HANDLERS dict {name: callable}); a node run "
        "delivers payload {'content': <editor text>, 'input': <upstream JSON "
        "or null>} and the returned value must be JSON-serializable",
        "import declared python dependencies INSIDE the handler function "
        "(lazily), never at module level — they install at Apply into the "
        "package's isolated overlay and do not exist when the build's probe "
        "loads the entry (a module-level import of a declared dependency "
        "fails the probe by construction)",
        "backend code is pure Python + declared python dependencies, executed "
        "in a per-invocation sandboxed worker with strict limits: NO "
        "subprocess/multiprocessing/ctypes, NO eval/exec/compile/__import__/"
        "importlib, NO flask/blueprints/resident servers (the build's policy "
        "scan blocks these and the probe phase must pass before review); a "
        "capped persistent dir rides CURIO_PKG_DATA_DIR; no secrets and no "
        "dataset store exist in the worker — a need beyond this contract "
        "(resident service, credentials) is a FINDING naming dev/89 "
        "Follow-up B, never smuggled code",
    ],
}


def _extract_reuse_finding(child_text: str) -> dict | None:
    """The child's "one of these already does it" answer, or None (dev/94).

    Deterministic and schema-keyed, never a heuristic over prose: the contract
    teaches exactly ``{"reuseExisting": {"dirName": …, "reason": …}}``, and
    only that shape counts. Guessing at intent from free text would put model
    wording in charge of control flow, which is precisely the mistake the
    typed-tail protocol exists to avoid.
    """

    if not isinstance(child_text, str) or not child_text.strip():
        return None
    candidates: list[str] = []
    stripped = child_text.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)
    for match in _re2.finditer(
            r"```(?:json|curio\.v1)?\s*\n(.*?)```", child_text, _re2.DOTALL):
        candidates.append(match.group(1).strip())
    for candidate in candidates:
        try:
            payload = _json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        finding = payload.get("reuseExisting")
        if not isinstance(finding, dict):
            continue
        dir_name = finding.get("dirName")
        if isinstance(dir_name, str) and dir_name.strip():
            reason = finding.get("reason")
            return {
                "dirName": dir_name.strip()[:120],
                "reason": reason.strip()[:300] if isinstance(reason, str) else "",
            }
    return None


def _reuse_finding_text(user_key: str, project_id: str, finding: dict) -> str:
    """What the parent is told when the delegate declines to author.

    Names the package and, load-bearing for the parent's next move, whether
    this project has it: an enlisted package can be used straight away, a
    store-only one needs the reviewed ``package.install`` first (dev/93 D4's
    middle rung). Unknown enlistment state simply omits the hint.
    """
    dir_name = finding["dirName"]
    reason = f" — {finding['reason']}" if finding.get("reason") else ""
    hint = ""
    try:
        from utk_curio.backend.app.packages import service as packages_services

        enlisted = dir_name in packages_services.get_project_lockfile(user_key, project_id)
        hint = (
            " It is already in this project: use it directly."
            if enlisted else
            " It is installed but NOT in this project: propose package.install "
            f"for {dir_name} first, then use its template."
        )
    except Exception:  # noqa: BLE001 — an unknown lockfile just omits the hint
        pass
    return (
        f"the authoring delegate reports that {dir_name} already does this{reason}. "
        f"Nothing was authored, which is the correct outcome.{hint} Do NOT ask for "
        "a new package that duplicates it."
    )


#: dev/95 (Follow-up D): the server-owned reply schema for a delegated
#: ``research.notes.compose`` — taught via inputs (the A8 posture: the child
#: answers to a schema it can SEE, never a shape it must invent) and
#: recognized ONLY by this schema at the mint (DEC-063: never by reading
#: intent out of prose).
_NOTES_REPLY_CONTRACT: dict = {
    "reply": (
        "Reply with ONE JSON object of exactly this shape (optionally inside "
        "a ```json fence), nothing after it."
    ),
    "shape": {
        "answer": "<the prose answer to the question — always present>",
        "nodeType": ("<one 'id' from inputs.notesTemplates — omit when that "
                     "list is empty>"),
        "notes": [{
            "title": "<short note title>",
            "content": "<the finding as clean markdown — bold fact labels, "
                       "'- ' bullets, [source](https://...) links>",
            "color": "yellow|pink|blue|green|orange|lavender|#rrggbb",
        }],
    },
    "rules": [
        "compose findings ONLY from inputs.searchResults — when it carries "
        "an 'error', say in 'answer' that search was unavailable and reply "
        "with an empty notes list; NEVER invent findings from memory",
        "the reference row (dev/90 A13): the FIRST note carries the user's "
        "question verbatim (title 'Question', color yellow); then one green "
        "note per answer with a subject title and every web-gathered fact "
        "linked to its source",
        "an empty notes list is valid when nothing should be placed "
        "(no template installed, or no findings)",
    ],
}


#: Bounds on the runtime-gathered search rows injected into a delegation —
#: the child's context is finite; five sourced rows beat fifty raw ones.
_DELEGATED_SEARCH_MAX_ROWS = 5


_DELEGATED_SEARCH_FIELD_CHARS = 300


def _delegated_search_results(question: object) -> dict:
    """dev/95: ONE egress-policed search, executed by the RUNTIME for a
    tool-less ``research.notes.compose`` child (the dev/67-4 posture —
    exactly how ``research.verify`` children get runtime-run validator
    evidence). Failures ride in as their honest error text: the child must
    SAY search was unavailable, never invent findings."""
    if not isinstance(question, str) or not question.strip():
        return {"error": "no 'question' input was supplied to the delegation"}

    status, text = agents_tools._execute_web_search({"q": question.strip()})
    if status != "ok":
        return {"error": text}

    try:
        rows = _json.loads(text).get("results") or []
    except (ValueError, AttributeError):
        return {"error": "the search provider returned malformed JSON"}
    bounded = []
    for row in rows[:_DELEGATED_SEARCH_MAX_ROWS]:
        if not isinstance(row, dict):
            continue
        bounded.append({
            key: str(row.get(key) or "")[:_DELEGATED_SEARCH_FIELD_CHARS]
            for key in ("title", "url", "snippet")
        })
    return {"query": question.strip(), "results": bounded}


def _extract_notes_reply(child_text: str) -> dict | None:
    """The child reply's ``notesReplyContract`` payload, or None.

    Schema-only recognition (DEC-063): a JSON object — bare, or inside one
    ```/```json fence — whose ``notes`` key is a LIST counts; nothing else
    does. Answer-only replies still carry ``"notes": []`` per the contract,
    so arbitrary chat JSON never matches by accident."""

    if not isinstance(child_text, str) or not child_text.strip():
        return None
    candidates = [child_text.strip()]
    candidates += [m.group(1).strip() for m in _re2.finditer(
        r"```(?:json)?[ \t]*\n(.*?)\n?```", child_text, _re2.DOTALL)]
    for candidate in candidates:
        try:
            payload = _json.loads(candidate)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("notes"), list):
            return payload
    return None


#: dev/95: the A13 defaults the runtime fills when a reply row omits its
#: color — question note yellow, answer notes green (user/model-chosen colors
#: always win; defaults only fill absences).
_NOTES_DEFAULT_COLORS = ("yellow", "green")


#: dev/105 A2: a node header is a short line — bounded like the goal.
_NODE_TITLE_MAX_CHARS = 120


def _notes_agent_run(loop_ctx: dict) -> bool:
    """True when the run's manifest declares ``research.notes.compose`` — the
    ONE capability whose node.create defaults follow the A13 row (dev/105
    A2). Keyed on the capability, never the agent id."""
    manifest = loop_ctx.get("manifest")
    return "research.notes.compose" in (getattr(manifest, "capability_ids", None) or [])


def _mint_notes_from_delegate(
    user_key: str, project_id: str, loop_ctx: dict, child_text: str,
) -> tuple[list, str, str]:
    """dev/95 (Follow-up D): the one-mint-policy extended to note sequences.

    A successful ``research.notes.compose`` delegation whose bounded child
    reply matches the notes schema becomes reviewed ``node.create``
    proposals minted by the RUNTIME at the parent's attachment — one per
    note, a same-run A16 jointly-pending sequence (apply in any order), each
    row re-validated through ``_mint_node_create`` (the ONE creation lane:
    dev/93 template vocabulary, A12 content bounds, dev/89 appearance
    normalization). Gated on the PARENT's ``node.create`` grant (the
    ``_mint_package_draft_from_delegate`` posture). Degradations land as
    text with the way out named: no grant, no/invalid template (→ the
    Researcher's own attachment owns the enlist/author ladder — depth-1
    keeps it out of reach here), every row refused.

    Returns ``(proposal_parts, text_for_model, outcome)`` — outcome "ok"
    when the delegation produced its answer (notes minted, legitimately
    empty, or honestly skipped for a missing template), "failed" when the
    reply broke the contract or notes existed but nothing could mint.
    """
    payload = _extract_notes_reply(child_text)
    if payload is None:
        return [], (
            "the delegate's reply did not match the notes reply contract "
            "(ONE JSON object with 'answer' and a 'notes' list) — nothing "
            "was placed; the reply was kept as text"
        ), "failed"
    answer = payload.get("answer")
    answer = answer.strip() if isinstance(answer, str) else ""
    rows = _notes_from_delegate_inputs({"notes": payload.get("notes")}) or []
    if not rows:
        # Empty notes is a VALID reply (no findings / no template offered) —
        # the answer is the product (dev/93 D5: this run produced it).
        return [], (answer or "the delegate returned no answer and no notes"), "ok"
    if "node.create" not in (loop_ctx.get("granted") or []):
        return [], (
            (f"{answer}\n\n" if answer else "")
            + "the delegate composed notes but this agent is not granted "
              "node.create — the notes were kept as text only"
        ), "failed"
    node_type = payload.get("nodeType")
    entry = err = None
    if isinstance(node_type, str) and node_type.strip():
        entry, err = agents_roster._available_template(user_key, project_id, node_type.strip())
    if entry is None:
        reason = (
            f"the chosen notes template was not available ({err})"
            if err else "no installed notes template was available"
        )
        return [], (
            (f"{answer}\n\n" if answer else "")
            + f"notes skipped: {reason} — ask the Researcher (attached to a "
              "node or the canvas) to enlist or author a notes package; its "
              "own runs hold the reuse ladder a delegate cannot reach"
        ), "ok"
    parts: list = []
    last_refusal = ""
    for index, row in enumerate(rows):
        appearance = row.get("appearance") or {
            "backgroundColor": _NOTES_DEFAULT_COLORS[min(index, 1)]}
        req = {"params": {
            "nodeType": entry["id"],
            "content": row["content"],
            # dev/105 A2: the row's title is the note's HEADER (what the
            # behavior renders), not its purpose line.
            **({"title": row["title"]} if row.get("title") else {}),
            "appearance": appearance,
        }}
        status, text, part = agents_mint._mint_node_create(user_key, project_id, loop_ctx, req)
        if status == "proposed" and part is not None:
            parts.append(part)
        else:
            last_refusal = text
    if not parts:
        return [], (
            (f"{answer}\n\n" if answer else "")
            + f"no notes could be proposed: {last_refusal}"
        ), "failed"
    summary = (
        (f"{answer}\n\n" if answer else "")
        + f"{len(parts)} reviewed note proposal(s) created"
        + (f" ({last_refusal})" if last_refusal else "")
        + " — they await the user's explicit Apply; do NOT claim the notes exist"
    )
    return parts, summary, "ok"


def _extract_draft_params(child_text: str) -> dict | None:
    """The child reply's build-request payload, or None.

    Thin wrapper over :func:`_extract_draft_params_verbose` — see there for
    the accepted shapes and for why the failure reason matters.
    """
    params, _ = _extract_draft_params_verbose(child_text)
    return params


def _extract_draft_params_verbose(child_text: str) -> tuple[dict | None, str]:
    """The child reply's build-request payload, or ``(None, why_not)``.

    Accepted shapes (the reply is already bounded by
    ``delegation.DELEGATE_RESULT_MAX_CHARS``): the whole reply as one JSON
    object, or one fenced ```/```json/```curio.v1 block containing it; the
    object may be the build request itself, wrapped as
    ``{"packageDraft": {...}}``, or — dev/90 A7, the instruction-faithful
    delegate shape — a ``package.draft.apply`` toolRequest whose ``params``
    are the request (a tool-less child that follows its own tool teaching
    emits exactly that; the payload is unwrapped, never executed as a tool).
    A candidate must carry ``mode`` + ``manifest`` to count — arbitrary JSON
    in a chatty reply never parses as a draft by accident.

    The REASON is the point (memo dev/93 D5). Returning a bare ``None`` made
    this a dead end for the parent: the runtime discarded the reply and said
    "refine the delegation inputs and try again" with no parse error, no
    offending fragment, and no line number — so the parent's "refinement" was
    to re-delegate under a DIFFERENT package id, which is how one weather
    question produced two near-identical note packages in a single run. A
    correction round needs something to correct against; the shape here
    mirrors ``_parse_dataflow_plan_verbose``, which plans have had since
    dev/54.
    """

    if not isinstance(child_text, str) or not child_text.strip():
        return None, "the delegate replied with no text at all"
    candidates: list[str] = []
    stripped = child_text.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)
    for match in _re2.finditer(
            r"```(?:json|curio\.v1)?\s*\n(.*?)```", child_text, _re2.DOTALL):
        candidates.append(match.group(1).strip())
    if not candidates:
        return None, (
            "no JSON build request found in the reply: it must be ONE JSON "
            "object, either the whole reply or a single ```json fenced block. "
            "Prose describing the package is not a build request"
        )
    decode_errors: list[str] = []
    shape_errors: list[str] = []
    for candidate in candidates:
        try:
            payload = _json.loads(candidate)
        except (ValueError, TypeError) as exc:
            decode_errors.append(str(exc))
            continue
        if not isinstance(payload, dict):
            shape_errors.append(f"the JSON is a {type(payload).__name__}, not an object")
            continue
        tool_req = payload.get("toolRequest")
        if (isinstance(tool_req, dict)
                and tool_req.get("tool") == "package.draft.apply"
                and isinstance(tool_req.get("params"), dict)):
            payload = tool_req["params"]  # dev/90 A7: unwrap, never execute
        wrapped = payload.get("packageDraft")
        inner = wrapped if isinstance(wrapped, dict) else payload
        if (isinstance(inner, dict) and inner.get("mode") in ("create", "extend")
                and isinstance(inner.get("manifest"), dict)):
            return inner, ""
        keys = ", ".join(sorted(k for k in inner if isinstance(k, str))[:12]) or "none"
        shape_errors.append(
            "the JSON parsed but is not a build request — it must carry "
            f"\"mode\" ('create' or 'extend') and a \"manifest\" object (top-level "
            f"keys were: {keys})"
        )
    if decode_errors and not shape_errors:
        # The overwhelmingly common weak-model failure: a long body containing
        # an embedded source file, cut off mid-string. Say so explicitly —
        # "invalid JSON" alone does not tell the model what to do differently.
        return None, (
            f"the JSON did not parse ({decode_errors[0]}). If the reply was cut "
            "off mid-object, re-emit the COMPLETE build request and keep the "
            "file bodies short enough to finish"
        )
    return None, (shape_errors or decode_errors)[0]


def _notes_from_delegate_inputs(inputs: dict) -> list[dict] | None:
    """The parent's findings as typed note rows (dev/90 A12), or None.

    Accepts ``inputs.notes`` (or ``inputs.findings``): a list of objects with
    non-empty string ``content`` (the finding text — the reason the note
    exists), optional ``title``, optional ``color`` /
    ``appearance.backgroundColor``. Malformed rows are skipped; an empty
    result is None (nothing to enforce).
    """
    raw = inputs.get("notes") or inputs.get("findings")
    if not isinstance(raw, list):
        return None
    rows: list[dict] = []
    for item in raw[:16]:
        if not isinstance(item, dict):
            continue
        content_text = item.get("content")
        if not isinstance(content_text, str) or not content_text.strip():
            continue
        row: dict = {"content": content_text}
        title = item.get("title")
        if isinstance(title, str) and title.strip():
            row["title"] = title.strip()
        color = item.get("color")
        if not isinstance(color, str) or not color:
            appearance = item.get("appearance")
            color = (appearance or {}).get("backgroundColor") if isinstance(
                appearance, dict) else None
        if isinstance(color, str) and color:
            row["appearance"] = {"backgroundColor": color}
        rows.append(row)
    return rows or None


def _reconcile_draft_notes(params: dict, notes: list[dict]) -> bool:
    """dev/90 A12: the PARENT's findings are authoritative note content.

    When the delegation inputs carried notes, they replace the draft's
    ``nodes[]`` wholesale — the child owns the LOOK (manifest, behavior
    source), the parent owns the FACTS, and the runtime marries them
    deterministically (models are never trusted to relay content; the live
    failure was child-invented filler and empty notes). The template comes
    from the draft itself: the first preview template when declared, else
    the manifest's first template. Returns True when a replacement happened.
    """
    manifest = params.get("manifest")
    if not isinstance(manifest, dict):
        return False
    template_id = None
    preview = params.get("previewTemplates")
    if isinstance(preview, list) and preview and isinstance(preview[0], str):
        template_id = preview[0]
    if template_id is None:
        for template in manifest.get("templates") or []:
            if isinstance(template, dict) and isinstance(template.get("id"), str):
                template_id = template["id"]
                break
    if template_id is None:
        return False
    params["nodes"] = [{"templateId": template_id, **row} for row in notes]
    return True


# How many extra attempts a delegated draft gets, mirroring the node-content
# path's ``_VALIDATE_CORRECTION_ROUNDS``. Plans have had correction rounds
# since dev/54 and generated node content since dev/67; the delegated package
# draft was the ONE mutation lane with none, and a weak local model emitting a
# long JSON body containing an embedded source file gets it slightly wrong as
# the NORMAL case, not the exception (memo dev/93 D5).
_DRAFT_CORRECTION_ROUNDS = 2


def _mint_package_draft_from_delegate(
    user_key: str, project_id: str, loop_ctx: dict, child_text: str,
    delegate_inputs: dict | None = None,
    redelegate=None,
) -> tuple[dict | None, str, str]:
    """dev/90: the dev/73 one-mint-policy extended to package drafts.

    A successful package-authoring delegation whose bounded child reply
    parses as a build request becomes a reviewed ``package.draft.apply``
    proposal minted by the RUNTIME at the parent's attachment — depth-1
    children are structurally tool-less, so the delegate can never emit the
    toolRequest itself. The mint reuses ``_mint_package_draft_apply``
    verbatim (one build/validation path); a reply that does not parse, a
    parent without the ``package.draft.apply`` grant, or a draft the build
    service refuses are all data the parent recovers from in chat — never a
    silent drop, never an unreviewed mutation.

    dev/93 D5 adds the CORRECTION ROUNDS every other mutation lane already
    had. ``redelegate(inputs) -> (status, text)`` re-runs the SAME delegate
    with ``previousAttempt`` + ``validationError`` appended to its inputs, so
    the model that made the mistake is the one that fixes it, against the real
    error. The package id from the first parseable draft is PINNED across
    rounds: a delegate that renames its package mid-correction is failing the
    correction, not authoring a new package — renaming is exactly what
    happened when the parent had no error to act on (curio.notes, then
    curio.postits, in one run).

    Returns ``(proposal_part | None, text_for_model, outcome)`` where outcome
    is ``"ok"`` only when a proposal was minted. The caller passes that to the
    delegation part instead of the child RUN's status, so a card can never
    read "Delegated task · ok" beside a summary saying nothing was produced.
    """
    if "package.draft.apply" not in (loop_ctx.get("granted") or []):
        return None, (
            "the delegate produced a package draft but this agent is not "
            "granted package.draft.apply — the draft was kept as text only"
        ), "failed"

    notes = _notes_from_delegate_inputs(delegate_inputs or {})
    pinned_package_id: str | None = None
    attempt_text = child_text
    last_error = ""
    rounds = 1 + (_DRAFT_CORRECTION_ROUNDS if redelegate is not None else 0)

    for round_index in range(rounds):
        # dev/94: "one of these already does it" is a COMPLETE answer, checked
        # before the draft parse — the doctrine is reuse-first, so a reply that
        # names a reuse target is deliberately declining to author and must not
        # be read as a failed draft. It spends NO correction rounds (nothing
        # failed) and reports "ok": dev/93 D5's rule is that a run producing
        # NOTHING must not claim success, and this run produced the answer.
        finding = _extract_reuse_finding(attempt_text)
        if finding is not None:
            return None, _reuse_finding_text(user_key, project_id, finding), "ok"
        params, parse_error = _extract_draft_params_verbose(attempt_text)
        if params is not None:
            draft_id = (params.get("manifest") or {}).get("id")
            if pinned_package_id is None and isinstance(draft_id, str):
                pinned_package_id = draft_id
            if (pinned_package_id is not None and isinstance(draft_id, str)
                    and draft_id != pinned_package_id):
                parse_error = (
                    f"this correction changed the package id from "
                    f"{pinned_package_id!r} to {draft_id!r}. Fix the SAME "
                    "package — a rename does not resolve the error, it just "
                    "creates a duplicate package"
                )
                params = None
        if params is not None:
            # dev/90 A12: the parent's findings override the draft's nodes —
            # the reference contract is "the agent's answer IS the note", and
            # the live failures were child-invented filler / empty notes.
            reconciled = _reconcile_draft_notes(params, notes) if notes else False
            status, text, part = agents_mint._mint_package_draft_apply(
                user_key, project_id, loop_ctx, {"params": params}
            )
            if status == "proposed":
                if reconciled:
                    text += (
                        f" (the draft's {len(notes)} note(s) carry the caller's "
                        "findings verbatim — runtime-reconciled from the "
                        "delegation inputs)"
                    )
                if round_index:
                    text += f" (after {round_index} correction round(s))"
                return part, text, "ok"
            # The build service refused. Some refusals cannot improve by
            # re-authoring (a policy or permission verdict); retrying those
            # would burn the parent's rounds to reach the same answer.
            last_error = text
            if not _draft_refusal_is_correctable(text):
                return None, text, "failed"
        else:
            last_error = parse_error

        if redelegate is None or round_index == rounds - 1:
            break
        status, attempt_text = redelegate({
            "previousAttempt": (attempt_text or "")[:6000],
            "validationError": last_error[:2000],
        })
        if status != "ok":
            return None, (
                "the authoring delegate could not be re-run to correct its "
                f"draft ({attempt_text or 'no reply'}); the last error was: "
                f"{last_error}"
            ), "failed"

    spent = f" after {rounds} attempt(s)" if rounds > 1 else ""
    return None, (
        f"the authoring delegate produced no usable package draft{spent}. The "
        f"last error was: {last_error} — fix THAT and keep the same package id, "
        "or tell the user plainly that authoring failed. Do NOT re-delegate "
        "under a different package name, and if a package that already does "
        "this job is listed as installed, use it instead of authoring one"
    ), "failed"


def _draft_corrector(
    user_key: str, project_id: str, loop_ctx: dict, req: dict, resolution,
    config, execution_id: str, delegations: list,
):
    """A ``redelegate(extra_inputs) -> (status, text)`` for the draft loop.

    Re-runs the SAME delegate, at the same coordinate and capability, with the
    original inputs plus ``previousAttempt``/``validationError`` — the shape
    the node-content path has used since dev/67, so a delegate that already
    understands self-correction there needs no new teaching here. Every
    attempt is traced: its execution record joins ``delegations`` exactly like
    the first, so the rounds are visible in the transcript rather than being
    an invisible retry.
    """
    def _redelegate(extra: dict) -> tuple[str, str]:
        inputs = dict(req.get("inputs") or {})
        inputs.update(extra)
        status, text, child, _home = _run_delegate_traced(
            user_key,
            project_id,
            resolution.coord,
            req["capability"],
            _enriched_delegate_inputs(
                user_key, project_id, loop_ctx, req["capability"], inputs,
            ),
            config,
            parent_execution_id=execution_id,
            parent_coord=loop_ctx["coord"],
            attachment_id=loop_ctx.get("attachment_id"),
            parent_name=getattr(loop_ctx.get("manifest"), "name", None),
        )
        delegations.append(child)
        return status, text

    return _redelegate


def _draft_refusal_is_correctable(refusal: str) -> bool:
    """Whether re-authoring could plausibly fix a build-service refusal.

    A malformed manifest, a bad file, a failed probe: the model can fix those.
    A permission or policy verdict is the build service's answer, not a typo —
    re-running the delegate would spend the parent's rounds arriving at the
    same refusal (memo dev/93 edge cases 31/37).
    """
    text = (refusal or "").lower()
    terminal = (
        "policy blocked", "permission", "not granted", "conflict",
        "is built-in", "already installed",
    )
    return not any(marker in text for marker in terminal)


# Bounds for the authoring delegate's reuse evidence (memo dev/94). The payload
# has to bound ITSELF: delegation._frame_inputs applies no size limit to the
# inputs body (only the child's REPLY is capped), so an account with a large
# package store would otherwise crowd the child's context.
_REUSE_EVIDENCE_MAX_PACKAGES = 40


_REUSE_EVIDENCE_MAX_TEMPLATES = 8


_REUSE_EVIDENCE_DESC_CHARS = 200


def _authoring_reuse_evidence(user_key: str, project_id: str) -> dict | None:
    """What already exists, for a TOOL-LESS authoring delegate (memo dev/94).

    The Package Builder's instruction opens with "Reuse first. Before authoring
    anything, read packages.catalog … never a duplicate package" — and it holds
    that tool only as a direct attachment. As a DEC-046 delegate it runs
    structurally tool-less, which is the path packages are actually authored
    on, so its first instruction was unexecutable and it had no way to know:
    one weather question produced two near-identical note packages while a
    usable one sat in the user's store. The runtime therefore serves the
    evidence the instruction depends on, exactly as it already serves the
    build-request contract (dev/90 A8) and verification results (dev/67-4).

    ``installedInProject`` is CARRIED, not filtered on: both answers are
    actionable and they differ — an enlisted package means "extend or reuse
    it", an installed-but-not-enlisted one means "report it, the parent can
    enlist it" (dev/93 D4's middle rung). Collapsing them would recreate the
    one-bucket mistake that caused this.

    Returns None when there is nothing to report (or the registry is
    unreadable) — honest absence, and the delegation proceeds either way.
    """
    from utk_curio.backend.app.packages import service as packages_services

    try:
        # ONE snapshot for the whole payload (memo dev/99 R2). This used to
        # call three public readers, each of which independently resolved the
        # project lockfile and walked the package store — three spec reads and
        # three traversals to build one piece of evidence. The composite also
        # makes the payload coherent once the seed lock reaches readers: every
        # part of it then describes the same instant, instead of three
        # individually-consistent reads that can straddle a seeding pass.
        landscape = packages_services.template_landscape(user_key, project_id)
        rows = landscape["catalog"]
        # Template ids make ``mode: "extend"`` followable rather than a guess.
        # Both listings are canonical and unversioned; keyed by packageId so a
        # row can name what it would be extending.
        by_package: dict[str, list[str]] = {}
        for entry in landscape["available"] + landscape["notEnlisted"]:
            package_id = str(entry["id"]).split("/", 1)[0]
            ids = by_package.setdefault(package_id, [])
            if entry["id"] not in ids:
                ids.append(entry["id"])
    except Exception:  # a broken registry degrades to no evidence, never a 500
        log.warning(
            "Could not compose reuse evidence for project %s — the authoring "
            "delegate will run without it", project_id, exc_info=True,
        )
        return None

    packages: list[dict] = []
    for row in rows[:_REUSE_EVIDENCE_MAX_PACKAGES]:
        item = {
            "dirName": row["dirName"],
            "name": row["name"],
            "description": (row.get("description") or "")[:_REUSE_EVIDENCE_DESC_CHARS],
            "installedInProject": bool(row.get("installed")),
        }
        templates = by_package.get(row["packageId"]) or []
        if templates:
            item["templates"] = templates[:_REUSE_EVIDENCE_MAX_TEMPLATES]
        packages.append(item)
    if len(rows) > len(packages):
        log.warning(
            "Reuse evidence truncated for project %s: %d of %d packages listed",
            project_id, len(packages), len(rows),
        )
    if not packages:
        return None
    return {
        "note": (
            "Packages that already exist for this user. If one of these already "
            "satisfies the requested need, say so and author nothing — name its "
            "dirName so the caller can use it (installedInProject false means the "
            "caller must enlist it first). Extend one by name instead of creating "
            "a near-duplicate."
        ),
        "packages": packages,
    }


def _enriched_delegate_inputs(
    user_key: str, project_id: str, loop_ctx: dict, capability: str, inputs: dict
) -> dict:
    """dev/67-6: content-generation delegates get the composed node context
    appended server-side (never overwriting the model's own keys) — the child
    stops generating blind to the graph. The node resolves from the model's
    ``nodeId`` input or the parent attachment's node target; no node, no
    enrichment (honest absence beats a fabricated neighborhood)."""
    if capability == "research.verify" and "verification" not in inputs:
        # dev/67-4: DEC-046 children are structurally tool-less — the runtime
        # runs the deterministic validators and the child synthesizes over
        # REAL evidence (the researcher's own attachment runs use the web
        # tools directly).
        url = inputs.get("url") or inputs.get("endpoint")
        if isinstance(url, str) and url.strip():
            return {**inputs, "verification": verify.verify_external_source(url)}
        return inputs
    if capability in PACKAGE_AUTHORING_CAPABILITIES:
        # dev/90 A8: tool-less authoring delegates get the build-request
        # contract server-side — the child answers to a schema it can SEE,
        # never a shape it has to invent (the model's own keys always win).
        if "buildRequestContract" not in inputs:
            inputs = {**inputs, "buildRequestContract": _BUILD_REQUEST_CONTRACT}
        # dev/94: and the reuse evidence its instruction's first line depends
        # on — "read packages.catalog before authoring" names a tool a
        # delegate does not have.
        if "existingPackages" not in inputs:
            evidence = _authoring_reuse_evidence(user_key, project_id)
            if evidence:
                inputs = {**inputs, "existingPackages": evidence}
        return inputs
    if capability == "research.notes.compose":
        # dev/95 (Follow-up D) — the FIFTH runtime-supplied-inputs application
        # (dev/67-4 verification, dev/67-6 nodeContext, A8 contract, dev/94
        # existingPackages): a DEC-046 child holds no web tools and cannot
        # browse the roster, so the runtime gathers the ONE policed search,
        # offers the installed presentation templates as candidates, and
        # teaches the reply schema. Model-supplied keys always win.
        enriched = dict(inputs)
        if "searchResults" not in enriched:
            enriched["searchResults"] = _delegated_search_results(
                enriched.get("question"))
        if "notesTemplates" not in enriched:
            from utk_curio.backend.app.packages import service as packages_services

            enriched["notesTemplates"] = packages_services.presentation_templates(
                user_key, project_id)
        if "notesReplyContract" not in enriched:
            enriched["notesReplyContract"] = _NOTES_REPLY_CONTRACT
        return enriched
    if capability == "dataset.discover":
        # dev/114 — the SIXTH runtime-supplied-inputs application (DEC-063):
        # a tool-less Dataset Finder child cannot run catalog.search, so the
        # runtime lists the catalog for it and teaches the ONE reply schema
        # (#269's). Model-supplied keys always win.
        return _dataset_discover_inputs(user_key, project_id, inputs)
    if capability != "node.content.generate" or "nodeContext" in inputs:
        return inputs
    node_id = inputs.get("nodeId")
    if not isinstance(node_id, str) or not node_id:
        target = loop_ctx.get("target")
        node_id = (
            target.get("targetId")
            if isinstance(target, dict) and target.get("kind") == "node"
            else None
        )
    if not node_id:
        return inputs
    spec = projects_storage.read_spec(user_key, project_id)
    composed = node_context.compose_node_context(user_key, project_id, spec, node_id)
    if composed is None:
        return inputs
    enriched = {**inputs, "nodeContext": composed}
    # dev/114 — the SEVENTH application: a data-loading node's content child
    # is HANDED its grounded sources (catalog paths, the user's paths, the
    # URLs already verified) instead of guessing a filename.
    from utk_curio.backend.app.packages import service as packages_services

    node_type = composed.get("nodeType")
    if "sourceGrounding" not in enriched and source_grounding.is_data_loading_type(
        packages_services.canonical_template_id(node_type)
    ):
        enriched["sourceGrounding"] = agents_grounding._source_grounding_inputs(
            agents_grounding._grounding_context(user_key, project_id, loop_ctx, node_type=node_type,
                               extra_texts=(str(inputs.get("intent") or ""),))
        )
    return enriched


def _resolve_delegate_request(
    user_key: str, project_id: str, loop_ctx: dict, req: dict, minted: list
) -> tuple[str, str, "delegation.Resolution | None"]:
    """Resolution half of one delegateRequest (memo dev/48): ``("ok", ...)``
    with the resolution when a child run may start; otherwise the refusal /
    missing-specialist result to feed back (proposals appended to *minted*)."""
    capability = req.get("capability", "")
    manifest = loop_ctx.get("manifest")
    if manifest is None or not manifest.delegates_to:
        return "refused", "this agent declares no delegates", None
    resolution = delegation.resolve(user_key, project_id, manifest, capability)
    if resolution.outcome == "ok":
        return "ok", "", resolution
    if resolution.outcome == "not-installed":
        # DEC-080 (dev/126): a REQUIRED delegate that is missing is a closure
        # the user already consented to — repaired once, here, instead of
        # stalling the conversation on an install proposal for it. A merely
        # PREFERRED delegate keeps the reviewed install lane below
        # (`REQ-ORCH-001`), unchanged.
        dependency_id = (resolution.coord or "").split("@", 1)[0]
        required_ids = {
            c.split("@", 1)[0]
            for c in delegation.required_closure(user_key, manifest)[0]
        }
        if dependency_id in required_ids and agents_lifecycle._repair_required_closure(
            user_key, project_id, loop_ctx.get("coord") or "",
            attachment_id=loop_ctx.get("attachment_id"),
        ):
            retried = delegation.resolve(user_key, project_id, manifest, capability)
            if retried.outcome == "ok":
                return "ok", "", retried
        status, text, part = agents_mint._mint_project_install(
            user_key,
            project_id,
            loop_ctx,
            resolution.coord,
            resolution.manifest.name if resolution.manifest else resolution.coord,
            capability,
        )
        if part is not None:
            minted.append(part)
        return status, text, None
    return (
        "refused",
        f"no delegate of this agent declares capability {capability!r}",
        None,
    )
