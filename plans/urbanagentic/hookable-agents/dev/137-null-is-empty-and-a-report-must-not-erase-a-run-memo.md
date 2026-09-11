# dev/137 — A column of nulls is an empty result, a stale line is not a status, and a browser report must never erase a sandbox run

**Status: PROPOSED (2026-09-10) on `imp/agentcatalog` @ `16e2a772`. Every claim below was read from
the owner's project `7a27b702-27a9-4abb-bd3b-2994ce40cad8` on disk.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `16e2a772` (dev/136's docs commit).
Origin: owner report — *"The data flow is still generating empty Vega Lite and Autark plots; nothing
seems to have changed. Additionally, there is an error in the solve status panel, even though all
nodes have the solved flag."* — with the screenshot of `7a27b702` and *"check the project in the
screenshot"*.
Family: dev/129 (the repair reads recorded failures) → dev/133 (an empty RESULT is a verdict; its
**F1**: *"a wrong-but-non-empty result … needs different evidence than a row count"*) → dev/134 (one
write gate) → dev/135 (browser outcomes journaled) → dev/136 (an empty RENDER is a failure) →
**dev/137 (this memo)**.
Design decisions consumed: `DEC-052`, `DEC-073`, `DEC-063`, `DEC-006`.

---

## 1. Problem Statement

### D1 — a browser report ERASES the sandbox's record of the same node (a dev/135 regression)

The project's journal holds six records. **Every one says `origin: "browser"`** — including the four
nodes that run in the sandbox:

```
1447d909 status=ok origin=browser kind=- dataType=''   (vis-vega)
1b133767 status=ok origin=browser kind=- dataType=''   (data-transformation — a PYTHON node)
72a4e478 status=ok origin=browser kind=- dataType=''   (computation-analysis — a PYTHON node)
75e150b8 status=ok origin=browser kind=- dataType=''   (data-loading — a PYTHON node)
87d2bfa2 status=ok origin=browser kind=- dataType=''   (data-loading — a PYTHON node)
cf928482 status=ok origin=browser kind=- dataType=''   (autk-grammar)
```

Those Python nodes ran: their editors show `[1]: Saved to file: 1789085558476_d3e445aa`. The sandbox
wrote their records — with `output.path`, `output.dataType`, the `stderrTail` and the code digest —
and then dev/135's reporter, which fires when `data.output` settles (i.e. AFTER the response lands),
overwrote each with `{status: ok, output: {path: "", dataType: ""}, stderrTail: ""}`. The journal is
latest-per-node, so the richer record is simply gone.

dev/135's memo predicted the opposite (*"the server's record is the later one for that run"*). It is
not: the client always writes last. What that destroys:

- `runtime_journal.last_failure` for a code node — a Play traceback is replaced by a browser `ok`, so
  dev/129's *repair from the error a Play run raised* is dead for every code node;
- `failure_matches` can never match (no digest, no stderr);
- `node_context.runtime` reports `origin: browser, outputType: ""` for a Python node that produced a
  `geodataframe`, so dev/135's own fix now hands agents a worse description than the sandbox had.

This is the most urgent item in this memo, because it silently removes evidence three other features
depend on.

### D2 — the Solve panel shows lines from passes that are over

The strip shows every pill **solved**, *"Finished — nothing left to do."*, and, at the same time:

- *"not fixed after 15 attempts (stopped by a repeated attempt) — execution-error: SyntaxError:
  invalid syntax · at `<string>`:3 · raised by the code's own check"*
- *"pending — waiting — upstream node `1b133767-d6cd-47dc-9f05-bfdc139f387b` has no content yet —
  solve or fill it first"*

`1b133767` ended `solved · pass after 5 rounds` and holds 620 characters of content, and the session
finished in 46 s. Both red lines are **true of an earlier pass and false now**: dev/131 made Solve a
session of passes, and the provider's per-node `solveErrors` / `solveNotices` / `solveRemedies` maps
are only ever written — never cleared when a later `node_result`, a later pass, or a completed
session supersedes them. A panel that says *solved* and *not fixed* at once is worse than either
message alone, because the user cannot tell which is current.

### D3 — a join that produced NULLS passes every check, and its plots are empty

`1b133767`'s content says what it did, in its own comment:

```python
# The current datasets have mismatched keys: 'area_numbe' (Community Area) vs 'tract_id' (Census Tract).
# In a real scenario, a crosswalk table would be needed.
# To allow the dataflow to proceed and be tested, we perform a join on the available columns
# if they were to match, but since they don't, this will likely result in an empty GDF.
joined_gdf = boundaries.merge(population_data, left_on='area_numbe', right_on='tract_id', how='left')
```

A **left** join on keys that cannot match keeps the two boundary rows and fills every population
column with null — which the Data Pool shows verbatim (`area_numbe 32, community Loop,
median_income null, population null`). Then:

- **dev/133 passes it**: the artifact has 2 rows, and the check counts rows. This is dev/133's own
  recorded **F1**, arriving as a live defect.
- **dev/134 passes the chart**: `1447d909` encodes `field: "population"`, which *exists* in the joined
  frame — the field check reads names, and names are fine.
- **dev/136 does not catch the picture**: with every `population` null, Vega-Lite's default invalid
  handling drops those rows, so the chart draws its axes (`Loop`, `Hyde Park`, a degenerate
  `0.000000` X tick) and no bars. The journal's record for `1447d909` is `status: ok` with **no
  `kind`** — so on this run nothing reported an empty render at all.
- The Autark map is the same story one node later: `72a4e478` projects the same all-null frame and
  `cf928482` colours by it.

Three failures of measurement, one cause: **a result can be non-empty and still contain nothing**.
And a fourth, of contract: a node told that its inputs cannot be joined chose to *"allow the dataflow
to proceed"* with a placeholder join rather than say so — the exact pattern this repo's own rule
forbids (fix the primary path; fail loudly; never swallow).

### Expected behavior

- **R1** A browser report never erases a sandbox or validation record. Each origin keeps its own
  facts, and a reader asking "what did this node's last RUN do" gets the run, not the render.
- **R2** The Solve panel shows only what is currently true: a node that solved carries no error,
  notice or waiting line from an earlier pass, and a finished session shows no pending line.
- **R3** A node whose produced result has rows but **no usable values in a column it created** is an
  empty result — a failed round with the column named, like dev/133's zero-row case.
- **R4** A render whose encoded field has no usable values is an empty render, whether or not the
  renderer drew a zero-extent mark.
- **R5** The content contract forbids the placeholder join: when inputs cannot be joined, the node
  says so and fails; it never fabricates rows, fills nulls, or "proceeds to be tested".
- **R6** No claim is invented anywhere: an unreadable preview, an unknown column, an uncountable
  render all keep today's behavior.

---

## 2. Scope

**In scope.**
- `app/execution/runtime_journal.py`: per-origin records — a browser report is stored beside the run
  record, never over it; `read_record` keeps meaning "the last RUN", and the render record is its own
  read. `last_failure` prefers the run's failure and falls back to the render's.
- `app/agents/node_context.py`: the `runtime` block reports the run and, when present, the render.
- `app/agents/result_shape.py`: `null_columns(summary)` — which columns a preview shows as entirely
  null — and the refusal text for it.
- `app/agents/services.py`: dev/133's check also fails a round whose produced columns are all null;
  the diagnosis names the columns and the join keys.
- `utils/renderOutcome.ts` + `hook/useVega.ts`: count the rows whose encoded fields are USABLE, so an
  all-null encoding is an empty render regardless of how the renderer treats invalid values.
- `components/agents/attach/AgentAttachmentsProvider.tsx`: clear a node's error/notice/remedy when a
  later result supersedes it, and clear the waiting list when a session ends complete.
- `llm-prompts/new_content_prompt.txt`: the placeholder-join prohibition, in the words the failure
  will use.
- Tests on both sides; docs; ledgers.

**Out of scope.**
- Whether the two datasets *should* be joinable (they are not; the honest outcome is a failed node
  and the Dataset Finder — dev/126/132's lane).
- Rewiring or replacing a dataset automatically (`DEC-006`).
- The Data Pool's own four empty states, which still reach no journal (recorded as **F1**).

---

## 3. Recommended Implementation Approach

### A. One record per origin (D1)

`<project>/runtime/<nodeId>.json` keeps its shape and its meaning — **the last RUN** — and a browser
report writes `<nodeId>.render.json`. Consequences, all of them deliberate:

- a code node's traceback, artifact and dataType survive forever, whatever the browser reports;
- a grammar node's only record is its render, which is exactly what it has;
- `read_record` is unchanged for every existing caller; `read_render_record` is the new read;
- `last_failure` asks the run first (a traceback is the stronger evidence and the repair loop's
  historical input), then the render — so dev/136's empty-render branch still fires, and dev/129's
  Play-traceback repair comes back;
- `status_map` reports the run when there is one, else the render, with the origin saying which.

### B. A status panel shows only what is current (D2)

In the provider, one helper — `clearNodeSolveState(attachmentId, nodeId)` — drops that node's error,
notice and remedy, called from the `node_result` handler before the new state is written, and from
the `solve_pass` handler for every node the new pass will attempt. On `done` with
`endedBy: "complete"`, the waiting list is cleared. The strip then cannot show *solved* and *not
fixed* at once, and *"Finished — nothing left to do"* cannot sit above a pending line.

### C. Nulls are emptiness (D3, the result half)

`result_shape.null_columns(summary)` returns the columns whose every sampled value is null, using
dev/127's bounded preview (`sampleRows`). The loop's dev/133 check gains a second condition: a
produced table whose **created** columns — those not present in any input — are entirely null is an
empty result. The refusal names them and the keys:

> the code ran and produced 2 rows, but every value of `population`, `median_income` and `density` is
> null — the join matched no rows and `how="left"` filled them. Join on columns whose values are the
> same kind of thing, or say plainly that these inputs cannot be joined; never keep rows with null
> values to let the dataflow proceed.

The comparison against the inputs' columns matters: a column that was *already* null upstream is not
this node's doing (dev/133's attribution rule), and a column this node created and left null is.

### D. Nulls are emptiness (D3, the render half)

`useVega` already parses the values before compiling. Counting, per encoded field, how many rows hold
a usable value (not null/undefined/NaN) costs one pass over the bounded array, and
`renderOutcome` gains `usableRows`: zero usable rows with rows present is `nothing-drawn`, whatever
the scenegraph shows — so a zero-extent bar can no longer read as "drawn". The message names the
field, which is what the correction needs.

### E. The contract (D3, the cause)

`new_content_prompt.txt` gains one prohibition in the words the refusal uses: *never fabricate rows,
fill nulls, or keep a join that matched nothing "to let the dataflow proceed" — if the inputs cannot
be joined, say so in one line and return no code.* dev/115 already treats such a decline as terminal
and reports it honestly; the prompt simply stops inviting the placeholder.

---

## 4. Data and State Handling

- **Two records, one node**: `<nodeId>.json` (the run) and `<nodeId>.render.json` (the render). Both
  latest-per-origin, both best-effort, both fail-open. No migration: an absent render record reads as
  None, and an existing run record is untouched.
- **Null detection** reads dev/127's bounded preview only — no new fetch, no full column scan; a
  preview of 8 rows all null is reported as "all sampled values are null", in those words.
- **Created vs inherited columns**: computed by comparing the produced summary's columns against the
  inputs' (`upstreamOutputs[].schema.columns`), which the loop already holds.
- **Frontend state**: the provider's maps stay per-attachment and per-node; clearing is a delete, not
  a sentinel, so nothing renders a cleared entry.
- **Unknowns**: no preview → no null claim; no input schemas → treat every null column as created
  only when the node has NO inputs, else make no claim.

---

## 5. UI and UX Requirements

- The strip's per-node line shows the CURRENT state only. A solved pill has no error text; a finished
  session has no waiting line.
- A node failed for all-null output reads *"not fixed after N attempts — empty-result: … every value
  of `population` is null …"*, in the existing failure register.
- A Vega node whose encoding has no usable values shows the dev/136 error message naming the field.
- No new controls, no layout change.

---

## 6. Edge Cases

| Case | Behavior |
|---|---|
| A column that was already null in the input | Not this node's doing; no claim (dev/133's attribution rule). |
| A column legitimately null for some rows | Only ALL-null columns count; a partially null column is data, not a defect. |
| A node with no inputs (a loader) that produces a null column | Reported: a loader that read nothing useful is the loader's problem. |
| A preview too large to read | No null claim, as dev/133 already does for row counts. |
| A run record and a render record disagreeing (`ok` run, empty render) | Both are true of different things; `last_failure` prefers the run's failure, and the render's is used when the run has none — which is exactly the grammar-node case. |
| A code node that never renders | No render record; everything reads as before. |
| A grammar node with no run record | Its render record is its record; `status_map` and `node_context` report it. |
| A cleared error line for a node that fails again in a later pass | The new failure writes a new line; clearing is per event, not permanent. |
| A session that ends `stopped`/`budget`/`blocked` | The waiting list is KEPT — it is still true that those nodes wait. |
| An all-null encoding in a chart whose other encoding is fine | Reported: a bar chart with no usable x has nothing to draw. |

---

## 7. Testing Strategy

**Journal** — a browser report does not touch the run record; both are readable; `last_failure`
prefers the run's failure and falls back to the render's; `status_map` reports the run when present
and the render otherwise; a grammar node with only a render record behaves as dev/135/136 expect; the
owner's exact sequence (sandbox write, then browser report) leaves the artifact and dataType intact.

**`result_shape.null_columns`** — all-null columns found from `sampleRows`; a partially null column is
not reported; inherited columns excluded; no preview → no claim; bounds.

**The loop** — a candidate producing rows whose created columns are all null fails with
`empty-result` naming the columns; the correction that produces values passes; an inherited null
column does not fail the node; the owner's exact shape (a `how="left"` join on mismatched keys) is a
regression test.

**Frontend** — `renderOutcome` with `usableRows: 0` is `nothing-drawn` naming the field;
`useVega`'s usable count over null/NaN/undefined values; the provider clears a node's error on a new
result, clears the waiting list on a complete session, and keeps it on stopped/budget/blocked.

**Integration** — after a Solve that fails the transformation, the strip shows a failed pill with
one current message and no stale pending line.

---

## 8. Acceptance Criteria

1. A Python node's journal record keeps its artifact, dataType and traceback after the browser
   reports its own outcome; `last_failure` finds the Play traceback again.
2. The Solve panel never shows an error, notice or pending line for a node whose current status is
   solved, and a completed session shows no waiting line.
3. A join that produces rows of nulls fails its round with the columns named, and the corrected code
   passes.
4. A chart whose encoded field has no usable values is reported as an empty render naming the field.
5. The content prompt forbids the placeholder join, in the words the refusal uses.
6. Nothing new is claimed where the evidence is absent.
7. Backend and jest suites green; `tsc --noEmit` clean.

---

## 9. Recommended Commit Breakdown

1. The journal: one record per origin, the reads, `last_failure`'s preference (+ tests).
2. `node_context`'s run-and-render block (+ tests).
3. `result_shape.null_columns` + the loop's null-column verdict (+ tests, the owner's regression).
4. The render half: `usableRows` in `renderOutcome` and `useVega` (+ jest).
5. The provider's stale-state clearing (+ jest).
6. The prompt, docs, memo close, `dev/00` row, BL entry.

---

## 10. Engineering Quality Checklist

- The regression is fixed by separating two records, not by ordering two writers — an ordering
  assumption is what broke it.
- Every existing reader of `read_record` keeps its meaning; the new read is additive.
- Null-emptiness reuses dev/127's bounded preview and dev/133's attribution rule; no new I/O.
- The frontend clears state on the event that supersedes it, so no timer, no sentinel, no drift.
- One vocabulary: `empty-result` for a result that contains nothing, `empty-render` for a picture that
  shows nothing, with the same "who is at fault" rule in both.
- The prompt states the prohibition in the words the failure uses, so the model reads the rule and
  the diagnosis as one thing (`DEC-063`).
- The honest limit is stated: these two datasets cannot be joined, and the product's job is to say so,
  not to draw an empty chart.
