"""Verified content rounds: attempts, carry-forward, probes, declines, remedies, and the attempts transcript part (memos dev/115, dev/127, dev/129).

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging
import hashlib
import io
import queue as _queue
import re as _re
import threading
import time
import tokenize

from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import contracts
from utk_curio.backend.app.agents.domain import document_validation
from utk_curio.backend.app.agents.domain import failure_text
from utk_curio.backend.app.agents.domain import input_contract
from utk_curio.backend.app.agents.domain import node_context
from utk_curio.backend.app.agents.domain import result_shape
from utk_curio.backend.app.agents.domain import upstream_schema
from utk_curio.backend.app.agents.infrastructure import egress
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.domain import validation as agents_validation
from utk_curio.backend.app.execution import workflow_spec

log = logging.getLogger(__name__)


#: dev/127: why the repair loop stopped. Every failure sentence names one, so
#: "not fixed after N attempts" can never again read as a verdict on the code
#: when it was a verdict on the round cap.
STOPPED_BY_PHRASES = {
    "rounds": "the attempt ceiling",
    "budget": "this node's time budget",
    "repeat": "a repeated attempt",
    "decline": "the builder's decline",
    "blocker": "an upstream blocker",
    "generation": "a generation error",
    "infrastructure": "a sandbox outage",
    "passed": "success",
    # dev/126's lane: the source is with the user, so the loop stopped ON PURPOSE.
    "source": "a source the user must confirm",
    # dev/131: the session's own endings.
    "complete": "nothing left to do",
    "stopped": "you stopped it",
    "budget": "this session's time budget",
    "blocked": "a specialist that must be installed first",
}


def _stopped_by_clause(stopped_by: object) -> str:
    """`" (stopped by this node's time budget)"`, or `""` when unrecorded."""
    phrase = STOPPED_BY_PHRASES.get(str(stopped_by or ""))
    return f" (stopped by {phrase})" if phrase and stopped_by != "passed" else ""


def _attempt_code_field(candidate: object, *, prose: bool = False) -> dict:
    """The attempt's ``code`` (+ ``codeIsProse``/``codeTruncated``) fields."""
    text = candidate if isinstance(candidate, str) else ""
    if not text.strip():
        return {}
    field: dict = {}
    if len(text) > agents_budgets._ATTEMPT_CODE_CHARS:
        field["code"] = text[:agents_budgets._ATTEMPT_CODE_CHARS] + agents_budgets._CODE_TRUNCATION_MARKER
        field["codeTruncated"] = True
    else:
        field["code"] = text
    if prose:
        # dev/115: the builder's sanctioned decline is prose, not content — the
        # card must not render it as code the user could run.
        field["codeIsProse"] = True
    return field


def _content_sha(text: str) -> str:

    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


#: Attempt kinds whose detail is read from the HEAD (a refusal names the
#: literal, a decline names the missing input); a traceback reads from its tail.
_HEAD_FIRST_KINDS = (
    "ungrounded-source", "source-missing", "repeated-attempt",
    # dev/128: the shape refusal's first line IS the answer.
    "input-contract",
    # dev/129/133/134: these details are composed prose, not tracebacks — the
    # sentence that says what is wrong is the FIRST one.
    "document-invalid", "empty-result",
    # dev/136: and the render that drew nothing.
    contracts.EMPTY_RENDER_KIND,
)


def _last_attempt_code(trail: dict) -> str | None:
    """The code of the last recorded attempt (dev/127) — what the failure's
    exception line is read against, so a self-raised error is named as one."""
    attempts = (trail or {}).get("attempts") or []
    return attempts[-1].get("code") if attempts else None


#: dev/131 (owner correction): remedies only the USER can act on. A node
#: parked on one of these has no new input to carry — attempting it again would
#: ask the same question of the same model, so the session WAITS and rechecks.
#: Everything else (an execution error, a refusal, a decline) IS a new input.
_USER_ACTION_REMEDIES = ("dataset-selection", "connection-key")


def _awaits_user_action(result: dict | None) -> bool:
    """Whether this node's last outcome is parked on something the user must do."""
    remedy = (result or {}).get("remedy")
    return (
        isinstance(remedy, dict)
        and str(remedy.get("kind") or "") in _USER_ACTION_REMEDIES
    )


#: Attempt kinds that say nothing about the CODE: the sandbox was down, the
#: runner refused the slice, an upstream has no content yet. Carrying one
#: forward would ask the builder to "fix" code that never ran — and the repeat
#: detector would then fail the node for returning the same correct code. The
#: node is still re-attempted; it just starts clean, because the blocker was
#: never in the code.
_NO_CARRY_KINDS = ("infrastructure", "precondition", "upstream-blocker", "not-executable")


#: A repeat notice is about the LOOP, not the code: when a real error sits
#: behind it, that error is what the next pass carries.
_WEAK_CARRY_KINDS = ("repeated-attempt",)


def _weak_failure(result: dict | None) -> bool:
    """Whether every failed attempt in this trail is about the LOOP or the
    environment rather than the code (a repeat notice, a sandbox outage, a
    slice bound) — so its sentence must not replace a concrete diagnosis."""
    failed = [
        a for a in ((result or {}).get("attempts") or [])
        if isinstance(a, dict) and a.get("verdict") != "pass"
    ]
    if not failed:
        return False
    weak = set(_WEAK_CARRY_KINDS) | set(_NO_CARRY_KINDS)
    return all(str(a.get("kind") or "") in weak for a in failed)


def _carry_forward_error(result: dict | None) -> dict | None:
    """The input a re-attempt carries: the last attempt's code and ITS error.

    The owner's correction to dev/131 — *"the keep attempting it should not
    carry the same inputs, supposing it doesn't depend on user's actions, it
    should carry the currently error that is being given"*. A later pass is not
    a fresh start: it continues from the candidate that failed and the error it
    produced, so round 0 generates a CORRECTION rather than another blank first
    draft that fails the same way.
    """
    attempts = [
        a for a in ((result or {}).get("attempts") or [])
        if isinstance(a, dict)
        and a.get("verdict") != "pass"
        and str(a.get("kind") or "") not in _NO_CARRY_KINDS
        and str(a.get("stderrTail") or a.get("detail") or "").strip()
    ]
    if not attempts:
        return None
    strong = [a for a in attempts if str(a.get("kind") or "") not in _WEAK_CARRY_KINDS]
    attempt = (strong or attempts)[-1]
    error = str(attempt.get("stderrTail") or attempt.get("detail") or "").strip()
    code = "" if attempt.get("codeIsProse") else str(attempt.get("code") or "")
    return {"code": code, "error": error, "kind": str(attempt.get("kind") or "")}


def _solve_attempts_part(
    spec: dict | None, node_id: str, label: str, result: dict | None
) -> dict | None:
    """dev/127: ONE node's repair attempts as a transcript part, or None.

    The owner's requirement — *"it is important to clearly display all attempts
    to fix in the chat transcript"* — is a durability requirement: the strip is
    transient and the card's lines cannot carry code. Every recorded attempt
    rides here with the code it ran and its error read through
    ``failure_text`` (the exception line first, whole), and the part links the
    node's own agent so the child's replies are one click away.
    """
    attempts = (result or {}).get("attempts") or []
    if not attempts:
        return None
    rows = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        rows.append({
            **attempt,
            "errorSummary": _attempt_why(
                attempt, limit=content.SOLVE_ATTEMPT_ERROR_MAX_CHARS
            ),
        })
    if not rows:
        return None
    home = agents_spec_reads._node_attachment_of(spec or {}, "agent.node-builder", node_id) or {}
    return content.make_solve_attempts_part(
        node_id=node_id,
        label=label,
        attachment_id=home.get("attachmentId"),
        rounds=(result or {}).get("rounds") or len(rows),
        stopped_by=(result or {}).get("stoppedBy") or "",
        attempts=rows,
        verdict=(result or {}).get("verdict") or "fail",
    )


def _attempt_why(attempt: dict, *, limit: int) -> str:
    """dev/127: ONE reading of a recorded attempt's failure, for every card.

    A refusal (the grounding gate, a decline) says what it refused in its FIRST
    line; a traceback says it in its exception line, which
    ``failure_text.summary`` puts first and keeps whole. The attempt's own code
    rides along so an error the candidate raised itself is labeled as such."""
    raw = str(attempt.get("stderrTail") or attempt.get("detail") or "")
    if not raw.strip():
        return ""
    if attempt.get("kind") in _HEAD_FIRST_KINDS:
        return failure_text.excerpt(raw, limit=limit, head=True)
    return failure_text.summary(raw, code=attempt.get("code"), limit=limit)


def _same_code(a: str, b: str) -> bool:
    """Byte-different but code-identical: comments, blank lines and spacing
    stripped through the tokenizer (a string literal with a '#' survives)."""

    def _norm(code: str) -> str:
        try:
            tokens = tokenize.generate_tokens(io.StringIO(code).readline)
            skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                    tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
            return " ".join(t.string for t in tokens if t.type not in skip and t.string.strip())
        except (tokenize.TokenError, SyntaxError, IndentationError):
            return "\n".join(l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("#"))

    return bool(a and b) and _norm(a) == _norm(b)


def _dataset_finder_attachment_id(spec: dict | None, node_id: str) -> str | None:
    """The node's own Dataset Finder attachment id, or None (dev/126)."""
    if not isinstance(spec, dict) or not isinstance(node_id, str) or not node_id:
        return None
    record = agents_spec_reads._node_attachment_of(spec, "agent.dataset-finder", node_id)
    return (record or {}).get("attachmentId")


_CODE_MARKERS = ("import ", "return ", " = ", "(", "def ", "{")


def _is_prose_decline(candidate: str) -> bool:
    """A short, single-line reply with no code shape — the content builder's
    sanctioned "what source is missing" line rather than content."""
    text = (candidate or "").strip()
    if not text or "\n" in text or len(text) > agents_budgets._PROSE_DECLINE_MAX_CHARS:
        return False
    return not any(marker in text for marker in _CODE_MARKERS)


def _correction_url_evidence(candidate: str, error_text: str, ctx) -> list[dict]:
    """dev/115: when a failed run names an HTTP problem, re-probe the URLs the
    candidate fetches (DEC-053, budgeted through the grounding context) so the
    correction is grounded in the endpoint's real answer — not a guess about
    why a 400 happened."""
    if ctx is None or ctx.probe is None:
        return []
    lowered = (error_text or "").lower()
    named_http = any(
        marker in lowered for marker in ("http", "status", "urlerror", "connection", "timeout")
    )
    # A data-loading node that fetches and then fails is an endpoint question
    # whatever the traceback says: the field case wrapped the request in a
    # bare ``except`` and returned an empty frame, so the only error named was
    # DuckDB's "need at least one column" (dev/115 field fix, 2026-09-08).
    if not named_http and not getattr(ctx, "is_data_loading", False):
        return []
    # The requests the loader actually made come first: a parameterised API's
    # base answers 200 while the composed query is what fails.
    targets = [(url, "composed") for url in source_grounding.composed_requests(candidate)]
    targets += [
        (ref.literal, "literal")
        for ref in source_grounding.scan_sources(candidate, "python")
        if ref.kind == "url" and ref.literal not in {u for u, _ in targets}
    ]
    out: list[dict] = []
    known = getattr(ctx, "verified_urls", None)
    for url, how in targets:
        if how == "composed":
            placeholder = _placeholder_probe(url, ctx)
            if placeholder is not None:
                # The code sends a saved key itself (curio_secret(...) as a
                # parameter): probe ONLY with the value swapped in — a bare probe
                # would send the placeholder text and answer nothing useful.
                out.append(placeholder)
                if len(out) >= agents_budgets._CORRECTION_URL_PROBES:
                    break
                continue
        already_known = isinstance(known, dict) and url in known
        try:
            verdict = ctx.probe(url)
        except Exception as exc:  # a broken prober is absence, never a claim
            verdict = {"status": "unverified", "detail": str(exc)[:200]}
        if how == "composed" and isinstance(known, dict) and not already_known:
            # Evidence for the correction, NOT a new grounded source: a
            # composed query is a derivative of its (already gated) base URL,
            # and a 200 HTML "Missing Key" page must never be listed as a URL
            # the builder may fetch.
            known.pop(url, None)
        entry = {"url": url, "verification": verdict}
        if how == "composed":
            entry["request"] = "the URL composed from the code's url + params"
        note = _endpoint_note(verdict)
        if note:
            entry["note"] = note
        keyed = _keyed_probe(candidate, url, how, ctx) if how == "composed" else None
        if keyed:
            entry.update(keyed)
        out.append(entry)
        if len(out) >= agents_budgets._CORRECTION_URL_PROBES:
            break
    return out


def _placeholder_probe(url: str, ctx) -> dict | None:
    """dev/116 live fix (2026-09-09): a composed request whose parameters carry
    ``curio_secret("<name>")`` placeholders. The saved values are sent in their
    place through the keyed (uncached, never-verified) probe path and the
    outcome is redacted; the entry shows the call, never the value."""
    bare, secret_params = source_grounding.split_secret_params(url)
    if not secret_params:
        return None
    shown = source_grounding.display_composed_url(url)
    names = sorted(set(secret_params.values()))
    entry: dict = {
        "url": shown,
        "request": "the URL composed from the code's url + params; the saved key was sent in place of curio_secret(...)",
        "keyed": ", ".join(names),
    }
    resolver = getattr(ctx, "secret_values", None)
    values: dict = {}
    if resolver is not None:
        try:
            values = resolver(names) or {}
        except Exception:
            values = {}
    missing = [n for n in names if not values.get(n)]
    if missing:
        entry["verification"] = {
            "status": "unverified",
            "detail": f"no connection key named {', '.join(repr(m) for m in missing)} is saved — not probed",
        }
        return entry
    params = {param: values[name] for param, name in secret_params.items()}
    try:
        outcome = ctx.probe(bare, params=params) or {}
    except Exception as exc:
        outcome = {"status": "unverified", "detail": str(exc)[:200]}
    from utk_curio.common.redaction import redact

    outcome = {k: (redact(v, values) if isinstance(v, str) else v) for k, v in outcome.items()}
    entry["verification"] = outcome
    note = _endpoint_note(outcome)
    if note:
        entry["note"] = note
    return entry


def _keyed_probe(candidate: str, url: str, how: str, ctx) -> dict | None:
    """dev/116: when a saved connection key is bound to the composed request's
    host and the API's ``delivery`` is known (``query:<p>`` / ``header:<H>``),
    probe the SAME request with the key and report what the keyed request
    answers — redacted, never cached, never a verified source. ``delivery:
    code`` only names the key (the run is the evidence)."""
    saved = source_grounding.secret_for_host(ctx, url)
    if saved is None:
        return None
    result: dict = {"keyed": saved.name, "keyedDelivery": saved.delivery}
    in_code = saved.name in source_grounding.secret_names(candidate)
    if not saved.delivery.startswith(("query:", "header:")):
        result["keyedNote"] = (
            f"a connection key {saved.name!r} is saved for this host"
            + ("" if in_code else f" — the code does not use it yet: {saved.use_line}")
            + "; the code decides how the API receives it"
        )
        return result
    resolver = getattr(ctx, "secret_values", None)
    if resolver is None:
        return result
    try:
        values = resolver([saved.name]) or {}
    except Exception:
        values = {}
    value = values.get(saved.name)
    if not value:
        return result
    kind, _, target = saved.delivery.partition(":")
    kwargs = {"params": {target: value}} if kind == "query" else {"headers": {target: value}}
    try:
        outcome = ctx.probe(url, **kwargs)
    except Exception as exc:
        outcome = {"status": "unverified", "detail": str(exc)[:200]}
    from utk_curio.common.redaction import redact

    outcome = {
        k: (redact(v, {saved.name: value}) if isinstance(v, str) else v)
        for k, v in (outcome or {}).items()
    }
    result["keyedVerification"] = outcome
    status = outcome.get("status")
    content_type = str(outcome.get("contentType") or "").lower()
    sent = f"as {kind} {target!r}"
    if status == "verified" and content_type and "json" not in content_type:
        result["keyedNote"] = (
            f"even with the saved key {saved.name!r} sent {sent}, the request answered "
            f"{content_type.split(';')[0]}{' (' + str(outcome.get('pageTitle')) + ')' if outcome.get('pageTitle') else ''}"
            " — the key or the way it is sent is wrong; say so instead of guessing parameters"
        )
    elif status == "verified":
        result["keyedNote"] = (
            f"with the saved key {saved.name!r} sent {sent} the request answers data — "
            f"the code must send it the same way: {saved.use_line}"
            + ("" if in_code else " (the code does not use it yet)")
        )
    else:
        result["keyedNote"] = (
            f"with the saved key {saved.name!r} sent {sent}: {status}"
            + (f" {outcome.get('httpStatus')}" if outcome.get("httpStatus") else "")
        )
    return result


_CREDENTIAL_DECLINE_RE = _re.compile(
    r"api[ _-]?key|\bkey\b|token|credential|sign[- ]?in|log[- ]?in|unauthori[sz]ed|missing key|forbidden",
    _re.IGNORECASE,
)


def _decline_remedy(decline: str, previous_attempt: str | None, ctx) -> dict | None:
    """dev/116: a decline about a credential + a host from the failed attempt
    → a concrete remedy the card can act on."""
    if not decline or not _CREDENTIAL_DECLINE_RE.search(decline):
        return None
    host = ""
    for url in source_grounding.composed_requests(previous_attempt or ""):
        host = source_grounding._host_of(url)
        if host:
            break
    if not host:
        for ref in source_grounding.scan_sources(previous_attempt or "", "python"):
            if ref.kind == "url":
                host = source_grounding._host_of(ref.literal)
                if host:
                    break
    if not host:
        return None
    from utk_curio.backend.app.users.connection_keys import suggest_name

    saved = source_grounding.secret_for_host(ctx, f"https://{host}/") if ctx is not None else None
    if saved is not None:
        return {"kind": "use-connection-key", "host": host, "name": saved.name}
    return {"kind": "connection-key", "host": host, "suggestedName": suggest_name(host)}


def _endpoint_note(verdict: dict) -> str:
    """A deterministic reading of a probe outcome for the correction and the
    card — only what the outcome itself shows, never a guess."""
    if not isinstance(verdict, dict):
        return ""
    status = verdict.get("status")
    content_type = str(verdict.get("contentType") or "")
    final_url = verdict.get("finalUrl")
    title = verdict.get("pageTitle")
    sample = verdict.get("bodySample")
    where = f" after redirecting to {final_url}" if final_url else ""
    if status == "verified" and content_type and "json" not in content_type.lower():
        what = f'an HTML page titled "{title}"' if title else f"{content_type.split(';')[0]} content"
        return (
            f"answered {what}{where} — not data. Read the page title: a key or "
            "sign-in requirement cannot be fixed by changing parameters; say what is missing."
        )
    if status == "unreachable" and verdict.get("httpStatus"):
        said = f': "{sample}"' if sample else (f' ("{title}")' if title else "")
        return f"the request itself answered {verdict['httpStatus']}{where}{said}"
    return ""


def _url_evidence_summary(url_evidence: list[dict]) -> str:
    """One line for the attempt trail: what the endpoint actually answered."""
    parts: list[str] = []
    for entry in url_evidence[:2]:
        verdict = entry.get("verification") or {}
        head = str(entry.get("url") or "")
        head = head if len(head) <= 90 else head[:87] + "…"
        status = verdict.get("status", "unverified")
        http = verdict.get("httpStatus")
        bit = f"{head} → {status}" + (f" {http}" if http else "")
        if entry.get("note"):
            bit += f": {entry['note']}"
        elif verdict.get("detail"):
            bit += f": {verdict['detail']}"
        parts.append(bit)
    return "; ".join(parts)[:agents_budgets._ATTEMPT_DETAIL_CHARS * 2]


def _verified_content_rounds(
    user_key: str,
    project_id: str,
    *,
    spec: dict,
    node: dict,
    resolution,
    config: ProviderConfig,
    parent_execution_id: str,
    parent_coord: str,
    attachment_id: str | None,
    exec_fn,
    grounding_loop_ctx: dict,
    grounding_base: dict | None = None,
    start_from_current: bool = False,
    extra_inputs: dict | None = None,
    delegate_runner=None,
    dataset_paths_fn=None,
    exec_user_key: str | None = None,
    secrets_fn=None,
    prior_outputs_fn=None,
    resolve_source=None,
    clock=time.monotonic,
    recorded_failure=None,
    node_budget_s=None,
    carry_forward=None,
    result_summary_fn=None,
):
    """dev/115 (DEC-073): the ONE generate → gate → execute → correct loop.

    The dev/67-7 round loop extracted from ``_validate_events`` so every
    caller — validate-node, Simulation Mode, and Solve — runs the same policy:

    - round 0 either delegates ``node.content.generate`` or, with
      ``start_from_current``, executes the node's CURRENT content as-is (the
      per-node Solve on code the user just applied: if it passes, nothing is
      generated, nothing changes);
    - every candidate passes the DEC-072 grounding gate BEFORE it runs — a
      refused candidate is a failed round (``kind: ungrounded-source``) whose
      refusal text is the correction's error, and it never reaches the sandbox;
    - a run's ``dataset_paths`` are resolved for the candidate + its slice;
    - a failed round feeds the next generation ``previousAttempt``,
      ``validationError``, ``sourceGrounding`` (data-loading nodes) and — when
      the failure names an HTTP problem — fresh probe evidence for the URLs
      the candidate fetches;
    - attempts continue while BOTH bounds allow (dev/127, widened by dev/128 at
      the owner's instruction): at most ``solve_max_attempts()`` of them — ten
      by default — and only while ``solve_node_budget_s()`` seconds have not
      been spent — fifteen minutes by default; the outcome's ``stoppedBy``
      names whichever bound ended it.

    A generator: yields ``("generation_round", …)``, ``("node_executed", …)``
    and ``("round_verdict", …)`` exactly as the validate-node stream always
    did, and RETURNS the outcome dict ``{verdict, evidence, rounds, candidate,
    delegations, roundsTrace, attempts}`` (``outcome = yield from …``).
    ``attempts`` is the bounded trail the cards render: one row per round
    with the content digest, verdict, kind, detail, stderr tail, and output.
    """

    from utk_curio.backend.app.packages import service as packages_services

    run_delegate = delegate_runner or (
        lambda inputs: delegation.run_delegate(
            user_key, project_id, resolution.coord,
            "node.content.generate", inputs, config,
            parent_execution_id=parent_execution_id,
            parent_coord=parent_coord,
            attachment_id=attachment_id,
        )
    )
    node_id = node.get("id")
    node_type = node.get("type")
    is_data_loading = source_grounding.is_data_loading_type(
        packages_services.canonical_template_id(node_type)
    )
    try:
        available = {
            t["id"]: t for t in packages_services.available_templates(user_key, project_id)
        }
    except Exception:
        available = None  # arity metadata unavailable: type check fails open
    # dev/119 (DEC-076): the same roster classifies executability for the runner.
    loop_templates = (
        {tid: {
            "executable": bool(row.get("executable")),
            "engine": row.get("engine") or "python",
            # dev/134: and the same snapshot routes the document validator.
            "contentKind": row.get("contentKind") or "none",
            **({"grammar": row["grammar"]} if row.get("grammar") else {}),
        } for tid, row in available.items()}
        if available else None
    )
    # ONE grounding context per loop: the same catalog/verified-URL evidence for
    # every round, one probe budget, and the sourceGrounding inputs derive from it.
    # dev/116 live fix (2026-09-09): the budget is the LOOP's own — a failed
    # round spends up to five calls (gate probe, composed request + redirect,
    # keyed probe) and the run-wide four starved every correction of its
    # evidence. The probe cache and the verified map stay shared with the
    # caller's context (a batch probes a base URL once).
    shared = grounding_loop_ctx
    grounding_loop_ctx = dict(shared)
    grounding_loop_ctx["_probe_cache"] = shared.setdefault("_probe_cache", {})
    grounding_loop_ctx["_verified_urls"] = shared.setdefault("_verified_urls", {})
    grounding_loop_ctx["_egress_budget"] = egress.CallBudget(agents_budgets._LOOP_EGRESS_CALLS)
    grounding_ctx = None
    dataflow = (spec or {}).get("dataflow") or {}
    try:
        # The node's goal and the dataflow's mission are human-authored intent
        # (a plan goal saying "synthetic sample data" authorizes inline data).
        grounding_ctx = agents_grounding._grounding_context(
            user_key, project_id, grounding_loop_ctx, node_type=node_type,
            base=grounding_base,
            extra_texts=(str(node.get("goal") or ""), str(dataflow.get("task") or "")),
        )
    except Exception:
        log.warning("Grounding context unavailable for node %s", node_id, exc_info=True)
    verdict_result: dict | None = None
    rounds_used = 0
    candidate = ""
    delegations: list = []
    rounds_trace: list[str] = []
    attempts: list[dict] = []
    previous_attempt: str | None = None
    previous_error: str | None = None
    url_evidence: list[dict] = []
    confirmed_source: dict | None = None
    stopped_by: str | None = None  # dev/127: which bound ended the loop
    repeats = 0
    if isinstance(recorded_failure, dict) and recorded_failure.get("stderr"):
        # dev/129: the loop is starting from code that already failed — in a
        # Play run or an earlier validation — and the traceback is on disk.
        # Round 0 re-runs it (start_from_current), so this line is the trail's
        # explanation of WHY it starts there; the correction gets the real
        # traceback from the run itself.
        rounds_trace.append(
            f"starting from the code on the node, which failed at "
            f"{recorded_failure.get('origin') or 'a previous run'}"
            f"{' (' + str(recorded_failure.get('ranAt')) + ')' if recorded_failure.get('ranAt') else ''}"
            f": {failure_text.summary(recorded_failure['stderr'], limit=200)}"
        )
        previous_error = str(recorded_failure["stderr"])[-2000:]
    if isinstance(carry_forward, dict) and (carry_forward.get("error") or "").strip():
        # dev/131 (owner correction): a retry must not carry the SAME inputs.
        # When an earlier pass of this session already tried and failed, its
        # last candidate and the error it produced are the inputs this pass
        # starts from — so round 0 generates a CORRECTION, not another blank
        # first draft. (A node blocked on the user has no such input, which is
        # why only that case waits.)
        previous_attempt = (
            str(carry_forward.get("code") or "")[:6000] or previous_attempt
        )
        previous_error = str(carry_forward["error"])[-2000:]
        rounds_trace.append(
            "carrying forward the previous attempt's error: "
            + failure_text.summary(
                str(carry_forward["error"]), code=carry_forward.get("code"), limit=200
            )
        )
    # dev/128: what ``arg`` IS for this node — a fact of the graph, computed
    # once (it cannot change mid-loop), handed to the child as an input, and
    # enforced before the sandbox. The owner's report: a node fed through a
    # merge received ``arg`` and treated it as a frame.
    arg_contract = input_contract.arg_shape(spec, node_id)
    if (extra_inputs or {}).get("upstreamOutputs"):
        arg_contract = input_contract.with_schemas(
            arg_contract, (extra_inputs or {}).get("upstreamOutputs")
        )
    # dev/126: a data-loading node RESOLVES ITS SOURCE FIRST. Discovery is
    # initiated by the runtime (never left to the model to think of), and a
    # node whose source the user has not confirmed yet waits for them instead
    # of ending in the old dead end — the content builder declining, or the
    # gate refusing a filename it had to invent.
    if is_data_loading and resolve_source is not None:
        try:
            source_state = resolve_source(node, grounding_ctx) or {}
        except Exception:  # noqa: BLE001
            log.warning("Source resolution failed for node %s", node_id, exc_info=True)
            source_state = {}
        if source_state.get("state") == "unresolved" and source_state.get("discovery"):
            # Discovery was initiated and produced nothing selectable: say so
            # in the trail and let the round proceed, so the node still ends
            # with ITS own evidence (a refusal naming the literal, or the
            # builder's own decline) rather than a promise of candidates.
            rounds_trace.append(
                f"discovery found no source — {str(source_state.get('detail'))[:160]}"
            )
        if source_state.get("state") == "awaiting":
            detail = str(source_state.get("detail") or "a source must be selected")
            return {
                "verdict": "awaiting-source",
                "evidence": {
                    "kind": "awaiting-selection",
                    "detail": detail[:2000],
                    **({"remedy": {
                        "kind": "dataset-selection",
                        "attachmentId": source_state["attachmentId"],
                        "nodeId": node_id,
                    }} if source_state.get("attachmentId") else {}),
                },
                "rounds": 0,
                "candidate": "",
                "delegations": delegations,
                "roundsTrace": [f"awaiting dataset selection — {detail[:160]}"],
                "attempts": [],
            }
        confirmed_source = source_state.get("confirmedSource")
        if source_state.get("detail"):
            rounds_trace.append(f"source: {str(source_state['detail'])[:160]}")
    # dev/129: the wall budget is the bound; the attempt count is a cap that
    # sits ABOVE what a quarter hour affords, so in practice the clock stops
    # the loop and `stoppedBy` says so. A deployment (or a test) that wants a
    # tighter cap sets CURIO_SOLVE_MAX_ATTEMPTS and gets it.
    max_rounds = min(agents_budgets.solve_max_attempts(), agents_budgets.MAX_SOLVE_ATTEMPTS)
    # dev/131: a node's repair budget is clamped by what remains of the
    # SESSION's, so the owner's fifteen minutes means the same thing at both
    # levels and one node cannot spend a session it shares.
    node_budget_s = (
        max(int(node_budget_s), 1) if isinstance(node_budget_s, (int, float))
        else agents_budgets.solve_node_budget_s()
    )
    loop_started = clock()
    for round_index in range(max_rounds):
        if round_index and (clock() - loop_started) >= node_budget_s:
            # dev/127: the budget is checked BEFORE a new round is dispatched,
            # so a round in flight always finishes and is recorded. dev/129:
            # this is now the NORMAL stop, which is why it is checked first.
            stopped_by = "budget"
            rounds_trace.append(
                f"stopped after round {rounds_used}: this node's "
                f"{node_budget_s}s repair budget is spent"
            )
            break
        rounds_used = round_index + 1
        yield "generation_round", {"round": rounds_used}
        use_current = (
            round_index == 0 and start_from_current and str(node.get("content") or "").strip()
        )
        if use_current:
            candidate = str(node.get("content") or "")
        else:
            inputs = {
                "nodeType": node_type,
                "intent": node.get("goal"),
                "nodeContext": node_context.compose_node_context(
                    user_key, project_id, spec, node_id
                ),
            }
            if is_data_loading and grounding_ctx is not None:
                # dev/114's seventh DEC-063 application, on every caller.
                inputs["sourceGrounding"] = agents_grounding._source_grounding_inputs(grounding_ctx)
                if confirmed_source is not None:
                    # dev/126: the source the USER confirmed on this node —
                    # handed over, not inferred from what was verified once.
                    inputs["sourceGrounding"]["confirmedSource"] = confirmed_source
            if arg_contract.get("kind") != input_contract.KIND_NONE:
                # dev/128 (DEC-063, ninth application): the shape of `arg`, per
                # node, on the first generation and on every correction.
                inputs["inputContract"] = arg_contract
            if extra_inputs:
                inputs.update({k: v for k, v in extra_inputs.items() if k not in inputs})
            if previous_attempt is not None or (previous_error or "").strip():
                # The NCB instruction's self-correction contract: fix
                # precisely the failure, grounded in the real traceback.
                # dev/131: a carried-forward error with no code (a prose
                # decline, a refusal that named no candidate) still rides —
                # the error IS the new input.
                inputs["validationError"] = (previous_error or "")[:2000]
                if previous_attempt is not None:
                    inputs["previousAttempt"] = previous_attempt[:6000]
                if url_evidence:
                    inputs["urlEvidence"] = url_evidence
            status, text, child = run_delegate(inputs)
            delegations.append(child)
            if status != "ok":
                verdict_result = {
                    "verdict": "fail",
                    "evidence": {"kind": "generation-error", "detail": (text or "")[:300]},
                }
                attempts.append({
                    "round": rounds_used, "verdict": "fail", "kind": "generation-error",
                    "detail": (text or "")[:agents_budgets._ATTEMPT_DETAIL_CHARS],
                })
                stopped_by = "generation"
                break
            candidate = content.extract_node_content(text)
        # DEC-072: the gate runs BEFORE the sandbox does — a fabricated path
        # or an unverified URL never executes, and the refusal is the error
        # the next round corrects.
        if grounding_ctx is not None:
            gate = source_grounding.check_grounding(candidate, "python", grounding_ctx)
            if not gate.ok:
                refusal = source_grounding.refusal_text(gate, grounding_ctx)
                kind = "ungrounded-source"
                declined = not use_current and _is_prose_decline(candidate)
                if declined:
                    # The delegate followed its rule ("return a one-line
                    # explanation of what source is missing instead of code").
                    # Record ITS words as the attempt, not a gate verdict on
                    # prose (dev/115 field fix, 2026-09-08).
                    refusal = f"the content builder declined: {candidate.strip()}"
                    kind = "source-missing"
                verdict_result = {
                    "verdict": "fail",
                    "evidence": {"kind": kind, "detail": refusal[:2000]},
                }
                yield "round_verdict", {"round": rounds_used, "verdict": "fail"}
                rounds_trace.append(f"round {rounds_used}: fail — {refusal[:160]}")
                attempts.append({
                    "round": rounds_used, "contentSha256": _content_sha(candidate),
                    "verdict": "fail", "kind": kind,
                    "detail": refusal[:agents_budgets._ATTEMPT_DETAIL_CHARS],
                    "source": "current content" if use_current else "generated",
                    # dev/127: what was refused, verbatim — the literal the
                    # gate named is IN this text, so showing it is the point.
                    **_attempt_code_field(candidate, prose=declined),
                })
                if declined:
                    # dev/116: when the decline is about a credential and the
                    # failed attempt named a host, the remedy is concrete —
                    # add a connection key for that host (or use the saved one).
                    remedy = _decline_remedy(candidate, previous_attempt, grounding_ctx)
                    if remedy:
                        verdict_result["evidence"]["remedy"] = remedy
                        attempts[-1]["remedy"] = remedy
                    # A decline names an input nobody in this loop can supply
                    # (a key, a path, a URL). Asking the same builder again
                    # with the same inputs only repeats it — the user is the
                    # correction; stop and say so.
                    stopped_by = "decline"
                    break
                previous_attempt = candidate
                previous_error = refusal
                url_evidence = []
                continue
        # dev/128: the shape gate, beside the DEC-072 source gate and before
        # the sandbox. A list-shaped `arg` used as a frame is provably wrong —
        # a list has no such attribute — so the round fails HERE, for free,
        # with the slot table as its correction instead of a library's
        # AttributeError three minutes later.
        violation = input_contract.check(candidate, arg_contract)
        if violation is not None:
            refusal = input_contract.refusal_text(arg_contract, violation)
            verdict_result = {
                "verdict": "fail",
                "evidence": {"kind": "input-contract", "detail": refusal[:2000]},
            }
            yield "round_verdict", {"round": rounds_used, "verdict": "fail"}
            rounds_trace.append(f"round {rounds_used}: fail — {refusal[:200]}")
            attempts.append({
                "round": rounds_used, "contentSha256": _content_sha(candidate),
                "verdict": "fail", "kind": "input-contract",
                "detail": refusal[:agents_budgets._ATTEMPT_DETAIL_CHARS],
                "source": "current content" if use_current else "generated",
                **_attempt_code_field(candidate),
            })
            previous_attempt = candidate
            previous_error = refusal
            url_evidence = []
            continue
        # A repeat is judged AFTER the gate: a refused candidate keeps its own kind.
        if not use_current and previous_attempt is not None and _same_code(candidate, previous_attempt):
            # dev/116 live fix (2026-09-09): the correction changed only
            # comments or spacing — running it again would fail the same
            # way. Not run; the next round is told so, in plain words.
            detail = (
                "the correction repeated the previous attempt (only comments or spacing "
                "changed) — not run again; change the request that failed: "
                + (previous_error or "")[:400]
            )
            verdict_result = {
                "verdict": "fail",
                "evidence": {"kind": "repeated-attempt", "detail": detail[:2000]},
            }
            yield "round_verdict", {"round": rounds_used, "verdict": "fail"}
            rounds_trace.append(f"round {rounds_used}: fail — repeated the previous attempt")
            attempts.append({
                "round": rounds_used, "contentSha256": _content_sha(candidate),
                "verdict": "fail", "kind": "repeated-attempt",
                "detail": detail[:agents_budgets._ATTEMPT_DETAIL_CHARS], "source": "generated",
                **_attempt_code_field(candidate),
            })
            repeats += 1
            if repeats >= agents_budgets._MAX_REPEATED_ATTEMPTS:
                # dev/129: a repeat no longer ends the loop — the owner asked
                # for as many retries as the budget affords. It ESCALATES: the
                # next round is told how many times it has repeated itself and
                # that it must change approach, not phrasing. Only an
                # implausible run of identical candidates stops the loop, so a
                # stuck model cannot spend fifteen minutes of provider calls.
                detail = (
                    f"you have now returned the same code {repeats} times. Stop repeating it: "
                    "change the APPROACH — a different library call, a different key or column, "
                    "a different shape of the result — or say plainly what you cannot do. "
                    + detail
                )
                previous_error = detail
                attempts[-1]["detail"] = detail[:agents_budgets._ATTEMPT_DETAIL_CHARS]
                if repeats >= agents_budgets._MAX_REPEATED_ATTEMPTS_HARD:
                    stopped_by = "repeat"
                    break
            previous_attempt = candidate
            previous_error = detail
            continue  # url_evidence: unchanged — same request, same answer
        dataset_paths = None
        if dataset_paths_fn is not None:
            try:
                slice_codes = [
                    str(n.get("content") or "")
                    for n in ((spec.get("dataflow") or {}).get("nodes") or [])
                    if isinstance(n, dict)
                ]
                dataset_paths = dataset_paths_fn([candidate, *slice_codes]) or None
            except Exception:
                dataset_paths = None
        # dev/116: the connection keys THIS candidate names, resolved per round
        # so a correction that adopts curio_secret("<name>") runs with it.
        secrets = None
        if secrets_fn is not None:
            try:
                secrets = secrets_fn([candidate]) or None
            except Exception:
                secrets = None
        # dev/118 commit 4: the outputs recorded for ancestors that passed
        # earlier in this batch stand in for their re-run (fresh per round).
        prior_outputs = None
        if prior_outputs_fn is not None:
            try:
                prior_outputs = prior_outputs_fn() or None
            except Exception:
                prior_outputs = None

        def _validate_with(prior, candidate_text=candidate, paths=dataset_paths, secret_values=secrets):
            progress_queue: _queue.Queue = _queue.Queue()

            def _run_validation():
                try:
                    result = agents_validation.validate_candidate(
                        user_key, project_id, spec, node_id, candidate_text,
                        exec_fn=exec_fn,
                        available_templates=available,
                        dataset_paths=paths,
                        exec_user_key=exec_user_key,
                        secrets=secret_values,
                        prior_outputs=prior,
                        templates=loop_templates,
                        progress=lambda nid, i, total: progress_queue.put(
                            ("progress", nid, i, total)
                        ),
                    )
                except Exception as exc:  # the validator must never kill the stream
                    result = {
                        "verdict": "infrastructure",
                        "evidence": {"kind": "infrastructure", "detail": str(exc)[:300]},
                    }
                progress_queue.put(("done", result))

            thread = threading.Thread(target=_run_validation)
            thread.start()
            while True:
                item = progress_queue.get()
                if item[0] == "progress":
                    _, nid, index, total = item
                    yield "node_executed", {"nodeId": nid, "index": index, "total": total}
                    continue
                thread.join(timeout=5)
                return item[1]

        verdict_result = yield from _validate_with(prior_outputs)
        reuse_retried = False
        if prior_outputs and agents_session._looks_like_a_vanished_reused_input(verdict_result):
            # A reused artifact is gone (the sandbox store moved on): that is
            # not the candidate's fault. Once, silently, the slice runs whole.
            verdict_result = yield from _validate_with(None)
            reuse_retried = True
        if verdict_result.get("verdict") == "not-executable" and str(candidate or "").strip():
            # dev/129: the sandbox cannot RUN a Vega or AUTK document, which is
            # not the same as being unable to CHECK it. An invalid document is
            # a failed round like any other — the validator's message is the
            # correction — and a valid one is written with a stronger, still
            # truthful claim than "no code to run".
            # dev/134: routed by the roster's own grammarId, and checked
            # against the columns this node's input actually has — the same
            # rows the generation request was handed (DEC-063).
            # The roster's own row only: an unknown kind is not passive.
            roster_row = (loop_templates or {}).get(str(node_type).split("@", 1)[0]) or {}
            document = document_validation.validate(
                node_type, candidate,
                grammar_id=workflow_spec.grammar_id_of(node_type, loop_templates),
                content_kind=roster_row.get("contentKind"),
                columns=upstream_schema.columns_of(
                    (extra_inputs or {}).get("upstreamOutputs")
                ),
            )
            if document["status"] == document_validation.STATUS_INVALID:
                refusal = document_validation.refusal_text(
                    node_type, document,
                    grammar_id=workflow_spec.grammar_id_of(node_type, loop_templates),
                )
                verdict_result = {
                    "verdict": "fail",
                    "evidence": {"kind": "document-invalid", "detail": refusal[:2000]},
                }
                yield "round_verdict", {"round": rounds_used, "verdict": "fail"}
                rounds_trace.append(f"round {rounds_used}: fail — {refusal[:200]}")
                attempts.append({
                    "round": rounds_used, "contentSha256": _content_sha(candidate),
                    "verdict": "fail", "kind": "document-invalid",
                    "detail": refusal[:agents_budgets._ATTEMPT_DETAIL_CHARS],
                    "source": "current content" if use_current else "generated",
                    **_attempt_code_field(candidate),
                })
                previous_attempt = candidate
                previous_error = refusal
                url_evidence = []
                continue
            evidence = verdict_result.setdefault("evidence", {})
            if document["status"] == document_validation.STATUS_VALID:
                # dev/136: a valid document is not a drawn picture. When the
                # node's last RENDER drew nothing and the document on it is the
                # one that drew nothing, passing here would end the loop on a
                # chart the user is looking at empty — the owner's report. The
                # recorded render failure becomes this round's verdict instead.
                render_cause = (
                    result_shape.empty_render_cause((recorded_failure or {}).get("kind"))
                    if use_current and isinstance(recorded_failure, dict) else None
                )
                if render_cause is not None:
                    upstream_rows = (extra_inputs or {}).get("upstreamOutputs")
                    refusal = result_shape.empty_render_refusal(
                        message=str((recorded_failure or {}).get("stderr") or ""),
                        cause=render_cause,
                        upstream_outputs=upstream_rows,
                    )
                    if not result_shape.is_document_at_fault(render_cause):
                        # Nothing arrived, so no document could have drawn
                        # anything: dev/133's rule, applied to a picture. The
                        # node WAITS on its upstream (dev/118's vocabulary) and
                        # its document is left exactly as it is.
                        return {
                            "verdict": "fail",
                            "evidence": {
                                "kind": contracts.EMPTY_RENDER_KIND,
                                "detail": refusal,
                                "upstreamEmpty": True,
                            },
                            "rounds": rounds_used,
                            "candidate": candidate,
                            "delegations": delegations,
                            "roundsTrace": rounds_trace + [
                                f"round {rounds_used}: the document is valid and its "
                                "last render drew nothing — its input was empty"
                            ],
                            "attempts": attempts + [{
                                "round": rounds_used,
                                "contentSha256": _content_sha(candidate),
                                "verdict": "fail", "kind": contracts.EMPTY_RENDER_KIND,
                                "detail": refusal[:agents_budgets._ATTEMPT_DETAIL_CHARS],
                                "source": "current content",
                                **_attempt_code_field(candidate),
                            }],
                            "stoppedBy": "blocker",
                        }
                    verdict_result = {
                        "verdict": "fail",
                        "evidence": {"kind": contracts.EMPTY_RENDER_KIND, "detail": refusal[:2000]},
                    }
                    yield "round_verdict", {"round": rounds_used, "verdict": "fail"}
                    rounds_trace.append(f"round {rounds_used}: fail — {refusal[:200]}")
                    attempts.append({
                        "round": rounds_used, "contentSha256": _content_sha(candidate),
                        "verdict": "fail", "kind": contracts.EMPTY_RENDER_KIND,
                        "detail": refusal[:agents_budgets._ATTEMPT_DETAIL_CHARS],
                        "source": "current content",
                        **_attempt_code_field(candidate),
                    })
                    previous_attempt = candidate
                    previous_error = refusal
                    url_evidence = []
                    continue
                evidence["documentValidated"] = document_validation.canonical_suffix(node_type)
            else:
                evidence["documentUnchecked"] = str(document.get("why") or "")[:300]
                evidence["documentPassive"] = bool(document.get("passive"))
        if verdict_result.get("verdict") == "pass":
            # dev/138: the run passed and produced NO output — `return None`
            # types as "null", which read as success in three places at once.
            # The journal and the consumer type check now name it too; here it
            # becomes the round's own verdict, with the node's own conclusion
            # quoted back and the decline path named.
            from utk_curio.backend.app.execution import runtime_journal as _journal

            produced = (verdict_result.get("evidence") or {}).get("output") or {}
            if _journal.is_absent_output(produced):
                refusal = result_shape.absent_output_refusal(
                    code=candidate,
                    output_data_type=str(
                        (verdict_result.get("evidence") or {}).get("outputDataType") or ""
                    ),
                    upstream_outputs=(extra_inputs or {}).get("upstreamOutputs"),
                )
                verdict_result = {
                    "verdict": "fail",
                    "evidence": {"kind": "empty-result", "detail": refusal[:2000]},
                }
                yield "round_verdict", {"round": rounds_used, "verdict": "fail"}
                rounds_trace.append(f"round {rounds_used}: fail — {refusal[:200]}")
                attempts.append({
                    "round": rounds_used, "contentSha256": _content_sha(candidate),
                    "verdict": "fail", "kind": "empty-result",
                    "detail": refusal[:agents_budgets._ATTEMPT_DETAIL_CHARS],
                    "source": "current content" if use_current else "generated",
                    **_attempt_code_field(candidate),
                })
                previous_attempt = candidate
                previous_error = refusal
                url_evidence = []
                continue
        if verdict_result.get("verdict") == "pass" and result_summary_fn is not None:
            # dev/133: "it ran" is not "it worked". A node that produced a
            # countable result with NO rows in it, out of inputs that had rows,
            # destroyed the dataflow's data — the owner's `e72c7080` joined
            # community-area numbers to census-tract ids, ran clean in 45 ms,
            # and left the pool and the chart empty while the chat said solved.
            # The check is silent whenever it cannot attribute the emptiness.
            artifact = ((verdict_result.get("evidence") or {}).get("output") or {}).get("path")
            summary = None
            if artifact:
                try:
                    summary = result_summary_fn(artifact)
                except Exception:  # noqa: BLE001 — a shape we cannot read is not a failure
                    summary = None
            upstream_rows = (extra_inputs or {}).get("upstreamOutputs")
            # dev/137 (dev/133's own F1): a result can be non-empty and still
            # contain nothing. A `how="left"` join on keys that cannot match
            # keeps its rows and fills the other side with nulls — the row
            # count passes, the field check passes (the column exists), and
            # every plot below is empty. An all-null column this node CREATED
            # is the same verdict as no rows at all.
            null_created = (
                result_shape.created_null_columns(summary, upstream_rows)
                if not result_shape.is_empty(summary) else []
            )
            if null_created and result_shape.inputs_had_rows(upstream_rows) is not False:
                refusal = result_shape.null_refusal_text(
                    columns=null_created,
                    summary=summary,
                    upstream_outputs=upstream_rows,
                )
                verdict_result = {
                    "verdict": "fail",
                    "evidence": {"kind": "empty-result", "detail": refusal[:2000]},
                }
                yield "round_verdict", {"round": rounds_used, "verdict": "fail"}
                rounds_trace.append(f"round {rounds_used}: fail — {refusal[:200]}")
                attempts.append({
                    "round": rounds_used, "contentSha256": _content_sha(candidate),
                    "verdict": "fail", "kind": "empty-result",
                    "detail": refusal[:agents_budgets._ATTEMPT_DETAIL_CHARS],
                    "source": "current content" if use_current else "generated",
                    **_attempt_code_field(candidate),
                })
                previous_attempt = candidate
                previous_error = refusal
                url_evidence = []
                continue
            if result_shape.is_empty(summary) and (
                result_shape.inputs_had_rows(upstream_rows) is not False
            ):
                refusal = result_shape.refusal_text(
                    summary=summary,
                    upstream_outputs=upstream_rows,
                    output_data_type=str(
                        (verdict_result.get("evidence") or {}).get("outputDataType") or ""
                    ),
                )
                verdict_result = {
                    "verdict": "fail",
                    "evidence": {"kind": "empty-result", "detail": refusal[:2000]},
                }
                yield "round_verdict", {"round": rounds_used, "verdict": "fail"}
                rounds_trace.append(f"round {rounds_used}: fail — {refusal[:200]}")
                attempts.append({
                    "round": rounds_used, "contentSha256": _content_sha(candidate),
                    "verdict": "fail", "kind": "empty-result",
                    "detail": refusal[:agents_budgets._ATTEMPT_DETAIL_CHARS],
                    "source": "current content" if use_current else "generated",
                    **_attempt_code_field(candidate),
                })
                previous_attempt = candidate
                previous_error = refusal
                url_evidence = []
                continue
        yield "round_verdict", {
            "round": rounds_used, "verdict": verdict_result["verdict"],
        }
        round_evidence = (verdict_result.get("evidence") or {})
        rounds_trace.append(
            f"round {rounds_used}: {verdict_result['verdict']}"
            + (
                # dev/127: the exception line, whole — this is the line that
                # reached the owner's chat as "round 2: execution-error — de".
                " — " + failure_text.summary(
                    round_evidence.get("stderrTail") or round_evidence.get("detail") or "",
                    code=candidate, limit=200,
                )
                if verdict_result["verdict"] != "pass"
                else f" — output {round_evidence.get('outputDataType') or '?'}"
            )
        )
        attempt = {
            "round": rounds_used,
            "contentSha256": _content_sha(candidate),
            "verdict": verdict_result["verdict"],
            "kind": round_evidence.get("kind"),
            "source": "current content" if use_current else "generated",
        }
        if round_evidence.get("detail"):
            attempt["detail"] = str(round_evidence["detail"])[:agents_budgets._ATTEMPT_DETAIL_CHARS]
        if round_evidence.get("stderrTail"):
            attempt["stderrTail"] = str(round_evidence["stderrTail"])[-agents_budgets._ATTEMPT_STDERR_CHARS:]
        if round_evidence.get("outputDataType"):
            attempt["outputDataType"] = round_evidence["outputDataType"]
        if round_evidence.get("durationMs") is not None:
            attempt["durationMs"] = round_evidence["durationMs"]
        if round_evidence.get("reusedNodes"):
            attempt["reusedNodes"] = list(round_evidence["reusedNodes"])[:12]
        if reuse_retried:
            attempt["reuseRetried"] = True
        if verdict_result["verdict"] != "pass":
            # dev/127: the code that ran and failed, ON the attempt — the
            # owner could not see any of it without opening another chat.
            attempt.update(_attempt_code_field(candidate))
        attempts.append(attempt)
        if verdict_result["verdict"] != "fail":
            stopped_by = "passed" if verdict_result["verdict"] == "pass" else (
                "infrastructure" if verdict_result["verdict"] == "infrastructure" else None
            )
            break
        if round_evidence.get("kind") == "precondition" or round_evidence.get("upstreamEmpty"):
            # dev/118: the runner refused the SLICE (bound, cycle), or an
            # upstream has no content yet — no correction of THIS content can
            # change that; one round says so.
            stopped_by = "blocker"
            break
        previous_attempt = candidate
        previous_error = round_evidence.get("stderrTail") or round_evidence.get("detail") or ""
        url_evidence = _correction_url_evidence(candidate, previous_error, grounding_ctx)
        if url_evidence:
            # The endpoint's real answer joins the trail the card shows, so a
            # key-gated API reads as such instead of as a JSON decode error.
            attempt["endpointEvidence"] = _url_evidence_summary(url_evidence)
    final_evidence = (verdict_result or {}).get("evidence") or {}
    final_verdict = verdict_result["verdict"] if verdict_result else "fail"
    if (
        is_data_loading
        and resolve_source is not None
        and final_verdict == "fail"
        and final_evidence.get("kind") in ("ungrounded-source", "source-missing")
    ):
        # dev/126: the round itself proved the source is missing — the gate
        # refused the literal the builder wrote, or the builder declined and
        # named what it needs. THIS is where the old dead end was: a failure
        # whose remedy text asked the user to attach the Dataset Finder by
        # hand. Discovery is initiated on that evidence, the attempt trail is
        # kept (the user sees what was tried), and the node WAITS instead of
        # failing.
        try:
            post = resolve_source(node, grounding_ctx, stage="post") or {}
        except Exception:  # noqa: BLE001
            log.warning("Post-failure source resolution failed for node %s",
                        node_id, exc_info=True)
            post = {}
        if post.get("state") == "unresolved" and post.get("detail"):
            final_evidence = {**final_evidence,
                              "discovery": str(post["detail"])[:600]}
            rounds_trace.append(
                f"discovery found no source — {str(post['detail'])[:160]}"
            )
        if post.get("state") == "awaiting":
            detail = str(post.get("detail") or "a source must be selected")
            rounds_trace.append(f"awaiting dataset selection — {detail[:160]}")
            return {
                "verdict": "awaiting-source",
                "evidence": {
                    "kind": "awaiting-selection",
                    "detail": detail[:2000],
                    "after": str(final_evidence.get("detail") or "")[:600],
                    **({"remedy": {
                        "kind": "dataset-selection",
                        "attachmentId": post["attachmentId"],
                        "nodeId": node_id,
                    }} if post.get("attachmentId") else {}),
                },
                "rounds": rounds_used,
                "candidate": "",
                "delegations": delegations,
                "roundsTrace": rounds_trace,
                "attempts": attempts,
                "stoppedBy": "source",
            }
    return {
        "verdict": final_verdict,
        "evidence": final_evidence,
        "rounds": rounds_used,
        "candidate": candidate,
        "delegations": delegations,
        "roundsTrace": rounds_trace,
        "attempts": attempts,
        # dev/127: which bound ended the loop. Unset means the rounds ran out.
        "stoppedBy": stopped_by or "rounds",
    }
