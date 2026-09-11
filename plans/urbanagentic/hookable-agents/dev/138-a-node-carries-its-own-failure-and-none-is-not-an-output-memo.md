# dev/138 — A node carries its own failure, and `return None` is not an output

**Status: PROPOSED (2026-09-10) on `imp/agentcatalog` @ `ea429b63`. Every claim below was read from
the owner's project `edd71e67-4806-47ee-8cfd-2149406e73f2` on disk.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `ea429b63` (dev/137's docs commit).
Origin: owner report — *"the vega lite node is giving an error, and again the error message seems to
be through the toast and not carried into node's spec object"* — with the screenshot of `edd71e67`.
Family: dev/133 (an empty result is a verdict) → dev/135 (browser outcomes journaled) → dev/136 (an
empty render is a failure) → dev/137 (nulls are empty; run and render kept apart) → **dev/138 (this
memo)**.
Design decisions consumed: `DEC-052`, `DEC-073`, `DEC-063`, `DEC-006`.

---

## 1. Problem Statement

dev/136 and dev/137 are working on this run — and that is what makes the remaining gaps legible.
The journal now reads:

```
1db29f4c  run     status=ok     origin=sandbox  dataType='null'        ← a PYTHON node
1db29f4c  render  status=ok     origin=browser
b352cd7c  render  status=error  origin=browser  kind=empty-render:no-input-rows
                  "rendered nothing — 0 rows arrived at this node …"
f1e40b07  run     status=ok     origin=sandbox  dataType='geodataframe'
fe0bc2ac  run     status=ok     origin=sandbox  dataType='dataframe'
```

The run records kept their own facts (dev/137 holds), and the Vega node's failure is recorded with
its cause. Two things are still wrong.

### D1 — the failure is not IN the node (the owner's report)

The Vega node's footer shows a red **Error** and the message appears in a **toast** that then
disappears. After that the node is a blank chart with a red word and no text: the reason lives in
the journal (server-side) and in `data.output.content` (in memory, this tab only). Nothing shows it
in the node, and nothing survives a reload. A code node at least prints its traceback into its own
output area; a grammar or presentation node has no such surface — dev/129's memo noted it in passing
(*"the node UI has no error tab"*), and this is the report it produces.

### D2 — `return None` passes every check, and it is the actual cause here

`1db29f4c` (Python Computation) holds, verbatim:

```python
# The goal is to join on community area ID and calculate density metrics.
# gdf_boundaries has 'area_numbe'
# df_population has 'tract_id'
# These IDs do not match in type or scale (area_numbe is small int, tract_id is long census id).
# A join is not possible with the provided columns.

return None
```

dev/137's contract worked — the model did **not** fabricate a left join this time, and it diagnosed
the problem correctly. Then it expressed that conclusion as `return None`, and **three fail-opens in
a row let it through**:

1. the sandbox stored an artifact and reported `output.dataType: "null"`, and
   `record_execution`'s predicate is `bool(output.path)` → **`status: ok`**;
2. `validation._consumer_type_mismatch` maps runtime types to ports through
   `_RUNTIME_TO_PORT_TYPE`, which has no `"null"` entry, so `port_type is None` → *"unmapped runtime
   type: fail open"* → no mismatch reported, even though the Data Pool downstream declares
   `DATAFRAME, GEODATAFRAME`;
3. `upstream_schema.summarize` on a `null` payload yields `{"kind": "null"}`, which is not countable,
   so dev/133's emptiness check correctly makes **no claim**.

So the round passed, the node was written, the plan said *solved*, and every node below it is empty:
the Data Pool shows *"Nothing to display — this input is not tabular data"* and the Vega node
reports *0 rows arrived*. `null` is not an unknown type to fail open on — it is the **absence** of
an output, and the one case where failing open is exactly wrong.

The honest path already exists: dev/115 accepts a one-line prose decline as terminal and reports it
(*"say plainly that these inputs cannot be joined"* is dev/133's own wording, and dev/137 put the
prohibition in the prompt). The model said the right thing in a comment and then returned code.

### D3 — the node that KNOWS the type is wrong says nothing to the harness

The Data Pool renders *"This input is not tabular data"* — it is the node that detected the real
problem — and reports nothing, because it renders through `NodeEmptyState` rather than
`nodeState.setOutput`, so dev/135's reporter never fires for it. Recorded as dev/137 **F1**; it is
the cheapest remaining signal in this dataflow, and it names the culprit one node upstream.

### Expected behavior

- **R1** A node that failed shows its reason **in the node**, and still shows it after a reload. The
  toast stays a notification, not the only record.
- **R2** A run whose output has no usable type (`null`, empty) is **not** `ok`: the journal says so,
  the type check says so instead of failing open, and the loop fails the round with the model's own
  diagnosis quoted back plus the honest alternative.
- **R3** A wired node that detects a bad input (the pool's four empty states) reports it, so the
  harness can name the node that produced it.
- **R4** Nothing new is claimed where evidence is absent: an unmapped-but-real type still fails open,
  an unreadable preview still makes no claim.
- **R5** No runtime state enters the saved spec (dev/135's separation): the node reads its last
  outcome from the journal, which is where it already lives.

---

## 2. Scope

**In scope.**
- `runtime_journal`: `"null"`/empty output types are a failed run (`status: "error"`) with a stated
  reason; `NULL_OUTPUT_TYPES` is the one list.
- `validation.py`: an ABSENT output type is a mismatch against any consumer that declares real port
  types — the "fail open" path keeps applying to types this build does not know.
- `app/agents/result_shape.py` + the loop: an untyped output is an empty result, with a refusal that
  quotes the node's own comment back when it has one and names the decline path.
- Frontend: a per-node **last-outcome strip** in the node body — the node's current error/notice text,
  read from `data.output` live and hydrated from the journal on mount (`GET` the record), so it
  survives a reload; shown for every kind, including the grammar and presentation kinds that have no
  output area.
- `dataPoolBehavior` / `DataPoolContent`: report the resolved empty reason through
  `nodeState.setOutput`, so dev/135's reporter carries it (closes dev/137 F1).
- `llm-prompts/new_content_prompt.txt`: `return None` is not an answer — the one-line decline is.
- Tests both sides; docs; ledgers.

**Out of scope.**
- Making the two datasets joinable (they are not; the Dataset Finder lane owns that).
- A node-level error HISTORY (the journal keeps the latest; provenance owns history).
- Changing the sandbox's own typing of `None`.

---

## 3. Recommended Implementation Approach

### A. `null` is the absence of an output, in all three places

```python
NULL_OUTPUT_TYPES = ("", "null", "none", "nonetype")
```

- **the journal**: a run whose `output.dataType` is in that set (or whose path is empty) records
  `status: "error"` with `stderrTail` stating *"the code returned no output (`None`) — a node must
  return the data it produces"*. One place, so every reader inherits it.
- **the type check**: `_consumer_type_mismatch` reports a mismatch when the produced type is absent
  and any consumer declares real port types — *"the code returned no output (`None`), which
  downstream node 'Neighborhood Pool' cannot accept (declares DATAFRAME, GEODATAFRAME)"*. A type
  this build simply does not recognize keeps failing open, which is the distinction that matters.
- **the loop**: the resulting `fail` verdict rides dev/133's `empty-result` vocabulary so the trail,
  the transcript and the carry-forward all behave as they already do.

The refusal adds the two sentences the case needs: the node's own comment is quoted (*"your code
says: 'A join is not possible with the provided columns'"*) and the decline path is named (*"if that
is your conclusion, return that sentence as your whole answer — no code — and it is reported as the
node's honest outcome"*). dev/115 already treats a prose decline as terminal; the model needs to be
told that it is allowed, in the moment it is deciding.

### B. The node carries its own reason (D1)

One small component — `NodeOutcomeStrip` — rendered inside the node body under the content area for
every kind:

- its text is `data.output.content` while the tab is live, so it appears the instant a render fails;
- on mount (and after a reload) it hydrates from the journal through a small read
  (`GET /nodeRuntime?dataflowId=…&nodeId=…`, returning the same record the agents read), so the
  reason is still there tomorrow;
- it is one line, expandable, with the node's own status word — the same register as
  `nodeEmptyState`'s copy;
- the toast stays, because a toast is how a user learns something happened *now*.

The strip reads the journal rather than a new spec field on purpose: dev/135 §4 keeps the document
and the run log apart, and the journal is already the durable, agent-readable truth.

### C. The pool reports what it detected (D3)

`dataPoolBehavior` resolves one of four reasons (`disconnected`, `upstream-not-run`, `not-tabular`,
`no-rows`) and renders it. Emitting the same reason through `nodeState.setOutput({code: 'error'|…})`
for the two that are real failures (`not-tabular`, `no-rows` with a connected, run upstream) makes
dev/135's reporter carry it, so the harness sees *"this input is not tabular data"* on the pool and
can point at the node that produced it.

---

## 4. Data and State Handling

- **Source of truth** for a node's last outcome stays the journal: the run record, the render record,
  or both (dev/137). The strip reads; it never writes.
- **The read endpoint** is the same shape as the write: authenticated, own-project only, bounded,
  and a 404-free empty answer when there is nothing.
- **Live vs hydrated**: `data.output` wins while it is set (it is the newest), the journal fills the
  gap after a reload, and the two use one formatter so they cannot disagree.
- **Nothing new in the spec.** No `output`, no `error`, no `lastRun` key is added to a saved node.
- **The null rule is data, not inference**: it reads `output.dataType` the sandbox itself reported.

---

## 5. UI and UX Requirements

- A failed node shows one line in its body: *"Error — rendered nothing: 0 rows arrived at this
  node…"*, clipped with a disclosure for the rest.
- A node whose last run was fine shows nothing new.
- The line uses the existing node type scale and the warning/danger tokens already in the node CSS;
  no new colours.
- It is selectable text (a user copying an error is the commonest next action) and reachable by
  keyboard when expandable.
- The Data Pool keeps its existing empty-state copy in the body; the strip is not a second copy of
  the same sentence (the pool's reason IS the strip's text there).

---

## 6. Edge Cases

| Case | Behavior |
|---|---|
| A code node whose traceback is already in its output area | The strip shows the same first line; no second panel of the same text (one line + disclosure). |
| A node that never ran | No strip. |
| A node with a run record AND a render record, one of each status | The strip leads with the failure — a user looking at a red node wants the reason, and dev/137 keeps both readable. |
| A reload with the backend unreachable | No strip (no claim), and the live path still works in the next render. |
| `return None` in a node whose consumer accepts JSON/LIST | Still an absent output: `null` is not `JSON`. |
| An output type this build does not know (a new sandbox type) | Fails open exactly as today — the distinction between "unknown" and "absent" is the point. |
| A pool that is simply not connected yet | `disconnected` is not a failure: no report (the user has not wired it). |
| A pool whose upstream has not run | `upstream-not-run` reports as a *notice*, not an error. |
| A node the user fills by hand after a failure | The next render/run overwrites the record; the strip follows. |

---

## 7. Testing Strategy

**Journal** — a run reporting `dataType: "null"` (or `""`) records `error` with the stated reason; a
known type still records `ok`; the reason is bounded; `last_failure` finds it and digest-matches the
content that produced it.

**Type check** — an absent type is a mismatch against a `DATAFRAME`-declaring consumer and names
both; an unknown-but-real type still fails open; no consumers → no mismatch.

**The loop** — `return None` fails its round with `empty-result`, the refusal quotes the node's own
comment and names the decline path, and a candidate that returns real data passes; the owner's exact
node content is the regression fixture.

**Frontend** — the strip renders from `data.output`, hydrates from the journal on mount, shows
nothing for a clean node, leads with the failure when both records exist, and survives an
unreachable backend; the pool emits `not-tabular` as an error and `upstream-not-run` as a notice, and
emits nothing when disconnected.

**Integration** — after a Solve where the computation returns `None`, the node is failed (not
solved), its reason is readable in the node and in the journal, and the plan does not claim it
solved.

---

## 8. Acceptance Criteria

1. A Vega/Autark node that fails shows its reason inside the node, and still shows it after a page
   reload.
2. A node whose code returns `None` fails its round; the refusal quotes the node's own diagnosis and
   tells it that a one-line decline is the accepted answer.
3. The Data Pool's *"this input is not tabular data"* reaches the journal, so an agent can name the
   node that produced the bad type.
4. An output type this build does not recognize still fails open; nothing new is invented.
5. No runtime state is added to the saved spec.
6. Backend and jest suites green; `tsc --noEmit` clean.

---

## 9. Recommended Commit Breakdown

1. `NULL_OUTPUT_TYPES` + the journal's verdict + the type check (+ tests).
2. The loop's untyped-output refusal, quoting the node's comment (+ tests, the owner's regression).
3. The read endpoint + `NodeOutcomeStrip` and its wiring in the node body (+ jest).
4. The pool's report (closes dev/137 F1) (+ jest).
5. The prompt, docs, memo close, `dev/00` row, BL entry.

---

## 10. Engineering Quality Checklist

- One list (`NULL_OUTPUT_TYPES`) read by the journal, the type check and the loop — the three places
  that failed open independently.
- "Absent" and "unknown" are distinguished, so the fix cannot turn a new sandbox type into a false
  failure.
- The node's visible reason and the agent's readable reason come from the SAME record, so a user and
  an agent never see different explanations (`DEC-063`'s spirit).
- The document/run-log separation holds: nothing runtime enters the spec.
- The refusal teaches the path that already exists rather than inventing a new one, and quotes the
  model's own words so the correction is grounded in what it already concluded.
- The pool's four reasons keep one vocabulary (`nodeEmptyState`) across the body, the report and the
  journal.
