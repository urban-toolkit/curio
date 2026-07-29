# Implementation Memo: Grounded Run Inputs — Preamble/Input Propagation for Attached Built-ins

Date: 2026-07-29
Status: implemented 2026-07-29 (`BL-P2-20260729-10`; commits `230364e6`, `fc6a4e6d`)
Feature slice: attachment runs finally receive the inputs their manifests declare (`inputs.reads`, dev/38), matching the legacy call sites — starting with Node Content Builder vs `clickGenerateContentNode` (`styles.tsx`). This is the "prompt-time `inputs.reads` grounding" slice that dev/39 §3 and dev/41 §3 deferred "to its own memo, with usage data to justify it" — this testing feedback is that usage data.
Design sources: memo `dev/38` (the grounded per-agent reads table — the contract this memo makes the runtime keep), the legacy call sites themselves (`styles.tsx:477-512` Get Code, `:435-441` connections, `:369-371` subtask-from-exec; `MainCanvas.tsx:218-252` explain/debug; `WorkflowGoal.tsx:82-329` suggester/keywords/syntax/refresh/planner/coherence; `NodeExplanation.tsx:26-38`; `LLMChat.tsx`), `dev/06` (migration parity rule), memos `dev/37`/`dev/41` (the envelope + tools this composes with; tools remain the pull-based complement).

## 1. Problem Statement (verified)

Tested behavior: an attached Node Content Builder answers generically — it never sees the dataflow, the node, the subtask, or the task. Verified against the code and the live store:

- **Preamble: resolves correctly** — including for stale pre-dev/38 store copies (the guest store's `agent.node-content-builder@1.0.0` manifest declares no `system` asset, but `_resolve_prompt_text` falls back to the roster preamble; verified empirically: 18,512-char default preamble composed). The *perceived* preamble failure is downstream of the missing inputs. One hygiene defect is real, though: `_materialize_builtin` no-ops when any store copy exists, so **stale copies never heal** — the store copy is not self-contained (contradicts dev/38's materialization goal).
- **Inputs: entirely missing.** Legacy Get Code sent, as the user message: `"Current Trill: " + JSON(trill with the target node's content blanked) + "\n Node ID: " + nodeId + "\nSubtask: " + goal + " Task: \n" + workflowGoal` — built from the **live canvas** (`getNodes()/getEdges()` → `TrillGenerator`), so unsaved nodes worked. The attachment run sends only preamble+instruction+tail and the user's free text. The dev/38 manifests *declare* `dataflowContext, nodeId, subtask, workflowGoal`; nothing supplies them. The T2b read tools pull from the **saved** spec — wrong for unsaved/new nodes and dependent on the model choosing to ask.
- Every other built-in has the same gap to its own legacy framing (full audit table in §4.3).

## 2. Scope

**Included**
- Backend: run/stream accept an optional bounded `context` string, framed as an **ephemeral** provider message (recomputed fresh every send — never persisted, never stale); the attachment card exposes the manifest's `reads` so the client is contract-driven; `_materialize_builtin` heals stale built-in store copies (tops up missing prompt assets + manifest, dev/38 self-containment).
- Frontend: a per-agent context composer (`agentRunContext.ts`) built from the **live canvas** (`useReactFlow` + `useFlowContext`), with Node Content Builder reproducing the legacy Get Code framing exactly (blanked target content included); wired through the dock overlay → `sendMessage` → both run paths.
- Audit of all 13 built-ins (§4.3) with the composer covering every server/canvas-derivable read; memo dev/38 + build log updated to tested behavior; regression tests for the shared pipeline + agent-specific framings.

**Out of scope**: reads that only existed inside removed bespoke UIs and have no chat-time source (`connectionSide` — the in/out picker; `keywords`/`currentTask` state owned by the legacy WorkflowGoal panel — the user's message carries task intent in chat); changing the T2b tools (they remain the mid-conversation refresh mechanism); uploaded/composite agents (they get the generic reads-driven composer for free where they declare known reads).

## 3. Design

### 3.1 Backend — the ephemeral context message

- `POST …/run` and `…/run/stream` bodies gain optional `"context": string` (≤ `CONTEXT_MAX_CHARS` = 120,000; longer input truncated with an explicit marker; non-string → 400).
- `_prepare_run` appends, when context is present, one provider message **between the session history and the user's message**: `{"role": "user", "content": "[attachment context — current canvas state]\n" + context}`. Ephemeral by design: never persisted to the session (the transcript stays what the user saw), never replayed from history (each send composes fresh — the "stale values" failure mode is structurally impossible), and absent-context runs are **byte-identical** to today (regression-pinned).
- The attachment card gains `"reads": [...]` from the manifest (`inputs_reads`) so the client composes exactly what the definition declares.
- `_materialize_builtin` heal: when a built-in's store copy exists but its manifest lacks assets the roster now declares (e.g. the pre-dev/38 missing `system`), rewrite the manifest and write the missing prompt files (idempotent top-up on install/import; runtime fallback already covered the preamble, this makes the store self-contained per dev/38).

### 3.2 Frontend — the live-canvas composer

`components/agents/attach/agentRunContext.ts` exports `composeAgentRunContext(attachment, canvas)` where `canvas = {nodes, edges, workflowName, workflowGoal}` comes from `useReactFlow()` + `useFlowContext()` in the dock overlay (verified in scope: the overlay renders inside MainCanvas's ReactFlow tree). Per-read fragment builders assembled in the manifest's `reads` order, with **coord-specific overrides where legacy framing must be exact**:

- `agent.node-content-builder` (the named requirement — byte-faithful to `clickGenerateContentNode`): generate the Trill from live nodes/edges, **blank the target node's `content`**, then `"Current Trill: " + JSON + "\n" + " Node ID: " + nodeId + "\n" + "Subtask: " + <node.data.goal> + " Task: " + "\n" + <workflowGoal>`.
- Generic fragments (canonical labels from the legacy sites): `dataflowContext` → `"Current Trill: " + JSON(liveTrill)`; `nodeId` → the node target's id; `subtask` → the target node's `data.goal`; `workflowGoal` → the FlowContext goal; `nodeContext` → `JSON({type, content, current_input, current_output})` from the live node; `codeContext` → the target node's code; `nodeContent`/`nodeType` → live node fields when the attachment targets a node.
- Composition happens **per send** in the overlay (`onSend` wraps `ctx.sendMessage(id, message, composeContext(...))`); `sendMessage` forwards `context` to the stream call and the blocking fallback alike.

### 3.3 The audit (all 13 built-ins — legacy source → chat-time status)

| Agent | Legacy inputs (call site) | After this memo |
|---|---|---|
| chat-agent | userMessage (`LLMChat`) | unchanged — the chat message is the read |
| debug-agent | selected-components Trill (`MainCanvas:252`) | live whole-canvas Trill (selection has no chat equivalent — documented widening) |
| dataflow-explainer | selected-components Trill (`MainCanvas:223`) | live whole-canvas Trill (same note) |
| node-explainer | `{type, content, current_input, current_output}` (`NodeExplanation:38`) | live node data (in/out empty when unexecuted — matches legacy pre-execution) |
| node-content-builder | Trill (target blanked) + nodeId + subtask + task (`styles:493`) | **exact legacy framing** (§3.2) |
| execution-subtask-planner | node content + type + task (`styles:370`) | node fields when node-targeted; task = user message |
| dataflow-task-planner | task + Trill (`WorkflowGoal:246`) | Trill; task = the user's message |
| connection-builder | task + nodeId + subtask + side + Trill (`styles:441`) | all but `connectionSide` (no chat source — out of scope, documented) |
| workflow-suggester | Trill + goal (`WorkflowGoal:82`) | both |
| plan-coherence-validator | task + Trill (`WorkflowGoal:329`) | Trill; task = user message |
| syntax-analysis | the code (`WorkflowGoal:155`) | node target's code |
| task-refresh | task + keywords + Trill (`WorkflowGoal:208`) | Trill; task/keywords = user message (legacy panel state, out of scope) |
| keyword-binding | keywords + Trill (`WorkflowGoal:125`) | Trill; keywords = user message (same) |

## 4. Data/State, Edge Cases

- Unsaved/new nodes: covered by construction — the composer reads the live ReactFlow state, exactly like legacy (the T2b tools keep covering the saved-spec pull case).
- No node target / canvas attachment asking about a node: node-scoped fragments are omitted; the trill still grounds it; the model can pull via `node.read`.
- Huge canvases: server-side truncation with a visible marker (legacy sent unbounded payloads; the bound is new and stated).
- Context is user-owned project data composed by our own client; the server bounds it and frames it as data. It never enters the transcript, the share surface, or later turns' history.
- Stale store copies: healed at the next install/import; runtime fallback unchanged meanwhile.

## 5. Testing Strategy

Backend: context message present with exact placement (after history, before the user message) and framing prefix; not persisted (session turns unchanged); truncation at the bound; non-string 400; **absent-context byte-identity pin**; `reads` on the attachment card; materialization heal (stale manifest gains the system asset + file; idempotent). Frontend: composer parity fixtures per agent — Node Content Builder's output string matches the legacy `clickGenerateContentNode` framing byte-for-byte (blanked content proven), generic fragments for each read, unsaved-node inclusion (composer sees live nodes); overlay wiring (send passes fresh context each time); API body forwarding on both paths. Docs: dev/38 gains a "tested behavior" amendment; build-log entry records the corrections.

## 6. Acceptance Criteria

- [x] An attached Node Content Builder receives the default preamble + `new_content_prompt` + the exact legacy Get Code context (live Trill with its target's content blanked, node id, subtask, task) on every send, for saved and unsaved nodes alike.
- [x] Every built-in receives every declared read that has a chat-time source (§3.3 table); the three legacy-panel-only reads are documented, not silently dropped.
- [x] Context is ephemeral: recomputed per send, never persisted, never in later turns' history; runs without context are byte-identical to before.
- [x] Stale built-in store copies self-heal to the dev/38 asset set on install/import.
- [x] dev/38 memo + build log reflect tested behavior; shared-pipeline and per-agent regression tests are green with the full suites.

## 7. Commits

1. `feat(agents): ephemeral run context — bounded body field, provider-message framing, reads on the card, materialization heal, with tests`.
2. `feat(agents): frontend live-canvas context composer (legacy-parity Node Content Builder framing) + send wiring, with tests`.
3. Docs: dev/38 amendment + build-log entry + docs/AGENTS.md + memo flip.

## 8. Engineering Quality Checklist

- One composer, data-driven by the manifest's `reads`, with exact-parity overrides only where a legacy framing is the named contract.
- Freshness by construction (compose-per-send), not by cache invalidation.
- Fail-open sizing (truncate + marker), byte-identical no-context path, nothing new persisted or shared.
- The push (this memo) and pull (T2b tools) mechanisms are complementary and both documented.
