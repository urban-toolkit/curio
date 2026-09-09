# Implementation Memo: Fix autk-grammar node content lost/collapsed on dataflow load→save round-trip

**Status:** Proposed (memo only — no code written) · **Branch:** `datacatalog` · **Author:** Karla
**Area:** `hook/useCode.ts` (load), `hook/useNodeState.ts` (per-node code state), `TrillGenerator.ts` (save), `components/UniversalNode.tsx` + `adapters/node/autkGrammarBehavior.tsx` + `components/editing/GrammarEditor.tsx` (autk grammar editor), + tests

---

## 1. Problem Statement

**Current behavior.** When a dataflow is loaded/duplicated from another project and then saved,
each `curio.builtin/autk-grammar` node can lose its own grammar: the saved spec ends up with
**every autk-grammar node holding the same `content`** (and/or empty/stale content) instead of
each node's distinct grammar. The dataflow then can't regenerate its computed datasets, because
the compute/map nodes no longer carry their compute/map grammar.

**Evidence (on disk).** Two "Autark what-if" projects loaded from a working twin are corrupted —
all five autk-grammar nodes have **byte-identical `content`** (the data-loading grammar; md5
`a3eb617a`), e.g. project `6df85d49-8cfc-4a14-9914-3507fc79afb7` and `2f84bb64…`. The three
original (un-duplicated) projects are clean: each node has a distinct `content` (one data-loading
grammar, two ~4.5 KB compute grammars, two map grammars). Because computed dataset ids are stable
(`computed.whatif-*`), the project shows only the **already-published hub copies** of those ids,
so a run appears to "generate nothing."

**Root cause (verified design flaw).** Autk-grammar node grammar is round-tripped through **two
different fields that diverge**:

- **Load** writes the spec node's `content` into **`data.defaultCode`** only —
  `useCode.ts:133` (`code: node.content`) → `generateCodeNode` sets `data.defaultCode = code`
  (`useCode.ts:282`); it never sets `data.code`.
- **Per-node state** is keyed on **`data.code`** — `useNodeState.ts:16`
  (`useState(data.code ?? '')`) and `:26` (`useEffect(() => { data.code = code; }, [code])`). On a
  freshly-loaded node `data.code` is `undefined`, so the state initializes to `''` and the effect
  writes **`data.code = ''`**, while the real grammar still lives only in `data.defaultCode`.
- **Save** serializes from **`data.code`** — `TrillGenerator.ts:176-177`
  (`if (node.data.code != undefined) trill_node.content = node.data.code`). So a node that was
  loaded but whose editor state didn't repopulate `data.code` with its own grammar serializes the
  wrong/empty/stale value.
- **Display** reads yet another precedence — `UniversalNode.tsx:137-140`
  (`behavior.defaultValueOverride ?? data.defaultCode ?? templateData.code`), and the autk editor's
  grammar is seeded from `defaultValue` (= `data.defaultCode`) via `GrammarEditor.tsx:46-52`, then
  floated back through `floatCode={nodeState.setCode}` (`UniversalNode.tsx:251`,
  `GrammarEditor.tsx:107-109`) into `data.code`.

So **display/load use `defaultCode`; save uses `code`.** Any load→save where `data.code` isn't
correctly repopulated per node (a node not re-rendered/edited, or a shared/misaligned editor
seed) drops or replaces that node's grammar. The duplicate-from-working-project flow hits exactly
this round-trip.

> **Note on the exact collapse-to-one-value step.** That all five nodes end up with the *same
> non-empty* grammar (rather than empty) is a secondary effect of this divergence (e.g. the
> editor's `defaultValue` seed or `floatCode` write not being isolated per node during the
> duplicate). The precise trigger should be **captured by an in-app reproduction** (see §7) — but
> the fix below removes the class of bug regardless of the exact trigger, because it makes the
> round-trip lossless and per-node by construction.

**Expected behavior.** Loading/duplicating a dataflow and saving it preserves **each** node's own
`content` exactly. An autk-grammar node that was never re-opened still serializes its own grammar.
A round-trip (load → save → load) is lossless and per-node stable.

**Why it matters.** Silent grammar loss corrupts projects (compute/map nodes become data-loading
clones), makes dataflows non-functional, and is invisible until the user notices no datasets are
generated. It also threatens any duplicated/template dataflow, not just this one.

---

## 2. Scope

**In scope**
- Make the grammar/code round-trip use a **single source of truth per node** so load, display,
  edit, and save can't diverge:
  - `TrillGenerator.ts:176-177` — serialize from the authoritative grammar field (fall back to
    `data.defaultCode` when `data.code` is unset/empty), so a not-re-edited node still saves its
    own grammar.
  - `useCode.ts` `generateCodeNode` (`:274-318`) and/or `useNodeState.ts:16,26` — initialize
    `data.code` from `data.defaultCode` on load so the save field is populated per node.
  - Confirm `GrammarEditor` seeds `defaultValue` and floats `floatCode` strictly per node id
    (no shared seed/ref across autk nodes).
- A **round-trip regression test** (load multi-autk-node spec → save → assert each node's content
  is preserved and distinct), plus an in-app reproduction of the duplicate/load that triggered it.

**Out of scope / must not regress**
- Python/JS code nodes (CodeEditor path) — they use the same `code`/`defaultCode` plumbing; the
  fix must preserve their behavior (verify with a round-trip test).
- Dataset-generation / auto-install pipeline — proven correct by the working projects; **not** the
  cause here. (Recommend reverting the earlier `auto_install.py`/`routes.py` JSON-parity +
  diagnostics changes and the `computed-dataset-execution-persistence.md` plan, which targeted the
  wrong cause.)
- Repairing the already-corrupted projects (`6df85d49`, `2f84bb64`) — their grammar is already gone
  from disk and must be restored separately (re-author, or adapt the Back Bay compute/map grammars
  to Chicago). Tracked as a follow-up, not part of this code fix.
- Collaboration/proposal flow in `GrammarEditor` (only touch if it shares state across nodes).

---

## 3. Recommended Implementation Approach

**Principle: one authoritative per-node grammar field, lossless on every round-trip.**

1. **Save defensively (smallest, highest-leverage change).** In `TrillGenerator.ts:176-177`,
   serialize `trill_node.content` from `node.data.code` **falling back to `node.data.defaultCode`**
   when `code` is `undefined`/empty:
   - prevents a loaded-but-not-re-edited node from saving empty/stale content;
   - is per-node (reads each node's own `data`), so it can't collapse to a shared value.
2. **Populate the save field on load.** In `generateCodeNode` (`useCode.ts`), set `data.code = code`
   alongside `data.defaultCode = code` (or have `useNodeState.ts:16` initialize from
   `data.code ?? data.defaultCode ?? ''`). This keeps the load→edit→save fields aligned so the two
   never diverge again.
3. **Verify editor isolation.** Confirm `GrammarEditor` (`autkGrammarBehavior.tsx` →
   `UniversalNode.tsx:251` `floatCode={nodeState.setCode}`) seeds `defaultValue` from *this* node's
   `data.defaultCode` and floats back to *this* node's state only — no module-level/shared ref or
   `defaultValue` seed shared across autk nodes. Fix any shared seed found during the repro.
4. **Single source of truth (preferred end state).** Consolidate on one field for node grammar
   (`defaultCode`) for load/display/save, with `useNodeState`'s `code` as the live editor mirror
   that always writes back to it. This removes the `code` vs `defaultCode` ambiguity that caused
   the bug.

Keep the change minimal and behavior-preserving for code nodes; the defensive save (step 1) +
load population (step 2) together make the round-trip lossless with the least risk.

---

## 4. Data and State Handling

- **Source of truth:** each node's own grammar string, stored per node and serialized per node.
  Load (`content` → node), display (editor `defaultValue`), edit (`floatCode` → state), and save
  (`content`) must all reference the *same* per-node field.
- **Load:** populate both the display field (`defaultCode`) and the save field (`code`) from
  `node.content` so a node never has a populated display but an empty save field.
- **Edit:** `nodeState.setCode` continues to write the live grammar to the node's `data.code`
  (per node); the editor seed is the node's own `defaultCode`.
- **Save:** read per-node grammar (`code ?? defaultCode`); never read a shared/global value.
- **Avoid divergence/races:** the bug is a divergence between two fields plus a not-yet-rendered
  node; the fix removes the divergence so render timing no longer affects what is saved.

---

## 5. UI and UX Requirements

- After duplicate/load + save + reload, each autk-grammar node shows and retains **its own**
  grammar (data node = data-loading grammar, compute nodes = compute grammar, map nodes = map
  grammar).
- No visible change for code (Python/JS) nodes.
- No silent grammar replacement; a node never adopts another node's content.

---

## 6. Edge Cases

- **Node never opened/rendered after load** (editor effect didn't run) → still serializes its own
  grammar (save falls back to `defaultCode`).
- **Empty/`"{}"` grammar** → distinguish "genuinely empty" from "not yet populated"; don't
  overwrite a real grammar with the editor's initial `"{}"` seed (`GrammarEditor.tsx:31`).
- **Duplicate of a duplicate** (round-trip applied twice) → remains lossless and per-node.
- **Code (Python/JS) nodes** → unchanged; covered by the round-trip test.
- **Collaboration remote apply** (`GrammarEditor` proposal flow) → writes to the correct node id
  only.
- **Already-corrupted projects** → not auto-repaired by this fix (grammar already lost on disk);
  handled separately.
- **Templates / "load example"** → same round-trip guarantees apply.

---

## 7. Testing Strategy

**Reproduction first (to capture the exact trigger).** In the app, duplicate/load a multi-autk-node
dataflow and save; capture the step where node contents collapse (watch `data.code` vs
`data.defaultCode` per node, and the `floatCode`/`defaultValue` seeding). Encode it as a test.

**Unit / integration (Jest)**
- `TrillGenerator`: given nodes with distinct `data.defaultCode` and unset `data.code`, the saved
  spec has each node's distinct `content` (not empty, not shared) — the core regression.
- Round-trip: parse a spec with 5 autk nodes (distinct content) → build nodes (`loadTrill`) →
  serialize (`generateTrill`) → assert each node's `content` is byte-preserved and distinct.
- `useNodeState`/`generateCodeNode`: a loaded node exposes its own grammar in the field `save`
  reads (`code`), seeded from `defaultCode`.
- Code-node regression: a Python/JS node round-trips its `code` unchanged.

**Component**
- `GrammarEditor` floats edits to the correct node id only; two autk editors don't cross-write.

**Regression**
- The duplicate-from-working-project scenario produces 5 distinct node contents after save.

---

## 8. Acceptance Criteria

1. Loading/duplicating a dataflow and saving preserves **each** autk-grammar node's own `content`;
   no two nodes collapse to the same grammar (unless they genuinely were identical).
2. A node not re-opened after load still serializes its own grammar (save falls back to
   `defaultCode`).
3. Load → save → load is lossless for autk-grammar **and** code (Python/JS) nodes.
4. A round-trip regression test fails on today's code and passes after the fix.
5. No regression to code-node editing/saving or to dataset generation.

---

## 9. Recommended Commit Breakdown

1. **Defensive save + load population.** `TrillGenerator` serializes `code ?? defaultCode`;
   `generateCodeNode`/`useNodeState` populate `data.code` from `defaultCode` on load. Add the
   `TrillGenerator` + round-trip unit tests (red→green).
2. **Editor isolation fix** (only if the repro shows a shared seed/ref): ensure `GrammarEditor`
   `defaultValue`/`floatCode` are strictly per node; component test.
3. **Consolidate to a single grammar field** (optional hardening): collapse `code`/`defaultCode`
   ambiguity to one source of truth; broaden round-trip tests.
4. **Follow-ups (separate):** repair the corrupted `6df85d49`/`2f84bb64` projects; revert the
   earlier wrong-cause `auto_install`/`routes`/plan changes.

---

## 10. Engineering Quality Checklist

- [ ] Save reads a per-node grammar field; never a shared/global value.
- [ ] Load populates the field `save` reads, so display and save can't diverge.
- [ ] Round-trip (load→save→load) lossless for autk-grammar and code nodes.
- [ ] Editor seed/write-back isolated per node id.
- [ ] Regression test reproduces the collapse on current code and passes after the fix.
- [ ] No change to code-node behavior or to the dataset pipeline.
- [ ] "Genuinely empty" vs "not yet populated" grammar disambiguated (no `"{}"` overwrite).
- [ ] Corrupted-project repair and earlier wrong-cause reverts tracked as explicit follow-ups.
