# dev/129 — Nothing unvalidated reaches a node, nothing stops trying before its budget, and every recorded execution error feeds the fix

**Status: PROPOSED (2026-09-10) on `imp/agentcatalog` @ `7f2b0baf`. Every line number and every
piece of evidence below was read on that commit.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `7f2b0baf` (dev/128 commit 5).
Origin: three owner instructions, in order —
1. *"the dataflow keeps failing, the validation runtime should keep trying to solve for at least
   15 mins, with many retries as possible, it should never put failing code inside a node."*
2. *"Check whether this has to do with a previously reported loose end:
   `nodeContext.current_input/current_output` still sent empty (BL-P2-10, restated BL-P5-02)."*
3. *"the dataflow resolution must be able to read errors raised by any execution and properly act
   to fix it."*
Family: dev/67-2 (`DEC-052`, the runtime journal) → dev/115 (`DEC-073`, the one verified loop) →
dev/118 (`DEC-075`, waves + *written, not executed*) → dev/119 (`DEC-076`, executability from the
roster) → dev/127 (the trail, the budget, the input schemas) → dev/128 (the slot authority and the
input contract) → **dev/129 (this memo)**.
Design decisions consumed: `DEC-073`, `DEC-075`, `DEC-076`, `DEC-052`, `DEC-063`, `DEC-072`,
`DEC-006`.

---

## 0. The question first: is this the `current_input/current_output` loose end?

**Partly — and it is live on this branch, which is worth knowing on its own.**

- The loose end is real here: `agentRunContext.ts:105`-`:115` still builds `nodeContext` as
  `{id, type, content, current_input: "", current_output: ""}` with the comment *"Legacy
  NodeExplanation payload shape; in/out empty when unexecuted"*, and
  `src/utils/nodeRuntimeSummary.ts` does not exist. dev/111 fixed exactly this — on
  `feat/agentscatalog`, which is never merged back (`git branch --contains` lists
  `feat/agentscatalog` and `bug/agentcatalog`, not `imp/agentcatalog`). Same situation dev/125
  found for dev/112.
- But it is **not the cause of the Solve failures**. That payload is the FRONTEND's run context,
  composed when you send a message to an attached agent (Node Explainer, Debug, a chat request).
  Solve never uses it: it composes its own context server-side (`node_context.compose_node_context`)
  and hands the child `upstreamOutputs`, `sourceGrounding`, `inputContract`. The failures in
  `623b6620` and `00708324` came from the merge slot order (dev/128 §0.1), invented column names
  (dev/127's schemas + dev/128's slot table), and — the subject of this memo — content written
  into a node without being validated at all.
- The loose end and this memo share one rule, which is why the question was the right one to ask:
  **the runtime knows, so it must tell the agent.** So the port is in scope here (§3D), and after
  it a chat agent asked *"why is this node red?"* reads the same runtime truth the repair loop does.

---

## 1. Problem Statement

### D1 — a "solved" node can hold content that was never validated at all

`DEC-075` (dev/118) made Solve honest about kinds the sandbox cannot run: they are written and
labeled *"no code to run; renders in the browser or its own service"*
(`services.py:4490`-`:4497`). Honest, and too permissive: for `vis-vega` and `autk-grammar` the
content is a **grammar document**, and being unrunnable in the sandbox does not mean being
uncheckable. The owner's `00708324` proves it — the Vega spec Solve wrote and called solved is
**invalid**, and `altair` (already a dependency, 6.2.1, schema bundled offline) says why in
milliseconds:

```
Additional properties are not allowed ('else' was unexpected)   ← encoding.color.condition
```

That node renders red on the canvas, and the chat says *solved*. Same for the AUTK node in that
project: 864 characters of grammar JSON, written unread. This is what *"it should never put
failing code inside a node"* names.

### D2 — the loop stops long before its budget

dev/127 gave the loop two bounds and dev/128 set them to the owner's numbers: **10 attempts** and
**15 minutes**, whichever binds first. In practice the attempt cap binds almost immediately — a
failing round takes seconds — so the loop stops at ten while 14 minutes of budget remain, and
reports *"(stopped by the attempt cap)"*. The owner's instruction is that **time is the bound**:
*"keep trying to solve for at least 15 mins, with many retries as possible"*. Two secondary
brakes work against that too: a second repeated candidate ends the loop
(`_MAX_REPEATED_ATTEMPTS = 2`), and `MAX_SOLVE_ATTEMPTS = 20` caps the ceiling well under what 15
minutes affords.

### D3 — the resolution never reads an error it did not itself produce

Every real run records its outcome: `_record_runtime_outcome` (`api/routes.py:478`-`:499`, memo
dev/67-2 / `DEC-052`) journals code, stdout, stderr and output per node for **Play** runs, and the
validation runner journals its own (`runner.py:466`). The journal has exactly **one** reader —
`tools.py:570`, the model-chosen `node.runtime.read` tool. The repair loop never opens it.

So the sequence the owner keeps hitting: Solve writes content, the user presses Play, the node
raises (`ed1a326f`: `KeyError: 'tract_id'`, recorded at `runtime/ed1a326f….json` with
`validation: false`), and the next Solve or Retry **starts from scratch** — generating a fresh
candidate as if nothing had happened, instead of fixing the failure that is on disk. *"The
dataflow resolution must be able to read errors raised by any execution and properly act to fix
it."*

### Expected behavior

- **R1** No content reaches a node unless it passed a check appropriate to its kind: executed in
  the sandbox (code kinds), or validated as a document (grammar kinds). A kind with no available
  check is **not written** — the node stays pending with the reason.
- **R2** The repair loop keeps trying while its wall budget allows — as many attempts as fit —
  and the attempt ceiling exists only as a safety net, not as the normal stop.
- **R3** A repeated candidate does not end the loop: it escalates what the next round is told.
- **R4** Resolution reads the **recorded outcome of any execution** — Play or validation — and
  when the node's current content is what last failed, the fix starts from that content and that
  traceback.
- **R5** `nodeContext.current_input/current_output` carry the truthful runtime summary on this
  branch too (the dev/111 port), so a chat agent sees what the loop sees.

### Why it matters

R1 is the difference between a dataflow that reports itself solved and one that is. R2/R3 are the
owner's patience, spent where it can help. R4 is the difference between a loop that repairs and a
loop that regenerates — and it is the cheapest fix of the four, because the evidence is already on
disk.

---

## 2. Scope

### In scope

- new `app/agents/document_validation.py` — kind-routed validation of non-executable content:
  Vega-Lite through `altair`'s bundled schema (offline, with the runtime's own data injection
  accounted for), AUTK grammar through JSON + required-key checks, and an explicit
  *"no validator for this kind"* answer.
- `app/agents/services.py` — the `not-executable` branch validates before writing; the loop's
  bounds re-tuned (time first, ceiling as a net, repeats escalating); the journal read at the
  start of a node's resolution and used to seed the fix.
- `app/execution/runtime_journal.py` — a small read helper for "the last recorded failure of this
  node, whatever ran it" (the record already carries it; this names it).
- Frontend: the dev/111 port — `utils/nodeRuntimeSummary.ts` + `agentRunContext.ts` — and the
  attempt card's wording for the new `document-invalid` kind.
- `llm-prompts/new_content_prompt.txt` — one line: a grammar document is validated before it is
  written, and the validator's message is the correction.
- Tests: new `test_document_validation.py`; the loop's budget/repeat behavior; the journal-seeded
  fix; the port's jest tests; a route test that an invalid Vega spec is NOT written.
- Docs + ledgers as usual.

### Out of scope

- Rendering AUTK/Vega in a headless browser to prove they draw. The reference preview runner
  (dev/98) exists behind a seam and is operator-installed; document validation is the cheap,
  always-available half. Recorded as a follow-up.
- A frontend endpoint that reports render errors back to the journal (so R4 covers browser
  failures too). Real and wanted; its own memo, because it is a new write path with its own
  permissions.
- The batch deadline (45 min) and the sandbox's per-run timeout (300 s) stay as they are; a node
  that spends 15 minutes is a node the batch's own budget then accounts for.
- Vega-Lite *semantics* beyond the schema (a field that does not exist in the data is a schema-valid
  spec; dev/127's column summaries are what address that, and they now ride grammar children too).

### Related code paths

`_node_is_executable` / `pins.executable` (dev/119), `_apply_contents` (the one write), the
`not-executable` branches in both Solve paths, `tools._node_runtime_read` (the existing journal
reader — its bounds are the precedent for the new one), dev/127's attempt trail (the new kind
must appear there with its code), dev/128's gate (the same pre-write refusal shape).

---

## 3. Recommended Implementation Approach

### A. `document_validation.py` — validate what cannot be run

```python
def validate(kind: str, content: str) -> dict:
    """{"status": "valid"} | {"status": "invalid", "detail": …} | {"status": "unchecked", "why": …}"""
```

Routed by the node's canonical template id, not by a name list (dev/119's rule):

- `vis-vega`: JSON parse → inject a minimal placeholder `data` (Curio's runtime supplies the
  node's input at render time, so a spec without `data` is correct here) → `altair.Chart.from_dict(
  spec, validate=True)`. A `ValidationError` becomes the refusal, its message trimmed to the
  offending property and path — the owner's spec yields *"encoding.color.condition: additional
  property 'else' is not allowed"*.
- `autk-grammar`: JSON parse → the grammar's required shape (a `map` object, at least one
  `layerRefs` entry, each with a `dataRef`; `initialView.center` a two-number array when present).
  Bounded, structural, and honest about what it does not check.
- `vis-simple`, `merge-flow`, `data-pool`, and any kind whose content is the *"not controllable"*
  marker: nothing to validate and nothing to write — those nodes carry no authored content, so the
  write is skipped rather than "validated".
- anything else: `unchecked`, with the kind named.

### B. The write gate

In both Solve paths, the `not-executable` branch becomes:

```python
verdict = document_validation.validate(kind, candidate)
if verdict["status"] == "valid":   # written, with verification {"status": "document-valid", …}
elif verdict["status"] == "invalid":  # a failed ROUND (kind: document-invalid) → the loop corrects
else:                              # unchecked → NOT written; node pending with the reason
```

The `invalid` case is the important one: it is not a terminal failure but a **round**, so the
existing loop corrects it with the validator's message — the same shape as the `DEC-072` source
gate and dev/128's input contract. A grammar node therefore gets the same retry budget as a code
node, and its trail shows the invalid document beside the validator's complaint.

### C. Time is the bound (R2, R3)

- `DEFAULT_SOLVE_ATTEMPTS` stays the owner's 10 as the *reported* target but stops being the
  practical stop: the loop continues while the wall budget allows, up to
  `MAX_SOLVE_ATTEMPTS`, which rises to a real safety net (40) sized so that 15 minutes of
  seconds-long rounds cannot exhaust it by accident. In other words the check order flips: budget
  first, ceiling second, and `stoppedBy` reports `budget` in the normal case.
- A repeat no longer ends the loop. `_MAX_REPEATED_ATTEMPTS` becomes the count at which the
  correction ESCALATES — the next round is told, in plain words, that it repeated itself N times
  and must change approach (a different library call, a different join key, a different shape) —
  and only an implausible run of identical candidates (8) stops it, as `stoppedBy: "repeat"`.

### D. The journal is an input to resolution (R4)

`runtime_journal.last_failure(user_key, project_id, node_id)` returns
`{code, stderr, status, ranAt, origin: "play" | "validation"}` for a record whose status is
`error` — bounded exactly as `tools._node_runtime_read` bounds its own read.

At the start of a node's resolution (both Solve paths), when the node HAS content and that
content's digest matches the journal's `executedCodeSha256` of a failed run, the loop starts
from it: `start_from_current` semantics for round 0 plus `previousAttempt`/`validationError` seeded
from the record, so the first correction is a fix of the real failure rather than a fresh guess.
The trail says so — *"round 1: the code on the node, which failed at Play with …"*.

### E. The dev/111 port (R5)

`utils/nodeRuntimeSummary.ts` (pure, dev/111's shape) + `agentRunContext.ts`'s `nodeContext`
branch: `current_input` names the upstream's dataType/artifact or *"no upstream input"*;
`current_output` is `success: <dataType> <artifact>`, `never-executed (declared: X)`, or
`error: <message>` truncated — never the output's content. The vocabulary matches the server's
`runtimeStatus` (dev/67-6) so the two never disagree.

---

## 4. Data and State Handling

| Datum | Source of truth | Read by |
|---|---|---|
| Whether content may be written | the sandbox run (code kinds) or `document_validation` (grammar kinds) | `_apply_contents`, both Solve paths |
| A node's last real failure | the runtime journal (`DEC-052`), any origin | the loop's round 0, the strip |
| The wall budget / ceiling | `solve_node_budget_s()` / `MAX_SOLVE_ATTEMPTS` | the loop |
| Runtime summary for a chat run | the live canvas + `FlowProvider.outputs` | `agentRunContext` |

No new persisted state. The journal is read-only here; the write gate changes *whether*
`applied_contents` receives an entry, not how it is written.

---

## 5. UI and UX Requirements

- A grammar node that failed validation appears in dev/127's trail with kind `document-invalid`,
  the validator's message, and the document it refused — so the user sees the offending property.
- A node whose content could not be validated at all is **pending**, with *"written nothing —
  no validator for `<kind>`; Play it to see whether it renders"*, never "solved".
- A node whose resolution started from a recorded Play failure says so in its first trail line —
  the user learns that the loop read the error they saw.
- The verification chip on a written grammar node reads *"document valid — not executed"* instead
  of *"no code to run"*: a stronger, still truthful claim.
- Accessibility and copy rules unchanged (bounded plain text, native disclosure).

---

## 6. Edge Cases

1. **A Vega spec that is valid but references absent fields** — schema-valid, so it is written;
   dev/127's column summaries are what make the fields right, and the memo says so rather than
   pretending the schema catches it.
2. **A Vega spec with `data` already present** — the injection must not overwrite it.
3. **An AUTK grammar with an unknown top-level key** — structural checks pass what they do not
   know; the validator states its limits in `unchecked` reasons rather than inventing rules.
4. **`not controllable` content** on a merge/pool/vis-simple — nothing written, nothing claimed.
5. **A JSON document with a trailing comma / single quotes** — a parse error is `invalid` with the
   line and column, which is a perfectly good correction.
6. **altair absent or a schema mismatch at import time** — `unchecked` with the reason; the gate
   degrades to today's behavior for that kind rather than blocking Solve.
7. **A node whose journal record is for OTHER content** (the user edited it since) — the digest
   comparison fails, so the loop does not "fix" code that is no longer there.
8. **A journal record from a validation run vs from Play** — both usable; the origin is named in
   the trail so the user knows which run they are reading.
9. **A node with content that failed at Play and passes validation now** (an upstream was fixed) —
   round 0 runs it as-is and passes: nothing regenerated, nothing rewritten.
10. **The wall budget expires mid-round** — unchanged from dev/127: the round completes and is
    recorded; no new round starts.
11. **An implausible run of identical candidates** — escalates, then stops at 8 with
    `stoppedBy: "repeat"`, so a stuck model cannot burn 15 minutes of provider calls.
12. **A batch of many nodes where one spends its full budget** — the batch deadline still applies
    and the remaining nodes stay pending with the reason (dev/118), which is the honest trade.

---

## 7. Testing Strategy

**Unit — `document_validation`**: the owner's own Vega spec is `invalid` and the message names
`else`; a corrected spec is `valid`; a spec that already has `data` keeps it; a parse error is
`invalid` with position; the owner's AUTK grammar is `valid`; grammars missing `map`, `layerRefs`
or a `dataRef` are `invalid`; `not controllable` is skipped; an unknown kind is `unchecked`.

**Loop**: an invalid Vega document is a failed ROUND that the next candidate fixes (and the trail
carries the document); an `unchecked` kind writes NOTHING and reports pending; the budget keeps
the loop going past the reported attempt target when the clock allows; a repeat escalates the next
correction and only a long run of them stops it.

**Journal-seeded fix**: a node whose content matches a failed Play record starts from that content
with that traceback in the correction, says so in the trail, and does not regenerate blindly; a
digest mismatch (edited since) does not seed.

**Route**: an invalid Vega spec never reaches the saved spec — the node is not written, the trail
explains, and Retry after a corrected candidate writes it.

**Frontend (jest)**: the dev/111 port's summary vocabulary (executed / never-executed / error),
`current_input`'s upstream naming, and that output CONTENT is never forwarded.

**Required before complete**: the validator units, the write-gate loop tests, the journal-seeded
test, the route test, the port's tests — and a live re-run of `00708324` where the Vega node is
either written valid or reported unwritten with the validator's reason.

---

## 8. Acceptance Criteria

1. No node ever receives content that was neither executed successfully nor validated as a
   document; a kind with no validator is left empty and reported, never "solved".
2. The owner's invalid Vega spec is refused, corrected within the budget, and only the corrected
   document is written.
3. A grammar node's failed validation appears in the transcript trail with the document and the
   validator's message.
4. The repair loop keeps attempting while its 15-minute budget allows; `stoppedBy` reads `budget`
   in the normal exhaustion case, and the attempt ceiling is a safety net, not the stop.
5. A repeated candidate escalates the next correction; only an implausible run of them stops the
   loop.
6. Resolution reads the recorded outcome of any execution: a node whose current content failed at
   Play is fixed FROM that failure, and the trail names the origin.
7. A journal record for content the node no longer has is never used as the basis of a fix.
8. `nodeContext.current_input/current_output` carry the runtime summary on this branch; output
   content is never forwarded.
9. Suites green: `tests/test_agents`, `tests/test_execution`, `tests/test_projects`, jest,
   `tsc --noEmit`, with only the pre-existing unrelated `test_packages` failure.
10. A live re-run of `00708324` reports no node as solved whose content was never checked.

---

## 9. Recommended Commit Breakdown

1. **`document_validation.py` + tests** — the validators, nothing wired.
2. **The write gate** — the `not-executable` branch validates; invalid becomes a round; unchecked
   writes nothing; the verification chip's copy; loop and route tests.
3. **Time is the bound** — budget-first checks, the ceiling as a net, repeats escalating; tests.
4. **The journal as an input** — `last_failure` + the seeded round 0; tests.
5. **The dev/111 port** — `nodeRuntimeSummary.ts`, `agentRunContext.ts`, jest.
6. **Prompts, docs, ledgers** — the instruction line, `AGENT-CATALOG.md`, `USAGE.md`, dev/00,
   `BL-P5-…-64`, this memo's status and §12, and the loose end marked closed on this branch.

---

## 10. Engineering Quality Checklist

- One validator module, kind-routed from the same roster `pins.executable` reads (`DEC-076`).
- One write gate: content reaches `applied_contents` only through it.
- One journal reader shape, bounded like the existing tool's.
- No fallback that writes unchecked content silently; absence is reported.
- The invalid case is a ROUND, so it inherits the trail, the budget and the correction contract
  rather than inventing a parallel failure path.
- The port reuses dev/111's pure summarizer shape and its vocabulary, so client and server agree.
- Types explicit; every new status a closed set (`valid` / `invalid` / `unchecked`).

---

## 11. Open questions and recorded follow-ups

- **F1** Headless rendering (dev/98's preview runner) would prove a grammar node draws, not just
  that it parses. Operator-installed today; worth wiring behind the same seam when demand exists.
- **F2** A frontend endpoint reporting render errors into the journal would let R4 cover browser
  failures as well as sandbox ones. Its own memo (a new write path, with permissions).
- **F3** Vega field references against the input's real columns — schema validation cannot see
  them; dev/127's summaries are the lever, and a targeted check ("every `encoding.*.field` exists
  in the input schema") is a candidate for the same gate.
- **F4** dev/128 F1 (a tuple-returning code upstream) and F3 (an unconnected merge slot) remain.
- **F5** Owner live re-run of `00708324` and `623b6620`.
