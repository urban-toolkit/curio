# Implementation Memo 67-6: Node Content Builder Apply Flow + Node Builder Modify-Existing (Simulation Mode: Solve)

Date: 2026-08-05
Status: proposed (part of the dev/67 program — see `67-1-index.md`)

## 1. Problem Statement

Per-node solving needs a first-class content interaction (67-0): the Node Content
Builder receives the full dataflow context, the node's goal/configuration, and its
upstream/downstream neighborhood; generates or modifies content; presents it for
review; and Apply writes it — the legacy Get Code ergonomics on the current agent
architecture. Today:

- Solve's children run the NCB as a depth-1 delegate with a thin `inputs` dict
  (`nodeType`, `intent`, `planSiblings` — services.py solve worker) — no edges, no
  upstream schemas, no runtime state; content lands without an interactive review
  (Solve's batch IS the review per DEC-048, but Simulation Mode wants per-node
  inspection).
- The NCB as an attachment already has the byte-faithful legacy framing
  (agentRunContext.ts:51-70) and `node.content.write` mints a reviewed proposal — the
  Apply flow EXISTS for chat; what is missing is the composed context (dataflow +
  neighbors + runtime) and the orchestrated invocation from the builder sequence.
- The Node Builder creates nodes but has no modify-existing posture; 67-0 makes it the
  orchestration layer around NCB behavior when the node exists.

## Expected Behavior (user-visible walkthrough)

1. Solving a node in Simulation Mode (propose mode) generates content but
   WRITES NOTHING: a `node.content.write` review card appears in the builder
   chat with the full proposed code as an inert preview and Apply/Dismiss.
   The node stays pending and the phase returns to simulating — nothing on
   the canvas changed yet.
2. The generated code is neighborhood-aware: the child saw the node's goal,
   its current content, the nearest upstream/downstream nodes (goals, sizes,
   last runtime status from the journal), the graph summary, and the dataset
   references — so it stops inventing upstream column names and stops saying
   "I don't have the dataflow context".
3. Clicking **Apply** on the content card writes the code into the node
   (live canvas included), flips the node's pill to solved, and advances the
   plan row's state to approved. If you edited the node meanwhile, the apply
   refuses with the stale message instead of clobbering your work.
4. Asking the Node Builder to change an EXISTING node produces a reviewed
   content-replacement proposal against that node (never a duplicate node):
   it reads the node first, may delegate generation to the Node Content
   Builder, and everything still lands as a card you approve.
5. Classic Solve (the strip button) behaves exactly as before — direct
   writes under the digest guard; propose mode is additive.
6. What no longer happens: solve children generating code blind to the graph,
   and content reaching a node in Simulation Mode without a review you
   clicked through.

## 2. Scope

In scope:
- Backend delegate inputs for `node.content.generate`: enriched, structured context —
  `{nodeType, intent, expects, upstream: [{id, type, goal, outputSchema?, runtimeStatus?}],
  downstream: [...], graphSummary, datasetRefs}` — composed server-side from the spec +
  67-2's journal (one composer, `app/agents/node_context.py`, used by Solve children
  AND the builder sequence).
- Solve-path review option: `solve` gains `mode: "propose"` — children's content mints
  per-node `node.content.write` proposals (existing machinery) instead of direct writes;
  Simulation Mode uses propose, classic Solve keeps direct writes (dev/52 authorization
  model unchanged for the batch path).
- Node Builder modify-existing: `node.build` accepts an existing nodeId — resolves to
  orchestrating an NCB delegate over the enriched context and minting
  `node.content.write` against that node (never node.create); instruction updated.
- Frontend: the existing review card for `node.content.write` is the Apply surface
  (diff-style preview already exists from dev/41); no new UI beyond wiring the builder
  sequence to open it.
- `node_content_builder` instruction: consume the structured context; self-correction
  contract (67-7 feeds validation failures back as corrective context).

Out of scope: executing/validating the applied content (67-7); the sequence
orchestration that calls this per node (67-9); Get Code UI retirement (the legacy
button remains; parity is behavioral, not removal); dev/57 extraction (already the
write-path guard everywhere).

## 3. Recommended Implementation Approach

- **One context composer.** `compose_node_context(spec, node_id, journal)` returns the
  structured dict above, bounded (schemas over contents; neighbor contents elided to
  lengths; ≤8 neighbors each way by graph distance). Solve workers and the Node
  Builder's NCB delegation both call it — the delegate prompt gains a framed
  `[node context]` block (dev/41 framing rules).
- **Propose-mode Solve.** The solve worker's write branch swaps
  `node["content"] = …` for `_mint_proposal(node.content.write, …)` when
  `mode == "propose"` — digest-pinned against the still-empty (or current) content
  exactly like chat-minted writes; the per-node stream events (dev/63) carry
  `proposalId` so the sequence can open the review. `nodeStates` (67-5) advances
  `solving → validated` only through 67-7; `approved` on apply.
- **Modify-existing.** The Node Builder's `node.build` handler grows a branch: target
  node exists → enriched-context NCB delegation → `node.content.write` mint (content
  replacement reviewed with the standard diff card). Its instruction states the split
  plainly: create when absent, orchestrate-modify when present, never both in one turn.

## 4. Data and State Handling

- Content proposals remain the only write path in propose mode; digest pins guard user
  edits exactly as dev/41 defined.
- The context composer reads spec + journal only — no new state.
- Sequence linkage: `builderSession.nodeStates[ref]` + the proposal id on the state
  record (`nodeProposals: {ref: proposalId}`) so reload finds the pending review.

## 5. UI and UX Requirements

- The Apply interaction is the existing node.content.write review card (preview,
  Apply/Dismiss) — Get Code parity: invoked from the node's goal context, writes on
  Apply, never silently.
- The builder strip / sequence surfaces "review content for <node>" as the current
  step (67-9 renders the stage; this memo only guarantees the proposal exists and is
  addressable).

## 6. Edge Cases

- Node deleted between mint and apply → existing stale/409 path.
- User edits content while a propose-mode child runs → digest pin refuses; sequence
  marks the node `approved` (user content wins — the dev/52 skip semantics translated).
- Upstream never executed → context says so honestly (`runtimeStatus: never-executed`)
  rather than fabricating schemas.
- Enriched context over budget → schemas and goals survive; neighbor lists truncate
  with markers.
- NCB missing → existing install-proposal path (delegation unchanged).

## 7. Testing Strategy

- Composer unit tests (neighborhood selection, schema inclusion from a journal fixture,
  bounds, never-executed honesty).
- Solve propose-mode: proposals minted per node with pins; stream events carry ids;
  classic mode byte-identical (regression).
- Modify-existing: existing node → content.write mint (never create); instruction test.
- Route-level: apply of a propose-mode proposal writes content + advances nodeStates.

## 8. Acceptance Criteria

- [ ] A Simulation Mode solve of one node yields a reviewable content proposal whose
      prompt context contained edges, neighbors, and runtime state — and Apply writes it.
- [ ] The Node Builder modifies an existing node via a reviewed content proposal.
- [ ] Classic Solve behavior is unchanged (regression-pinned).

## 9. Recommended Commit Breakdown

1. Backend: context composer + enriched delegate inputs + tests.
2. Backend: propose-mode Solve + stream proposalId + tests.
3. Backend: Node Builder modify-existing + instruction + tests.
4. Docs: memo flip + BL-P5 amendment.

## 10. Engineering Quality Checklist

- One composer feeds every content generation — no per-caller context drift.
- Propose mode reuses the review machinery wholesale; no second write path.
- User work protection (digest pins) holds on every branch.
