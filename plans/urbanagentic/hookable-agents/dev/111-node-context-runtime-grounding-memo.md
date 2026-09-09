# dev/111 — `nodeContext.current_input/current_output` are sent empty: ground them in the live runtime state the composer already receives

**Status: IMPLEMENTED (2026-08-27) — commits `4b3d8cf6` (1, `nodeRuntimeSummary` + 15 tests), `6e454775` (2, composer/overlay wiring + tightened `agentRunContext` tests + 1 overlay test), docs in the closing commit. Backlog `BL-P2-20260827-11`; entry-10 follow-up premise corrected in place. Full jest 93/1064 green. Defaults taken: raw sandbox `dataType` reported beside the declared label (no re-mapping); server-side `node_context.py` untouched.**

Date: 2026-08-27
Branch / tree: `feat/agentscatalog` @ `0323613c`. Line numbers pinned to that commit.
Origin: loose end reported by another session — "`nodeContext.current_input/current_output` still sent empty (BL-P2-10, restated BL-P5-02)". Verified true; the *premise* recorded with it is not (§1).
Family: dev/44 (grounded run inputs — the composer this memo amends) → dev/38 (`inputs.reads` contract) → dev/67-6 (the **server-side** `node_context.compose_node_context` for the `node.content.generate` delegation path — a sibling, not this read; §2) → dev/67-2 (runtime journal / `node.runtime.read`, the pull-based complement) → dev/96 (bounded payload slices — the caps discipline reused here) → dev/104 (consolidated this as a tracked remainder).
Backlog: `BL-P2-runtime-providers.md` entry 10 (line 196) — its follow-up line is **rewritten** at closure; `BL-P5-first-release-orchestration.md:49` cross-reference updated. **No new DEC** — this completes an existing contract (dev/38 declared read → dev/44 producer) with no new policy. Closing entry `BL-P2-20260827-11` minted (number checked on disk).

---

## 1. Problem Statement

**Current behavior.** For every agent whose manifest declares the `nodeContext` read, the live-canvas composer emits a fixed payload with two dead fields (`agentRunContext.ts:92-101`):

```ts
return JSON.stringify({ id, type, content, current_input: "", current_output: "" });
```

Four built-ins declare that read (`builtin.py:116, 170, 212, 295`): **Node Explainer**, **Node Researcher**, **Dataset Finder**, **Generated Content Evaluator**. Each is told, on every send, that its node has no input and no output — even after the node ran. The only test touching the fields asserts that the keys *exist* (`agentRunContext.test.ts:104-105`), so the emptiness is unpinned in either direction.

**The recorded premise is wrong in two ways, and this changes the design.**

1. *"Legacy passed live execution values."* It did not. The legacy explanation tab passes `data.in` / `data.out` (`NodeEditor.tsx:280-281`), which are the node's **declared expected I/O types** (`SupportedType` — `DATAFRAME`, `GEODATAFRAME`, …) chosen in the box selects (`styles.tsx:672, 701`). The widget refines its *local* copies after a run (`styles.tsx:206-229`: `data.output.outputType` → `expectedOutputType`; `data.input.dataType` → `expectedInputType`) but never writes them back to `data.in/out`. Byte-faithful parity would therefore reproduce two type labels, not execution facts.

2. *"Wire … when the exec store exposes them to the overlay."* It already does. `AgentDockOverlay.tsx:22` consumes `useFlowContext()`, whose value carries `outputs: IOutput[]` (`FlowProvider.tsx:88`, `{ nodeId, output }` where `output` is the raw sandbox response `{ path, dataType, dataset? }`). And the composer is already handed the live ReactFlow nodes (`getNodes()`, `AgentDockOverlay.tsx:101-106`), whose `data` carries:
   - `data.input` — the propagated upstream artifact ref, `FlowNodeInput { path, dataType? }`, `""` when none, or a per-slot **array** for Merge Flow (`FlowProvider.tsx:606-625`, `662-665`; refilled from `outputs` on load, `:1182`).
   - `data.output` — `NodeOutput { code: "" | "exec" | "success" | "error", content, outputType }`, written by the node's own state hook via **object mutation** (`useNodeState.ts:28`: `data.output = output`).
   - `data.in` / `data.out` — the declared types (also copied onto the Trill node by `TrillGenerator.ts:180-184`, but the composer's `TrillNode` type at `agentRunContext.ts:29` doesn't declare them, so they are dropped).

   Nothing is missing upstream; the composer simply never looks.

**Expected behavior.** `current_input` and `current_output` carry a **bounded, truthful runtime summary** of the target node at send time:
- what flows in (data type + artifact identity, per slot for merges; or "no upstream input"),
- what came out (execution status; produced artifact's data type + identity on success; a truncated error message on error; "never-executed" when the node has not run),
- with the declared expected type shown alongside as `declared: <TYPE>` so the agent can spot mismatches (declared `DATAFRAME`, produced `geodataframe`).

Never the output *content*: a successful `data.output.content` can be a full table/geometry blob and would crowd the 120k-char server bound (dev/44) and the model's window.

**Why it matters.** The Node Explainer's whole job is "explain what this node does with its data"; today it must guess types from code. The Evaluator judges generated content without knowing whether it ran or errored. Dataset Finder cannot see what the node already consumes. The fix costs one small utility and closes an item that has been restated across three backlog documents.

## 2. Scope

**Included**
- `src/components/agents/attach/agentRunContext.ts` — the `nodeContext` case reads the live node (not only the Trill node) and calls the new summarizer; `AgentCanvasState` gains an optional `outputs?: IOutput[]`.
- **New shared utility**: `src/components/agents/attach/nodeRuntimeSummary.ts` — pure functions `summarizeNodeInput(data, opts)` and `summarizeNodeOutput(data, storeOutput, opts)` → `string`. Pure, no React, no I/O; all caps live here as named constants.
- `src/components/agents/attach/AgentDockOverlay.tsx` — pass `outputs` from `useFlowContext()` into the canvas state (one line).
- Tests: new `tests/attach/nodeRuntimeSummary.test.ts`; `tests/attach/agentRunContext.test.ts` tightened from "keys exist" to real-value assertions plus the never-executed and merge cases.
- Docs: `BL-P2-runtime-providers.md` entry 10 follow-up line rewritten (premise corrected); `BL-P5-first-release-orchestration.md:49` cross-ref; `3.1-Agents-Catalog-Build-Log.md:69` remainder list; `docs/AGENTS.md` one sentence in the grounded-context paragraph; this memo's status line.

**Must be checked but not changed**
- `utk_curio/backend/app/agents/node_context.py` and `services.py:7090-7106` — the **server-side** `nodeContext` for `node.content.generate` delegation children (dev/67-6). Same key, different path (runtime-supplied delegate inputs, composed from the saved spec + runtime journal). It is not affected by this memo; the memo only aligns **vocabulary** with it (`never-executed` spelled identically, see §5) so an agent that sees both never meets two dialects.
- `styles.tsx:206-229` — the widget's type-refinement logic. The summarizer must reproduce its `dataType → SupportedType` mapping *semantics* for the `declared:` comparison only if we choose to normalize; §3 recommends **not** normalizing (report the raw sandbox `dataType` string) to avoid a second copy of that mapping.
- Backend context bound (dev/44, 120k chars) — unchanged; our per-field caps sit far below it.

**Out of scope (explicitly)**
- Including output content / rows / schema. Column metadata arrives when the runtime journal captures it (dev/67-6 recorded follow-up); this memo leaves a documented seam, nothing more.
- Changing the `nodeContext` key set or the manifests. The five keys stay; the two strings become meaningful. No manifest churn, no prompt changes.
- Writing refined types back to `data.in/out` (fixing the widget's local-state-only refinement). Separate UI concern.
- The server-side composer (`node_context.py`) — see above.
- The `TrillNode` type gap for `in/out` — we read from the live node instead; the Trill stays the serialization concern it is.

## 3. Recommended Implementation Approach

**3.1 One summarizer module, pure and capped.** `nodeRuntimeSummary.ts`:

```ts
export const RUNTIME_SUMMARY_LIMITS = {
  errorChars: 240,      // error message tail shown to the agent
  mergeSlots: 8,        // slots enumerated before "… (+N more)"
  artifactIdChars: 64,  // path / dataset id is an identifier, never a payload
} as const;

export const NEVER_EXECUTED = "never-executed"; // dev/67-6 vocabulary, verbatim

export function summarizeNodeInput(data: LiveNodeData): string;
export function summarizeNodeOutput(data: LiveNodeData, storeOutput: unknown | undefined): string;
```

`LiveNodeData` is a narrow local type (`{ in?, out?, input?, output? }` with `unknown`-typed members) so the module tolerates whatever a live node carries. Every accessor is defensive (`typeof` guards); malformed values degrade to the honest fallback, never throw.

**3.2 Input summary** (`data.input`):
- `""` / `null` / `undefined` → `"no upstream input" + declared(data.in)`.
- object with `dataType` and/or `path`/`dataset` → `"<dataType|unknown type> from artifact <id>"` (id = `dataset ?? path`, truncated) `+ declared`.
- array (Merge Flow) → `"MULTIPLE (N slots): [0] <summary>; [1] <summary>; …"` capped at `mergeSlots`, empty slots as `"[i] empty"`. `declared` appended once.
- anything else → `"input present (unrecognized shape)" + declared`.

**3.3 Output summary** (`data.output` for status, `outputs` store for the artifact):
- `code === "success"` → `"success: <dataType|outputType|unknown type>"` + artifact id from `storeOutput` when present (`path`/`dataset`), `+ declared(data.out)`.
- `code === "error"` → `"error: " + truncate(String(content), errorChars)` `+ declared`. Error text is the one `content` we forward — it is short, human-authored by the runtime, and exactly what the Explainer/Evaluator need.
- `code === "exec"` → `"running"` `+ declared`.
- `code` empty/missing and no store output → `NEVER_EXECUTED + declared`.
- No `data.output` but the store has an artifact (post-load, widget state not yet rebuilt) → `"success (restored): <dataType> artifact <id>"` — truthful about provenance.

`declared(x)` renders `" (declared: X)"` when `x` is a non-empty string, else `""`. We report the sandbox `dataType` **raw** (`dataframe`, `geodataframe`, `int`, `outputs`…) rather than mapping it to `SupportedType`; the declared label sits next to it and the model can compare. This avoids duplicating `styles.tsx:210-229`.

**3.4 Composer wiring** (`agentRunContext.ts`): add `findLiveNode(canvas.nodes, nodeId)` (id match on the ReactFlow node), keep `findTrillNode` for `id/type/content` (unchanged bytes), and fill:

```ts
current_input:  live ? summarizeNodeInput(live.data) : "",
current_output: live ? summarizeNodeOutput(live.data, storeOutputFor(canvas.outputs, nodeId)) : "",
```

`storeOutputFor` is a two-line helper (`outputs?.find(o => o.nodeId === id)?.output`). Fragment order, labels, and the other four keys are byte-unchanged (pinned by the existing dev/44 parity tests, which must stay green untouched).

**3.5 Overlay**: `composeAgentRunContext(selected, { nodes, edges, workflowName, workflowGoal, outputs })` with `outputs` destructured from the already-present `useFlowContext()` call. `outputs` is optional on `AgentCanvasState` so the type stays backward-compatible for every other caller/test.

**Why not read `outputs` only, or `data.output` only?** The store knows the *artifact* (path/dataType) but not error text or "running"; `data.output` knows status and error text but its `content` is unbounded and it reaches `getNodes()` only via the `useNodeState.ts:28` mutation. Using each for what it is authoritative on gives a truthful summary and keeps the mutation as a status source only — if that mutation is ever removed, the store path still yields "success (restored)".

## 4. Data and State Handling

- **Sources of truth**: input → `node.data.input` (FlowProvider propagation); status/error → `node.data.output.code/content`; produced artifact → `FlowProvider.outputs`; declared types → `node.data.in/out`.
- **Derivation is pure and per send** — the dev/44 invariant holds: composed from live state at the moment of `onSend`, never stored, never replayed (`context` remains ephemeral server-side). No new React state, no effects, no subscriptions.
- **Loading / running**: a node mid-execution reports `running`; the user can still send (chat is non-modal, dev/108) and gets an honest snapshot.
- **Empty**: never-executed nodes say so in dev/67-6's word. Unconnected inputs say "no upstream input".
- **Error**: truncated message; never the stack of a huge blob.
- **After actions**: run → next send sees `success`/`error`; delete an edge → propagation clears `data.input` → next send says "no upstream input"; project reload → `hydrateRestoredOutputs` + `:1182` refill → "success (restored)" until the node re-runs.
- **No stale data by construction**; no flicker (nothing renders); no race (synchronous read of the current tree at click time — same as today's Trill composition).

## 5. UI and UX Requirements

No visible UI changes. The attachment card already exposes the manifest `reads` (dev/44) — unchanged. The **agent-facing** text is the UX here:

- Vocabulary fixed and reused: `never-executed` (dev/67-6, verbatim), `running`, `success`, `error`, `no upstream input`, `MULTIPLE (N slots)`, `(declared: TYPE)`.
- Every string is single-line, ASCII-safe, ≤ ~400 chars worst case (merge with 8 slots), so the JSON payload stays scannable in the transcript's context view if ever surfaced.
- Accessibility: n/a (no rendered element changes).

## 6. Edge Cases

- `data.input` is a **string path** (legacy shape) → `normalizeFlowInput` semantics: treat as `{ path }`, "unknown type from artifact <path>".
- Merge Flow with holes (`[ref, null, ref]`) → slots enumerated with `[1] empty`; length reported as N.
- Merge with > 8 slots → cap with `… (+N more)`.
- `data.output.content` is an object, not a string (some behaviors set structured content) → `String()` guarded; for `success` it is **never** included regardless of type.
- `data.output` exists but `code === ""` (fresh `useNodeState` default) and the store has nothing → `never-executed`.
- Store output present but `data.output.code === "error"` (re-run failed after an earlier success) → report `error: …` and append `last artifact: <id>` — the store is stale-by-design here and the agent should know both facts.
- Node deleted between `getNodes()` and compose → impossible (same synchronous tick); node id present in Trill but not in live nodes → cannot happen (Trill is generated from those nodes), but the code path degrades to `""` for both fields (today's behavior) rather than throwing.
- Non-node targets (canvas attachments declaring `nodeContext`) → unchanged: fragment omitted (`agentRunContext.test.ts:107-116` pins this).
- Artifact ids longer than 64 chars → truncated with `…`.
- `outputs` omitted by a caller (tests, future callers) → output summary still valid from `data.output` alone.

## 7. Testing Strategy

**Unit — `nodeRuntimeSummary.test.ts` (new, ~12 cases)**
- input: none / typed ref / path-only string / merge 3 slots with a hole / merge 10 slots capped / malformed (number) → each exact expected string, `declared:` appended when `data.in` present, absent otherwise.
- output: never-executed / running / success with store artifact / success without store (widget only) / error truncated at 240 chars / restored (store only) / error-after-success carries `last artifact`.
- caps are asserted against the exported constants, not literals.

**Composer — `agentRunContext.test.ts` (tighten + add)**
- Replace `toHaveProperty("current_input")` with exact-value assertions on an executed fixture node (`data.input`, `data.output`, `outputs`).
- Add: never-executed node → both fields carry the honest fallbacks (not `""`).
- Add: `outputs` omitted → still composes.
- Keep every existing dev/44 byte-parity test **unchanged** — they are the regression guard that the other keys and the Node Content Builder framing did not move.

**Overlay — `AgentDockOverlay.test.tsx` (dev/108's file)**
- One assertion: `onSend` composes with `outputs` from the flow context (mock context returns one output; the sent context string contains its `dataType`).

**Regression gate**: full frontend `npx jest` green (conda env `curio-feat` for node). Backend untouched → no backend run required, but `pytest tests/test_agents -k context` is cheap insurance that the server bound tests still pass with realistic payloads.

## 8. Acceptance Criteria

1. Sending to a Node Explainer attached to a node that ran successfully produces a `nodeContext` payload whose `current_output` starts with `success:` and names the sandbox `dataType` and artifact id, and whose `current_input` names the upstream `dataType`/artifact or says `no upstream input`.
2. For a node that never ran, `current_output` is `never-executed` (plus `(declared: X)` when a type is set) — not `""`.
3. For a node whose last run errored, `current_output` is `error: <message>` truncated to 240 chars; no success content is ever forwarded.
4. Merge Flow nodes report `MULTIPLE (N slots)` with per-slot summaries, capped at 8.
5. The other `nodeContext` keys (`id`, `type`, `content`) and every other read fragment are byte-identical to today (existing parity tests pass unmodified).
6. Canvas-targeted attachments still omit the `nodeContext` fragment.
7. No new React state, effect, or subscription; the overlay change is a single added property.
8. `nodeRuntimeSummary.ts` has no imports from React, providers, or the API layer.
9. `BL-P2-runtime-providers.md:196` no longer claims legacy passed execution values or that the exec store was missing; it records the closure and this memo.
10. Full frontend jest green.

## 9. Recommended Commit Breakdown

- **Commit 1 — summarizer + tests.** `nodeRuntimeSummary.ts` with constants, `NEVER_EXECUTED`, both functions; `nodeRuntimeSummary.test.ts`. No behavior change yet.
- **Commit 2 — composer + overlay wiring + tightened tests.** `AgentCanvasState.outputs?`, `findLiveNode`, the `nodeContext` case; `AgentDockOverlay.tsx` passes `outputs`; `agentRunContext.test.ts` real-value assertions; overlay test addition.
- **Commit 3 — docs.** BL-P2 entry 10 follow-up rewrite + closing BL entry (number checked on disk), BL-P5:49 cross-ref, build-log remainder list, `docs/AGENTS.md` sentence, memo status → IMPLEMENTED with hashes.

Multi-session protocol applies: `git status` before every add; pathspec commits (`git commit -- <paths>`); `git diff --cached -- <file>` before touching any file another session has staged.

## 10. Engineering Quality Checklist

- [ ] No duplicated mapping logic: the `dataType → SupportedType` table in `styles.tsx` is **not** copied; raw types are reported beside the declared label.
- [ ] Shared logic centralized in one pure module with exported caps.
- [ ] Types explicit; all live-node accessors guarded against `unknown`.
- [ ] Composer function stays a pure `(attachment, canvas) → string | null`.
- [ ] No new state; no race (synchronous snapshot at send).
- [ ] Byte-parity of every untouched fragment proven by existing tests.
- [ ] Never-executed / running / error / restored states each have a truthful string and a test.
- [ ] Vocabulary aligned with the server-side composer (`never-executed`).
- [ ] Payload bounded by named constants; output content never forwarded.
- [ ] Backlog premise corrected in the same change that closes it.
