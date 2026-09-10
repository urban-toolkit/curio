# dev/134 — One write gate for every node kind: a grammar document is validated, a wired node is never authored, and prose is never content

**Status: PROPOSED (2026-09-10) on `imp/agentcatalog` @ `743cec57`. Every line number below was read
on that commit; every claim about the failing dataflow was read from the owner's saved project.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `743cec57` (dev/132's docs commit).
Origin: owner report — *"the autark node is not solved with the correct JSON grammar structure"* and
*"the Vega Lite doesn't plot any data"* — with the screenshot of
`e72c7080-0ec7-4d6a-8e05-e4ea115997c7` and that project's saved files.
Family: dev/118 (`DEC-075`, written-not-executed) → dev/119 (`DEC-076`, executability from the
roster) → dev/127/128 (the trail, the input contract) → dev/129 (nothing unvalidated is written —
`document_validation.py`) → dev/131 (the session) → **dev/134 (this memo)**. Sibling: dev/133 (the
empty result), which owns the *data* half of the same screenshot.
Design decisions consumed: `DEC-075`, `DEC-076`, `DEC-063`, `DEC-006`, `DEC-053`.

---

## 1. Problem Statement

**The evidence, read from disk.** In project `e72c7080`, three nodes hold the literal string
`not controllable` as their **content**:

| Node | Type | Content on disk | The child's reply (`agent-sessions/`) |
|---|---|---|---|
| `6719ef79` | `curio.builtin/merge-flow` | `not controllable` | `not controllable` |
| `6d88d2fc` | `curio.builtin/data-pool` | `not controllable` | `not controllable` |
| `b7c01f6a` | `curio.builtin/autk-grammar` | `not controllable` | `not controllable` |

and one holds a Vega-Lite document that **does not validate**:

- `6aff812f` (`curio.builtin/vis-vega`): running dev/129's own validator over the content on disk
  returns `{"status": "invalid", "detail": "Additional properties are not allowed ('else' was
  unexpected) — Failed validating 'additionalProperties'"}` — the malformed conditional inside
  `encoding.color`. It also encodes `y.field: "neighborhood"`, a column that exists in **no**
  upstream frame (the joined frame's name column is `community`).

Yet the chat says *Solved 7 of 7 plan nodes* and the strip shows seven green pills. The four nodes
above were reported as *"curio.builtin/<kind> has no code the sandbox could run — written, not
executed"*.

**Why.** dev/129 built exactly the right machinery — `document_validation.validate` returns
`valid` / `invalid` / `unchecked`, an invalid document is a failed ROUND, an unchecked one is
**written nothing** — and put it inside `_verified_content_rounds`. But the batch only enters that
loop for nodes the roster calls executable:

```
services.py:5137   if verify and _is_executable(node):        # dev/119 (DEC-076)
```

and `is_executable_kind` is `category == "code"` (`workflow_spec.py:113-121`). `vis-vega` and
`autk-grammar` are `grammar`; `merge-flow`, `data-pool`, `vis-simple` and `spatial-join` are
`passive`. All of them therefore take the plain generate-and-write path at `services.py:4826`, which

1. extracts content from the reply,
2. runs the `DEC-072` source-grounding gate (a path/URL check — it has nothing to say about a
   document's structure), and
3. **writes whatever came back**, marking the node `solved` with
   `verification: {"status": "not-executable"}`.

So dev/129's document validation is, on the product path, **unreachable for the two kinds it was
written for**, and there is no gate at all against a prose reply. Three consequences, all visible in
the screenshot:

- **D1 — prose becomes content.** `not controllable` is a model's way of saying *"I have nothing to
  author here"*. It was written into three nodes as their document/code, so the Autark node's
  grammar is the string `not controllable` (the owner's third symptom) and two wired nodes carry
  junk. (dev/129's `document_validation.NOT_CONTROLLABLE` already knows that string means "no
  document" — nothing consulted it.)
- **D2 — an invalid Vega document is written and called solved.** The exact class of defect dev/129
  was written to stop, reproduced because the gate is not on this path.
- **D3 — nodes that have no content at all are asked to author it.** `merge-flow` and `data-pool`
  are wired, not written: `merge-flow` declares `containerStyle.noContent: true`, both declare
  `hasCode: false`, `hasGrammar: false`, `editor: "none"`, and their behaviors
  (`mergeFlowBehavior.ts`, `dataPoolBehavior.tsx`) derive everything from the wiring and the input.
  Asking a model for their content spends a provider call to produce something that can only be
  wrong — and `_template_entry`'s `authorable` flag (dev/90 A14, for the post-it note profile) says
  they are authorable, which is how they became Solve targets in the first place.

**Expected behavior.**

- **R1** Every node kind that carries **authored content** goes through ONE write gate. For a code
  kind that is dev/115's run-and-verify loop; for a grammar kind it is dev/129's document
  validation. Nothing unvalidated is written, on any path.
- **R2** A grammar node whose document does not validate is a **failed round** with the validator's
  message as the correction — the same budget, trail and transcript as any other failure — and after
  exhaustion the node fails with nothing written.
- **R3** A reply that is not a document at all (prose, a decline, `not controllable`) is a refusal,
  never content. A model that genuinely cannot author the document says so and the node fails
  honestly.
- **R4** A node with **no** authored content (`merge-flow`, `data-pool`, `vis-simple`,
  `spatial-join`) is never asked for content and never written to. Solve resolves it immediately,
  truthfully: *"wired, not written"*.
- **R5** A Vega-Lite document's **field references** are checked against the columns the upstream
  actually produced (dev/127's schemas, already handed to the generation request) — the
  `neighborhood`-that-does-not-exist class of defect, recorded as dev/129 **F3**.
- **R6** The routing is read from the **roster** (`DEC-076`), not from a hand-kept list of node
  names: `hasCode` → code, `hasGrammar` + `grammarId` → that grammar's validator, `editor: none`
  with input ports → no content.

---

## 2. Scope

**In scope.**
- `app/packages/services.py`: `_template_entry` and `roster_templates` expose the content facts the
  manifest already declares (`hasGrammar`, `grammarId`), plus the derived `contentKind`.
- `app/execution/workflow_spec.py`: `content_kind(node_type, templates) -> "code" | "grammar" |
  "note" | "none"` beside `is_executable_kind`, with the legacy tables as the offline fallback
  (dev/119's rule).
- `app/agents/services.py`: the batch and the per-node Solve route on `content_kind` —
  code + grammar (and note) enter the verified loop; `none` resolves without a model call.
- `app/agents/document_validation.py`: routing by `grammarId` rather than by template-name suffix; a
  non-document reply is `invalid` (a correction) for a kind that HAS a validator; Vega field
  references checked against known upstream columns; the AUTK `dataRef` check stated against what
  the upstream provides.
- `llm-prompts/new_content_prompt.txt`: the grammar contract — for `vis-vega`, the runtime injects
  `data` (so the document must not carry one) and the fields must come from the named upstream
  columns; for `autk-grammar`, the `{"map": {"layerRefs": [{"dataRef": …}]}}` shape.
- Tests (backend), docs, ledgers.

**Out of scope.**
- Rendering. Whether a *valid* Vega spec looks good, or whether an AUTK map is the right map, is not
  checkable here (dev/129 F1 keeps the headless-render idea; still not proposed).
- The full Vega-Lite and AUTK grammars as hand-written rules — the schema `altair` bundles is the
  authority for Vega, and the AUTK check stays deliberately structural.
- The empty-data half of the same screenshot — dev/133.
- `DEC-006`: unchanged. A node that already has content still changes only through review.

---

## 3. Recommended Implementation Approach

### A. The roster answers "what content does this kind carry?"

The builtin manifest already declares everything needed (read on this commit):

| template | `hasCode` | `hasGrammar` | `grammarId` | `editor` | input ports | → content kind |
|---|---|---|---|---|---|---|
| `data-loading`, `computation-analysis`, … | true | false | — | code | 0–1 | **code** |
| `vis-vega` | false | true | `vega-lite` | grammar | 1 | **grammar** |
| `autk-grammar` | false | true | `autk-grammar` | grammar | 1 | **grammar** |
| `data-pool`, `vis-simple`, `spatial-join` | false | false | — | none | 1–2 | **none** |
| `merge-flow` (`containerStyle.noContent`) | false | false | — | none | 1 | **none** |
| a post-it note (dev/89 profile) | false | false | — | none | **0** | **note** |

So `content_kind` is a derivation, not a list: `hasCode` → `code`; `hasGrammar` → `grammar`;
otherwise `editor == "none"` **with** input ports → `none` (it renders its input, not authored
content); `editor == "none"` **without** input ports → `note` (dev/90 A14's presentation content,
which is authored and has no validator). `containerStyle.noContent` forces `none`. The legacy
category tables answer when there is no roster, exactly as `is_executable_kind` does.

### B. One loop, three verdict sources

The batch's condition becomes "does this node author content?", so a grammar node enters the SAME
loop:

```python
kind = content_kind(node.get("type"), batch_templates)     # dev/134
if kind == "none":
    ...resolve immediately, no model call (§3D)
elif verify and kind in ("code", "grammar", "note"):
    ...the verified loop
```

Inside the loop nothing structural changes, because dev/129 already built the branch: the runner
reports `notExecutable` for a grammar node → `verdict == "not-executable"` → the document validator
runs → `invalid` becomes a failed round (its message is the next round's `validationError`), `valid`
writes with `documentValidated`, `unchecked` writes NOTHING. The gate that was unreachable becomes
the gate on the product path.

### C. `document_validation`, corrected on three points

1. **Routing by `grammarId`.** `validate(node_type, content, *, grammar_id=None, columns=None)`
   prefers the roster's `grammarId` and falls back to the canonical suffix (today's behavior), so a
   package that ships its own Vega node validates too.
2. **A non-document reply is a REFUSAL, not "unchecked".** Today `not controllable` (and any
   non-JSON prose) returns `unchecked`, which for a grammar kind means "write nothing" and stops the
   loop from asking again. For a kind that HAS a validator this becomes `invalid` with a refusal that
   names what was expected — the model gets its correction rounds, and only exhaustion ends it.
   `unchecked` stays exactly what it means: *nothing here can check this kind*.
3. **Vega field references.** When the upstream columns are known, every `field` in `encoding` (and
   in `transform` aggregates/joins) must be one of them, plus the runtime-injected `interacted` and
   `__row_index__` (`useVega.parseInputData` adds them). An unknown field is `invalid`:
   *"encoding.y.field 'neighborhood' is not a column of this node's input — available: community,
   area_numbe, tract_id, population, median_income, area_sqm, density, interacted"*. Unknown columns
   (no artifact, no preview) → the check does not fire; an unverifiable claim is not made.

### D. A wired node is resolved, not authored

For `content_kind == "none"` the batch records, without a model call:

```python
results[node_id] = {"status": "solved", "verification": {
    "status": "no-content",
    "reason": "<label> is wired, not written — this kind has no content to author"}}
```

and its plan row advances. The strip's per-node line says the same. This is honest (the node needs
nothing), cheap (no provider call), and it removes the only way prose could reach those nodes.

### E. The prompt states the two grammar contracts

`new_content_prompt.txt` gains, for a grammar node, the two facts a model cannot infer:

- **Vega-Lite**: *do not include a `data` block — Curio injects this node's input as the data* (the
  runtime overwrites `spec.data`, `useVega.ts`), and *every `field` must be a column named in
  `upstreamOutputs`*; the interaction fields available are `interacted` and `__row_index__`.
- **AUTK**: the document is `{"map": {"layerRefs": [{"dataRef": "upstream", …}], "initialView": …}}`
  and `dataRef: "upstream"` names this node's own input (the shape `docs/examples/09-…json` uses).

---

## 4. Data and State Handling

- **Source of truth for routing**: the project's roster snapshot (dev/119), fetched once per Solve
  and already threaded through the batch as `batch_templates`. No new I/O.
- **Source of truth for the columns**: the `upstreamOutputs` the loop already composes for the
  generation request (dev/127's bounded artifact preview + `upstream_schema.summarize`) — the same
  data the model is handed, so the check and the instruction cannot disagree (`DEC-063`).
- **Derived, never stored**: the content kind and the column list are computed per Solve; nothing
  new is persisted in the spec.
- **A `none` node's state**: `nodeRuns[node] = "solved"` with a `no-content` verification. It is not
  `skipped` (that means a bound refused it) and not `pending` (nothing is owed).
- **Race safety**: unchanged — the batch's single write path and dev/131's merge rules still own the
  persistence.
- **Failure of the check**: an unreachable roster → the legacy tables; an unreadable preview → no
  field check. Both degrade to today's behavior, loudly in the trail and never as a false pass.

---

## 5. UI and UX Requirements

- A grammar node's failure looks like any other failure: the `document-invalid` round in the strip,
  the code + message in the `solveAttempts` transcript part (dev/127), the bound named on exhaustion.
- A `no-content` node's pill reads **solved** with the reason *"wired, not written"* on its row,
  instead of today's *"has no code the sandbox could run — written, not executed"* (which was
  technically true and told the user nothing about what happened to their pool).
- The Solve card's per-node lines keep their existing shape; only the words change.
- No new controls, no new colors, no layout change. Accessibility unchanged.

---

## 6. Edge Cases

| Case | Behavior |
|---|---|
| The model replies `not controllable` for a grammar node | `invalid` → a correction round that names the expected document; exhaustion fails the node with nothing written. |
| The model replies prose for a CODE node | Unchanged: dev/115's prose-decline path (terminal `source-missing`). |
| A valid Vega document that carries its own `data` | Allowed and validated as authored (the runtime overwrites it at render time); the prompt says not to, and the field check still runs against the upstream columns. |
| A Vega document whose fields cannot be checked (no upstream artifact) | Schema-validated only; the trail says the fields were not checked. |
| A multi-view Vega spec (`layer`, `hconcat`, `facet`) | Fields are collected recursively; a spec with per-view `data` is left alone. |
| An AUTK grammar with several `layerRefs` | Each must name a `dataRef`; the structural check is unchanged. |
| A package template with `hasGrammar` and an unknown `grammarId` | `unchecked` → nothing written, and the trail says no validator exists for that grammar. |
| A post-it note template (`note`) | Authored, no validator → `unchecked` → today's behavior for presentation content (written, said to be unexecuted) — deliberately unchanged. |
| `spatial-join` (two input ports, `editor: none`) | `none`: wired, not written. Its legacy mapping remains dev/118 F5's business. |
| A node the user already filled | Unchanged: `skipped`, content preserved. |
| The roster is unreachable | Legacy tables: grammar kinds still route to the loop (they are `grammar` in `classify_node`), passive kinds still resolve as `none`. |

---

## 7. Testing Strategy

**Unit — `content_kind` (`test_content_kind.py`)**: every builtin template's kind from a roster
snapshot; the `noContent` override; the note case (no input ports); an unknown type; no roster
(legacy fallback).

**Unit — `document_validation` (extend `test_document_validation.py`)**:
`not controllable` and prose are now `invalid` for a kind with a validator and still `unchecked` for
one without; routing by `grammarId`; the Vega field check (a good spec passes, an unknown field is
invalid and the message lists the available columns, `interacted`/`__row_index__` are allowed, a
`layer`/`hconcat` spec is walked, unknown columns skip the check); the owner's exact invalid spec is
still reported with `'else' was unexpected`.

**Loop (`test_verified_rounds.py`)**: a `vis-vega` target whose first document is invalid gets a
correction round and the valid second document is written; an `autk-grammar` target that replies
`not controllable` three times ends failed with nothing written; a `data-pool` target is resolved
with `no-content` and **no** provider call.

**Regression (`test_written_documents_regression.py`)** — the owner's exact project shape: a plan
with `merge-flow`, `data-pool`, `autk-grammar` and `vis-vega`; the scripted child replies exactly
what the field log shows (`not controllable`, and the invalid Vega spec); assert that **no** node's
content is `not controllable`, that the Vega node is not written while invalid, that the two wired
nodes are `no-content`, and that the Solve card does not claim seven solved.

**Frontend**: no change (the strip and the cards read the same fields); the jest suite is the
regression check that nothing regressed.

---

## 8. Acceptance Criteria

1. No node in any project can end a Solve holding `not controllable` (or any other prose) as its
   content.
2. An invalid Vega-Lite document is never written: it is a failed round with the validator's message,
   and the owner's exact spec is reported as `'else' was unexpected` inside `encoding.color`.
3. A Vega document referencing a field no upstream column provides is refused, with the available
   columns named.
4. An AUTK node either holds a document with `map.layerRefs[].dataRef` or fails with the shape
   stated — never a sentence.
5. `merge-flow` and `data-pool` are never sent to a model and are reported *wired, not written*.
6. A code node's behavior is byte-for-byte unchanged (same rounds, same trail, same writes).
7. The routing reads the roster: no new hand-kept list of node names exists in the backend.
8. `tests/test_agents` green, jest green, `tsc --noEmit` clean.

---

## 9. Recommended Commit Breakdown

1. The roster's content facts + `content_kind` + its unit tests (no behavior change yet).
2. `document_validation`: `grammarId` routing, prose-is-invalid, the Vega field check (+ tests).
3. The batch and the per-node Solve route on `content_kind`: grammar kinds enter the loop, `none`
   kinds resolve without a call (+ loop tests).
4. The prompt's grammar contracts (+ the byte-pin update, if the prompt is pinned).
5. The regression suite from the owner's project, docs, memo close, `dev/00` row, BL entry.

---

## 10. Engineering Quality Checklist

- One gate, one loop: the document check is not duplicated on a second path — the second path is
  removed by routing into the first.
- Routing derives from declared facts (`DEC-076`), so a new grammar kind or a package's own
  visualization node needs no backend edit.
- `document_validation` stays pure and total; the field check is optional and silent when the columns
  are unknown — no invented failures.
- The instruction and the check read the SAME columns (`DEC-063`): a model is never refused for
  ignoring something it was not told.
- No new persisted state, no new request per round, no provider call for a node that has no content
  (a saving, not a cost).
- Truthful copy: *wired, not written* for a `none` node; *validated as a document, not executed* for
  a grammar node; both already in dev/129's vocabulary.
- Deliberate limits recorded rather than hidden: rendering is still unchecked (dev/129 F1), and a
  `note`'s content still has no validator.
