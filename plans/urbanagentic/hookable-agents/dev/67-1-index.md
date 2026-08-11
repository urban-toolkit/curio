# dev/67 Index — Granular Simulation Mode, Per-Node Validation, and Orchestration Hardening

Date: 2026-08-05
Status: 67-2, 67-3, 67-5, 67-6, 67-7, 67-8, 67-9 IMPLEMENTED (2026-08-05 —
DEC-051/052/054 minted; BL-P5-20260805-07..13). Remaining: 67-4 (Node Researcher +
verified external discovery — DEC-053), independent of the completed sequence.
Source: `67-0-entry.md` (owner's observations and objectives)

## The program in one paragraph

Move the Dataflow Builder from `plan → bulk-create → discover errors → repair` to
`plan → inspect → create → solve → execute → validate → approve`, per node — with agents
that can actually SEE the dataflow (context + runtime state), a deterministic topology
model that makes invalid multi-input graphs unmintable, and external facts (dataset ids,
API endpoints) verified by a real research agent before they enter the graph.

## Investigation findings that shape the decomposition (confirmed in code, 2026-08-05)

1. **The three P5 composites receive NO grounded context.** `composeAgentRunContext`
   (agentRunContext.ts:122) maps `attachment.reads` through `readFragment`, but the
   composites' declared reads (`graphContext`, `mission`, `installedTemplates`,
   `targetContext`, `nodeIntent`, `externalSelection`) have **no producer case** —
   the function returns `null` and no context message is sent. Their only window is
   `dataflow.read` (tools.py:272), which reads the SAVED spec and truncates at 32 000
   chars **nodes-first** (trill key order puts `nodes` with full `content` before
   `edges`) — so on any non-trivial dataflow the edges are exactly what gets cut.
   "I don't have the full dataflow edges" is a literal description of the payload.
2. **Runtime errors are never persisted.** The sandbox already returns machine-readable
   failures (`worker.py:161` — full traceback in `stderr`, `output.path == ""` as the
   canonical failure predicate), but the result exists only in the HTTP response and a
   transient React string (`useNodeState.output.content`). `nodeProvenance` records types
   only; `OutputRef` records successes only; `node.warnings` is LLM coherence advice and
   is dropped by the serializer. No agent can retrieve why a node failed.
3. **Topology metadata exists but is unplumbed.** Every template manifest declares
   `inputPorts[].cardinality` (`"1"`, `"[1,n]"`, …; node-package.v4.json), but
   `available_templates` (packages/services.py:187) strips ports before the agents module
   ever sees them; NOTHING parses cardinality into min/max anywhere; multi-input handling
   is `if nodeType === MERGE_FLOW` hardcoded in four FlowProvider sites (spatial-join's
   two named handles are silently excluded); `isValidConnection` returns `true`
   unconditionally; a second edge into a plain `in` handle silently overwrites
   `data.input` (last writer wins) and deleting either edge blanks the input entirely.
   Plan mint validates edges referentially only; the bridge inserts plan edges with a
   hardcoded `targetHandle: "in"` — which for a merge target names a handle that does
   not exist (`in_0..in_4`), so the slot never fills until a reload heals it.
4. **No research capability exists at any layer.** No researcher agent in the 16-spec
   roster (builtin.py:91-195), no web/HTTP tool among the 8 registry contracts
   (tools.py:51-161), no provider-side web-search pass-through (providers.py sends no
   `tools=`), no egress/SSRF policy precedent. The Dataset Finder's external lane is a
   display contract with a URL scheme-prefix check (content.py:227) — model-invented ids
   exit as prose in a suggested prompt and meet reality only when the fetch node runs.
   The catalog lane, by contrast, is fully server-verified at mint
   (`_resolve_catalog_dataset`) — the asymmetry names the fix.
5. **A headless dataflow runner already exists — in the test tree.**
   `execute_workflow_programmatically` (tests/test_frontend/utils.py:530) + `WorkflowSpec`
   (workflow_spec.py: Kahn sort, merge `in_N` ordering, pass-through semantics for
   browser-only node types) run whole dataflows over sandbox `/exec` and read artifacts
   back. Promoting it into the app is the execution backbone for per-node validation.
   The browser primitive `playNodesUpTo` (FlowProvider.tsx:1079) is the interactive twin.

## Memo map

| Memo | Title | Layer | Depends on |
|---|---|---|---|
| `67-2` | Full dataflow awareness + per-node runtime journal | Foundation A (context/state) | — |
| `67-3` | Topology model + Merge-node resolution | Foundation B (deterministic) | — |
| `67-4` | Node Researcher + verified external discovery | Research/verification | 67-2 (context) |
| `67-5` | Plan cards v2 — per-node review, editable goals, per-node Apply | Simulation Mode: create | 67-2, 67-3 |
| `67-6` | Node Content Builder Apply flow + Node Builder modify-existing | Simulation Mode: solve | 67-2, 67-5 |
| `67-7` | Execute-through-node validation + self-correction | Simulation Mode: validate | 67-2 (journal), 67-6 |
| `67-8` | Connection review stage | Simulation Mode: connect | 67-3, 67-5 |
| `67-9` | Simulation Mode orchestration + Apply Plan as automated sequence | Assembly | 67-5..67-8 |

Recommended implementation order: **67-2 → 67-3 → 67-5 → 67-6 → 67-7 → 67-8 → 67-9**,
with **67-4** parallelizable any time after 67-2 (its egress infrastructure is
self-contained). Each memo is independently shippable and testable; nothing in a later
memo re-opens an earlier one.

## Decision points this program will mint (proposed ids; final at implementation)

- **DEC-051** (67-3): the input-arity model — ports parsed to `{min,max}`, served through
  `available_templates`, enforced at plan mint, connection apply, AND `onConnect`;
  multi-input becomes a descriptor capability, never a nodeType identity check.
- **DEC-052** (67-2): the per-node runtime journal — execution outcomes persisted
  server-side at the `/processPythonCode` seam (FS per DEC-040), exposed to agents via a
  `node.runtime.read` tool and a structure-first `dataflow.read` projection.
- **DEC-053** (67-4): agent egress — a server-mediated, policy-gated `web.fetch` /
  `web.search` read-tool pair (allowlist + SSRF guards + byte caps), the researcher as a
  chainable delegation capability (`research.verify`), and verification-before-acceptance
  for the Dataset Finder's external lane.
- **DEC-054** (67-9): Simulation Mode is the default build model; Apply Plan remains as
  the automated sequential form of the SAME validated loop (never bulk generation).

## LangChain placement (the 67-0 directive, answered once here)

The dev/49 consolidation and DEC-048 stand: deterministic validation (topology, arity,
URL probing, id verification, execution) stays direct application code — reliability
comes from the validator being boring. The one genuinely new candidate is the
researcher's multi-step chains (search → fetch → extract → confirm, 67-4); the memo
evaluates LangChain there and recommends starting with the existing bounded tool loop +
delegation seam (the chain is ≤3 deterministic steps around one model call), keeping
`delegation.py` as the recorded adapter seam. DEC-021 background execution remains
LangChain's standing re-open condition; 67-4 adds "unbounded research chains" as a
second, explicitly monitored one.

## Out of scope for the whole program

- DEC-021 proper (leases/heartbeats, background execution) — 67-7/67-9 run inside the
  dev/63 streamed-request model.
- New node types (the dev/48 reuse-first policy holds; the Merge resolution reuses
  `curio.builtin/merge-flow`).
- Provider-side web-search tools (Anthropic/Gemini native search) — recorded as a 67-4
  follow-up behind the server-mediated tools.
- The deterministic canvas-diff engine and removal undo (dev/59 deferrals, unchanged).
