# dev/133 — A node that destroys its data has not passed: the empty result is a verdict, not a success

**Status: PROPOSED (2026-09-10) on `imp/agentcatalog` @ `743cec57`. Every line number below was read
on that commit; every claim about the failing dataflow was read from the owner's saved project.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `743cec57` (dev/132's docs commit).
Origin: owner report — *"Still some issues with the dataflow built: the datapool is empty; the Vega
Lite doesn't plot any data"* — with the screenshot of `e72c7080-0ec7-4d6a-8e05-e4ea115997c7`
("Solved 7 of 7 plan nodes", "Finished in 12s", every pill green) and that project's saved files.
Family: dev/115 (`DEC-073`, the verified Solve — code that RAN) → dev/118 (`DEC-075`, every
executable kind) → dev/127 (upstream columns handed to every round) → dev/128 (the input contract)
→ dev/129 (nothing unvalidated is written) → **dev/133 (this memo)**.
Design decisions consumed: `DEC-073`, `DEC-075`, `DEC-063`, `DEC-006`.

---

## 1. Problem Statement

**The evidence, read from disk.** In project `e72c7080`:

- `fc185d92` (Python Computation) holds
  `joined_gdf = gdf_boundaries.merge(df_population, left_on='area_numbe', right_on='tract_id')`,
  and its own comment says *"Based on inputContract, boundaries use 'area_numbe' and population uses
  'tract_id'"*.
- `runtime/fc185d92-….json` records `status: ok`, `output.dataType: geodataframe`, 45 ms — a clean
  run, on the user's own Play.
- The two datasets it joined: `data.urbanlab.chicago-community-areas` has
  `area_numbe ∈ {32, 41}` (integer community-area numbers, 2 features) and
  `data.urbanlab.acs-neighborhood-profile` has `tract_id ∈ {17031010100, 17031010200, 17031010300}`
  (11-digit census tract ids, 3 rows). **The join key sets are disjoint by construction — these are
  two different geographies.** The merge returns **zero rows**.
- Downstream, `6d88d2fc` (Data Pool) renders `NODE_EMPTY_COPY["not-tabular"]` — *"Nothing to
  display / This input is not tabular data"* — because `useTableData` drops a `geodataframe` whose
  `data.features` is empty (`hook/useTableData.ts:243`), so the pool has no tab to show.
- `6aff812f` (Vega-Lite) plots nothing because `useVega.compileGrammar` injects
  `specObj["data"] = {values: await parseInputData(...)}` (`hook/useVega.ts`) and that array is
  empty.

So the owner's two symptoms — *the datapool is empty*, *the Vega-Lite doesn't plot any data* — are
**one defect**: a node destroyed all of its data and Solve called it **solved**.

**Why the runtime could not see it.** `DEC-073`'s verified loop asks the sandbox to RUN the
candidate and reads the run's status. `validation.py:175-182` turns a successful run into
`{"verdict": "pass", "evidence": {"kind": "executed", "outputDataType": …}}`. Nothing in that
verdict describes the SHAPE of what was produced. "It ran" and "it worked" are different claims, and
for a join, a filter, a spatial predicate or a groupby they come apart exactly when the model
guessed a key: the code is syntactically fine, the run is clean, and the result is empty.

An empty result is also the most expensive failure mode in the product, because it propagates
silently: every downstream node "succeeds" on nothing, the canvas looks built, and the user is left
comparing an empty pool against a chat that says *Finished — nothing left to do*.

**Expected behavior.**

- **R1** A round whose code ran but produced an EMPTY table (or geotable) — where every input it
  consumed had rows — is a **failed round**, not a pass. Nothing empty is written to the node.
- **R2** The failure names the real diagnosis, not the symptom: which node, what it produced, what
  its inputs held (row counts, the key columns and their **sample values**), and the likeliest
  cause — a join or filter that matched nothing.
- **R3** The correction rounds get that text as their error, so the loop's existing budget (dev/129:
  40 attempts / 15 min) is spent on the real problem.
- **R4** When no round can produce rows — the honest case here, because these two datasets cannot be
  joined — the node ends **failed with that diagnosis**, its downstream dependants stay pending with
  *"waiting — upstream"*, and the Dataset Finder attached to the loader is the named next step
  (dev/126/132). A green *solved* on an empty dataflow is the outcome this memo removes.
- **R5** No new claim is invented. Every number in the diagnosis is read from an artifact the
  sandbox already stored (dev/127's bounded preview), never from the model.

---

## 2. Scope

**In scope.**
- `app/agents/result_shape.py` (new, pure): is a produced artifact empty, and the refusal text for
  the case, composed from the node's own inputs.
- `app/agents/services.py`: inside `_verified_content_rounds`, after a `pass` verdict, the
  emptiness check → a `empty-result` failed round; the diagnosis carries the inputs the loop already
  holds (`upstreamOutputs`, dev/127's schemas with `rowCount` and `sampleRows`).
- `app/agents/upstream_schema.py`: reuse `summarize` (it already reports `rowCount` for tables and
  geotables) — read-only.
- Tests: unit tests for the pure module; loop tests for the round; a regression test built from the
  owner's exact shape (two frames whose key sets are disjoint).
- Docs + ledgers.

**Out of scope / deliberately unchanged.**
- Play's semantics. A user's own Play run is theirs: it keeps reporting what happened and writes
  nothing. Only the AGENT's verified loop gains a verdict.
- The runner, the sandbox and the artifact store: the preview endpoint already exists (dev/127).
- Any judgement about whether a non-empty result is *correct* (the values, the projection, the
  units). This memo is about the one claim the runtime can check cheaply and certainly: emptiness.
- The datasets themselves. Curio must not silently substitute a dataset that joins.

---

## 3. Recommended Implementation Approach

### A. One pure module for the verdict (`result_shape.py`)

```python
def is_empty(summary: dict | None) -> bool          # a table/geotable with rowCount == 0
def inputs_had_rows(upstream_outputs: list | None) -> bool | None   # True / False / None (unknown)
def refusal_text(*, summary, upstream_outputs, code) -> str
```

`summarize` (dev/127) already yields `{"kind": "table"|"geotable"|"parts", "columns": [...],
"rowCount": n, "sampleRows": [...]}`, so `is_empty` is a read of facts the runtime holds, and
`refusal_text` composes the diagnosis from the same structure. Pure: no I/O, no spec, no network —
tested directly, like `failure_text` and `input_contract`.

The refusal reads, for the owner's case:

> the code ran but produced an EMPTY result — 0 rows out of a `geodataframe`. Its inputs were not
> empty: slot 0 `Chicago Boundaries` (geotable, 2 rows: `community` str e.g. "Loop", `area_numbe`
> int e.g. 32), slot 1 `Population Data` (table, 3 rows: `tract_id` str e.g. "17031010100",
> `population` int e.g. 4521). A join or filter matched nothing: compare the key columns' VALUES,
> not their names — `area_numbe` is a community-area number and `tract_id` is an 11-digit census
> tract id, so they cannot match. Either join on columns whose values are the same kind of thing, or
> say plainly that these inputs cannot be joined.

Three properties of that text matter: it states the cause class (join/filter), it shows values (the
column NAMES looked joinable — the values never did), and it offers the honest alternative (say it
cannot be done), which the loop already treats as a terminal decline rather than looping (dev/115).

### B. Where the check runs

In `_verified_content_rounds`, immediately after `verdict_result` is computed and before the loop
breaks on a non-`fail` verdict — the same seam dev/129 used for document validation, so the
generate → gate → execute → **check** → correct pipeline stays one loop with one budget:

```python
if verdict_result["verdict"] == "pass":
    summary = result_summary_fn(evidence.get("output"))     # bounded preview → summarize
    if result_shape.is_empty(summary) and result_shape.inputs_had_rows(upstream) is not False:
        verdict_result = {"verdict": "fail",
                          "evidence": {"kind": "empty-result", "detail": refusal}}
```

`result_summary_fn` is the batch's existing `_schema_of_artifact` (already memoized per batch, so a
re-check of the same artifact costs nothing), injected as a parameter for the per-node Solve and the
tests — the `dataset_paths_fn` pattern.

**The guard that keeps it honest**: the round fails only when the emptiness was *introduced here* —
every input the node consumed had rows (`inputs_had_rows is True`), or there are no inputs and the
node is a data-loading node (an empty load is a failure of the load). When the inputs' shapes are
unknown (`None` — no artifact, no preview), the check does not fire: an unverifiable claim is not
made. When an input was itself empty, the blame belongs upstream and the node is not corrected for
someone else's failure.

### C. What the user sees

- The strip and the Solve card report the round as `empty-result`, with the same attempt trail every
  other failure gets (dev/127: the code + the diagnosis, in the transcript).
- On exhaustion the node is `failed` with *"not fixed after N attempts … empty-result: the code ran
  but produced an EMPTY result …"*, and its content is **not** written — dev/129's rule.
- Dependants report *waiting — upstream* (dev/118), which is what the pool, the chart and the map
  should have said all along.

---

## 4. Data and State Handling

- **Source of truth for the shape**: the artifact the sandbox stored for this node's own run, read
  through `runner.load_artifact_preview` (bounded: 512 KB / 8 rows) and described by
  `upstream_schema.summarize`. Never the model, never the node's content.
- **Derived values**: `rowCount` per input comes from the `upstreamOutputs` the loop already built
  for the generation request (dev/127), so the diagnosis costs no extra request.
- **Caching**: one summary per artifact per batch (the existing `schema_cache`), so a wide plan does
  not re-fetch previews.
- **Failure of the check itself**: an unreachable sandbox, an oversized preview or a payload
  `summarize` cannot read all yield `None` → the check does not fire and the verdict stays `pass`.
  A check that cannot see must not invent a failure.
- **No new persisted state.** The verdict rides the existing attempt trail and `nodeRuns`.

---

## 5. UI and UX Requirements

Nothing new is drawn. The existing surfaces carry it because the round is an ordinary failed round:

- the live strip's per-node line reads `empty-result` like it reads `execution-error`;
- the `solveAttempts` transcript part (dev/127) shows the code and the diagnosis, wrapped at its
  existing bounds;
- the node's reason line names the bound that stopped the loop (dev/127's `stoppedBy`);
- the Data Pool's own *"Nothing to display / This input is not tabular data"* stays exactly as it
  is — it was never wrong, it was just the only place the truth appeared.

Accessibility: unchanged (no new controls).

---

## 6. Edge Cases

| Case | Behavior |
|---|---|
| A legitimately empty filter (the user wants "rows where x > 1000" and there are none) | The round fails and the loop asks for a fix; after the budget the node fails with the diagnosis. **Accepted trade-off**, stated plainly: silently building a dataflow on nothing is the worse failure, and the user can still write the code by hand. |
| An input was itself empty | The check does not fire (`inputs_had_rows is False`); the blame is upstream, where dev/118 already reports it. |
| No artifact / no preview / oversized preview | `summarize` returns `None` → no check, verdict unchanged. |
| Output is not tabular (a `VALUE`, a `dict`, a raster, a plot) | `summarize().kind` is not `table`/`geotable` → no check. Emptiness is not defined for those here. |
| `parts` (a merge's list of frames) | Empty when EVERY part is empty; a partly-empty list is not a failure. |
| A data-loading node with no inputs that loads 0 rows | Fails: an empty load is the load's failure (its source or its filter is wrong). |
| The node is not executable (a grammar document) | No run, no artifact, no check — dev/134 owns that path. |
| Repeated identical empty results | dev/129's repeat escalation and dev/131's `_MAX_WEAK_PASSES` already bound it. |
| A same-batch reused upstream artifact that has vanished | Already handled before this check (`_looks_like_a_vanished_reused_input`). |

---

## 7. Testing Strategy

**Unit (`test_result_shape.py`)** — the pure module:
1. a table with `rowCount: 0` is empty; with rows is not;
2. a geotable with 0 features is empty;
3. `parts`: all-empty is empty, one non-empty is not;
4. a non-tabular summary is never empty;
5. `None` is never empty (an unknown shape is not a failure);
6. `inputs_had_rows`: all inputs with rows → True; any empty input → False; unknown → None;
7. the refusal names the row counts, the key columns AND their sample values;
8. the refusal is bounded and mentions the honest alternative.

**Loop (`test_verified_rounds.py` additions)**:
9. a candidate that runs clean but returns an empty frame is a `fail` round with kind
   `empty-result`, and the next round's `validationError` carries the diagnosis;
10. the correction that returns rows passes and is written;
11. exhaustion writes NOTHING and the node's reason names `empty-result`;
12. an empty input makes the check silent (the node is not blamed);
13. an unreadable preview makes the check silent (the verdict stays `pass`).

**Regression (`test_empty_join_regression.py`)** — the owner's exact shape: boundaries keyed by
`area_numbe` (ints) and population keyed by `tract_id` (tract strings); the first candidate joins
them and returns 0 rows; the trail shows the diagnosis with both sample values; the node ends failed
and its content stays empty; the dependent pool node reports *waiting — upstream*.

---

## 8. Acceptance Criteria

1. Re-running Solve on a dataflow shaped like `e72c7080` no longer reports *Solved 7 of 7*: the
   join node fails with `empty-result` and the three nodes below it are pending, naming the upstream.
2. The failing node's content is **not** the empty-join code — nothing empty is written.
3. The attempt trail in the chat shows the code that produced nothing and a diagnosis containing
   both key columns and their sample values.
4. A node whose result has rows behaves exactly as before (no new round, no new request, no change
   to the trail).
5. A node whose input was empty is never blamed for it.
6. When the sandbox cannot describe the artifact, Solve behaves exactly as it does today.
7. `tests/test_agents` green, including the new suites; no change to jest (`tsc` untouched).

---

## 9. Recommended Commit Breakdown

1. `result_shape.py` + its unit tests (pure, no wiring).
2. The loop check: the `empty-result` round, the injected summary function, both Solve paths.
3. The regression test built from the owner's datasets' shapes.
4. Docs (`AGENT-CATALOG.md`'s Solve section), memo close, `dev/00` row, BL entry.

---

## 10. Engineering Quality Checklist

- No duplicated logic: emptiness and the diagnosis live in ONE pure module; the preview + summarize
  path is dev/127's, reused, not reimplemented.
- The check is injected (`result_summary_fn`), so the per-node Solve, the batch and the tests share
  one seam and no test needs a sandbox.
- Types explicit; the module is pure and total (never raises, `None` means unknown).
- No new state, no new persisted field, no new request per round (the batch's schema cache).
- The failure text is composed from observed facts only — row counts and sample values the runtime
  read — and says what to do next.
- The trade-off (a deliberately empty filter now fails) is stated in the memo and in the docs
  rather than hidden.
- Play, the runner and the sandbox are untouched.
