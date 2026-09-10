# dev/128 — `arg` from a merge is a LIST: the runtime knows it per node, so it must say it and refuse code that ignores it

**Status: IMPLEMENTED (2026-09-10) on `imp/agentcatalog` — `BL-P5-20260910-63`, and **no new
`DEC`**: `DEC-063`'s ninth application (an input the agent needs must be supplied on the path it
runs on) in the `DEC-072` gate's shape (a deterministic refusal before the sandbox, whose text is
the next round's correction). Five commits: `b6835da6` (this memo), `4e9dd45c` (the owner's
budget — ten attempts, fifteen minutes), `35a1e46a` (the merge slot authority — the field defect
in §0.1), `d717ba31` (`input_contract.py`), `fef64abb` (the contract handed over and enforced),
plus a tracking commit for the docs and ledgers. Every line number below was read on `13fd93df`.**

**Suites: `tests/test_agents` + `tests/test_execution` 2363 passed (2336 before);
`tests/test_projects` 304; jest 2400 across 206 suites; `tsc --noEmit` clean.**

**Two things changed from the plan while building — §12 — and one of them is the reason the
phase is worth reading: the owner's second report exposed a defect UNDER this one (§0.1), where
validation and Play disagreed about slot order, so the contract's own slot table would have been
wrong had it shipped first.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `13fd93df` (dev/127 commit 7).
Origin: owner report — *"The merge node always outputs a list called `arg`, where each item in
this list corresponds to the linked nodes in the order of their connections to the input handles
of the merge node. Your attempts always used `arg` alone; when I changed it to `arg[0]`, it
worked correctly."*
Family: dev/115 (`DEC-073`, the one verified loop) → dev/118 (`DEC-075`, waves +
`upstreamOutputs`) → dev/114 (`DEC-072`, the grounding gate: a deterministic refusal BEFORE the
sandbox) → dev/126 (`DEC-080`) → dev/127 (the attempt trail, the budget, the inputs' columns) →
**dev/128 (this memo)**.
Design decisions consumed: `DEC-063` (an input the agent needs must be supplied on the path it
runs on — this is its ninth application), `DEC-072` (the deterministic pre-sandbox gate whose
refusal is the next round's error), `DEC-073`, `DEC-075`.

---

## 0. The evidence, and what it corrects in dev/127

The owner's node is `08b108a1` in dataflow `623b6620`, fed by `6b36ee91`, a `merge-flow` with two
inputs (`74e9a1cd → in_0`, `55b0e938 → in_1`). Its content on disk now begins:

```python
gdf = arg[0]
```

— the owner's own edit, and the runtime journal records that version running clean (`status: ok`,
`output.dataType: geodataframe`, 101 ms). The generated version used `arg` alone.

**dev/127 shipped the wrong half of this fix.** It gave that node's child the columns of both
upstream frames and an `argIndex` per row — real information, arrived at through a real bug —
but `argIndex` is *metadata about a list*, offered to a model that had already decided `arg` was
a frame. The owner's sentence is the correction: the shape of `arg` is not a hint, it is a
contract, and the runtime knows it exactly.

---

## 0.1 A second report, and the defect under it: validation and Play disagreed about slot order

**Owner, mid-phase:** *"I attempted to recreate the same dataflow, but it generated a node with an
error. This must never happen; the dataflow must be completely validated before inserting into a
node."* — with dataflow `00708324` and a screenshot.

Read from disk, that project's Solve card says `ed1a326f · solved · pass after 1 round`, and its
runtime journal for the same node says `status: error`, `validation: false`, ending in
`KeyError: 'tract_id'`. **The node passed validation and failed at Play** — which is exactly what
"validated before inserting" must rule out.

The generated code is the evidence:

```python
# Since the input comes from a MERGE_FLOW node, arg is a list.
# Based on upstreamOutputs:
# arg[0] is the Population Data (DataFrame)
# arg[1] is the Chicago Boundaries (GeoDataFrame)
```

while the spec's edges read `03fb2c00 (Boundaries) → in_0`, `88086398 (Population) → in_1`. The
model was told the mapping backwards and repeated it faithfully. Where the lie came from:

- `workflow_spec.upstream_nodes` ordered a merge's inputs by parsing `in_N` out of **each edge's
  id** (`_merge_edge_handle_index`, `workflow_spec.py:17`-`:25`) — the canvas's own encoding
  (`reactflow__edge-…78504in_0`);
- an **agent-applied** edge has a UUID id and carries the slot in `targetHandle` (dev/67-3 made
  handles explicit, and `_apply_dataflow_plan` writes them);
- **and both spec parsers dropped `targetHandle` entirely** (`workflow_spec.py:318`-`:326` and
  `:383`-`:392`), so the slot was not even available to read;
- so every plan-created merge was ordered **lexicographically by UUID**: `0c05b055…` (Population,
  `in_1`) before `b396ed2d…` (Boundaries, `in_0`);
- while Play orders by the handle — `mergeFlowUtils.parseHandleIndex(e.targetHandle)`,
  `connectedMergeSlotIndices` sorted ascending.

One command shows both, on the owner's own spec:

```
VALIDATION ORDER (backend upstream_nodes):   arg[0] = Population Data · arg[1] = Chicago Boundaries
PLAY ORDER (handles, as the frontend sorts): in_0  = Chicago Boundaries · in_1 = Population Data
```

**This also corrects dev/127.** Its `upstreamOutputs[].argIndex` — and therefore the columns each
slot was said to hold — came from `upstream_nodes`, so for every agent-applied merge dev/127
handed the model an authoritative-looking mapping that was inverted. The schema plumbing worked;
the order it was keyed on did not.

**Fix (implemented as this phase's first code commit):** `merge_slot_index(edge)` reads the
**handle** first (`targetHandle`, tolerating `target_handle`) and keeps the id's `in_N` suffix as
the fallback for canvas-saved specs; both parsers carry `targetHandle`/`sourceHandle` through. One
authority, matching the canvas's, for the validation runner, the schema walk, `argIndex`, and this
memo's own slot table — which had to be right before it could be enforced.

---

## 1. Problem Statement

### D1 — the runtime knows the shape of `arg` and never states it for this node

`runner.run_through_node` decides it, in one place (`runner.py:391`-`:400`):

```python
if not is_code:                                     # merge / vis / pool
    upstreams = spec.upstream_nodes(node.id)
    if len(upstreams) == 1 and upstreams[0] in outputs:
        outputs[node.id] = outputs[upstreams[0]]    # ONE input → passes the value through
    elif len(upstreams) > 1:
        outputs[node.id] = {"path": [...], "dataType": "outputs"}   # → a LIST, in slot order
```

and `spec.upstream_nodes` already orders those sources by `in_0`, `in_1`, … (`workflow_spec.py:197`-
`:213`), which is exactly the owner's sentence. So for any node the runtime is about to solve,
`arg`'s shape is a fact it can compute before generating a line.

What the child gets instead is a *general rule* it must apply by reasoning about the graph:
`default_preamble.txt:177`-`:190` explains that "if the previous node is a merge node … `arg`
will be a list that can be indexed", and the preamble's worked examples use `arg[0]`/`arg[1]`
correctly. The rule is right and the model still wrote `arg`, which is the `DEC-063` shape
exactly: an instruction whose correct application depends on knowledge the runtime holds and
does not hand over.

### D2 — nothing refuses it, though the check is deterministic

`DEC-072` established the pattern: a candidate that names an ungrounded source is refused BEFORE
the sandbox, and the refusal becomes the next round's error. There is no equivalent for a shape
the runtime can see. `arg.<attribute>` when `arg` is a list is **always** wrong — a list has no
`.crs`, no `.merge`, no `.columns` — and it is a two-line AST check.

Without it, the loop pays for the mistake three times: the sandbox runs, the traceback comes back
as an `AttributeError` about a *frame* type (`'DataFrame' object has no attribute 'crs'` — the
error the owner reported earlier), and the correction is left to infer a shape error from a type
error. dev/127 gave those rounds a budget and a visible trail; this gives them a reason not to
happen.

### D3 — the naive rule is wrong, so the predicate must be the runner's own

A merge with exactly ONE connected input passes its value through: `arg` is then the frame, not a
list of one. Any fix that says "upstream is a merge → index it" would break that case and produce
the mirror bug. The shape must be read the way the runner reads it: a non-code upstream with more
than one upstream of its own.

### Expected behavior

- **R1** Every node whose code the runtime generates is TOLD the shape of its `arg`: a list of N
  in input-handle order, with what sits in each slot, or a single value of a named type.
- **R2** A candidate that treats a list-shaped `arg` as a value is refused before the sandbox
  runs, with the slot table in the refusal, and the refusal is the next round's correction.
- **R3** A merge with one connected input is described as a single value — the runner's rule,
  not a simplification of it.
- **R4** The refusal is visible in the transcript trail with the code that caused it (dev/127),
  so a reader sees `arg` become `arg[0]` between two rounds.

### Why it matters

This is the last mile of dev/127. The budget and the trail made the loop honest and patient; the
node still failed for a reason the runtime could have stated in one sentence and refused in one
check. It is also a correctness rule for every future node fed through a merge, not a fix for one
dataflow.

---

## 2. Scope

### In scope

- new `app/agents/input_contract.py` — `arg_shape(spec, node_id)` (the runner's predicate, read
  from the spec), `check(code, shape)` (the AST rule), `refusal_text(shape, violation)`,
  `describe(shape)`.
- `app/agents/services.py` — the contract composed once per node and handed to the child as
  `inputContract` (`DEC-063`); the check run on every candidate beside the `DEC-072` gate, before
  the sandbox, as a failed round of kind `input-contract` whose refusal feeds the correction;
  the contract's slots enriched with dev/127's column summaries when they exist.
- `llm-prompts/new_content_prompt.txt` — one paragraph: when `inputContract.kind` is `list`,
  index it; `arg` alone IS the list.
- Tests: `test_input_contract.py` (new), the loop's refusal round, one route test on the owner's
  exact graph shape.
- Docs: `docs/AGENT-CATALOG.md` (the refusal joins the gate's table), `docs/USAGE.md` if it says
  anything about merges; dev/00, `BL-P5-…-62`, this memo's status.

### Out of scope

- The preamble's general paragraph stays as it is: it is correct, and the per-node contract is
  what makes it executable (dev/127 **F2** is thereby answered — the paragraph is not retired,
  it is superseded in force by an input).
- A tuple returned by a code upstream (`return (a, b)`) also makes `arg` a list, and the runtime
  cannot know that statically. The contract states what it knows; the gate refuses only the case
  it is certain about (`kind: list`), and a single-value contract is never used to refuse
  indexing. Recorded as a follow-up.
- `arg` in JavaScript nodes: the same contract rides the input, but the AST check is Python-only
  (a JS parser is not worth adding for one rule); a JS candidate is not gated.
- Changing the merge's own semantics, its arity, or the handle scheme.
- The `vis-simple`/`data-pool` pass-throughs behave identically by the runner's rule and are
  therefore covered by construction — not by a second predicate.

### Related code paths

`workflow_spec.upstream_nodes` (the slot order — the ONE source), `runner.run_through_node`'s
pass-through branch (the shape's authority), dev/127's `_upstream_outputs_for` (the same walk,
for columns), `source_grounding.check_grounding` (the gate this sits beside), the attempt trail
(the refusal must carry its code, which dev/127 already does for refused rounds).

---

## 3. Recommended Implementation Approach

### A. `input_contract.py` — the shape, read the way the runner reads it

```python
def arg_shape(spec: dict | None, node_id: str) -> dict:
    """{"kind": "list", "length": 2, "slots": [{"argIndex": 0, "nodeId": …, "goal": …,
        "nodeType": …}, …], "via": "<merge node id>"} | {"kind": "single", …} | {"kind": "none"}"""
```

Rules, in the runner's own terms: the node's direct upstreams (data edges only); if there is
exactly one and it is a **non-code** node (`category != "code"` — merge, pool, vis), then its own
ordered upstreams decide: more than one → `list` of that length, in `in_0…in_n` order; exactly
one → `single` (the value passes through). A single code upstream → `single`. No upstream →
`none`. Depth-bounded like dev/127's walk (a pool feeding a merge is still resolvable).

```python
def check(code: str, shape: dict) -> dict | None:
    """The ONE deterministic rule: with a list-shaped arg, `arg.<attr>` is wrong."""
```

AST, not regex: refuse an `Attribute` access whose value is the Name `arg`, or on a name bound
directly to `arg` (`gdf = arg` then `gdf.to_crs(...)` — the owner's exact code). Explicitly NOT
refused: `arg[0]`, `for x in arg`, `len(arg)`, `pd.concat(arg)`, `arg` returned as-is. A syntax
error in the candidate is not this gate's business (the sandbox reports it).

`refusal_text` names the shape and the slots — *"`arg` is a list of 2 inputs, in the merge's
handle order: arg[0] = Chicago Community Boundaries (geodataframe: the_geom, area_numbe,
community…), arg[1] = Population Data (dataframe: GEOID, community_area_name, TOT_POP…). Your
code used `arg.crs`: a list has no such attribute — index the slot you need."* — which is both
the correction and, for a human reading the trail, the answer.

### B. The contract as an input, and the gate before the sandbox

In `_verified_content_rounds`: compose `shape` once (it cannot change between rounds), enrich its
slots with the column summaries dev/127 already fetched, and pass `inputContract` in `inputs` for
the first generation and every correction. Then, immediately after the `DEC-072` grounding gate
and before `dataset_paths`/the sandbox:

```python
violation = input_contract.check(candidate, shape)
if violation:  # kind: "input-contract"
```

— a failed round with the refusal as its detail, the candidate as its `code` (dev/127), and the
refusal as `previous_error` for the next round. It costs no sandbox run, and like the grounding
gate it is a *free* correction: the model gets the specific, executable statement it needed.

### C. One paragraph in the content builder's instruction

`new_content_prompt.txt`: *"`inputContract` tells you the shape of `arg` for THIS node. When its
`kind` is `list`, `arg` is a list in the merge's input-handle order and you MUST index it —
`arg[0]`, `arg[1]` — using the slot table's goals and columns to pick; `arg` alone is the list
object, never a frame. When its `kind` is `single`, `arg` IS the value."* The preamble's general
rule stays; this is the sentence that applies it to the node at hand.

### D. Nothing new to show in the UI

The refusal rides the existing surfaces: dev/127's attempt trail shows the refused code with the
refusal text (kind `input-contract`), and the failure line reads *"input-contract: `arg` is a
list of 2 inputs…"*. That is the whole UI change — which is the point of having built the trail
first.

---

## 4. Data and State Handling

| Datum | Source of truth | Read by |
|---|---|---|
| `arg`'s shape for a node | the spec's graph, through the runner's own pass-through rule | the contract input, the gate |
| Slot order | `workflow_spec.upstream_nodes` (`in_0…in_n`) | the contract, dev/127's walk |
| What sits in each slot | dev/127's bounded artifact summaries, when the upstream has run | the contract's slots |
| The refusal | computed per round, never stored beyond the attempt trail | the correction, the trail |

The shape is computed once per loop (the graph does not change mid-loop) and is a pure function
of the spec — no cache to invalidate, nothing persisted, no new state. An upstream that has not
run yet still yields a shape (ids, goals, types); only the column detail is absent, and its
absence is stated rather than filled in.

---

## 5. UI and UX Requirements

- The refused round appears in the transcript trail exactly like a grounding refusal: kind
  `input-contract`, the refusal text (which leads with the shape, not with a traceback), and the
  code that was refused. A reader sees `gdf = arg` in round 1 and `gdf = arg[0]` in round 2.
- The failure line, if a node exhausts its budget on this, names the contract rather than an
  `AttributeError` from a library file — the true cause, in the user's words.
- No new control, no new card, no new colour: the surfaces dev/127 built carry it.

---

## 6. Edge Cases

1. **A merge with ONE connected input** — `single`; indexing is not required and never refused
   (D3, the mirror bug).
2. **A merge with an unconnected slot** — the shape's `length` is what is CONNECTED, in handle
   order, which is what the runner assembles; dev/127 **F6** (naming the gap) stays open and this
   contract does not pretend otherwise.
3. **A pool or `vis-simple` between the merge and the node** — the same pass-through rule applies,
   resolved through the depth-bounded walk.
4. **A code upstream returning a tuple** — `single` by the contract, and NOT gated: the runtime
   cannot see the tuple statically, so it says what it knows (out of scope; follow-up).
5. **`pd.concat(arg)` / `for frame in arg` / `len(arg)` / `return arg`** — legitimate uses of a
   list; never refused.
6. **`arg[0].crs`** — correct, and the gate must not fire on the attribute of a subscript.
7. **A name reassigned** (`gdf = arg` … `gdf = gdf.to_crs(…)`) — the first attribute access on the
   bound name is the violation; a later rebinding does not excuse it.
8. **A candidate that does not mention `arg` at all** (a data-loading node, a constant) — nothing
   to check, no refusal.
9. **A syntax error in the candidate** — not this gate's business; the sandbox reports it, and the
   check returns None rather than guessing.
10. **A JavaScript node** — the contract is supplied, the AST check is skipped (Python-only), and
    the skip is silent rather than a false pass claim.
11. **A node with no upstream** — `kind: none`; a candidate using `arg` at all is left to the
    sandbox, which will say `arg` is undefined.
12. **A merge feeding a merge** — resolved through the walk; the outer list's slots are the inner
    merge's own upstreams, which is what the runner assembles.

---

## 7. Testing Strategy

**Unit — `arg_shape`**: the owner's graph (two loaders → merge(in_0, in_1) → analysis) yields
`list` of 2 in handle order; a one-input merge yields `single`; a direct code upstream yields
`single`; no upstream yields `none`; a pool between merge and node resolves through; the walk is
depth-bounded.

**Unit — `check`**: the owner's exact code (`gdf = arg` then `gdf.crs`) is refused, and the
refusal names the slots; `arg.crs`, `arg.merge(...)`, `arg.columns` refused; `arg[0]`,
`arg[0].crs`, `for x in arg`, `len(arg)`, `pd.concat(arg)`, `return arg` accepted; a `single`
shape refuses nothing; a syntax error returns None; a candidate without `arg` returns None.

**Loop**: a merge-fed node whose first candidate uses `arg` produces a failed round of kind
`input-contract` with NO sandbox call, the refusal as the correction's `validationError`, and the
second candidate (using `arg[0]`) passing — the owner's sequence, mechanised.

**Route**: the contract reaches the child on the first generation and every correction
(`inputContract` in the captured frame, with the slot table), and the refused round appears in
the transcript trail with its code (dev/127's part).

**Required before complete**: the shape and check units, the loop test, the route test, and a
live re-run of `623b6620` where the analysis node is generated with `arg[0]` without a hand edit.

---

## 8. Acceptance Criteria

1. A node fed by a multi-input merge is told, in its inputs, that `arg` is a list of N in handle
   order, with each slot's node, goal, type and (when known) columns.
2. A candidate that treats such an `arg` as a value is refused before the sandbox runs, and the
   refusal names the slots and the attribute that gave it away.
3. That refusal is a free correction round, and the trail shows the refused code beside it.
4. A merge with one connected input is described as a single value and nothing is refused.
5. Legitimate list uses (`arg[0]`, iteration, `len`, `concat`, returning it) are never refused.
6. The contract rides every correction, not only the first generation.
7. Nothing in the preamble is removed; the per-node contract is what makes its rule executable.
8. `tests/test_agents`, `tests/test_execution`, `tests/test_projects`, jest and `tsc --noEmit`
   green, only the pre-existing unrelated `test_packages` failure remaining.
9. A live re-run of the owner's dataflow generates `arg[0]` — or fails for a reason that is not
   the shape of `arg`.

---

## 9. Recommended Commit Breakdown

1. **`input_contract.py` + tests** — the shape, the check, the refusal text. Nothing wired.
2. **The contract as an input + the gate** — composed once per loop, handed to every round,
   checked before the sandbox; loop and route tests.
3. **The instruction paragraph** — `new_content_prompt.txt`.
4. **Docs + ledgers** — `docs/AGENT-CATALOG.md`, dev/00, `BL-P5-…-62`, this memo's status and §12,
   and dev/127 **F2** marked answered.

---

## 10. Engineering Quality Checklist

- **One predicate**, derived from the runner's own rule, in one module; the gate and the input
  read the same shape.
- **One slot order** — `workflow_spec.upstream_nodes`, already the runtime's authority.
- **AST, not regex**: the check refuses what is provably wrong and nothing that merely looks it.
- **A refusal, not a rewrite**: the runtime never edits the candidate's code — the correction is
  the model's, on evidence.
- **No new state**, no cache, no persistence beyond the existing attempt trail.
- **Honest absence**: an upstream that has not run contributes ids and goals without columns.
- **Bounded**: the refusal text and the slot table are capped like every other input.
- **Types explicit**, the shape a closed set (`list` / `single` / `none`).

---

## 11. Open questions and recorded follow-ups

- **F1** A code upstream returning a tuple makes `arg` a list the runtime cannot see statically.
  Options: teach the loop from the recorded artifact's `dataType` (`outputs`) once the upstream
  has run — which would make the contract *empirical* for that case. Deferred with its own memo.
- **F2** A JavaScript candidate is not gated (Python AST only). If JS nodes start being fed
  through merges, this needs a JS-side check or a shared shape assertion.
- **F3** dev/127 **F6** (an unconnected merge slot) is still open and is visible here too: the
  contract's `length` counts connected inputs.
- **F4** Owner live re-run of `623b6620`.

---

## 12. What changed while building

1. **The order had to be fixed first (§0.1).** The memo as written assumed
   `upstream_nodes` was authoritative and built the contract's slot table on it. The owner's
   second report proved otherwise: both spec parsers dropped `targetHandle`, the merge sort read
   `in_N` out of the edge *id*, and an agent-applied edge carries a UUID id — so validation
   ordered a plan-created merge lexicographically while Play ordered it by handle. Enforcing a
   contract built on that order would have made the runtime confidently wrong. `merge_slot_index`
   (handle first, id suffix as the canvas-legacy fallback) and the two projections carrying the
   handle are therefore this phase's first code commit, and dev/127's `argIndex` is corrected by
   the same change.
2. **Slots name `upstreamNodeId` / `upstreamNodeType`, not `nodeId` / `nodeType`.** Not in the
   plan, and not cosmetic: the child's own inputs already carry both keys for the node being
   generated, and the collision broke two suites the moment the contract rode a prompt — a dev/126
   harness keying on `"nodeId": "<loader>"` began matching the analysis node's frames, and a
   dev/115 fixture keying on `"nodeType": "<data-loading>"` mis-routed a request so a node
   "solved" without its code ever running. One key with two meanings misleads a reader whether
   that reader is a model or a test.

Everything else in §3 landed as written: the shape read the way the runner reads it (with a
one-input merge as `single`), the AST rule that refuses only what is provably wrong, the refusal
that names the slots and their columns, the contract on every round, the gate beside the source
gate, the instruction paragraph, and no UI work — dev/127's trail carries it.
