"""Typed agent content parts + the structured-tail protocol (memo ``dev/39``).

An agent reply may end with exactly one fenced block::

    ```curio.v1
    {"suggestedPrompts": {"primary": "...", "alternatives": ["..."]}}
    ```

The runtime strips a **terminal** block from the reply, validates it against
the bounded v1 part contracts below, and persists the resulting parts on the
agent turn (`DEC-043`). Fail-open for model content: a malformed, oversized,
or unknown block is *not* stripped — it stays visible exactly as the model
wrote it and no parts attach; nothing the model says is ever silently lost.
Bounds are enforced here, server-side, never trusted from the model.

Part types (v1) and their bounds — the single place limits are named:

- ``suggestedPrompts``: ``{primary, alternatives[]}`` — primary and each
  alternative ≤ 200 chars, ≤ 3 alternatives (de-duplicated), ≤ 1 such part.
- ``card``: ``{kind, title, lines[]}`` — kind ≤ 64, title ≤ 120, ≤ 10 lines
  of ≤ 300 chars, ≤ 4 cards. Cards are informational plain data: no actions,
  no interpreted markup (docs/08 — actions are suggested prompts, not
  buttons). Producers arrive with the P5 composites; the contract and the
  renderer exist now so they have something to land on.
"""

from __future__ import annotations

import json
import re

TAIL_FENCE = "```curio.v1"
TAIL_MAX_BYTES = 4096
MAX_PARTS = 8

_PROMPT_MAX_CHARS = 200
_MAX_ALTERNATIVES = 3
_CARD_KIND_MAX_CHARS = 64
_CARD_TITLE_MAX_CHARS = 120
_CARD_LINE_MAX_CHARS = 300
_CARD_MAX_LINES = 10
_MAX_CARDS = 4

# toolRequest bounds (memo dev/41): one request per reply, small params.
_TOOL_PARAMS_MAX_BYTES = 1024
# delegateRequest bounds (memo dev/48): one request per reply; inputs carry a
# node's intent + context so they get more room than tool params (the whole
# tail is still capped at TAIL_MAX_BYTES).
_DELEGATE_INPUTS_MAX_BYTES = 3072
# Tool ids share the capability grammar (mirrors manifest.CAPABILITY_ID_RE —
# duplicated here so the content contract stays import-light).
_TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+$")

# Proposal display bounds (runtime-emitted part, memo dev/41).
_PROPOSAL_SUMMARY_MAX_CHARS = 200
PROPOSAL_CONTENT_MAX_CHARS = 65536

# dataflowPlan bounds (memo dev/52). The node/edge caps are ABUSE BACKSTOPS,
# never product ceilings — far above what one review meaningfully covers,
# present only so a hostile tail can't allocate unbounded structures. Plans
# get their own tail budget (the classic TAIL_MAX_BYTES was sized for prompts
# and tool requests, dev/39); the practical governors of plan size are
# maxOutputTokens (policy) and per-child quota admission — and large designs
# chain across successive additive plans, so nothing here is a ceiling.
PLAN_TAIL_MAX_BYTES = 256 * 1024
_PLAN_MAX_NODES = 200
_PLAN_MAX_EDGES = 600
_PLAN_GOAL_MAX_CHARS = 300
_PLAN_TEMPLATE_ID_MAX_CHARS = 64
_PLAN_REF_MAX_CHARS = 32
_PLAN_TITLE_MAX_CHARS = 120
_PLAN_INTENT_MAX_CHARS = 300
_PLAN_NODE_TYPE_MAX_CHARS = 120
# dev/59 revision fields: existing node/edge ids (uuids in practice).
_PLAN_REMOVAL_ID_MAX_CHARS = 64

# datasetCandidates bounds (memo dev/50 — the docs/06 two-lane row contract).
# Rows are informational display metadata; every string is bounded here and
# URLs are scheme-allowlisted at parse time (REQ-SEC-002 belt-and-braces —
# rendering still goes through the sanitizer).
_CANDIDATE_LANES = ("external", "catalog")
_CANDIDATE_SOURCE_TYPES = ("api", "endpoint", "portal", "catalog", "document", "database")
_CANDIDATES_MAX_ROWS_PER_LANE = 8
_CANDIDATE_NAME_MAX_CHARS = 120
_CANDIDATE_TEXT_MAX_CHARS = 160
_CANDIDATE_URL_MAX_CHARS = 300

# The runtime-owned instruction appended to every attachment run's system turn
# (after the preamble + intent composition, dev/38 — so an edited intent can
# neither strip nor spoof it). Deliberately optional in tone, and it invites
# only suggestedPrompts: the card contract exists (above) but nothing should
# prompt the model to fabricate result cards before a real producer exists.
TAIL_INSTRUCTION = (
    "When one or more follow-up prompts would help the user continue, you may "
    "end your reply with exactly one fenced block of this form:\n"
    "```curio.v1\n"
    '{"suggestedPrompts": {"primary": "<the single most useful next prompt>", '
    '"alternatives": ["<up to 3 short alternative prompts>"]}}\n'
    "```\n"
    "The block must be the very last thing in the reply, the JSON must be "
    "valid, and each prompt must stay under 200 characters. Omit the block "
    "entirely when no follow-up is useful."
)


def split_tail(reply: str) -> tuple[str, str | None]:
    """Split *reply* into ``(visible_text, tail_body_or_None)``.

    Only a **terminal** block counts: the last `````curio.v1`` fence whose
    closing ``````` is followed by nothing but whitespace. Fenced blocks
    mid-reply (e.g. the model quoting the syntax) are body text.
    """
    if not isinstance(reply, str):
        return reply, None
    idx = reply.rfind(TAIL_FENCE)
    if idx == -1:
        return reply, None
    # The fence must start the reply or its own line.
    if idx > 0 and reply[idx - 1] != "\n":
        return reply, None
    after = reply[idx + len(TAIL_FENCE) :]
    if not after.startswith("\n"):
        return reply, None
    close = after.find("\n```")
    if close == -1:
        return reply, None
    if after[close + 4 :].strip():
        return reply, None  # content after the closing fence — not terminal
    body = after[1:close]
    visible = reply[:idx].rstrip()
    return visible, body


def _valid_prompt(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > _PROMPT_MAX_CHARS:
        return None
    return text


def _parse_suggested_prompts(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    primary = _valid_prompt(raw.get("primary"))
    if primary is None:
        return None
    alts_raw = raw.get("alternatives", [])
    if not isinstance(alts_raw, list) or len(alts_raw) > _MAX_ALTERNATIVES:
        return None
    alternatives: list[str] = []
    for alt in alts_raw:
        text = _valid_prompt(alt)
        if text is None:
            return None
        if text != primary and text not in alternatives:
            alternatives.append(text)
    return {"type": "suggestedPrompts", "primary": primary, "alternatives": alternatives}


def _parse_card(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    title = raw.get("title")
    if not (isinstance(kind, str) and kind.strip() and len(kind) <= _CARD_KIND_MAX_CHARS):
        return None
    if not (isinstance(title, str) and title.strip() and len(title) <= _CARD_TITLE_MAX_CHARS):
        return None
    lines_raw = raw.get("lines", [])
    if not isinstance(lines_raw, list) or len(lines_raw) > _CARD_MAX_LINES:
        return None
    lines: list[str] = []
    for line in lines_raw:
        if not isinstance(line, str) or len(line) > _CARD_LINE_MAX_CHARS:
            return None
        lines.append(line)
    return {"type": "card", "kind": kind.strip(), "title": title.strip(), "lines": lines}


# Per-tool params budgets (dev/55): the plan's toolRequest form carries a
# whole graph — it gets the plan budget; every other tool keeps the classic
# cap byte-identically.
_TOOL_PARAM_BUDGETS = {"dataflow.plan.write": PLAN_TAIL_MAX_BYTES}


def _parse_tool_request(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    tool = raw.get("tool")
    if not (isinstance(tool, str) and _TOOL_ID_RE.match(tool)):
        return None
    params = raw.get("params", {})
    if not isinstance(params, dict):
        return None
    try:
        budget = _TOOL_PARAM_BUDGETS.get(tool, _TOOL_PARAMS_MAX_BYTES)
        if len(json.dumps(params).encode("utf-8")) > budget:
            return None
    except (TypeError, ValueError):
        return None
    return {"type": "toolRequest", "tool": tool, "params": params}


def _bounded_str(value: object, max_chars: int) -> str | None:
    """A non-empty, bounded string — or ``None`` (absent/invalid alike)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > max_chars:
        return None
    return text


def _parse_candidate_row(raw: object, lane: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = _bounded_str(raw.get("name"), _CANDIDATE_NAME_MAX_CHARS)
    if name is None:
        return None
    source_type = raw.get("sourceType")
    if source_type not in _CANDIDATE_SOURCE_TYPES:
        return None
    row: dict = {"name": name, "sourceType": source_type}
    url = raw.get("url")
    if url is not None:
        url_text = _bounded_str(url, _CANDIDATE_URL_MAX_CHARS)
        # Scheme allowlist at parse time: display metadata only, and never a
        # javascript:/data: vector even before the sanitizer sees it.
        if url_text is None or not (
            url_text.startswith("http://") or url_text.startswith("https://")
        ):
            return None
        row["url"] = url_text
    for key in ("provider", "format", "coverage", "requirement"):
        if raw.get(key) is not None:
            text = _bounded_str(raw.get(key), _CANDIDATE_TEXT_MAX_CHARS)
            if text is None:
                return None
            row[key] = text
    fit = raw.get("fit")
    if fit is not None:
        if not isinstance(fit, dict):
            return None
        rationale = _bounded_str(fit.get("rationale"), _CANDIDATE_TEXT_MAX_CHARS)
        score = fit.get("score")
        if rationale is None or not isinstance(score, (int, float)) or not (0 <= score <= 100):
            return None
        row["fit"] = {"score": round(float(score)), "rationale": rationale}
    if lane == "catalog":
        dataset_id = _bounded_str(raw.get("datasetId"), _CANDIDATE_NAME_MAX_CHARS)
        if dataset_id is None:
            return None  # catalog rows are tool-grounded: the id is mandatory
        row["datasetId"] = dataset_id
        row["installed"] = bool(raw.get("installed"))
    return row


def _parse_dataset_candidates(raw: object) -> dict | None:
    """The dev/50 two-lane suggestions part (docs/06). Informational rows —
    selection, multi-select, and confirmation live client-side; a malformed
    row invalidates the whole block (fail-open to text, the T2 rule)."""
    if not isinstance(raw, dict):
        return None
    lanes_raw = raw.get("lanes")
    if not isinstance(lanes_raw, dict):
        return None
    lanes: dict = {}
    total = 0
    for lane in _CANDIDATE_LANES:
        rows_raw = lanes_raw.get(lane, [])
        if not isinstance(rows_raw, list) or len(rows_raw) > _CANDIDATES_MAX_ROWS_PER_LANE:
            return None
        rows = []
        for row_raw in rows_raw:
            row = _parse_candidate_row(row_raw, lane)
            if row is None:
                return None
            rows.append(row)
        lanes[lane] = rows
        total += len(rows)
    if total == 0:
        return None
    return {"type": "datasetCandidates", "lanes": lanes}


def _field_error(where: str, value: object, max_chars: int) -> str | None:
    """A precise, model-correctable description of what is wrong, or None."""
    if not isinstance(value, str):
        return f"{where} must be a string"
    text = value.strip()
    if not text:
        return f"{where} must not be empty"
    if len(text) > max_chars:
        return f"{where} is {len(text)} chars (max {max_chars})"
    return None


def _parse_removal_list(
    raw: object, key: str, max_entries: int, errors: list[str]
) -> list[str]:
    """A bounded, deduplicated list of existing-element ids (dev/59) —
    existence against the saved spec is the MINT's check, not the grammar's."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append(f"{key} must be a list of ids")
        return []
    if len(raw) > max_entries:
        errors.append(f"{key} has {len(raw)} entries (max {max_entries})")
        return []
    out: list[str] = []
    seen: set[str] = set()
    for i, value in enumerate(raw):
        err = _field_error(f"{key}[{i}]", value, _PLAN_REMOVAL_ID_MAX_CHARS)
        if err:
            errors.append(err)
            continue
        entry = str(value).strip()
        if entry in seen:
            errors.append(f"{key}[{i}] duplicates {entry!r}")
            continue
        seen.add(entry)
        out.append(entry)
    return out


def _parse_dataflow_plan_verbose(raw: object) -> tuple[dict | None, list[str]]:
    """The dev/52 typed plan part (DR-1), with field-level errors (dev/54)
    and the dev/59 revision fields (``removeNodes``/``removeEdges``; edge
    endpoints may name existing nodes). The loop feeds errors back so an
    imperfect first attempt self-corrects.
    Returns ``(plan, [])`` on success or ``(None, errors)``."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["dataflowPlan must be an object"]
    err = _field_error("goal", raw.get("goal"), _PLAN_GOAL_MAX_CHARS)
    if err:
        errors.append(err)
    plan: dict = {"type": "dataflowPlan", "goal": str(raw.get("goal") or "").strip()}
    if raw.get("templateId") is not None:
        err = _field_error("templateId", raw.get("templateId"), _PLAN_TEMPLATE_ID_MAX_CHARS)
        if err:
            errors.append(err)
        else:
            plan["templateId"] = str(raw.get("templateId")).strip()
    # dev/59: revision fields parse first — a remove-only plan is valid.
    remove_nodes = _parse_removal_list(raw.get("removeNodes"), "removeNodes", _PLAN_MAX_NODES, errors)
    remove_edges = _parse_removal_list(raw.get("removeEdges"), "removeEdges", _PLAN_MAX_EDGES, errors)
    nodes_raw = raw.get("nodes")
    if nodes_raw is None and (remove_nodes or remove_edges):
        nodes_raw = []  # a remove-only revision carries no new nodes
    if not isinstance(nodes_raw, list) or (not nodes_raw and not (remove_nodes or remove_edges)):
        errors.append("nodes must be a non-empty list (unless the plan only removes)")
        nodes_raw = []
    elif len(nodes_raw) > _PLAN_MAX_NODES:
        errors.append(f"nodes has {len(nodes_raw)} entries (max {_PLAN_MAX_NODES})")
        nodes_raw = []
    nodes: list[dict] = []
    refs: set[str] = set()
    for i, node_raw in enumerate(nodes_raw):
        where = f"nodes[{i}]"
        if not isinstance(node_raw, dict):
            errors.append(f"{where} must be an object")
            continue
        node_errors = [
            e
            for e in (
                _field_error(f"{where}.ref", node_raw.get("ref"), _PLAN_REF_MAX_CHARS),
                _field_error(f"{where}.nodeType", node_raw.get("nodeType"), _PLAN_NODE_TYPE_MAX_CHARS),
                _field_error(f"{where}.title", node_raw.get("title"), _PLAN_TITLE_MAX_CHARS),
                _field_error(f"{where}.intent", node_raw.get("intent"), _PLAN_INTENT_MAX_CHARS),
            )
            if e
        ]
        if node_errors:
            errors.extend(node_errors)
            continue
        ref = str(node_raw["ref"]).strip()
        if ref in refs:
            errors.append(f"{where}.ref {ref!r} is used by an earlier node — refs must be unique")
            continue
        refs.add(ref)
        node = {
            "ref": ref,
            "nodeType": str(node_raw["nodeType"]).strip(),
            "title": str(node_raw["title"]).strip(),
            "intent": str(node_raw["intent"]).strip(),
        }
        node_content = node_raw.get("content")
        if node_content is not None:
            if not isinstance(node_content, str):
                errors.append(f"{where}.content must be a string")
            elif len(node_content) > PROPOSAL_CONTENT_MAX_CHARS:
                errors.append(
                    f"{where}.content is {len(node_content)} chars (max {PROPOSAL_CONTENT_MAX_CHARS})"
                )
            else:
                node["content"] = node_content
        nodes.append(node)
    plan["nodes"] = nodes
    edges_raw = raw.get("edges", [])
    if not isinstance(edges_raw, list):
        errors.append("edges must be a list")
        edges_raw = []
    elif len(edges_raw) > _PLAN_MAX_EDGES:
        errors.append(f"edges has {len(edges_raw)} entries (max {_PLAN_MAX_EDGES})")
        edges_raw = []
    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()
    removed = set(remove_nodes)
    for i, edge_raw in enumerate(edges_raw):
        where = f"edges[{i}]"
        if not isinstance(edge_raw, dict):
            errors.append(f"{where} must be an object")
            continue
        src, dst = edge_raw.get("from"), edge_raw.get("to")
        endpoint_errors = []
        for label, value in (("from", src), ("to", dst)):
            # dev/59: an endpoint outside the plan refs names an EXISTING
            # node — its existence is the mint's spec check; the grammar
            # verifies the string shape and that it isn't a removal victim.
            err = _field_error(f"{where}.{label}", value, _PLAN_REMOVAL_ID_MAX_CHARS)
            if err:
                endpoint_errors.append(err)
            elif str(value).strip() in removed:
                endpoint_errors.append(
                    f"{where}.{label} references {value!r}, which this plan removes"
                )
        if endpoint_errors:
            errors.extend(endpoint_errors)
            continue
        src, dst = str(src).strip(), str(dst).strip()
        if src == dst:
            errors.append(f"{where} connects {src!r} to itself")
            continue
        if (src, dst) in seen_edges:
            errors.append(f"{where} duplicates an earlier {src!r}→{dst!r} edge")
            continue
        seen_edges.add((src, dst))
        edges.append({"from": src, "to": dst})
    plan["edges"] = edges
    # dev/59: keys present only when used — additive plans stay byte-identical.
    if remove_nodes:
        plan["removeNodes"] = remove_nodes
    if remove_edges:
        plan["removeEdges"] = remove_edges
    if errors:
        return None, errors
    return plan, []


def _parse_dataflow_plan(raw: object) -> dict | None:
    """Strict-parse contract (the T2 rule): valid plan or None — the verbose
    sibling carries the correction detail (dev/54)."""
    plan, errors = _parse_dataflow_plan_verbose(raw)
    return plan if not errors else None


def parse_dataflow_plan_verbose(raw: object) -> tuple[dict | None, list[str]]:
    """Public verbose plan parse (dev/55): the mint validates the plan's
    toolRequest form with the same field-level errors the correction rounds
    feed back."""
    return _parse_dataflow_plan_verbose(raw)


# Any fenced block, any info string ("json", "", "curio.v1", …), any position.
_FENCE_RE = re.compile(r"```[A-Za-z0-9.\-]*\n(.*?)\n```", re.DOTALL)


def extract_plan_attempt(reply: str) -> tuple[str, object]:
    """Fence-agnostic plan-attempt recognition (dev/56) — consulted only by
    the plan handler for plan-granted agents, and only after the terminal
    curio.v1 tail paths found nothing.

    Scans every fenced block (models emit ```json / bare fences, often
    mid-reply with prose after) for a plan payload: ``{"dataflowPlan": …}``,
    the toolRequest form, or the bare plan object. Returns
    ``(reply_with_the_block_stripped, payload)`` where payload is the raw
    plan dict, the unparseable block body (``str`` — so the JSON error still
    feeds back), or ``None`` when the reply carries no plan attempt.
    """
    if not isinstance(reply, str) or "```" not in reply:
        return reply, None
    for match in reversed(list(_FENCE_RE.finditer(reply))):
        body = match.group(1)
        marked = "dataflowPlan" in body or "dataflow.plan.write" in body
        bare_shape = '"goal"' in body and '"nodes"' in body
        if not marked and not bare_shape:
            continue
        if len(body.encode("utf-8")) > PLAN_TAIL_MAX_BYTES:
            continue
        stripped = (reply[: match.start()] + reply[match.end() :]).strip()
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            if marked:
                return stripped, body  # a plan-ish block with broken JSON: diagnose it
            continue  # a broken unmarked block is too ambiguous to claim
        if not isinstance(payload, dict):
            continue
        if "dataflowPlan" in payload:
            return stripped, payload["dataflowPlan"]
        req = payload.get("toolRequest")
        if isinstance(req, dict) and req.get("tool") == "dataflow.plan.write":
            params = req.get("params") or {}
            return stripped, params.get("dataflowPlan", params)
        if "goal" in payload and "nodes" in payload:
            return stripped, payload  # the bare plan object itself
    return reply, None


def plan_tail_diagnosis(tail_body: str | None) -> list[str] | None:
    """Classify a terminal tail body as a plan attempt (dev/54).

    ``None`` — not a plan attempt (no ``dataflowPlan`` mention, or a valid
    non-plan payload): generic fail-open applies untouched. ``[]`` — a valid
    plan. ``[errors]`` — a plan attempt with correctable problems, JSON
    breakage included: exactly what the corrective round feeds back.
    """
    if not isinstance(tail_body, str) or (
        "dataflowPlan" not in tail_body and "dataflow.plan.write" not in tail_body
    ):
        return None
    try:
        payload = json.loads(tail_body)
    except (ValueError, TypeError) as exc:
        return [f"the block is not valid JSON: {exc}"]
    if not isinstance(payload, dict) or "dataflowPlan" not in payload:
        return None
    _, errors = _parse_dataflow_plan_verbose(payload["dataflowPlan"])
    return errors


def _parse_delegate_request(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    capability = raw.get("capability")
    if not (isinstance(capability, str) and _TOOL_ID_RE.match(capability)):
        return None
    inputs = raw.get("inputs", {})
    if not isinstance(inputs, dict):
        return None
    try:
        if len(json.dumps(inputs).encode("utf-8")) > _DELEGATE_INPUTS_MAX_BYTES:
            return None
    except (TypeError, ValueError):
        return None
    return {"type": "delegateRequest", "capability": capability, "inputs": inputs}


def parse_parts(body: str) -> list[dict] | None:
    """Validate a tail body into typed parts, or ``None`` when the whole block
    is invalid (bad JSON, over bounds, a malformed known part, or nothing
    usable). Unknown top-level keys are ignored — forward tolerance — but a
    *known* key that fails its contract invalidates the block (fail-open to
    text beats attaching half-validated content).

    Request rules (dev/41, dev/48): a ``proposal`` key is **runtime-emitted
    only** — a model that writes one invalidates the block (fail-open; the
    review flow can never be spoofed from the tail). A valid ``toolRequest``
    or ``delegateRequest`` is exclusive: a request turn is a request turn, so
    other parts alongside it are dropped — and both requests in one tail is
    an invalid block (one request per reply).
    """
    if not isinstance(body, str):
        return None
    body_bytes = len(body.encode("utf-8"))
    if body_bytes > TAIL_MAX_BYTES:
        # Plans get their own budget (dev/52; the toolRequest form too,
        # dev/55): the classic cap was sized for prompts/tool requests. The
        # substring check bounds json.loads cost before parsing; the
        # payload-key check below closes the loophole.
        if body_bytes > PLAN_TAIL_MAX_BYTES or (
            '"dataflowPlan"' not in body and '"dataflow.plan.write"' not in body
        ):
            return None
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if body_bytes > TAIL_MAX_BYTES and "dataflowPlan" not in payload:
        req = payload.get("toolRequest")
        if not (isinstance(req, dict) and req.get("tool") == "dataflow.plan.write"):
            return None  # the enlarged budget is for plan payloads only
    if "proposal" in payload or "proposals" in payload:
        return None  # never accepted from the model (memo dev/41 §4.1)
    if "toolRequest" in payload and "delegateRequest" in payload:
        return None  # one request per reply (memo dev/48)
    if "toolRequest" in payload:
        request = _parse_tool_request(payload["toolRequest"])
        if request is None:
            return None
        return [request]
    if "delegateRequest" in payload:
        request = _parse_delegate_request(payload["delegateRequest"])
        if request is None:
            return None
        return [request]
    parts: list[dict] = []
    if "dataflowPlan" in payload:
        plan = _parse_dataflow_plan(payload["dataflowPlan"])
        if plan is None:
            return None
        parts.append(plan)
    if "datasetCandidates" in payload:
        candidates = _parse_dataset_candidates(payload["datasetCandidates"])
        if candidates is None:
            return None
        parts.append(candidates)
    if "cards" in payload:
        cards_raw = payload["cards"]
        if not isinstance(cards_raw, list) or len(cards_raw) > _MAX_CARDS:
            return None
        for raw in cards_raw:
            card = _parse_card(raw)
            if card is None:
                return None
            parts.append(card)
    if "suggestedPrompts" in payload:
        prompts = _parse_suggested_prompts(payload["suggestedPrompts"])
        if prompts is None:
            return None
        parts.append(prompts)
    if not parts or len(parts) > MAX_PARTS:
        return None
    return parts


def extract_content(reply: str) -> tuple[str, list[dict]]:
    """The runtime entry point: ``(visible_text, parts)`` for one reply.

    A valid terminal tail is stripped and returned as parts; anything else —
    no tail, malformed tail, unknown-only payload — returns the reply
    untouched with no parts (fail-open, §4.2 of memo dev/39).
    """
    visible, body = split_tail(reply)
    if body is None:
        return reply, []
    parts = parse_parts(body)
    if parts is None:
        return reply, []
    return visible, parts


def tail_instruction(grants: list[tuple[str, str]] | None = None) -> str:
    """The system-turn tail instruction for one run (memo dev/41).

    Grant-less runs get :data:`TAIL_INSTRUCTION` byte-identical (regression-
    pinned); runs with granted tools get an appended paragraph enumerating
    exactly the granted ids with their registry descriptions and the
    ``toolRequest`` syntax. The list is server-resolved grants — never the
    manifest's raw declarations.
    """
    if not grants:
        return TAIL_INSTRUCTION
    lines = "\n".join(f"- {tool_id}: {description}" for tool_id, description in grants)
    return (
        f"{TAIL_INSTRUCTION}\n\n"
        "You may also use these tools, granted for this conversation:\n"
        f"{lines}\n"
        "To use one, end your reply with exactly one fenced block of this form "
        "instead (one tool per reply; you will receive the result and can then "
        "answer):\n"
        "```curio.v1\n"
        '{"toolRequest": {"tool": "<tool id>", "params": {}}}\n'
        "```"
    )


def delegation_instruction(entries: list[tuple[str, str]]) -> str:
    """The delegation paragraph for one run's system tail (memo dev/48).

    Composed only when the agent's manifest names delegates that resolve to
    visible definitions — the entries are ``(capability_id, delegate name)``
    pairs the runtime resolved server-side, never the manifest's raw list.
    """
    lines = "\n".join(f"- {cap} — handled by {name}" for cap, name in entries)
    return (
        "You may also delegate these specialized capabilities, granted for "
        "this conversation:\n"
        f"{lines}\n"
        "To delegate, end your reply with exactly one fenced block of this "
        "form instead (one request per reply; you will receive the delegate's "
        "result and can then continue):\n"
        "```curio.v1\n"
        '{"delegateRequest": {"capability": "<capability id>", "inputs": {}}}\n'
        "```"
    )


# Node-content extraction (dev/57): plausible single-field JSON wrappers a
# model may put around generated code.
_CONTENT_WRAPPER_KEYS = ("content", "code", "source", "result")


def extract_node_content(text: object) -> str:
    """Extract the executable content from a model's generated-code reply
    (dev/57) — applied at EVERY model-output→node-content boundary (Solve,
    the node-content mints, plan-carried content, the legacy Get Code path).

    Deterministic and conservative: JSON wrappers with a single plausible
    string field unwrap; when fenced blocks exist, the LARGEST block's body
    is the content (language identifier dropped, surrounding prose discarded
    — that is response formatting, not code); unfenced text is returned
    trimmed and otherwise untouched — preserving legitimate content outranks
    cosmetic cleanup (the legacy ``not controllable`` sentinel passes through
    exactly).
    """
    if not isinstance(text, str):
        return ""
    current = text.strip()
    # Bounded unwrap: a wrapper may contain a fence, or vice versa.
    for _ in range(3):
        # 1. Whole-text JSON wrapper with one plausible content field.
        if current.startswith("{") and current.endswith("}"):
            try:
                payload = json.loads(current)
            except (ValueError, TypeError):
                payload = None
            if isinstance(payload, dict):
                string_fields = [
                    k for k in _CONTENT_WRAPPER_KEYS
                    if isinstance(payload.get(k), str)
                ]
                if len(string_fields) == 1:
                    current = payload[string_fields[0]].strip()
                    continue
        # 2. Fenced blocks: the largest body is the content.
        fences = list(_FENCE_RE.finditer(current))
        if fences:
            largest = max(fences, key=lambda m: len(m.group(1)))
            current = largest.group(1).strip()
            continue
        break
    return current


def make_proposal_part(
    *,
    proposal_id: str,
    tool: str,
    summary: str,
    preview: str,
    pins: dict,
    status: str = "pending",
) -> dict:
    """The runtime-emitted ``proposal`` part (memos dev/41, dev/48).

    Minted only by the runtime when a granted mutate tool is requested; the
    parser above rejects any model-authored proposal. ``pins`` carries the
    tool-specific revision-safety basis the apply endpoint re-checks
    (`REQ-REVIEW-001`): ``{nodeId, contentSha256}`` for ``node.content.write``
    (the target's current content digest); ``{nodeType}`` for ``node.create``
    (no digest — the node id is server-minted at apply, so there is no target
    whose drift can corrupt; the template is re-validated at apply instead).
    """
    return {
        "type": "proposal",
        "proposalId": proposal_id,
        "tool": tool,
        "summary": summary[:_PROPOSAL_SUMMARY_MAX_CHARS],
        "preview": preview,
        "pins": dict(pins),
        "status": status,
    }
