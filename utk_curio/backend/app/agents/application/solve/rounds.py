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
import re as _re
import time
import tokenize

from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import contracts
from utk_curio.backend.app.agents.domain import failure_text
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import verified_loop

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
    loop = verified_loop.VerifiedRounds(
        user_key, project_id,
        spec=spec, node=node, resolution=resolution, config=config,
        parent_execution_id=parent_execution_id, parent_coord=parent_coord,
        attachment_id=attachment_id, exec_fn=exec_fn,
        grounding_loop_ctx=grounding_loop_ctx, grounding_base=grounding_base,
        start_from_current=start_from_current, extra_inputs=extra_inputs,
        delegate_runner=delegate_runner, dataset_paths_fn=dataset_paths_fn,
        exec_user_key=exec_user_key, secrets_fn=secrets_fn,
        prior_outputs_fn=prior_outputs_fn, resolve_source=resolve_source, clock=clock,
        recorded_failure=recorded_failure, node_budget_s=node_budget_s,
        carry_forward=carry_forward, result_summary_fn=result_summary_fn,
    )
    return (yield from loop.run())
