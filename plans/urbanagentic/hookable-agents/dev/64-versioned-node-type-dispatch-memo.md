# Implementation Memo: Versioned Dispatcher Ids Break `NodeType` Dispatch — Merge Flow Dead, Play Runs Hang, Reloads Lose Inputs (dev/64, recreated)

Date: 2026-08-06
Status: implemented 2026-08-06 on `bug/datacalog` — COMMIT-7d1acf11 (single
commit: dev/64 port from `feat/hookable-agents-loop` + the two deeper fixes;
user-verified live before committing). Verification: frontend `npx jest` →
697 passed, 66 suites; `tsc --noEmit` clean for touched files. Original memo file
exists only on the other branch; this recreation supersedes it.

## 1. Problem Statement — three stacked defects

**Controlled A/B that pins defect 1.** Project
`fefb7f58-210e-4329-93af-e799cef0c3f3` (2 loaders → merge `in_0`/`in_1` →
computation) fails with the sandbox tripwire ("received no input but its code
references `arg`", worker.py:238), while `docs/examples/dataflows/Merge.json`
and `MergeFlowDataPool.json` — the same graph shape — work. The only relevant
delta: the examples carry **unversioned** node types (`curio.builtin/merge-flow`),
the project carries **versioned** ones (`curio.builtin/merge-flow@1`, written by
the palette since the `curio.builtin@1` manifest pack, COMMIT-f7879051).

1. **Versioned ids never match the `NodeType` enum.** `NodeType.MERGE_FLOW` is
   unversioned (constants.ts:26) and `getFlowNodeCanonicalType` returns
   `data.nodeType` verbatim. Every `== NodeType.X` site in FlowProvider is false
   for `@1` nodes, so `propagateDownstreamInputs` treats a merge as an ordinary
   node: each upstream completion **overwrites** the merge's whole `data.input`
   instead of filling its `in_N` slot; `buildMergeOutputArray` gets a non-array,
   emits nothing, downstream `arg` stays `None`. Also disabled: merge handle
   auto-resolution/limits, slot clearing on edge delete, data-pool interaction
   routing, vis-sink exclusion from dataset saving. Invisible in the UI because
   the behavior registry resolves versioned ids (`registerBehavior('merge-flow')`)
   — handles render purple while provider dispatch silently fails.

2. **Play runs hang on repeated errors ("play up to" appears broken).**
   UniversalNode signals exec-done from an effect keyed on `[output?.code]`
   (UniversalNode.tsx:112-124). A node that errors **twice in a row** — exactly
   what a broken merge produces when the user retries "play up to" — keeps
   `code === "error"`, the effect never re-fires, no `signalNodeExecDone`, and
   the run sits on the 10-minute stall watchdog (`PLAY_ALL_STALL_TIMEOUT_MS`).
   First attempt fails fast; every retry hangs. This is why the fix "seemed to
   make things worse": retrying against the still-broken merge hit the stall.

3. **Reloads strand all inputs.** `propagateDownstreamInputs` runs only on live
   execution (applyNewOutput) and on new connections (onConnect cached-output
   fan-out). ProjectLoader restores the `outputs` list but nothing refills
   `data.input`, so after any reload a merge dataflow demands manually rerunning
   every upstream before the merge can assemble — misread as "still broken".

Secondary (same arc): `loadParsedTrill` passed `[]` (truthy) as `custom_edges`,
blanking load-time merge-handle resolution; `TrillGenerator` dropped
`sourceHandle`/`targetHandle`, so agent-built UUID-id edges lose slot wiring and
reload as unrenderable `"in"` edges (the dev/62-guard delete-deadlock).

## 2. Scope

- `utils/flowNodeCanonicalType.ts` — `stripNodeTypeVersion` (delegates to
  `splitCanonicalNodeType`) + `unversionedFlowNodeType`.
- `providers/FlowProvider.tsx` — 11 enum-comparison swaps; `custom_edges !==
  undefined` guard; new `hydrateRestoredOutputs(outputs)` on FlowContext.
- `components/UniversalNode.tsx` — done-signal effect keyed on `[output]`
  (object identity), not `[output?.code]`.
- `components/ProjectLoader.tsx` — calls `hydrateRestoredOutputs` after
  restoring outputs.
- `hook/useWorkflowOperations.ts` — loadParsedTrill accumulates spec edges for
  resolution.
- `TrillGenerator.ts` — persists edge handles (loadTrill already prefers them).
- Audit fixes: `NotebookConvertor.ts` export branches, `styles.tsx` border-color
  lookup, `CodeEditor.tsx` dedupes its local unversioned helper,
  `saveOutputDataset.ts` sink check, behaviors-test fixture uses a real
  versioned id.

Out of scope: `getFlowNodeCanonicalType` itself (registry lookups need the full
id); the manual-delete guard UX; backend/sandbox (tripwire behaved correctly).

## 3. Approach

One stripping implementation (`stripNodeTypeVersion` →
`splitCanonicalNodeType(...)?.unversioned ?? id`); enum comparisons go through
`unversionedFlowNodeType`. Hydration reuses `propagateDownstreamInputs` with no
exec bookkeeping (no signal/install-sync — nothing executed), deferred one tick
so loadTrill's graph commits first. The done-signal fix relies on `setOutput`
always producing a fresh object and on `signalNodeExecDone` ignoring nodes
outside the active level, so duplicate signals are harmless.

## 4. Edge Cases

Package nodes with real versions dispatch by full id (registry untouched);
unversioned legacy ids are a no-op strip; hydration skips empty outputs and
overwrites nothing that a live rerun wouldn't; repeated identical errors now
each signal done; a source feeding two slots of one merge fills both.

## 5. Tests (all in-tree, 697 passing)

- `tests/utils/flowNodeCanonicalType.test.ts` — strip semantics; the exact
  versioned-vs-enum regression.
- `tests/providers/mergeFlowPropagation.test.tsx` — drives the REAL FlowProvider:
  slot filling with `@1` ids (A/B-verified to fail pre-fix), dual-slot source,
  load-time handle resolution against the accumulating edge list, `[]` = "no
  edges yet", downstream outputs-bundle delivery, and hydration refilling merge
  slots from restored filename refs.
- `tests/TrillGenerator.test.ts` — UUID-id edges round-trip their handles.

## 6. Acceptance Criteria

- Project `fefb7f58…` (versioned ids, untouched spec): run both loaders → merge
  emits with no user action → computation receives `arg[0]`/`arg[1]`.
- "Play up to" the computation node completes the run — and if a node errors
  repeatedly, each retry fails fast (toast/error state), never a 10-minute hang.
- Reload the project → run ONLY the computation node → it executes with inputs
  hydrated from the restored outputs (no upstream reruns needed).
- Example dataflows (unversioned ids) behave exactly as before.

## 7. Commit Breakdown (when committing)

1. helper + unit tests; 2. FlowProvider dispatch swaps + load-time resolution +
merge regression suite; 3. UniversalNode done-signal + hydration (FlowProvider,
ProjectLoader) + hydration test; 4. TrillGenerator handles + audit fixes; 5. this
memo.
