# dev/127 — When Solve cannot fix a node: show every attempt, name the error precisely, retry within a real budget, and stop guessing the upstream's columns

**Status: PROPOSED (2026-09-10) on `imp/agentcatalog` @ `64490ca7`. Every line number below was
read on that commit.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `64490ca7` (the owner's "removing heavy plan files" commit,
on top of dev/126's `63300741`).
Origin: owner report with a screenshot of `localhost:8080/dataflow/623b6620-d92a-4dfb-815d-dfe1c2659378`
— *"The agent is still unable to correctly solve the data flow. It displayed an error, but this
diagnosis is too vague. It should also show the code it attempted to execute alongside the error
message. Additionally, the agent should have more retry attempts before reaching the 5-minute
timeout."* Followed by: *"It is important to clearly display all attempts to fix in the chat
transcript."*
Family: dev/67-7 (the round loop) → dev/115 (`DEC-073`, Solve as a detached job, the ONE verified
loop) → dev/116 (the remedy payload) → dev/118 (`DEC-075`, waves + `upstreamOutputs` +
not-executable honesty + the batch deadline) → dev/119/120 (executability) → dev/126 (`DEC-080`,
node-attached discovery) → **dev/127 (this memo)**.
Design decisions consumed: `DEC-073` (the detached job and its one loop), `DEC-075` (waves,
per-wave persist, honest non-execution), `DEC-072` (source grounding), `DEC-063` (an input the
agent needs must be supplied on the path it runs on), `DEC-006` (nothing mutates without review),
`DEC-040` (graph-backed state), `REQ-SEC-002` (bounded, plain-text rendering of runtime text).

---

## 0. What the screenshot actually shows

The project is on disk (`.curio/users/31/projects/623b6620-…`), and it is a **dev/126 project**:
seven plan nodes, and the attachment set the applied plan created — a Node Builder on all seven,
a Dataset Finder on both `data-loading` nodes — with the applied card reading *"agents attached:
Dataset Finder ×2 · Node Builder ×7"* and *"no Dataset Finder: does not attach to merge-flow
nodes"*. So dev/126 works in the field; what failed is the repair loop behind Solve.

Five of seven nodes solved. The failure, from session `3f54ce87`'s Solve card, verbatim:

```
08b108a1 · failed · fail after 3 rounds
  round 1: execution-error — ic.py", line 1776, in _get_label_or_level_values
    raise KeyError(key)
KeyError: 'community_area'
  round 2: execution-error — de
KeyError: 'No common column found between boundaries and population datasets to perform a join.'
  round 3: execution-error —       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'DataFrame' object has no attribute 'crs'
b09dcac4 · pending · fail after 1 round — waiting — upstream node '08b108a1-…' has no content yet
```

Four separate defects are visible in those five lines, and the fifth explains why the three
rounds were spent badly.

**The node itself:** `08b108a1`, `curio.builtin/computation-analysis`, goal *"Calculate Density —
Join population data to boundaries and calculate density per area"*. Its upstream is
`6b36ee91`, a `merge-flow` (no code — written, not executed), whose own upstreams are the two
loaders that DID run: a GeoDataFrame of community areas and a CSV of ACS population. The three
attempts, all preserved in the Node Content Builder's home session (`f1667605`), guess a join
key (`community_area`), then raise their own `KeyError('No common column found…')`, then lose the
GeoDataFrame and ask a plain `DataFrame` for `.crs`. **Nothing in the loop ever told the child
what columns those two upstream frames have.**

---

## 1. Problem Statement

### D1 — the diagnosis is sliced by character count, not by meaning

Three places cut raw tracebacks to a fixed number of characters:

- the batch's per-node error line: `detail = raw_detail[:200] if kind in _HEAD_FIRST_KINDS else
  raw_detail[-200:]` (`services.py:4272`), which is what the strip renders — hence the owner's
  *"das/core/generic.py"* (the tail of `pandas/core/generic.py`);
- the Solve card's round lines: `(stderrTail or detail)[-160:]` (`services.py:7040`-`7047`) —
  hence *"round 1: execution-error — ic.py\", line 1776"* and *"round 2: execution-error — de"*,
  where `de` is all that survived of the line before the exception;
- the per-node Solve card: `raw[:100]` / `raw[-100:]` (`services.py:5800` region).

Every one of them can land mid-token, and none of them is anchored on the two things a reader
needs: **the exception type and message** (present, at the tail, but often orphaned from its
frame) and **the file/line that raised**. `AttributeError: 'DataFrame' object has no attribute
'crs'` survived by luck of length; `round 2`'s message survived with two junk characters glued to
it and no indication that the exception was raised BY THE MODEL'S OWN CODE rather than by pandas.

### D2 — the code that failed is not in the transcript

An attempt row carries `contentSha256` and never the content (`services.py:6900` region: `{round,
contentSha256, verdict, kind, detail, stderrTail, outputDataType, durationMs, source}`). The code
exists in the delegate's home session — the node's Node Builder chat — but only as the model's raw
reply, and the Solve turn that reports the failure neither shows it nor points at it. The card
part schema (`content.py:185`-`202`) is `{kind, title, lines[]}` with per-line caps, so the
existing surface *cannot* carry code even if the runtime had kept it.

Consequence, exactly as reported: the user sees three truncated tracebacks, cannot see what ran,
and cannot tell whether the loop tried three different things or the same thing three times.

### D3 — three attempts, 25 seconds, against budgets of 5 and 45 minutes

`_VALIDATE_CORRECTION_ROUNDS = 2` (`services.py:5624`) is a hard, unconfigurable 1 + 2: three
attempts and stop. The sandbox's own per-run timeout is `DEFAULT_EXEC_TIMEOUT_S = 300`
(`runner.py:42`) — the "5-minute timeout" of the report — and the batch deadline is
`DEFAULT_SOLVE_BATCH_DEADLINE_S = 45 * 60` (`services.py:5724`). The batch under discussion
**finished in 25 s**. The loop stopped for want of a round, with 99% of both budgets unspent, and
the failure text says *"not fixed after 3 attempts"* without saying that three was a cap rather
than a conclusion.

### D4 — a repeated failure is reported as three unrelated ones

The three rounds are three symptoms of ONE cause (an unknown join key). The trail presents them
as a list with no statement of what changed between attempts, and the run's own summary
(`not fixed after 3 attempts — execution-error: <tail of round 3>`) names only the last, so the
strip's one-line verdict is the least informative of the three.

### D5 — the loop never hands the child its inputs' schema (the reason the attempts were wasted)

`_upstream_outputs_for` (`services.py:5662`) supplies `{nodeId, goal, outputDataType, wave}` per
upstream — a TYPE, never a column list — and only for upstreams that are in `wave_outputs`, which
holds nodes that **executed and passed**. `6b36ee91` is a `merge-flow`: written, not executed
(`DEC-075`), so it is absent from `wave_outputs`, so the analysis node's `upstreamOutputs` was
**empty**. The child was asked to join two frames while being told nothing about either.

The data was right there: the sandbox stores every artifact and serves a bounded preview at
`GET /get?fileName=<artifactId>&maxRows=<n>` (`sandbox/app/api.py:88`), and the backend already
fetches from it (`runner.load_artifact_as_dict`, `runner.py:85`, whose comment records the
MemoryError that unbounded fetching once caused). Three rounds of guessing were spent on a
question one bounded request answers.

### Expected behavior

- **R1** Every attempt is visible in the chat transcript, durably: its round number, the verdict,
  the **code** it ran, and the error it produced — not a summary line.
- **R2** A failure names the exception type, its message, and the frame that raised it, never a
  string cut mid-token; and it says whether the code failed or the model's own guard raised.
- **R3** Solve keeps correcting while there is budget to correct in — a raised round cap AND a
  per-node wall-clock budget, whichever binds first — and the outcome SAYS which bound stopped it.
- **R4** A node whose inputs already ran is told what those inputs actually contain: columns,
  dtypes, row count, and the merge-slot order they arrive in.

### Why it matters

Correctness first: R4 is the difference between three attempts and a solved node — the loop
currently spends its whole budget on a question it can answer deterministically. Truthfulness
second: "not fixed after 3 attempts" reads as a verdict on the code when it is a verdict on the
round cap. Usability third: the user's only way to see what was tried is to open another agent's
chat and read raw model replies.

---

## 2. Scope

### In scope

Backend (`utk_curio/backend/app/agents/`):

- new `failure_text.py` — the ONE excerpt/anchor helper (pure, tested): exception line, raising
  frame, line-boundary truncation, and the "raised by the candidate's own guard" distinction.
- `services.py` — the three slicing sites re-pointed at it; the attempt row gains `code`
  (bounded) and the loop gains `stoppedBy`; `_VALIDATE_CORRECTION_ROUNDS` becomes
  `solve_correction_rounds()` + `solve_node_budget_s()` (env-overridable, the `exec_timeout_s`
  pattern); the new `solveAttempts` part minted per failed node on the Solve turn and on the
  per-node Solve turn; `_upstream_outputs_for` gains the schema summary and walks through
  pass-through upstreams in merge-slot order.
- new `upstream_schema.py` (or a section of `failure_text.py`'s neighbour module) — the bounded
  artifact preview → `{columns:[{name, dtype}], rowCount, sample?}`, one place, always bounded.
- `content.py` — the `solveAttempts` part's parser (runtime-minted only, like
  `datasetCandidates`): bounded rounds, bounded code, bounded error text.
- `execution/runner.py` — a `maxRows`-bounded preview call beside `load_artifact_as_dict`.

Frontend (`utk_curio/frontend/urban-workflows/src/`): `agentsApi.ts` (the part + the attempt's
`code`/`stoppedBy`), a new `AgentSolveAttemptsCard` (one `<details>` per attempt: verdict, error
excerpt, `<pre>` code, and an **Open Node Builder** action through `ctx.openChat`),
`AgentChatPanel` (render the part), `AgentBuilderStrip` / `NodeSolveRow` (the live equivalent and
the "stopped by" wording), `AgentReviewCard` (show each attempt's code in the existing trail).

Docs / ledgers: `docs/AGENT-CATALOG.md` (Solve's failure surface + the retry budget),
`docs/USAGE.md`, dev/03 (a `DEC` row only if §3 keeps the decision — see below), dev/00,
`BL-P5-…-61`, this memo's status.

Tests: `test_failure_text.py` (new), `test_upstream_schema.py` (new), `test_verified_rounds.py`
(budget + stoppedBy + attempt code), `test_routes.py` (the part reaches the transcript), jest for
the new card and the strip wording.

### Out of scope

- The sandbox's own timeout (`DEFAULT_EXEC_TIMEOUT_S`) and the batch deadline stay as they are;
  this memo spends the budget that exists rather than enlarging it.
- Streaming the child's raw prompt into the transcript. The framed delegation turn stays a
  summary (`_run_delegate_traced`); what becomes visible is the CODE and the ERROR, which is what
  the report asks for.
- Changing what the Node Content Builder is asked to produce beyond the new inputs (no new
  instruction rules about joins — the schema is data, not advice).
- The `data-transformation` node's own `gdf.metadata = {...}` pattern, and the merge-flow's
  `arg`-is-a-list convention: both are content questions for the prompts, recorded as follow-ups.
- Retrying a node whose failure is `upstream-blocker`, `precondition` or `awaiting-selection` —
  those are bounds and waits, not fixable code (unchanged).

### Related code paths to check

`sessions.append_turns` size behavior (the transcript grows by the attempts part — bounded);
`attachments.reconcile_proposal_queue` (untouched); the evaluation harness
(`app/agents/evaluation/*`) which reads Solve results and must not mistake a longer trail for a
different outcome; `_HEAD_FIRST_KINDS`; dev/126's `awaiting-source` verdict (a different lane —
its trail also gains the code for its refused rounds).

---

## 3. Recommended Implementation Approach

### A. One failure-text helper, three call sites (`failure_text.py`)

```python
def exception_line(raw: str) -> str | None      # "AttributeError: 'DataFrame' object has no attribute 'crs'"
def raising_frame(raw: str) -> str | None       # 'pandas/core/generic.py", line 6206, in __getattr__'
def excerpt(raw: str, *, limit: int, head: bool = False) -> str
def is_self_raised(raw: str, code: str) -> bool  # the guard the candidate itself wrote
def summary(raw: str, code: str, *, limit: int) -> str
```

`excerpt` truncates on **line boundaries** and never mid-token, prefixing `…` when it drops lines.
`summary` is what the strip and the cards show: the exception line first (it is the answer), then
the raising frame, then — when `is_self_raised` — the honest note *"raised by the code's own
check, not by the library"*, which is precisely round 2's case and reads today as a pandas error.

No behavior lives in the callers: `_record_node_outcome`, the loop's `rounds_trace`, the per-node
Solve card and the attempt row all call the same two functions, so the strip, the card and the
persisted trail can never disagree about what failed.

### B. The attempt row carries the code, and the loop says what stopped it

`attempts[]` gains `code` — the candidate the round ran, bounded at `_ATTEMPT_CODE_CHARS = 4000`
with a truncation marker, and stored for **failed** rounds only (a passing round's code is the
node's content or its review). `contentSha256` stays: it is how a reader sees round 2 and round 3
were different attempts rather than a repeat.

The loop's outcome gains `stoppedBy ∈ {"passed", "rounds", "budget", "repeat", "decline",
"blocker"}`, and every failure sentence uses it: *"not fixed after 5 attempts (round cap)"* vs
*"not fixed after 3 attempts (5-minute budget for this node spent)"* vs *"stopped after 2
attempts — the second attempt was identical to the first"*.

### C. A real retry budget (R3)

```python
DEFAULT_SOLVE_CORRECTION_ROUNDS = 5      # 6 attempts; CURIO_SOLVE_CORRECTION_ROUNDS
DEFAULT_SOLVE_NODE_BUDGET_S     = 300    # CURIO_SOLVE_NODE_BUDGET — the owner's 5 minutes
```

The loop checks the wall budget **at round boundaries** (before dispatching another generation),
so a single slow round can overrun it but a new one never starts past it; the batch deadline
(`DEFAULT_SOLVE_BATCH_DEADLINE_S`) still bounds the whole run and is checked first, so one
pathological node cannot starve the rest. `_same_code` keeps stopping a repeat immediately — more
rounds must not mean more identical rounds. Both knobs follow the `exec_timeout_s` pattern (an
unusable env value falls back to the default rather than raising).

`_VALIDATE_CORRECTION_ROUNDS` is retired in favour of the accessor, so validate-node, Simulation
Mode and both Solves share one policy — which is what makes "more retries" true everywhere the
user can ask for a fix, rather than in the batch only.

### D. Every attempt in the transcript: the `solveAttempts` part (R1)

A card cannot carry code (§1 D2), so the trail becomes a **runtime-minted part**, in the shape the
codebase already uses for runtime-minted structured content (`datasetCandidates`, dev/114):

```json
{"type": "solveAttempts", "nodeId": "08b108a1-…", "label": "Calculate Density — …",
 "attachmentId": "65b1c401…", "rounds": 5, "stoppedBy": "budget",
 "attempts": [{"round": 1, "verdict": "fail", "kind": "execution-error",
               "error": "KeyError: 'community_area'\n  at pandas/core/generic.py\", line 1776, in _get_label_or_level_values",
               "selfRaised": false, "code": "import pandas as pd\n…", "durationMs": 4120}]}
```

Minted by the runtime only — `content.py` parses it for the persisted-turn round trip and the
model can never author one (it is not in the model-facing tail contract). It rides:

- the batch's Solve turn, one part per failed node (bounded: at most 8 nodes, then a line saying
  how many more failed and where to look);
- the per-node Solve turn, for the node it solved;
- dev/126's `awaiting-source` outcome too — its refused rounds have code and a refusal, and the
  user asked for *all* attempts.

`attachmentId` is that node's Node Builder attachment, so the card can open the chat where the
child's own replies live.

### E. The child is handed its inputs' schema (R4)

`upstream_schema.summarize(user_key, project_id, artifact_id)` fetches a **bounded** preview
(`GET /get?fileName=…&maxRows=5`) and returns `{columns: [{name, dtype}], rowCount, sample}` with
hard caps (≤ 60 columns, ≤ 3 sample rows, strings clipped). Never unbounded — the MemoryError
comment on `load_artifact_as_dict` is the reason the cap is in the function rather than in its
callers.

`_upstream_outputs_for` then changes in two ways:

1. it **walks through pass-through upstreams** — a node with no code (`merge-flow`, a data pool)
   contributes its own upstreams instead of nothing, in **merge-slot order** (`in_0`, `in_1`, …),
   so the row list matches the `arg[0]`, `arg[1]` the child will index;
2. each row gains `schema` when its artifact is available, plus `argIndex` when it arrived
   through a merge.

So the analysis node's inputs read *"arg[0]: community areas — columns [the_geom, area_numbe,
community, shape_area…]; arg[1]: ACS profile — columns [GEOID, community_area_name, TOT_POP…]"*,
and the join key is a fact rather than a guess. The same rows ride the correction rounds, where
today only `previousAttempt`/`validationError` do.

The preview is fetched once per artifact per batch (cached in the batch context) and skipped
silently when the sandbox cannot serve it — an absent schema is an absent input, never a fabricated
one (`DEC-063`'s honesty clause).

### Does this need a `DEC`?

No new decision is proposed. Every part of it is an existing decision applied: `DEC-075` already
says a Solve reports honestly what it did; `DEC-063` already says an input the agent needs must be
supplied on the path it runs on (this is its eighth application, and D5 is exactly its failure
shape); `DEC-073` already owns the loop. The memo records the budgets as configuration, not as
policy. If review disagrees, the candidate decision is "*a repair loop is bounded by time and by
repetition, not by a round count, and every attempt it makes is part of the record*" — worth a
`DEC` only if the ledger wants the budget shape pinned.

---

## 4. Data and State Handling

| Datum | Source of truth | Written by | Read by |
|---|---|---|---|
| A round's code + error | the loop's `attempts[]` | `_verified_content_rounds` | the `solveAttempts` part, the strip, the review card |
| Which bound stopped the loop | the loop's `stoppedBy` | the loop | every failure sentence |
| The durable attempt trail | the `solveAttempts` part in the session file | the Solve paths (one part per failed node) | the transcript, after any reload |
| An upstream's schema | the sandbox artifact (`/get`, bounded) | nobody — read-only | the generation + correction inputs |
| Node status / nodeRuns | `builderSession` | the Solve paths | the strip, Retry |

**Bounds, because this is where a trail becomes a liability**: 4000 chars of code per attempt,
2000 of error text, ≤ 8 attempts rendered per node, ≤ 8 failed nodes per turn; a truncated field
says so. A node that fails five times therefore adds ~30 KB to a session file, not megabytes.

**Loading / empty / error / success.** The part is minted only for a node that actually failed (or
awaits a source); a node that passed keeps today's one-line result. A sandbox outage stays
`pending — not verified` with no attempts part (nothing was attempted). An unavailable artifact
preview means the schema key is absent — the child is told nothing rather than something invented.

**No races added.** The attempts trail is assembled in the worker that owns the node and appended
by the existing single persist (`_persist_wave` / `_finish`) under the spec lock; the schema cache
is per-batch, in memory, keyed by artifact id.

---

## 5. UI and UX Requirements

- **In the transcript**, under the Solve card: one `AgentSolveAttemptsCard` per failed node,
  headed *"Calculate Density — 5 attempts, stopped by the 5-minute budget"*. Each attempt is a
  collapsed `<details>` — *"Round 3 · execution-error · 4.1 s — AttributeError: 'DataFrame' object
  has no attribute 'crs'"* — expanding to the raising frame, the honest note when the code raised
  its own error, and the code in a `<pre>` with a copy button (the dev/78 `AgentCodeBlock` is the
  existing one). The last attempt is expanded by default; the rest are collapsed, so a five-round
  trail does not bury the chat.
- **An Open Node Builder button** on the card (dev/126's `OpenDatasetFinderAction` pattern):
  the node's own chat, where the child's replies and any later fix live.
- **The strip** shows the same verdict wording with the bound named, and its reason line stops
  being the only place the error appears.
- **Truthful copy**: never *"not fixed after N attempts"* alone — always the bound; never a
  library name for an error the candidate raised itself; a truncated field is marked truncated.
- **Accessibility**: `<details>`/`<summary>` are native disclosure (keyboard-operable, announced);
  each summary names round, kind and duration so a screen reader gets the shape without expanding;
  the code block is `<pre>` with a real `<code>` child and an accessible copy button; the card is a
  `role="group"` with an accessible name naming the node.
- Every string arrives bounded and plain-text from the server and renders as text (`REQ-SEC-002`);
  no HTML from a traceback, no ANSI.

---

## 6. Edge Cases

1. **A traceback with no recognizable exception line** (a bare sandbox message, a timeout notice):
   `summary` falls back to the last non-empty line, whole, and says nothing it cannot see.
2. **A multi-exception traceback** (`During handling of the above exception…`): the LAST exception
   line wins, and the first is kept in the expanded view.
3. **stderr with warnings only, on a failed run**: the exception line is absent; the excerpt names
   the failure predicate (`output.path == ""`) rather than a warning.
4. **A round that failed the grounding gate** (dev/114): `kind: ungrounded-source`, head-first
   excerpt, code included — the refused literal is in the code, which is now visible.
5. **Round 2 identical to round 1**: `stoppedBy: "repeat"`, two attempts recorded, and the card
   says so instead of implying the budget was spent.
6. **A prose decline** (dev/115): `stoppedBy: "decline"`, one attempt whose "code" is the
   decline text, labeled as prose rather than as code.
7. **The wall budget expires mid-round**: the round completes and is recorded; no new round starts.
8. **The batch deadline expires first**: the node reverts to `pending` with the batch's reason,
   and the attempts made so far are still minted — a partial trail beats none.
9. **A node with 8+ failed attempts** (only reachable with a raised env value): the first and last
   four are rendered with a line naming what was elided; the persisted part keeps its cap.
10. **More than 8 failed nodes in one batch**: 8 parts plus a line naming the rest, each still
    reachable from its own node's chat.
11. **A merge-flow upstream with an unfilled slot**: the row list has a gap, and it is stated
    (*"arg[1]: not connected"*) rather than silently shortened — an index the child must not use.
12. **A pass-through chain** (pool → merge → node): the walk is depth-bounded (4) and cycle-safe
    (the graph is a DAG by `DEC-070`, but the walk does not rely on that).
13. **An artifact the sandbox no longer has** (a later run overwrote it): no schema key; dev/118's
    vanished-input handling is untouched.
14. **A huge frame** (2000 columns, 10M rows): the cap yields 60 columns and a stated total; the
    preview request is `maxRows=5` so the sandbox never serializes the body.
15. **A JavaScript node** (`custom-js`): the same trail; `dtype` is absent and the schema is
    whatever the artifact preview reports.
16. **A node solved on Retry after a failed trail**: the old attempts part stays in the transcript
    (it is the record of what happened) and the new turn says solved — no rewriting of history.

---

## 7. Testing Strategy

**Unit — `failure_text.py`**: the owner's three real tracebacks (the `KeyError` with the pandas
frame, the self-raised `KeyError`, the `.crs` `AttributeError`) produce the exception line intact,
the right frame, and `selfRaised` true only for the middle one; a bare message, a chained
traceback, a warning-only stderr, an empty string; `excerpt` never returns a partial line and
marks what it dropped. **This is the test that would have caught `"— de"`.**

**Unit — the budget**: `solve_correction_rounds()`/`solve_node_budget_s()` read the env, fall back
on garbage, and are read once per loop; a fake clock proves a new round does not start past the
budget, that the round cap binds when the clock is slow, and that `stoppedBy` names the bound that
actually bound (four cases: `rounds`, `budget`, `repeat`, `decline`).

**Unit — `upstream_schema`**: the preview is always requested with `maxRows`; caps applied
(columns, sample rows, string length); a 500 / 401 / timeout yields no schema and no raise; the
pass-through walk resolves merge slots in order, states an unconnected slot, and is depth-bounded.

**Unit — the part**: `content.py` parses a minted `solveAttempts` round trip and rejects a
malformed one (fail-open to text, the T2 rule); a model reply containing that JSON is NOT parsed
as one (runtime-minted only).

**Integration — routes**: a Solve whose node fails N rounds mints one `solveAttempts` part on the
Solve turn with N attempts, each carrying code and an exception line; the part survives a session
reload; the per-node Solve mints its own; a passing node mints none; an `awaiting-source` node
mints one for its refused rounds; a batch with two failed nodes mints two parts.

**Integration — the schema reaches the child**: the analysis-node shape from the report (two
loaders → merge → analysis) puts `arg[0]`/`arg[1]` column lists in the child's inputs — asserted
on the captured provider frame — and the correction round receives them too.

**Frontend (jest)**: the card renders one disclosure per attempt with the summary text, expands
the last by default, shows the code, copies it, opens the node's chat; the strip names the bound;
the review card shows an attempt's code; nothing renders HTML from the error text.

**Required before this is complete**: the failure-text unit tests, the budget tests, the schema
tests, routes (the part on both Solve paths, reload-durable), the jest card tests — and a live
re-run of the owner's dataflow: `08b108a1` must either solve or fail with a trail showing five
attempts, each with its code, and the bound named.

---

## 8. Acceptance Criteria

1. The transcript shows **every** attempt of a failed node — round, verdict, kind, duration, the
   exception line, the raising frame, and the code — and still shows them after a reload.
2. No failure string is ever cut mid-token; the exception type and message are always intact and
   always first.
3. An error the candidate's own code raised is labeled as such, never attributed to the library
   whose file happens to appear in the frame.
4. A failure sentence always names the bound that stopped the loop; *"not fixed after 3
   attempts"* never appears without one.
5. Solve makes up to 6 attempts by default and keeps going while its per-node budget (5 min by
   default) allows; both are env-configurable and an unusable value falls back to the default.
6. A repeat still stops the loop immediately, and the card says the attempt was identical.
7. A node whose upstreams have run receives their real columns and dtypes — through a merge, in
   `arg` order, with an unconnected slot stated — on the first generation and on every correction.
8. The artifact preview is always bounded, is cached per batch, and its absence removes the input
   rather than inventing one.
9. Every attempts payload is bounded and marked when truncated; a five-round trail adds tens of
   kilobytes to a session, not megabytes.
10. Opening the node's Node Builder chat is one click from the failure card.
11. `tests/test_agents`, `tests/test_projects`, `tests/test_datasets`, jest and `tsc --noEmit` are
    green, with only the pre-existing unrelated `test_packages` failure recorded before this work.
12. A live re-run of dataflow `623b6620` shows either a solved `08b108a1` or a trail that explains
    itself without opening another chat.

---

## 9. Recommended Commit Breakdown

1. **`failure_text.py` + its tests**, and the three slicing sites re-pointed at it (no other
   behavior change).
2. **The attempt row carries code, and the loop reports `stoppedBy`** — plus every failure
   sentence naming the bound.
3. **The retry budget**: the two accessors, `_VALIDATE_CORRECTION_ROUNDS` retired, the
   round-boundary wall check, tests with a fake clock.
4. **The `solveAttempts` part**: `content.py` parsing, minting on both Solve paths and on
   `awaiting-source`, route tests for durability.
5. **`upstream_schema.py` + the pass-through walk**: bounded preview, merge-slot order, handed to
   generation and corrections; tests including the report's exact graph shape.
6. **Frontend**: the card, the strip's wording, the review card's code, `agentsApi` types, jest.
7. **Docs + ledgers**: `docs/AGENT-CATALOG.md`, `docs/USAGE.md`, dev/00, dev/03 (only if a `DEC`
   is minted), `BL-P5-…-61`, this memo's status and its §12.

---

## 10. Engineering Quality Checklist

- **No duplicated logic**: one failure-text module for three call sites; one budget accessor pair
  for all four resolution paths; one schema summarizer with its caps inside it; one part parser.
- **Centralized**: the trail is assembled in the loop that owns the rounds, minted by the callers
  that own the turn, and rendered by one component.
- **Types explicit**: the part and the attempt row are parsed at the boundary; `stoppedBy` is a
  closed set; the frontend types are declared, not inferred.
- **Predictable state**: the trail is appended by the existing single persist under the spec lock;
  the schema cache is per-batch and in-memory; no new writer.
- **Consistent UI**: native disclosure, the existing code block, the dev/126 open-chat pattern.
- **Every state named**: passed, rounds, budget, repeat, decline, blocker, infrastructure.
- **Accessibility** in §5; **security**: bounded plain text, no HTML from tracebacks.
- **Bounded by construction**: every field, every list, every fetch.
- **Conventions**: `DEC-063` applied rather than restated; `DEC-075`'s honesty preserved; no
  fallback that invents data; loud absence instead.

---

## 11. Open questions and recorded follow-ups

- **F1** Should the round cap and the node budget be per-agent settings (dev/23's project defaults)
  rather than env-only? Deferred: env now, settings when someone needs two different policies in
  one deployment.
- **F2** The merge-flow's `arg`-is-a-list convention is taught only by the preamble's exemplars;
  with §3E the runtime now states it per node, and the prompt paragraph could be retired. Needs a
  prompt-byte change of its own.
- **F3** `data-transformation` wrote `gdf.metadata = {...}` — a pandas attribute assignment that
  does not survive; a content-quality question for the AUTK map lane, not this loop.
- **F4** Whether a passing round's code should also be recorded (it is the node's content, so it
  is already visible; a diff between the failing and the passing attempt might be worth it).
- **F5** Owner live re-run of `623b6620` after commit 5 and again after commit 6.
