# dev/136 — An empty plot is a failed render: Curio counts what was drawn, and the harness fixes what emptied it

**Status: PROPOSED (2026-09-10) on `imp/agentcatalog` @ `f5cf04b7`. Every line number below was read
on that commit.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `f5cf04b7` (dev/135's docs commit).
Origin: owner report — *"Another major issue: Vega-Lite and Autark nodes render empty plots. Curio
must properly detect empty output so the harness can validate and fix it accordingly."*
Family: dev/118 (`DEC-075`, written-not-executed) → dev/129 (documents validated before written) →
dev/133 (an empty RESULT is a verdict — for code nodes) → dev/134 (one write gate; the Vega field
check) → dev/135 (`DEC-052`'s journal takes browser outcomes) → **dev/136 (this memo)**.
Design decisions consumed: `DEC-052`, `DEC-073`, `DEC-075`, `DEC-063`, `DEC-006`.

---

## 1. Problem Statement

dev/133 made an empty **result** a verdict, and dev/134 made a document's **structure** a verdict.
Neither sees an empty **picture**: a document can be schema-valid, reference columns that exist, run
without an error, and draw nothing at all. Both renderers report that as success, and since dev/135
they now journal it as success — so the harness is told the node is fine.

### D1 — Vega-Lite emits success whatever it drew

`useVega.compileGrammar` injects the node's input as the data and compiles:

```ts
let values: any = await parseInputData(data.input);   // may be []
specObj["data"] = { values: values, name: "data" };
…
view.runAsync().then(…)                               // no count is read
```

and `vegaBehavior.applyGrammar` then calls
`nodeState.setOutput({ code: 'success', content: '', outputType: '' })` unconditionally. A chart over
zero rows renders its axes and nothing else; a chart over rows whose encoded field is entirely null
renders an empty panel. Both are `success`, and dev/135 journals both as `status: "ok"`.

### D2 — an Autark map silently drops the layers it cannot resolve

`autkGrammarBehavior` resolves the spec's `layerRefs` against the tables the data section actually
produced and **drops** the ones it cannot find:

```ts
const dangling = spec.map.layerRefs.filter(r => r?.dataRef && !availableNames.has(r.dataRef));
if (dangling.length > 0) { console.warn('[autk-grammar] dropping map layerRef(s) …');
                           spec.map = { ...spec.map, layerRefs: spec.map.layerRefs.filter(…) }; }
```

A `console.warn` is the only trace. When **every** ref is dropped, `grammar.run(spec)` renders a map
with no layers — a grey canvas — and the node emits `{code: 'success'}`. The plot section is dropped
the same way. This is the Autark half of the owner's report, and it is invisible to everything
except the browser console.

### D3 — a data/compute Autark run reports zero rows as a success

`describeAutkRun('Computed', 'layer', layers.map(l => \`${l.name} (${…features?.length ?? 0} rows)\`))`
already counts what it produced, and a run whose every layer is `0 rows` still emits
`{code: 'success', content: summary}`. The count is in the sentence; nothing reads it.

### D4 — the harness could not fix it even if it were told

Two reasons, both structural:

1. **The verdict does not exist for a document kind.** dev/133's emptiness check reads the artifact a
   *sandbox* run stored (`result_summary_fn` over `evidence.output.path`); a grammar node produces no
   artifact, so no shape is ever checked for it.
2. **Round 0 would pass.** dev/134 routes a grammar node into the verified loop, where round 0
   validates the document that is already there. An empty-rendering document **validates**, so the
   round passes, the loop stops, and nothing is corrected — even when dev/135's journal holds the
   render failure, because the loop has nothing that turns a recorded *render* failure into a failed
   round the way a re-run turns a recorded traceback into one.

### Expected behavior

- **R1** A render that drew nothing is reported as a **failure**, not a success — by both renderers,
  through dev/135's journal, with the counts as evidence.
- **R2** The report names the cause class, because the fix differs: **no rows arrived** (the input is
  empty — the upstream is what must change), **rows arrived and nothing was drawn** (the document is
  what must change), or **no layers left to draw** (the document references data the graph does not
  produce).
- **R3** The harness treats a recorded empty render as a failed round for a grammar node: round 0
  reports it instead of passing a document that validates, the correction gets the counts and the
  cause, and nothing is written until a document is produced that has something to draw — or the
  node fails honestly with the diagnosis.
- **R4** Attribution is never guessed. When the input had no rows, the document is not blamed and the
  upstream is named (dev/133's own rule, applied to a render).
- **R5** The detection never blocks, delays or changes a render (dev/135's contract), and never
  forwards the data — only counts.

---

## 2. Scope

**In scope.**
- `utils/renderOutcome.ts` (new, pure, frontend): the one decision — given `{rowsIn, drawn,
  layersRequested, layersDrawn}`, did this render draw anything, and if not, which cause class is it?
  Plus the message each class produces.
- `hook/useVega.ts`: count the injected rows and the marks the view actually rendered (the scenegraph
  walk `buildVgsidMap` already performs), and hand both to the behavior.
- `adapters/node/vegaBehavior.ts`: emit `error` with the render-outcome message when nothing was
  drawn, `success` otherwise.
- `adapters/node/autkGrammarBehavior.tsx`: the dropped-`layerRef` path stops being a `console.warn`
  only — dropping every layer is an empty render; a data/compute run whose every table is empty is
  an empty result; both go through the same module.
- `services/nodeRuntimeReport.ts` + `POST /nodeRuntime` + `runtime_journal`: an optional `kind` on the
  report (`empty-render`), so a reader can branch without matching a string, and the counts ride the
  message.
- `app/agents/services.py`: the loop's grammar path turns a recorded `empty-render` failure into a
  failed round 0 with the diagnosis, instead of passing a document that validates.
- `app/agents/result_shape.py`: the empty-render refusal text, beside dev/133's empty-result one —
  one module for "this produced nothing" in both its forms.
- Tests on both sides, docs, ledgers.

**Out of scope.**
- Judging whether a non-empty plot is a GOOD plot (dev/129 F1's headless render idea).
- Auto-rewiring a graph whose upstream is empty (`DEC-006`: a graph change is a proposal).
- Counting marks for kinds Curio does not render itself (a package's own visualization declares its
  own outcome through the same report).

---

## 3. Recommended Implementation Approach

### A. One pure decision, two renderers (`renderOutcome.ts`)

```ts
export type RenderCause = "no-input-rows" | "nothing-drawn" | "no-layers" | null;
export function renderOutcome(counts: RenderCounts): { empty: boolean; cause: RenderCause; message: string };
```

The rule, in order, because the order IS the attribution:

1. `layersRequested > 0 && layersDrawn === 0` → **`no-layers`**: *"the map has no layer left to draw
   — every layerRef names a table this dataflow does not produce (requested: a, b; available:
   table_osm)"*. The document is what must change.
2. `rowsIn === 0` → **`no-input-rows`**: *"nothing to draw — 0 rows arrived at this node"*. The
   UPSTREAM is what must change, and the message says so.
3. `rowsIn > 0 && drawn === 0` → **`nothing-drawn`**: *"3 rows arrived and nothing was drawn — the
   encoding, a transform or a scale domain removed every row"*. The document is what must change.
4. otherwise not empty.

Pure and total, tested directly — the same discipline as `nodeRuntimeSummary` and `result_shape`.

### B. Vega counts what it drew

`parseInputData` already produces the array; `compileGrammar` already walks the scene graph
(`buildVgsidMap`). Counting the mark items in that same walk costs nothing, so the behavior receives
`{rowsIn: values.length, drawn: markCount}` and emits `error` with the message when the outcome is
empty. A spec that legitimately draws no marks (a text-only annotation layer) is the edge case §6
answers.

### C. Autark reports what it dropped, and what it produced

The dangling-ref filter keeps its behavior (dropping is the right recovery) and gains a report:
`layersRequested`/`layersDrawn` and the available table names go into the outcome, so *"every
layerRef names a table this dataflow does not produce"* reaches the journal instead of the console.
A data/compute run passes its per-layer feature counts, so an all-zero run is an empty result with
the same vocabulary.

### D. The report carries a kind, and the journal keeps it

`{kind: "empty-render"}` on the report and on the record. Two consumers need it: the loop, which must
distinguish "the render failed with an error" from "the render drew nothing" (the corrections
differ), and `node_context`, which can then say which it was without a reader parsing prose.

### E. The harness: a recorded empty render is a failed round 0

In `_verified_content_rounds`, for a `grammar` node whose recorded failure is an `empty-render`:

- round 0 does **not** pass on a valid document. The document validation still runs (an invalid
  document is still an invalid document, and that is the first thing to fix), and when the document
  is valid the recorded render failure becomes the round's verdict:
  `{"verdict": "fail", "evidence": {"kind": "empty-render", "detail": <the message + the counts>}}`;
- the correction request carries `previousAttempt` (the document) and `validationError` (the render
  message), exactly as a traceback would;
- when the cause is `no-input-rows`, the loop does not ask for a new document at all: the diagnosis
  names the upstream, the node ends with that reason, and dev/133's rule holds — a node is never
  blamed for emptiness it did not create.

`result_shape.empty_render_refusal(...)` composes the text from the counts plus the upstream columns
the loop already holds, so the child reads *what the input actually was* alongside *what was drawn*.

---

## 4. Data and State Handling

- **Source of truth for the counts**: the renderer itself, at render time — the injected row array
  and the rendered scene graph (Vega), the resolved layers and their feature counts (Autark).
  Nothing is inferred from the document.
- **Transport**: dev/135's report (status + bounded message + kind); the data is never sent, and the
  counts travel inside the message plus the kind field.
- **Persistence**: the journal record, as dev/135 established — latest per node, `origin: "browser"`.
- **The loop's read**: `runtime_journal.last_failure` + `failure_matches` against the node's current
  content (already wired) — so a document edited since its empty render is not corrected from a
  stale complaint.
- **Empty vs unknown**: a renderer that cannot count (a package's own visualization) reports no
  counts, and the outcome is *not* empty — an unverifiable claim is never made.

---

## 5. UI and UX Requirements

- A Vega or Autark node that drew nothing shows the node's existing **error** state with the
  render-outcome message, instead of a green *Done* over a blank panel. That is the whole user-facing
  change, and it is the honest one: the picture is empty, the badge should not say otherwise.
- The message is one short sentence and names the next action implicitly (fix the upstream vs fix the
  encoding), matching `nodeEmptyState`'s existing register.
- The Autark console warning stays for debugging; it is no longer the only trace.
- No new controls, no layout change, no blocking.

---

## 6. Edge Cases

| Case | Behavior |
|---|---|
| A spec that legitimately draws no marks for its data (a rule/annotation-only layer, a text mark over an empty selection) | `drawn` counts every mark item the scene graph holds, including text and rules, so an annotation-only chart is not empty. A spec whose scene graph is genuinely empty is empty. |
| A deliberately empty filter | Reported as `nothing-drawn`, and the harness's correction may legitimately fail — the same accepted trade-off dev/133 recorded, stated in the docs. |
| An Autark map with SOME layers dropped | Not empty (something was drawn); the dropped names still ride the message as a warning on a successful run (dev/135's stdout note). |
| An Autark data/compute node with one non-empty table | Not empty. |
| A render that throws | Unchanged: dev/135 already reports the error, and it is not an empty render. |
| A renderer that cannot count | No counts → not empty; nothing is claimed. |
| The document is invalid AND the last render was empty | The invalid document wins: dev/134's validation is the first thing to fix, and an invalid document cannot draw at all. |
| `no-input-rows` where the upstream is a pass-through (a pool, a merge) | The message names the immediate upstream and its own status, which dev/135's runtime block already carries for neighbours. |
| A stale empty-render record after the user edits the grammar | `failure_matches` refuses it (digest mismatch), so the loop does not correct a complaint about a document that is gone. |
| Repeated identical empty renders | dev/135's deduplication keeps it to one report per real change. |

---

## 7. Testing Strategy

**Frontend unit (`renderOutcome.test.ts`)** — the four answers in order: layers requested and none
drawn; zero rows in; rows in and nothing drawn; a normal render. Plus: partial layer drops are not
empty; absent counts are not empty; the message names the requested and available tables for
`no-layers`, the row count for `no-input-rows`, and both counts for `nothing-drawn`; every message
is bounded.

**Frontend behavior tests** — a Vega render over zero rows emits `error` with the message and reports
`kind: "empty-render"`; a render with marks emits `success`; an Autark map whose every `layerRef` is
dangling emits `error` naming the tables; one surviving layer emits `success`; an all-zero
data/compute run emits `error`.

**Backend** — the journal keeps `kind`; `node_context` carries it; the loop's grammar path turns a
recorded `empty-render` into a failed round 0 whose correction receives the message; a
`no-input-rows` cause does NOT ask for a new document and names the upstream instead; a document
that is invalid AND has an empty-render record is corrected for the invalidity first; a stale record
(digest mismatch) is ignored.

**Integration** — the owner's shape: a Vega node with a valid document over an empty pool renders
nothing, reports it, and the next Solve of that node reports the upstream rather than rewriting the
chart; and a Vega node over real rows whose encoding removes everything gets a corrected document.

---

## 8. Acceptance Criteria

1. A Vega-Lite node that renders an empty plot shows an error with a message that says why, and
   journals `status: "error"`, `kind: "empty-render"`.
2. An Autark node whose every `layerRef` was dropped does the same, naming the unavailable tables —
   instead of a grey canvas under a green *Done*.
3. An Autark data/compute run whose every layer is empty does the same.
4. A render that drew something is unchanged in every respect.
5. Solving a grammar node whose last render was empty produces a **correction**, not a pass on a
   document that merely validates.
6. When the input had no rows, the diagnosis names the upstream and the document is not rewritten.
7. No render is blocked, delayed or otherwise changed; no data leaves the browser.
8. `tests/test_agents` + `tests/test_execution` green; jest green; `tsc --noEmit` clean.

---

## 9. Recommended Commit Breakdown

1. `renderOutcome.ts` + its unit tests (pure, no wiring).
2. Vega: the counts and the emit (+ tests).
3. Autark: the dropped-layer and all-empty reports (+ tests).
4. The `kind` through the report, the route, the journal and `node_context` (+ tests).
5. The harness: a recorded empty render as a failed round 0, with `no-input-rows` attributed
   upstream (+ tests, integration).
6. Docs, memo close, `dev/00` row, BL entry.

---

## 10. Engineering Quality Checklist

- One decision module for both renderers, so "empty" cannot mean two things in one product.
- The counts come from the renderers themselves; nothing is inferred from a document or a model.
- Attribution before blame: the input's row count decides whether the document or the upstream is at
  fault, and the harness acts accordingly (dev/133's rule, extended to renders).
- `DEC-052`'s contract holds: observational, bounded, fire-and-forget, never blocking a render.
- No data crosses the wire — counts and a sentence.
- The loop gains one branch, not a second loop: the same rounds, budget, trail and transcript.
- The trade-off (a deliberately empty chart now reads as a failure) is stated in the docs, as
  dev/133's was.
