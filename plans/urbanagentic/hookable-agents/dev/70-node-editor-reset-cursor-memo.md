# dev/70 — Node editor content reset (Autark) + cursor-to-end (Python) — Implementation Memo

Status: IMPLEMENTED (2026-08-11, unstaged) — all four fix layers landed with tests
(shared hook `useMonacoExternalValue`, uncontrolled editors, mount-frozen autk
seed yielding to `data.defaultCode`, idempotent exec-status marks). Full frontend
suite green (71 suites / 770 tests). Manual in-app typing verification pending.

## 1. Problem Statement

Two related editing bugs on the canvas dataflow page, both rooted in how node
editors synchronize Monaco content with React state.

**Bug A — Autark (autk-grammar) node resets to the default spec while editing.**
On a freshly palette-dropped Autark node, typing in the grammar editor loses the
user's edits every couple of keystrokes: the whole editor content snaps back to
the built-in `DEFAULT_SPEC` (the Chicago Loop OSM example).

Root cause (deterministic, confirmed by code trace):

- `useAutkGrammarBehavior` recomputes its editor seed on **every render**:
  `hasExistingCode = !!(data.defaultCode || data.code)` and
  `defaultValueOverride = hasExistingCode ? undefined : getDefaultSpec()`
  (`adapters/node/autkGrammarBehavior.tsx:526-534`).
- `data.code` is a **mutable field written one commit late**: the editor floats
  each keystroke via `floatCode` → `nodeState.setCode`, and `useNodeState`
  copies it into `data.code` in a post-commit effect (`hook/useNodeState.ts:26`).
  During the render triggered by keystroke *N*, `data.code` still holds
  keystroke *N−1*'s value.
- `UniversalNode` computes
  `defaultValue = behavior.defaultValueOverride ?? data.defaultCode ?? nodeState.templateData.code`
  (`components/UniversalNode.tsx:144-147`). For a palette-dropped node,
  `data.defaultCode` and `templateData.code` are both `undefined`
  (`hook/useCode.ts:282-287`, `components/MainCanvas.tsx:349`).
- Any change of `defaultValue` re-fires the reload chain:
  `NodeEditor` `useEffect([defaultValue]) → setDefaultCode`
  (`editing/NodeEditor.tsx:132-134`) → `GrammarEditor`
  `useEffect([defaultValue]) → setGrammar(defaultValue)`
  (`editing/GrammarEditor.tsx:46-52`), which unconditionally replaces the
  editor content.
- `GrammarEditor` also floats **whatever** its state becomes — including
  `undefined` — back into `nodeState.code` (`editing/GrammarEditor.tsx:107-109`),
  which later clears `data.code`.

The resulting cycle on a fresh Autark node:

1. Keystroke 1 (`t1`): `setGrammar(t1)`, float → `setCode(t1)`. During that
   render `data.code` is still `""` → `hasExistingCode` false → override stays
   `DEFAULT_SPEC`. After commit, `data.code = t1`.
2. Keystroke 2 (`t2`): render now sees `data.code = t1` → `hasExistingCode`
   flips **true** → override becomes `undefined` → `defaultValue` becomes
   `undefined` → GrammarEditor's effect runs `setGrammar(undefined)` →
   `floatCode(undefined)` → after commit `data.code = undefined`.
3. Keystroke 3 (`t3`): render sees `data.code = undefined` → `hasExistingCode`
   flips **false** again → `defaultValue` flips back to `DEFAULT_SPEC` → the
   effect chain calls `setGrammar(DEFAULT_SPEC)` → Monaco receives a `value`
   that differs from the model → full-content replace. **User edits are gone;
   content is back to the default spec; cursor lands at the end.**
4. The float of `DEFAULT_SPEC` re-seeds `data.code` and the cycle repeats.

Nodes loaded from a saved dataflow have a string `data.defaultCode`, so
`hasExistingCode` is stably true and they don't reset — which is why the bug
reads as "the Autark editor never accepts modifications" on new nodes
specifically.

**Bug B — Python code editor cursor jumps to the end while typing.**
Both editors are *fully controlled* Monaco instances
(`value={code}` at `editing/CodeEditor.tsx:363`, `value={grammar}` at
`editing/GrammarEditor.tsx:176`). `@monaco-editor/react` (v4.7) applies any
`value` prop that differs from the current model as a **full-model-range
`executeEdits`**, which leaves the cursor at the end of the document.

Every keystroke round-trips model → `onChange` → `setCode` → re-render →
`value` prop. If the user types again before the previous round-trip commits,
the render lands with a *stale* `value`, Monaco does a full replace, the last
character(s) are dropped, and the cursor jumps to the end. The race window is
wide in practice because every keystroke also calls `markNodeStale`
(`editing/CodeEditor.tsx:78`), which updates `nodeExecStatus`
(`hook/useWorkflowOperations.ts:1016-1018`) even when the node is already
stale; `FlowContext`'s provider value is an inline object literal
(`providers/FlowProvider.tsx:1612+`), so **every context consumer on the
canvas re-renders on every keystroke**, making the round-trip slow enough to
lose the race consistently.

Why it matters: the Autark node is effectively uneditable when created from
the palette; the Python editor corrupts input under normal typing speed. Both
are core authoring surfaces of the dataflow canvas.

## 2. Scope

Included:

- `src/components/editing/CodeEditor.tsx` — controlled-value handling,
  `defaultValue` reload effect, `markNodeStale` call per keystroke.
- `src/components/editing/GrammarEditor.tsx` — same, plus the
  `floatCode(undefined)` leak.
- `src/components/editing/NodeEditor.tsx` — `defaultValue → defaultCode`
  forwarding (verify only; likely unchanged).
- `src/adapters/node/autkGrammarBehavior.tsx` — per-render
  `defaultValueOverride` recomputation.
- `src/hook/useWorkflowOperations.ts` — idempotence guard in
  `markNodeStale` / `markNodeExecuted`.
- New shared hook (e.g. `src/hook/useMonacoExternalValue.ts`) centralizing the
  "external content update" contract for both editors.
- Tests under `src/tests/` for the hook, both editors, and the autk behavior.

Must be checked but not changed unless required:

- `src/components/UniversalNode.tsx` `defaultValue` chain (works correctly once
  the override stops flip-flopping).
- External writers of editor content, which must keep working: dataset
  drag-and-drop (`components/styles.tsx:549-552`), LLM "generate content"
  (`components/styles.tsx:503`), provenance navigation
  (`editing/NodeEditor.tsx:136-139` `navigateProv`), collaboration
  `code_change_applied` handlers in both editors.
- `useNodeState`'s `data.code = code` mutation (the Trill serializer reads it;
  keep, but it must never feed back into editor content).

Out of scope:

- Splitting/memoizing the whole `FlowContext` value (worthwhile perf follow-up,
  not needed for correctness here).
- Collaboration proposal semantics (blur-diff proposals stay as they are).
- WidgetsEditor marker resolution and the execution pipeline.

## 3. Recommended Implementation Approach

Fix the root causes in three layers, smallest-first:

**3a. Freeze the Autark default-spec decision at mount**
(`autkGrammarBehavior.tsx`). The default spec is a *seed for an empty node*,
not a render-time derivation. Capture it once:
`const seededDefault = useRef(!!(data.defaultCode || data.code) ? undefined : getDefaultSpec()).current`
and return that stable value as `defaultValueOverride`. It must never flip
after mount. (Alternative considered — writing `data.defaultCode` at node
creation for autk nodes — rejected: it special-cases one node type in generic
creation code and changes saved-dataflow serialization.)

**3b. Centralize the "external content update" contract in one shared hook**
used by both `CodeEditor` and `GrammarEditor` (they currently duplicate this
logic with slightly different bugs). The hook owns:

- a `baselineRef` (the as-loaded / last-externally-applied content — the same
  baseline the collab blur-diff already needs);
- the rule for applying an incoming `defaultValue`: apply **only when it is a
  defined string AND differs from the baseline** (a genuine external update:
  dataset drop, LLM apply, provenance navigation). A `defaultValue` that merely
  became `undefined` or reverted to a stale value must never clobber the
  editor;
- imperative application to Monaco via the editor instance with **cursor
  preservation**: save `editor.getPosition()`, apply the edit
  (`model.pushEditOperations` / `executeEdits` over the full range), restore
  the position clamped to the new content. Update the baseline on apply.

**3c. Decouple typing from the controlled-`value` round trip.** Keep Monaco as
the source of truth while the user types: pass the initial content via
Monaco's own `defaultValue` (uncontrolled), keep the latest text in a ref
(plus the existing React state where execution/collab needs it), and stop
passing a per-keystroke `value` prop back into `<Editor>`. External updates go
through the imperative channel from 3b, including the collab
`code_change_applied` path (currently `setCode`/`setGrammar`, which would no
longer reach the editor once `value` is removed). This eliminates the
stale-write race — and therefore the cursor jump — by construction rather than
by timing.

**3d. Make `markNodeStale` idempotent** (`useWorkflowOperations.ts`): return
`prev` unchanged when `prev[nodeId]` is already `"stale"` (same for
`markNodeExecuted`). This removes the per-keystroke canvas-wide re-render
storm. It is a performance amplifier fix, independent of correctness.

Also fix the `floatCode(undefined)` leak: GrammarEditor must only float string
content, and with 3a+3b the `setGrammar(undefined)` path disappears entirely.

## 4. Data and State Handling

- **Source of truth while typing:** the Monaco model. React mirrors it (ref +
  state) for execution, collab diffing, and `floatCode` — never the reverse.
- **`defaultValue` (prop):** initial seed + explicit external updates only.
  Derived in `UniversalNode` from `defaultValueOverride ?? data.defaultCode ??
  templateData.code`; after 3a this chain is stable across renders unless an
  external writer calls `updateDefaultCode` (which creates a new node `data`
  with the new string — exactly the "genuine external update" case 3b applies).
- **`nodeState.code` / `data.code`:** continue to receive every keystroke via
  `floatCode` (the serializer and Play flow read them), but strings only.
- **Baseline:** updated when content is loaded, when an external update is
  applied, and when a collab proposal is acknowledged — preserving current
  collab blur-diff behavior.
- No loading/error state changes; execution output handling is untouched.
- Race safety: with the editor uncontrolled during typing, there is no window
  in which a slow render can rewrite the model; external updates are applied
  in an effect that compares against the baseline, so repeated renders with
  the same `defaultValue` are no-ops.

## 5. UI and UX Requirements

- Typing in any node editor (Python, JS, grammar/Autark) behaves like a normal
  code editor: no content replacement, no cursor relocation, no dropped
  characters, no visible flicker.
- A fresh Autark node still opens pre-filled with the default OSM spec.
- Dataset drag-and-drop onto a node still replaces the code visibly and
  immediately (it is an explicit user action; replacing a dirty editor is the
  intended behavior, unchanged).
- LLM "Apply task" content generation and provenance version navigation still
  load content into the editor, with the cursor placed sensibly (start or
  preserved-clamped position — not silently at the end of the document).
- Collab: remote-applied changes still appear for peers; the proposer's editor
  is not disturbed. Read-only (`readOnly`) nodes remain non-editable.
- No accessibility regressions: Monaco keyboard behavior, focus, and the
  existing blur-based collab proposal flow stay intact.

## 6. Edge Cases

- Fresh palette node (both `defaultCode` and `code` undefined) — Bug A's case.
- Node loaded from a saved dataflow (string `defaultCode`).
- `defaultValue` transitioning string → undefined → string (must never reset).
- External update arriving while the editor is dirty *and focused* (dataset
  drop, LLM apply): applied, baseline updated, cursor clamped.
- External update string-equal to current content: no-op (no cursor movement).
- Fast typing / IME composition: no interleaved programmatic writes.
- `floatCode` receiving non-string values: guarded, never floated.
- Node deleted or unmounted mid-typing; editor remount after tab switch
  (NodeEditor tabs keep panes mounted — verify no re-seed on tab return).
- `markNodeStale` called repeatedly (every keystroke): state object identity
  unchanged after the first call → no context churn.
- Collab disabled (default): baseline logic still correct since load/apply
  paths maintain it.
- Undo/redo: Ctrl+Z history must survive external applies via
  `pushEditOperations` (undo stop before/after), and must not be wiped by the
  removal of per-keystroke `value` writes.

## 7. Testing Strategy

Follow the existing test layout (`src/tests/…`, jest + RTL; Monaco is mocked —
extend the mock to expose `getPosition`/`setPosition`/`executeEdits` spies as
needed).

- **Unit — shared hook:** applies a defined, baseline-differing value;
  ignores `undefined`; ignores baseline-equal values; updates baseline on
  apply; restores/clamps cursor.
- **Unit — `useWorkflowOperations`:** `markNodeStale` returns the same state
  object when already stale (regression for the re-render storm).
- **Component — `GrammarEditor`/`CodeEditor`:** typing sequence with
  `defaultValue` flipping string → undefined → string keeps the typed content
  (direct regression for Bug A); external `defaultValue` change replaces
  content; `floatCode` never called with `undefined`; collab
  `code_change_applied` still updates content and baseline.
- **Behavior — `useAutkGrammarBehavior`:** `defaultValueOverride` is stable
  across re-renders after `data.code` mutates (regression for the flip-flop);
  existing behaviors.test.tsx suite stays green.
- **Integration:** dataset-drop flow (`applyDatasetToNodeData` →
  `updateDefaultCode` → editor shows new code) and provenance `navigateProv`
  still load content.
- Manual verification on the running app (fresh Autark node + Python node,
  sustained typing) before considering the change complete, since the cursor
  race is timing-dependent and jsdom can't reproduce it.

## 8. Acceptance Criteria

1. On a freshly created Autark node, typing 20+ characters (including pauses)
   never resets the editor to the default spec; the edited grammar runs when
   Play is pressed.
2. In the Python (and JS) code editor, sustained fast typing never moves the
   cursor to the end of the document and never drops characters.
3. A fresh Autark node still opens pre-populated with the default OSM spec;
   saved dataflows still load their stored code into every editor.
4. Dataset drag-and-drop, LLM "Apply task", and provenance navigation still
   replace editor content, and afterwards further typing behaves normally.
5. Collab code/grammar proposals still fire on blur with the correct baseline
   diff, and remote-applied changes still render for peers.
6. `nodeExecStatus` no longer changes identity on keystrokes after the first
   stale mark (verifiable via React devtools/profiler or the unit test).
7. All existing editor/behavior test suites pass; the new regression tests
   from §7 pass.

## 9. Recommended Commit Breakdown

1. **Commit 1:** `markNodeStale`/`markNodeExecuted` idempotence guard + unit
   test (isolated, independently revertable perf fix).
2. **Commit 2:** Add the shared external-value hook with unit tests; adopt it
   in `GrammarEditor` (including the `floatCode(undefined)` guard) and
   `CodeEditor`; move both editors off per-keystroke controlled `value`;
   route collab applies through the imperative channel.
3. **Commit 3:** Stabilize `defaultValueOverride` in `useAutkGrammarBehavior`
   (mount-frozen seed) + behavior regression test.
4. **Commit 4:** Integration/regression tests for dataset-drop, provenance
   navigation, and the string→undefined→string `defaultValue` sequence;
   cleanup of any now-dead code paths.

(Per repo convention: leave changes unstaged; no auto-push.)

## 10. Engineering Quality Checklist

- [ ] Reload/baseline logic exists once (shared hook), not duplicated per editor.
- [ ] No render-derived values from mutable `data.*` fields feed editor content.
- [ ] `floatCode`/`sendCodeToWidgets` receive strings only; types tightened
      where currently `any` allows the `undefined` leak.
- [ ] Editors never rewrite the Monaco model except for genuine external
      updates, and always preserve/clamp the cursor when they do.
- [ ] Keystrokes cause no canvas-wide context re-render.
- [ ] Loading (seed), external-replace, collab, and read-only states verified
      on both editor kinds.
- [ ] Regression tests cover Bug A's exact flip-flop sequence and Bug B's
      stale-value write.
- [ ] Existing conventions followed (hooks in `src/hook/`, tests mirrored under
      `src/tests/`, comment style matched).
