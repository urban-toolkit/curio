# Implementation Memo: Built-in Preamble Assets + Proper Inputs (Migration Parity Fix)

Date: 2026-07-27
Status: **implemented** (same-session; amendment on `BL-P5-20260719-01`)

## 1. Problem Statement

The 13 migrated built-ins' generated manifests were incomplete against the canonical roster (`dev/05` §"Required roster and contracts") in two ways, both flagged by review:

1. **No system preamble asset.** The roster's "System file" column assigns `default_preamble.txt` to every agent (the syntax agent gets `syntax_analysis_preamble.txt`), and **every legacy call site composed `llmRequest("default_preamble", "<prompt>", …)`** — so `dev/06`'s parity rule ("the same prompt/preamble composition") was violated: the migrated runtime sent the instruction alone as the system turn, dropping the ~18 KB Curio preamble the legacy paths always included.
2. **No `inputs`.** The manifests omitted `inputs.reads` entirely; the contract parses it and the docs example shows it.

## 2. As-Built Fix

- `BuiltinAgentSpec` gains `preamble_file` (default `default_preamble.txt`; syntax overrides) and `reads`; `build_builtin_manifest` emits `prompts.system` and `inputs.reads`.
- **`reads` grounded per agent in what its legacy call site actually passed** (not invented): e.g. chat → `userMessage`; debug/dataflow-explainer → `dataflowContext` (both send the Trill spec); node-explainer → `nodeContext`; connection-builder → `workflowGoal, nodeId, subtask, connectionSide, dataflowContext`; task-refresh → `currentTask, keywords, dataflowContext`; etc.
- Materialization (`_materialize_builtin`) writes **both** assets into the user store; `read_prompt_text(coord, name)` generalizes the roster reader.
- Runtime parity: `_prepare_run` composes the system turn as `preamble + "\n\n" + (intent or instruction)` via the store-first `_resolve_prompt_text` — an edited intent replaces the **instruction portion only**, so the preamble still applies; a definition that resolves no system asset (e.g. an upload without one) runs instruction-only as before.

## 3. Verification

New `TestPreambleAndInputs` (all 13 manifests declare the system asset + non-empty reads; the syntax override; every preamble readable from `llm-prompts/`) and `TestMaterializePreamble` (install writes both files); the two run-path tests updated to assert the composed system turn. Agents suite 245 passed; full backend 744+ green. The `dev/36` example package (which ships its own preamble) composes correctly through the same path.

## 4. Traceability

- Amends `BL-P5-20260719-01` (the roster) and the `BL-P4-…-02` run contract; `dev/05` roster table + `dev/06` parity rule are the sources; `RISK-PROMPT-002` (composition divergence) addressed.
