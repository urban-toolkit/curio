# Implementation Memo: Built-in Preamble Assets + Proper Inputs (Migration Parity Fix)

Date: 2026-07-27
Status: **implemented** (same-session; amendment on `BL-P5-20260719-01`)

## 1. Problem Statement

The 13 migrated built-ins' generated manifests were incomplete against the canonical roster (`dev/05` §"Required roster and contracts") in two ways, both flagged by review:

1. **No system preamble asset.** The roster's "System file" column assigns `default_preamble.txt` to every agent (the syntax agent gets `syntax_analysis_preamble.txt`), and **every legacy call site composed `llmRequest("default_preamble", "<prompt>", …)`** — so `dev/06`'s parity rule ("the same prompt/preamble composition") was violated: the migrated runtime sent the instruction alone as the system turn, dropping the ~18 KB Curio preamble the legacy paths always included.
2. **No `inputs`.** The manifests omitted `inputs.reads` entirely; the contract parses it and the docs example shows it.

## 2. As-Built Fix

- `BuiltinAgentSpec` gains `preamble_file` (default `default_preamble.txt`; syntax overrides) and `reads`; `build_builtin_manifest` emits `prompts.system` and `inputs.reads`.
- **`reads` grounded per agent in what its legacy call site actually passed** (not invented). The complete mapping:

| Agent | Preamble asset | `inputs.reads` | Grounded in (legacy call site) |
| --- | --- | --- | --- |
| `agent.chat-agent` | `default_preamble.txt` | `userMessage` | `LLMChat.tsx:33` — the user's chat input |
| `agent.debug-agent` | `default_preamble.txt` | `dataflowContext` | `MainCanvas.tsx:252` — the selected components' Trill spec |
| `agent.dataflow-explainer` | `default_preamble.txt` | `dataflowContext` | `MainCanvas.tsx:223` — the selected components' Trill spec |
| `agent.node-explainer` | `default_preamble.txt` | `nodeContext` | `NodeExplanation.tsx:38` — `{type, content, current_input, current_output}` |
| `agent.node-content-builder` | `default_preamble.txt` | `dataflowContext`, `nodeId`, `subtask`, `workflowGoal` | `styles.tsx:493` — Trill + node id + subtask + task |
| `agent.execution-subtask-planner` | `default_preamble.txt` | `nodeContent`, `nodeType`, `currentTask` | `styles.tsx:370` — node content + node type + task |
| `agent.dataflow-task-planner` | `default_preamble.txt` | `currentTask`, `dataflowContext` | `WorkflowGoal.tsx:246` — current task + Trill |
| `agent.connection-builder` | `default_preamble.txt` | `workflowGoal`, `nodeId`, `subtask`, `connectionSide`, `dataflowContext` | `styles.tsx:441` — task + node id + subtask + in/out side + Trill |
| `agent.workflow-suggester` | `default_preamble.txt` | `dataflowContext`, `workflowGoal` | `WorkflowGoal.tsx:82` — Trill + user goal |
| `agent.plan-coherence-validator` | `default_preamble.txt` | `workflowGoal`, `dataflowContext` | `WorkflowGoal.tsx:329` — task + Trill |
| `agent.syntax-analysis-agent` | `syntax_analysis_preamble.txt` | `codeContext` | `WorkflowGoal.tsx:155` — the code under analysis |
| `agent.task-refresh-agent` | `default_preamble.txt` | `currentTask`, `keywords`, `dataflowContext` | `WorkflowGoal.tsx:208` — task + keywords + Trill |
| `agent.keyword-binding-agent` | `default_preamble.txt` | `keywords`, `dataflowContext` | `WorkflowGoal.tsx:125` — current keywords + Trill |

  (The blocked `agent.generated-content-evaluator` has no legacy call site, so its inputs remain unspecified with the rest of its contract — `OQ-007`.) Legacy line numbers are as of 2026-07-27; the roster in `app/agents/builtin.py` is the living source.
- Materialization (`_materialize_builtin`) writes **both** assets into the user store; `read_prompt_text(coord, name)` generalizes the roster reader.
- Runtime parity: `_prepare_run` composes the system turn as `preamble + "\n\n" + (intent or instruction)` via the store-first `_resolve_prompt_text` — an edited intent replaces the **instruction portion only**, so the preamble still applies; a definition that resolves no system asset (e.g. an upload without one) runs instruction-only as before.

## 3. Verification

New `TestPreambleAndInputs` (all 13 manifests declare the system asset + non-empty reads; the syntax override; every preamble readable from `llm-prompts/`) and `TestMaterializePreamble` (install writes both files); the two run-path tests updated to assert the composed system turn. Agents suite 245 passed; full backend 744+ green. The `dev/36` example package (which ships its own preamble) composes correctly through the same path.

## 4. Traceability

- Amends `BL-P5-20260719-01` (the roster) and the `BL-P4-…-02` run contract; `dev/05` roster table + `dev/06` parity rule are the sources; `RISK-PROMPT-002` (composition divergence) addressed.

## 5. Post-Implementation Testing Amendment (2026-07-29, memo dev/44)

Feature testing found that declaring the reads was necessary but not sufficient: **nothing supplied them at run time** — an attached Node Content Builder received preamble + instruction + the user's free text only, never the Trill/nodeId/subtask/task its legacy call site pushed. Verified findings and corrections (implemented in memo `dev/44`, `BL-P2-20260729-10`):

- **Preamble: correct as shipped** — verified empirically, including for stale pre-dev/38 store copies (the runtime's roster fallback composed the full 18.5 KB default preamble). The perceived preamble failure was the missing inputs.
- **Inputs: now supplied** — the client composes each attachment's declared reads from the **live canvas** on every send (unsaved nodes included) and the runtime frames them as one ephemeral provider message; Node Content Builder reproduces the legacy `clickGenerateContentNode` framing byte-for-byte, target-content blanking included. Reads with no chat-time source (`connectionSide`, panel-owned `keywords`/`currentTask`) are documented omissions — the user's message carries that intent in chat.
- **Store hygiene**: `_materialize_builtin` now heals stale built-in copies to the current roster asset set on install/import (this section's "materialization writes both assets" is thereby true for pre-dev/38 copies too).

The §2 mapping table remains the authoritative reads contract; `dev/44` §3.3 records its chat-time realization per agent.
